#!/usr/bin/env python3
"""Move the Fruit Store's pins to the apps' newest releases.

    python3 scripts/catalog-sync.py [--catalog config/catalog.json] [--owner NAME]
                                    [--dry-run]

For each native entry of ``config/catalog.json`` whose repository belongs to
``--owner`` (default: the owner of this repository, from $GITHUB_REPOSITORY,
else the system repository in config/default.json), the newest published
release is pinned when it is newer than the entry, after these checks:

* the release has the package asset ``<id>-<version>...tar.gz`` (or .zip);
* the asset's SHA-256, worked out here from the downloaded bytes, matches the
  one GitHub records for it, or its ``<asset>.sha256`` / ``SHA256SUMS`` file;
* the package's manifest has the entry's id, the release's version and no
  ``min_os_version`` newer than this mFruit OS (devices would drop the entry);
* the whole list still passes the devices' own checks (catalog.check_entry).

Then ``version``, ``url``, ``sha256`` and ``ref`` (the release's commit) are
updated; nothing else in an entry changes. Entries from other owners stay
pinned by hand (a reviewed pull request, docs/apps/PUBLISHING.md).
.github/workflows/catalog-sync.yml runs it every hour and commits the result.
Exit status: 0 also when nothing changed; 1 when the list could not be
updated safely.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mfruitos import __version__  # noqa: E402
from mfruitos.updater import catalog  # noqa: E402
from mfruitos.updater.version import parse_version  # noqa: E402

API = "https://api.github.com"
MAX_ASSET_BYTES = 200 * 1024 * 1024
ARCHIVES = (".tar.gz", ".tgz", ".zip")


class SyncError(Exception):
    """This entry cannot be moved; the message says why."""


def http_get(url: str, token: str = "", limit: int = MAX_ASSET_BYTES) -> bytes:
    headers = {"User-Agent": "mfruit-os-catalog-sync", "Accept": "application/vnd.github+json"}
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise SyncError(f"{url} is larger than {limit} bytes")
    return data


def repo_parts(repository: str) -> tuple:
    path = repository.rstrip("/").removesuffix(".git").split("github.com/", 1)[-1]
    owner, repo = path.split("/")[:2]
    return owner, repo


def expected_sha256(release: dict, asset: dict, get) -> str:
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:") and len(digest) == 71:
        return digest[7:].lower()
    names = {a["name"].lower(): a for a in release.get("assets", [])}
    for name in (asset["name"].lower() + ".sha256", "sha256sums", "sha256sums.txt"):
        found = names.get(name)
        if not found:
            continue
        for line in get(found["browser_download_url"], 1024 * 1024).decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) == 1 and name.endswith(".sha256"):
                return parts[0].lower()
            if len(parts) >= 2 and parts[-1].lstrip("*") in (asset["name"], ""):
                return parts[0].lower()
    raise SyncError(f"no checksum published for {asset['name']}")


def package_manifest(data: bytes, name: str) -> dict:
    """manifest.json at the package root (the archive's one top folder)."""
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = {n: n for n in archive.namelist()}
            read = archive.read
    else:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        members = {m.name.lstrip("./"): m for m in archive.getmembers() if m.isfile()}

        def read(member):
            return archive.extractfile(member).read()
    candidates = sorted((n for n in members if n.endswith("manifest.json") and n.count("/") <= 1),
                        key=lambda n: n.count("/"))
    if not candidates:
        raise SyncError(f"{name} has no manifest.json at its root")
    return json.loads(read(members[candidates[0]]).decode("utf-8"))


def newest_release(entry: dict, get) -> dict | None:
    owner, repo = repo_parts(entry["repository"])
    try:
        release = json.loads(get(f"{API}/repos/{owner}/{repo}/releases/latest", 4 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if release.get("draft") or release.get("prerelease"):
        return None
    return release


def sync_entry(entry: dict, get, os_version: str = __version__) -> dict | None:
    """The entry moved to its newest release, or None when there is nothing to do."""
    release = newest_release(entry, get)
    if release is None:
        return None
    tag = str(release.get("tag_name") or "")
    version = tag[1:] if tag[:1] in "vV" else tag
    offered, pinned = parse_version(version), parse_version(entry.get("version"))
    if offered is None or pinned is None or not offered > pinned:
        return None
    prefix = f"{entry['id']}-{version}".lower()
    asset = next((a for a in release.get("assets", [])
                  if a["name"].lower().startswith(prefix) and a["name"].lower().endswith(ARCHIVES)),
                 None)
    if asset is None:
        raise SyncError(f"{tag} has no package asset {prefix}*.tar.gz")
    expected = expected_sha256(release, asset, get)
    data = get(asset["browser_download_url"], MAX_ASSET_BYTES)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SyncError(f"{asset['name']}: SHA-256 {actual} does not match the published {expected}")
    manifest = package_manifest(data, asset["name"])
    if manifest.get("id") != entry["id"] or manifest.get("version") != version:
        raise SyncError(f"{asset['name']} holds {manifest.get('id')} {manifest.get('version')}, "
                        f"not {entry['id']} {version}")
    needs = manifest.get("min_os_version")
    if needs and parse_version(needs) and parse_version(needs) > parse_version(os_version):
        raise SyncError(f"{entry['id']} {version} needs mFruit OS {needs}; this list is for "
                        f"{os_version} (devices would drop the entry)")
    owner, repo = repo_parts(entry["repository"])
    commit = json.loads(get(f"{API}/repos/{owner}/{repo}/commits/{tag}", 4 * 1024 * 1024))["sha"]
    moved = dict(entry)
    moved.update({"version": version, "url": asset["browser_download_url"], "sha256": actual,
                  "ref": commit})
    return moved


def default_owner() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"].split("/")[0]
    with open(os.path.join(ROOT, "config", "default.json"), encoding="utf-8") as fp:
        return repo_parts(json.load(fp)["system"]["repository"])[0]


def sync(items: list, owner: str, get, os_version: str = __version__, say=print) -> tuple:
    """(new list, changes, problems)."""
    result, changes, problems = [], [], []
    for entry in items:
        mine = (catalog.is_native(entry) and isinstance(entry.get("repository"), str)
                and repo_parts(entry["repository"])[0].lower() == owner.lower())
        if not mine:
            result.append(entry)
            continue
        try:
            moved = sync_entry(entry, get, os_version)
        except (SyncError, urllib.error.URLError, ValueError, KeyError, tarfile.TarError,
                zipfile.BadZipFile) as exc:
            problems.append(f"{entry['id']}: {exc}")
            say(f"{entry['id']}: kept at {entry.get('version')} ({exc})")
            result.append(entry)
            continue
        if moved is None:
            say(f"{entry['id']}: {entry.get('version')} is the newest release")
            result.append(entry)
        else:
            changes.append(f"{entry['id']} {entry.get('version')} -> {moved['version']}")
            say(f"{entry['id']}: {entry.get('version')} -> {moved['version']} "
                f"(sha256 {moved['sha256'][:12]}…, commit {moved['ref'][:7]})")
            result.append(moved)
    kept = catalog.valid_entries(result, "synced catalogue")
    if len(kept) != len(result):
        raise SyncError("the updated list fails the devices' checks; nothing written")
    return result, changes, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--catalog", default=os.path.join(ROOT, catalog.CATALOG_PATH))
    parser.add_argument("--owner", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    with open(args.catalog, encoding="utf-8") as fp:
        items = json.load(fp)
    try:
        result, changes, problems = sync(items, args.owner or default_owner(),
                                         lambda url, limit: http_get(url, token, limit))
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if changes and not args.dry_run:
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        tmp = args.catalog + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write(text)
        os.replace(tmp, args.catalog)
    print(("Changed: " + "; ".join(changes)) if changes else "No pin moved.")
    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
