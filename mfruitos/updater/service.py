"""Updater service: update checks, caching and all install operations.

Everything here blocks (network, disk, subprocesses) and must run on a
worker thread. Results are cached in ``cache/updates.json`` so the Updater
screen and Home badges work offline and after a reboot.

Update channels:
  ``system``   MFruit OS itself (GitHub releases of ``system.repository``)
  ``release``  OS-managed apps (GitHub releases/tags, semantic versions)
  ``git``      existing apps installed as git checkouts (commit tracking)
  ``none``     apps the updater cannot manage
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from mfruitos import OS_APP_ID, OS_NAME
from mfruitos.apps.manifest import (ManifestError, normalize_repository, repository_parts,
                                    validate_manifest)
from mfruitos.apps.registry import AppEntry
from mfruitos.paths import Paths
from mfruitos.system.settings import atomic_write_json
from mfruitos.updater import gittrack
from mfruitos.updater.github import (GitHubClient, GitHubError, NotFoundError, OfflineError,
                                     RateLimitError, Release, checksum_asset, pick_asset)
from mfruitos.updater.installer import InstallError, Installer, InstallRequest, InstallResult
from mfruitos.updater.verifier import expected_from_digest, parse_checksums
from mfruitos.updater.version import is_newer, parse_version

log = logging.getLogger("mfruitos.updater")

MAX_COMPAT_PROBES = 5
OFFLINE_RETRY_SEC = 600
RELEASES_MAX_AGE_SEC = 300


@dataclass
class UpdateInfo:
    app_id: str
    name: str
    channel: str
    installed: str = ""
    latest: str = ""
    update_available: bool = False
    error: str = ""
    notes: str = ""
    repository: str = ""
    checked_at: float = 0.0
    versions: list = field(default_factory=list)


class UpdateService:
    def __init__(self, paths: Paths, settings, github: GitHubClient, installer: Installer,
                 os_version: str):
        self.paths = paths
        self.settings = settings
        self.github = github
        self.installer = installer
        self.os_version = os_version
        self.cache_file = os.path.join(paths.cache_dir, "updates.json")
        self._lock = threading.Lock()
        self._infos: dict[str, UpdateInfo] = {}
        self.last_check = 0.0
        self.last_error = ""
        self.online: bool | None = None
        self.busy = False
        self.load_cache()

    # ================================================================ cache
    def load_cache(self) -> None:
        try:
            with open(self.cache_file, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable update cache: %s", exc)
            return
        infos = {}
        for app_id, raw in (data.get("apps") or {}).items():
            try:
                infos[app_id] = UpdateInfo(**raw)
            except TypeError:
                continue
        with self._lock:
            self._infos = infos
            self.last_check = float(data.get("checked_at") or 0)
            self.last_error = str(data.get("error") or "")
            self.online = data.get("online")

    def _save_cache(self) -> None:
        with self._lock:
            data = {"checked_at": self.last_check, "error": self.last_error, "online": self.online,
                    "apps": {k: asdict(v) for k, v in self._infos.items()}}
        try:
            atomic_write_json(self.cache_file, data)
        except OSError as exc:
            log.warning("Cannot save update cache: %s", exc)

    def infos(self) -> dict[str, UpdateInfo]:
        with self._lock:
            return dict(self._infos)

    def info(self, app_id: str) -> UpdateInfo | None:
        with self._lock:
            return self._infos.get(app_id)

    def latest_map(self) -> dict[str, str]:
        """{app_id: newer version} for OS-managed apps with an update."""
        with self._lock:
            return {k: v.latest for k, v in self._infos.items()
                    if v.update_available and v.channel == "release"}

    def update_count(self) -> int:
        with self._lock:
            return sum(1 for v in self._infos.values() if v.update_available)

    def check_due(self) -> bool:
        interval = self.settings.get("updater.check_interval_hours") * 3600
        if self.online is False:
            # The last check could not reach GitHub (often: network not up yet
            # right after boot). Retry soon instead of waiting a full interval.
            interval = min(interval, OFFLINE_RETRY_SEC)
        return time.time() - self.last_check >= interval

    # ================================================================ check
    def check(self, entries: list[AppEntry]) -> dict[str, UpdateInfo]:
        """Check the OS and every manageable app. Blocking."""
        self.busy = True
        try:
            return self._check(entries)
        finally:
            self.busy = False

    def _check(self, entries: list[AppEntry]) -> dict[str, UpdateInfo]:
        log.info("Checking for updates (%d apps)", len(entries))
        results: dict[str, UpdateInfo] = {}
        offline_error = ""
        system = self._check_system()
        results[OS_APP_ID] = system
        if system.error and system.error.startswith("offline:"):
            offline_error = system.error[8:]
        for entry in entries:
            if entry.kind == "os":
                info = UpdateInfo(entry.id, entry.name, "release", installed=entry.version,
                                  repository=entry.repository)
                if not entry.repository:
                    info.error = "No repository recorded"
                elif offline_error:
                    info.error = "offline"
                else:
                    self._check_release(info, entry.id)
            elif entry.kind == "daemon":
                info = self._check_git(entry, offline_error)
            else:
                continue
            info.checked_at = time.time()
            results[entry.id] = info
        with self._lock:
            self._infos = results
            self.last_check = time.time()
            self.online = not offline_error
            self.last_error = offline_error
        self._save_cache()
        log.info("Update check done: %d update(s)%s", self.update_count(),
                 f", offline ({offline_error})" if offline_error else "")
        return results

    def _check_system(self) -> UpdateInfo:
        repo = self.settings.get("system.repository")
        info = UpdateInfo(OS_APP_ID, OS_NAME, "system", installed=self.os_version, repository=repo,
                          checked_at=time.time())
        if not repo:
            info.error = "No system repository configured"
            return info
        self._check_release(info, OS_APP_ID)
        return info

    def _check_release(self, info: UpdateInfo, app_id: str) -> None:
        try:
            owner, repo = repository_parts(info.repository)
            releases = self.github.releases(owner, repo, self.settings.get("updater.include_prereleases"))
        except OfflineError as exc:
            info.error = f"offline:{exc}"
            return
        except RateLimitError as exc:
            info.error = str(exc)
            return
        except NotFoundError:
            info.error = "Repository not found"
            return
        except (GitHubError, ManifestError) as exc:
            info.error = str(exc)[:100]
            return
        info.versions = [r.version for r in releases]
        if not releases:
            info.error = "No releases or version tags"
            return
        newest = releases[0]
        info.latest = newest.version
        info.notes = newest.body[:600]
        info.update_available = is_newer(newest.version, info.installed)

    def _check_git(self, entry: AppEntry, offline_error: str) -> UpdateInfo:
        info = UpdateInfo(entry.id, entry.name, "none")
        checkout = gittrack.inspect(entry.cwd) if entry.cwd else None
        if checkout is None:
            info.error = "Not a git checkout"
            return info
        info.channel = "git"
        info.installed = checkout.label
        info.repository = checkout.repository or checkout.remote
        if offline_error:
            info.error = "offline"
            return info
        try:
            result = gittrack.check(checkout)
        except gittrack.GitError as exc:
            info.error = str(exc)[:100]
            return info
        info.latest = f"{checkout.branch} @ {result['remote'][:7]}"
        info.update_available = result["update"]
        if checkout.dirty and result["update"]:
            info.error = "Local changes; cannot update automatically"
        return info

    # ============================================================ releases
    def releases_for(self, repository: str) -> list[Release]:
        """Release list for screens and installs; reuses a lookup from the last
        5 minutes so browsing versions does not spend GitHub API calls."""
        owner, repo = repository_parts(repository)
        return self.github.releases(owner, repo, self.settings.get("updater.include_prereleases"),
                                    max_age=RELEASES_MAX_AGE_SEC)

    def plan(self, repository: str, release: Release, app_id: str, mode: str) -> InstallRequest:
        asset = pick_asset(release, app_id if app_id != OS_APP_ID else "mfruit")
        expected = ""
        notes = []
        if asset is not None:
            url = asset.url
            expected = expected_from_digest(asset.digest) or ""
            if not expected:
                sums = checksum_asset(release, asset)
                if sums is not None:
                    try:
                        table = parse_checksums(self.github.fetch_small(sums.url).decode("utf-8", "replace"))
                        expected = table.get(asset.name, table.get("", ""))
                    except GitHubError as exc:
                        notes.append(f"checksum file unavailable: {exc}")
        else:
            url = release.tarball_url
            notes.append("source archive (no release asset)")
        return InstallRequest(repository=normalize_repository(repository), version=release.version,
                              ref=release.tag, url=url, expected_sha256=expected, app_id=app_id,
                              mode=mode, notes=notes)

    def latest_compatible(self, repository: str) -> tuple[Release, str]:
        """Newest release whose manifest supports this OS version; returns (release, app_id)."""
        owner, repo = repository_parts(repository)
        releases = self.releases_for(repository)
        if not releases:
            raise InstallError("check", "The repository has no releases or version tags")
        last_error = ""
        for release in releases[:MAX_COMPAT_PROBES]:
            try:
                raw = self.github.raw_file(owner, repo, release.tag, "manifest.json")
                manifest = validate_manifest(json.loads(raw.decode("utf-8")),
                                             os_version=self.os_version)
                return release, manifest.id
            except NotFoundError:
                last_error = "No manifest.json in the repository (not an MFruit OS app package)"
            except (ValueError, ManifestError) as exc:
                last_error = f"{release.tag}: {exc}"
        raise InstallError("check", last_error or "No compatible release found")

    # ============================================================ actions
    def install_from_repository(self, repository: str, progress=None) -> InstallResult:
        repository = normalize_repository(repository)
        release, app_id = self.latest_compatible(repository)
        mode = "install"
        if os.path.isdir(self.paths.app_root(app_id)):
            mode = "update"
        return self.installer.run(self.plan(repository, release, app_id, mode), progress)

    def install_version(self, entry: AppEntry, version: str, progress=None) -> InstallResult:
        releases = self.releases_for(entry.repository)
        release = next((r for r in releases if r.version == version), None)
        if release is None:
            raise InstallError("check", f"Version {version} is not available")
        current = parse_version(entry.version)
        target = parse_version(version)
        mode = "reinstall" if current == target else (
            "downgrade" if current is not None and target < current else "update")
        return self.installer.run(self.plan(entry.repository, release, entry.id, mode), progress)

    def update_system(self, version: str, progress=None) -> InstallResult:
        repository = self.settings.get("system.repository")
        releases = self.releases_for(repository)
        release = next((r for r in releases if r.version == version), None)
        if release is None:
            raise InstallError("check", f"MFruit OS {version} is not available")
        return self.installer.run(self.plan(repository, release, OS_APP_ID, "system"), progress)

    def sideload(self, path: str, progress=None) -> InstallResult:
        """Install a local package archive or folder (developer feature)."""
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            raise InstallError("check", f"{path} does not exist")
        return self.installer.run(InstallRequest(repository="", local_path=path, mode="install"),
                                  progress)

    def discover(self) -> list[dict]:
        results = []
        seen = set()
        for repo in self.settings.get("updater.sources"):
            owner, name = repository_parts(repo)
            key = f"{owner}/{name}".lower()
            if key not in seen:
                seen.add(key)
                results.append({"full_name": f"{owner}/{name}", "description": "From your sources list",
                                "stars": None, "url": repo})
        topic = self.settings.get("updater.discovery_topic")
        if topic:
            for item in self.github.search_topic(topic):
                if item["full_name"].lower() not in seen:
                    seen.add(item["full_name"].lower())
                    results.append(item)
        return results

    def git_update(self, entry: AppEntry, progress=None) -> str:
        checkout = gittrack.inspect(entry.cwd)
        if checkout is None:
            raise gittrack.GitError("not a git checkout")
        new_head = gittrack.update(checkout, self.paths.state_dir, entry.id, progress)
        self._refresh_git_info(entry)
        return new_head[:7]

    def git_rollback(self, entry: AppEntry) -> str:
        checkout = gittrack.inspect(entry.cwd)
        if checkout is None:
            raise gittrack.GitError("not a git checkout")
        previous = gittrack.rollback(checkout, self.paths.state_dir, entry.id)
        self._refresh_git_info(entry)
        return previous[:7]

    def _refresh_git_info(self, entry: AppEntry) -> None:
        info = self._check_git(entry, "")
        info.checked_at = time.time()
        with self._lock:
            self._infos[entry.id] = info
        self._save_cache()

    def mark_installed(self, app_id: str, version: str) -> None:
        """Update cached state after a successful install without a new check."""
        with self._lock:
            info = self._infos.get(app_id)
            if info is not None:
                info.installed = version
                info.update_available = is_newer(info.latest, version) if info.latest else False
        self._save_cache()

    def forget(self, app_id: str) -> None:
        with self._lock:
            self._infos.pop(app_id, None)
        self._save_cache()
