"""Package installation pipeline:

    CHECK -> DOWNLOAD -> VERIFY -> BACKUP -> INSTALL -> TEST -> ACTIVATE

The running version is never modified. A new version is extracted to a
staging directory, moved into ``versions/``, set up and tested there, and
only then activated by an atomic symlink swap. Any failure after BACKUP
triggers a rollback: the previous version stays (or becomes again) active,
app data is restored from its snapshot, and the half-installed version is
deleted.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from mfruitos import OS_APP_ID
from mfruitos.apps.manifest import (Manifest, ManifestError, is_safe_relative_path,
                                    load_manifest, same_repository)
from mfruitos.apps.registry import UNINSTALLED_FILE
from mfruitos.paths import Paths, is_valid_app_id
from mfruitos.system.settings import atomic_write_json
from mfruitos.updater import rollback
from mfruitos.updater.github import GitHubError
from mfruitos.updater.verifier import (VerificationError, copy_package_dir, safe_extract,
                                       sha256_file, verify_sha256)
from mfruitos.updater.version import parse_version

log = logging.getLogger("mfruitos.updater.installer")

STEPS = ("check", "download", "verify", "backup", "install", "test", "activate")
STEP_LABELS = {"check": "Check", "download": "Download", "verify": "Verify", "backup": "Backup",
               "install": "Install", "test": "Test", "activate": "Activate"}
INSTALL_TIMEOUT_SEC = 900
TEST_TIMEOUT_SEC = 120
MIN_FREE_BYTES = 50 * 1024 * 1024
ENTRYPOINT_FILE = ".mfruit-entrypoint"
KEPT_ON_UNINSTALL = ("data", "backups")

Progress = Callable[[str, str, float | None], None]


class InstallError(Exception):
    def __init__(self, step: str, message: str, rolled_back: bool = False):
        super().__init__(message)
        self.step = step
        self.message = message
        self.rolled_back = rolled_back


@dataclass
class InstallRequest:
    repository: str                 # canonical https://github.com/owner/repo ("" for sideload)
    version: str = ""               # expected manifest version ("" = accept any, sideload)
    ref: str = ""                   # tag
    url: str = ""                   # archive URL (asset or source tarball)
    expected_sha256: str = ""       # from a release checksum, if published
    local_path: str = ""            # sideload: archive file or package directory
    app_id: str = ""                # expected id ("" for a first install)
    mode: str = "install"           # install | update | downgrade | reinstall | system
    notes: list[str] = field(default_factory=list)
    catalog_id: str = ""


@dataclass
class InstallResult:
    app_id: str
    name: str
    version: str
    previous_version: str
    verified: bool
    warnings: list[str]
    restart_required: bool = False


class Installer:
    def __init__(self, paths: Paths, os_version: str, settings, github=None,
                 register: Callable[[Manifest], None] | None = None,
                 python: str = sys.executable or "python3",
                 in_use: Callable[[str], bool] | None = None):
        self.paths = paths
        self.os_version = os_version
        self.settings = settings
        self.github = github
        self.register = register
        self.python = python
        # True while an app is open or running: installing over it would leave
        # the running process on the old code with its data changing under it.
        self.in_use = in_use or (lambda app_id: False)

    # ================================================================ public
    def run(self, request: InstallRequest, progress: Progress | None = None) -> InstallResult:
        report = progress or (lambda step, detail, fraction=None: None)
        job = _Job(self, request, report)
        return job.execute()

    def target_root(self, app_id: str, system: bool) -> str:
        return self.paths.system_dir if system else self.paths.app_root(app_id)

    def record_path(self, root: str) -> str:
        return os.path.join(root, "app.json")

    def read_record(self, root: str) -> dict:
        try:
            with open(self.record_path(root), "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    # ---------------------------------------------------- user-level actions
    def rollback_to_previous(self, app_id: str, system: bool = False) -> str:
        """Re-activate the previously installed version (kept on disk)."""
        root = self.target_root(app_id, system)
        record = self.read_record(root)
        previous_dir = record.get("previous_dir", "")
        if not previous_dir or not os.path.isdir(previous_dir):
            raise InstallError("activate", "No previous version is available to roll back to.")
        current_dir = rollback.current_target(root)
        manifest = load_manifest(previous_dir)
        _write_entrypoint(previous_dir, manifest.entrypoint)
        rollback.switch_current(root, previous_dir)
        old_record = dict(record)
        record.update({
            "installed_version": manifest.version,
            "installed_dir": previous_dir,
            "previous_version": record.get("installed_version", ""),
            "previous_dir": current_dir or "",
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        try:
            atomic_write_json(self.record_path(root), record)
            if self.register and not system:
                self.register(manifest)
            if system:
                _write_guard_file(self.paths.state_dir, current_dir or "")
                atomic_write_json(os.path.join(self.paths.state_dir, "pending_system_update.json"),
                                  {"version": manifest.version, "previous_dir": current_dir or "",
                                   "new_dir": previous_dir, "at": time.time()})
        except Exception:
            if current_dir:
                rollback.switch_current(root, current_dir)
            atomic_write_json(self.record_path(root), old_record)
            raise
        log.info("Rolled %s back to %s", app_id, manifest.version)
        return manifest.version

    def uninstall(self, app_id: str, keep_data: bool = True) -> bool:
        """Remove an installed app's code. True if its data was kept.

        With ``keep_data`` the package folder keeps ``data/`` and ``backups/``
        plus an ``uninstalled.json`` note; reinstalling the app finds its data
        again, and ``delete_data`` removes the rest. An app with no data, or
        ``keep_data=False``, is removed completely.
        """
        self._check_app_id(app_id, "uninstall")
        root = self.paths.app_root(app_id)
        current = rollback.current_target(root)
        if not os.path.isdir(root) or current is None:
            raise InstallError("check", "App is not installed by MFruit OS")
        record = self.read_record(root)
        script = os.path.join(current, "uninstall.sh")
        if os.path.isfile(script):
            log.info("Running uninstall.sh for %s", app_id)
            try:
                _run_script(["/bin/bash", script], current, self._env(app_id, root, current),
                            self.paths.app_log(app_id), 120)
            except InstallError as exc:
                log.warning("uninstall.sh failed for %s (continuing): %s", app_id, exc.message)
        data = os.path.join(root, "data")
        if not keep_data or not (os.path.isdir(data) and os.listdir(data)):
            self._remove_everything(app_id)
            log.info("Uninstalled %s (nothing kept)", app_id)
            return False
        for name in sorted(os.listdir(root)):
            if name in KEPT_ON_UNINSTALL:
                continue
            path = os.path.join(root, name)
            if os.path.isdir(path) and not os.path.islink(path):
                rollback.safe_rmtree(path, root)
            else:
                os.remove(path)
        atomic_write_json(os.path.join(root, UNINSTALLED_FILE), {
            "id": app_id, "name": record.get("name") or app_id,
            "version": record.get("installed_version", ""),
            "repository": record.get("repository", ""),
            "uninstalled_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self._remove_run_record(app_id)
        log.info("Uninstalled %s; its data is kept in %s", app_id, data)
        return True

    def delete_data(self, app_id: str) -> list[str]:
        """Delete what MFruit OS keeps for an app that is no longer installed:
        its package folder (data, backups), logs, run record and adoption
        record. Refused while the app is installed. Returns what was removed.

        Files outside MFruit OS's folders (a daemon app's own folder, data an
        app keeps under the home directory, the shared radio store) are never
        touched.
        """
        self._check_app_id(app_id, "delete")
        root = self.paths.app_root(app_id)
        if rollback.current_target(root) is not None:
            raise InstallError("check", "Uninstall the app before deleting its data")
        removed = self._remove_everything(app_id)
        log.info("Deleted the data of %s: %s", app_id, ", ".join(removed) or "nothing left")
        return removed

    def reset_data(self, app_id: str) -> int:
        """Empty an installed app's data folder (a fresh start; the app and its
        settings in MFruit OS stay). Returns the number of entries removed."""
        self._check_app_id(app_id, "reset")
        root = self.paths.app_root(app_id)
        if rollback.current_target(root) is None:
            raise InstallError("check", "App is not installed by MFruit OS")
        data = os.path.join(root, "data")
        count = 0
        for name in sorted(os.listdir(data)) if os.path.isdir(data) else []:
            path = os.path.join(data, name)
            if os.path.isdir(path) and not os.path.islink(path):
                rollback.safe_rmtree(path, data)
            else:
                os.remove(path)
            count += 1
        backups = os.path.join(root, "backups")
        if os.path.isdir(backups):
            rollback.safe_rmtree(backups, root)
        log.info("Reset %s: %d data entries removed", app_id, count)
        return count

    def _check_app_id(self, app_id: str, action: str) -> None:
        if not is_valid_app_id(app_id) or app_id == OS_APP_ID:
            raise InstallError("check", f"Refusing to {action} {app_id!r}")

    def _remove_everything(self, app_id: str) -> list[str]:
        removed = []
        root = self.paths.app_root(app_id)
        if os.path.isdir(root):
            rollback.safe_rmtree(root, self.paths.apps_dir)
            removed.append(root)
        adopted = os.path.join(self.paths.home, "adopted", app_id)
        if os.path.isdir(adopted):
            rollback.safe_rmtree(adopted, os.path.join(self.paths.home, "adopted"))
            removed.append(adopted)
        for path in (self.paths.app_log(app_id), self.paths.app_log(app_id) + ".1"):
            if self._remove_file(path):
                removed.append(path)
        if self._remove_run_record(app_id):
            removed.append(os.path.join(self.paths.runs_dir, f"{app_id}.json"))
        return removed

    def _remove_run_record(self, app_id: str) -> bool:
        return self._remove_file(os.path.join(self.paths.runs_dir, f"{app_id}.json"))

    @staticmethod
    def _remove_file(path: str) -> bool:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            log.warning("Cannot remove %s: %s", path, exc)
            return False

    def _env(self, app_id: str, root: str, version_dir: str, previous: str = "") -> dict:
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "XDG_RUNTIME_DIR")}
        env.update({
            "WHISPLAY_APP_ID": app_id,
            "WHISPLAY_OS_VERSION": self.os_version,
            "WHISPLAY_OS_APP_DIR": version_dir,
            "WHISPLAY_OS_APP_DATA": os.path.join(root, "data"),
            "WHISPLAY_OS_PREVIOUS_VERSION": previous,
            "PYTHONUNBUFFERED": "1",
        })
        return env


class _Job:
    """One pipeline run. Holds the state needed to roll back."""

    def __init__(self, installer: Installer, request: InstallRequest, report: Progress):
        self.i = installer
        self.req = request
        self.report = report
        self.system = request.mode == "system"
        self.warnings: list[str] = []
        self.verified = False
        self.work = os.path.join(installer.paths.apps_dir if not self.system else installer.paths.home,
                                 f".work-{secrets.token_hex(4)}")
        self.archive = ""
        self.package_dir = ""
        self.manifest: Manifest | None = None
        self.root = ""
        self.fresh = False
        self.kept_root = False
        self.previous_dir: str | None = None
        self.previous_version = ""
        self.new_dir = ""
        self.data_snapshot: str | None = None
        self.activated = False
        self.scripts_ran = False
        self.previous_record = None

    # ------------------------------------------------------------- driver
    def execute(self) -> InstallResult:
        log.info("Install job: mode=%s repo=%s version=%s local=%s", self.req.mode,
                 self.req.repository, self.req.version or "-", self.req.local_path or "-")
        step = "check"
        try:
            for step in STEPS:
                self.report(step, STEP_LABELS[step], None)
                getattr(self, f"_{step}")()
        except InstallError as exc:
            exc.step = exc.step or step
            exc.rolled_back = self._rollback(step)
            log.error("Install failed at %s: %s (rolled back: %s)", step, exc.message,
                      exc.rolled_back)
            raise
        except (OSError, GitHubError, VerificationError, ManifestError,
                subprocess.SubprocessError, ValueError) as exc:
            rolled = self._rollback(step)
            log.exception("Install failed at %s", step)
            raise InstallError(step, _friendly(exc), rolled) from exc
        finally:
            self._cleanup_work()
        self._post_activate_cleanup()
        manifest = self.manifest
        log.info("Installed %s %s (previous %s, verified=%s)", manifest.id, manifest.version,
                 self.previous_version or "-", self.verified)
        return InstallResult(manifest.id, manifest.name, manifest.version, self.previous_version,
                             self.verified, self.warnings, restart_required=self.system)

    # ---------------------------------------------------------------- steps
    def _check(self) -> None:
        if not self.req.local_path and not self.req.url:
            raise InstallError("check", "Nothing to install: no download URL")
        if self.req.url and not self.req.url.startswith("https://"):
            raise InstallError("check", "Downloads must use HTTPS")
        os.makedirs(self.work, exist_ok=True)
        free = shutil.disk_usage(self.work).free
        if free < MIN_FREE_BYTES:
            raise InstallError("check", f"Not enough storage ({free // 1048576} MB free)")

    def _download(self) -> None:
        if self.req.local_path:
            self.archive = self.req.local_path
            self.report("download", "Using local package", 1.0)
            return
        if self.i.github is None:
            raise InstallError("download", "GitHub client unavailable")
        self.archive = os.path.join(self.work, "package.archive")
        limit = self.i.settings.get("updater.max_download_mb") * 1024 * 1024

        def on_progress(done: int, total: int) -> None:
            fraction = done / total if total else None
            self.report("download", f"{done // 1024} KB", fraction)

        size, digest = self.i.github.download(self.req.url, self.archive, limit, on_progress)
        self.download_sha = digest
        log.info("Downloaded %d bytes sha256=%s", size, digest)

    def _verify(self) -> None:
        if self.req.expected_sha256:
            actual = getattr(self, "download_sha", "") or sha256_file(self.archive)
            verify_sha256(actual, self.req.expected_sha256)
            self.verified = True
            self.report("verify", "Checksum OK", None)
        elif not self.req.local_path:
            if self.i.settings.get("updater.require_checksum"):
                raise InstallError("verify", "Release has no checksum and checksums are required")
            self.warnings.append("No checksum published; integrity relies on HTTPS")
        if os.path.isdir(self.archive):
            # Sideloaded folder: checked like an archive, copied, never moved.
            self.package_dir = copy_package_dir(self.archive, os.path.join(self.work, "pkg"))
        else:
            self.package_dir = safe_extract(self.archive, os.path.join(self.work, "pkg"))
        if self.req.catalog_id:
            from mfruitos.updater import catalog
            item = catalog.get(self.req.catalog_id)
            if (self.req.expected_sha256 != item['sha256'] or not self.verified
                    or self.req.repository != item['repository']):
                raise InstallError('verify', 'Catalogue source verification failed')
            catalog.prepare(self.package_dir, item)
        try:
            manifest = load_manifest(self.package_dir, os_version=self.i.os_version)
        except ManifestError as exc:
            raise InstallError("verify", f"Invalid package: {exc}") from exc
        if self.system and (manifest.type != "system" or manifest.id != OS_APP_ID):
            raise InstallError("verify", "This is not an MFruit OS system package")
        if not self.system and manifest.type != "app":
            raise InstallError("verify", "System packages cannot be installed as apps")
        if self.req.app_id and manifest.id != self.req.app_id:
            raise InstallError("verify", f"Package is '{manifest.id}', expected '{self.req.app_id}'")
        if self.req.repository and manifest.repository and \
                not same_repository(manifest.repository, self.req.repository):
            raise InstallError("verify", "Manifest repository does not match the download source")
        if self.req.version:
            expected, found = parse_version(self.req.version), parse_version(manifest.version)
            if expected is not None and found != expected:
                raise InstallError("verify", f"Release {self.req.version} contains version "
                                             f"{manifest.version}")
        if not manifest.repository and self.req.repository:
            manifest.repository = self.req.repository
        self.manifest = manifest
        self.root = self.i.target_root(manifest.id, self.system)
        self.previous_record = self.i.read_record(self.root)
        self.previous_dir = rollback.current_target(self.root)
        if self.previous_dir and not self.system and self.i.in_use(manifest.id):
            raise InstallError("check", f"{manifest.name} is open; close it, then install again")
        self.fresh = self.previous_dir is None
        # Reinstalling an app uninstalled with its data kept: that data is the
        # user's, so a failure must not take it with the half-installed version.
        self.kept_root = self.fresh and not self.system and os.path.isdir(self.root)
        if self.previous_dir:
            try:
                self.previous_version = load_manifest(self.previous_dir).version
            except ManifestError:
                self.previous_version = self.i.read_record(self.root).get("installed_version", "")

    def _backup(self) -> None:
        # The previous version directory itself is the code backup; it is never touched.
        os.makedirs(os.path.join(self.root, "versions"), exist_ok=True)
        if not self.system:
            os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
            if not self.fresh or self.kept_root:
                self.data_snapshot = rollback.snapshot_data(self.root, self.previous_version or "kept")
        self.report("backup", "Previous version kept" if not self.fresh else "Fresh install", None)

    def _install(self) -> None:
        manifest = self.manifest
        name = f"{manifest.version}-{secrets.token_hex(3)}"
        self.new_dir = os.path.join(self.root, "versions", name)
        shutil.move(self.package_dir, self.new_dir)
        self._carry_persistent_paths()
        _write_entrypoint(self.new_dir, manifest.entrypoint)
        if self.system:
            return  # the OS installer script needs root; system updates only swap code
        env = self.i._env(manifest.id, self.root, self.new_dir, self.previous_version)
        log_path = self.i.paths.app_log(manifest.id)
        for script, applies in (("install.sh", True),
                                ("update.sh", not self.fresh)):
            path = os.path.join(self.new_dir, script)
            if applies and os.path.isfile(path):
                self.report("install", f"Running {script}", None)
                self.scripts_ran = True
                _run_script(["/bin/bash", path], self.new_dir, env, log_path, INSTALL_TIMEOUT_SEC)

    def _carry_persistent_paths(self) -> None:
        """Copy manifest ``persist`` paths (a venv, a user-edited config file) from
        the previous version. The user's copy replaces any packaged default."""
        persist = self.manifest.raw.get("persist") or []
        if not self.previous_dir or not isinstance(persist, list):
            return
        for relative in persist:
            if not is_safe_relative_path(relative):
                self.warnings.append(f"Ignored unsafe persist path {relative!r}")
                continue
            source = os.path.join(self.previous_dir, relative)
            target = os.path.join(self.new_dir, relative)
            if not os.path.lexists(source):
                continue
            if os.path.lexists(target):
                if os.path.isdir(target) and not os.path.islink(target):
                    rollback.safe_rmtree(target, self.new_dir)
                else:
                    os.remove(target)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.isdir(source) and not os.path.islink(source):
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)
            log.info("Carried %s over from the previous version", relative)

    def _test(self) -> None:
        try:
            manifest = load_manifest(self.new_dir, os_version=self.i.os_version)
        except ManifestError as exc:
            raise InstallError("test", f"Installed package is invalid: {exc}") from exc
        entry = os.path.join(self.new_dir, manifest.entrypoint)
        if not os.access(entry, os.X_OK) and not entry.endswith((".py", ".sh")):
            raise InstallError("test", f"Entrypoint {manifest.entrypoint} is not executable")
        if self.system:
            self._test_system()
            return
        if manifest.test:
            self.report("test", f"Running {manifest.test}", None)
            env = self.i._env(manifest.id, self.root, self.new_dir, self.previous_version)
            _run_script(["/bin/bash", os.path.join(self.new_dir, manifest.test)], self.new_dir, env,
                        self.i.paths.app_log(manifest.id), TEST_TIMEOUT_SEC)

    def _test_system(self) -> None:
        self.report("test", "Self-test", None)
        env = dict(os.environ, PYTHONPATH=self.new_dir, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([self.i.python, "-m", "mfruitos", "--self-test"],
                                cwd=self.new_dir, env=env, capture_output=True, text=True,
                                timeout=TEST_TIMEOUT_SEC)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
            raise InstallError("test", "New system version failed its self-test: " + " / ".join(tail))

    def _activate(self) -> None:
        manifest = self.manifest
        rollback.switch_current(self.root, self.new_dir)
        self.activated = True
        if os.path.realpath(os.path.join(self.root, "current")) != os.path.realpath(self.new_dir):
            raise InstallError("activate", "Activation did not take effect")
        record = self.i.read_record(self.root)
        record.update({
            "id": manifest.id, "name": manifest.name,
            "installed_version": manifest.version, "installed_dir": self.new_dir,
            "previous_version": self.previous_version, "previous_dir": self.previous_dir or "",
            "repository": self.req.repository or manifest.repository,
            "branch": manifest.branch, "ref": self.req.ref,
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "verified": self.verified, "source": "local" if self.req.local_path else "github",
        })
        atomic_write_json(self.i.record_path(self.root), record)
        if not self.system:
            try:
                os.remove(os.path.join(self.root, UNINSTALLED_FILE))   # installed again
            except FileNotFoundError:
                pass
        if self.system:
            atomic_write_json(os.path.join(self.i.paths.state_dir, "pending_system_update.json"),
                              {"version": manifest.version, "previous_dir": self.previous_dir or "",
                               "new_dir": self.new_dir, "at": time.time()})
            _write_guard_file(self.i.paths.state_dir, self.previous_dir or "")
        elif self.i.register:
            self.i.register(manifest)

    # ------------------------------------------------------------ recovery
    def _rollback(self, step: str) -> bool:
        if STEPS.index(step) < STEPS.index("backup") or not self.root:
            return False  # nothing had changed yet
        ok = True
        try:
            if self.activated and self.previous_dir:
                rollback.switch_current(self.root, self.previous_dir)
                atomic_write_json(self.i.record_path(self.root), self.previous_record)
                log.warning("Rolled back to %s", self.previous_dir)
            if self.scripts_ran and self.data_snapshot:
                rollback.restore_data(self.root, self.data_snapshot)
            if self.new_dir and os.path.isdir(self.new_dir):
                rollback.safe_rmtree(self.new_dir, os.path.join(self.root, "versions"))
            if self.fresh and not self.system and os.path.isdir(self.root):
                if self.kept_root:
                    self._remove_job_files()
                else:
                    rollback.safe_rmtree(self.root, self.i.paths.apps_dir)
            if self.previous_dir:
                current = rollback.current_target(self.root)
                ok = current is not None and os.path.realpath(current) == os.path.realpath(self.previous_dir)
        except (OSError, rollback.UnsafePathError) as exc:
            log.critical("Rollback failed: %s", exc)
            ok = False
        return ok

    def _remove_job_files(self) -> None:
        """Undo a failed reinstall over kept data: everything but that data."""
        for name in ("current", "app.json"):
            path = os.path.join(self.root, name)
            if os.path.lexists(path):
                os.remove(path)
        versions = os.path.join(self.root, "versions")
        if os.path.isdir(versions) and not os.listdir(versions):
            os.rmdir(versions)

    def _cleanup_work(self) -> None:
        if os.path.isdir(self.work):
            try:
                parent = self.i.paths.apps_dir if not self.system else self.i.paths.home
                rollback.safe_rmtree(self.work, parent)
            except (OSError, rollback.UnsafePathError) as exc:
                log.warning("Could not clean %s: %s", self.work, exc)

    def _post_activate_cleanup(self) -> None:
        keep = self.i.settings.get("updater.keep_versions")
        try:
            rollback.prune_versions(self.root, keep, [self.new_dir, self.previous_dir or ""])
            backups = os.path.join(self.root, "backups")
            if os.path.isdir(backups):
                for name in os.listdir(backups):
                    path = os.path.join(backups, name)
                    if path != self.data_snapshot:
                        rollback.safe_rmtree(path, backups)
        except (OSError, rollback.UnsafePathError) as exc:
            log.warning("Cleanup after install: %s", exc)


def _write_entrypoint(version_dir: str, entrypoint: str) -> None:
    with open(os.path.join(version_dir, ENTRYPOINT_FILE), "w", encoding="utf-8") as fp:
        fp.write(entrypoint + "\n")


def _write_guard_file(state_dir: str, previous_dir: str) -> None:
    """Plain key=value file read by bin/boot-guard.sh (no JSON parser in sh)."""
    path = os.path.join(state_dir, "pending_system_update.env")
    with open(path + ".tmp", "w", encoding="utf-8") as fp:
        fp.write(f"PREVIOUS_DIR={previous_dir}\nATTEMPTS=0\n")
    os.replace(path + ".tmp", path)


def _run_script(command: list[str], cwd: str, env: dict, log_path: str, timeout: int) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "ab") as out:
        out.write(f"=== {time.strftime('%F %T')} {' '.join(command)} ===\n".encode())
        out.flush()
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, timeout=timeout, start_new_session=True)
        except subprocess.TimeoutExpired as exc:
            raise InstallError("", f"{os.path.basename(command[-1])} timed out after {timeout}s") from exc
        except OSError as exc:
            raise InstallError("", f"Cannot run {os.path.basename(command[-1])}: {exc}") from exc
    if result.returncode != 0:
        raise InstallError("", f"{os.path.basename(command[-1])} failed (exit code "
                               f"{result.returncode}); see the app log")


def _friendly(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "Storage is full"
    return text[:160]
