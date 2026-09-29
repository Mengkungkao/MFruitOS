"""Version switching, backups and guarded deletion.

Layout of an installed package::

    <root>/current -> versions/1.2.0-a1b2c3    (relative symlink, swapped atomically)
    <root>/versions/1.2.0-a1b2c3/              (never modified after install)
    <root>/versions/1.1.0-9f8e7d/              (previous version = code backup)
    <root>/data/                               (app data, survives updates)
    <root>/backups/data-<version>/             (data snapshot taken before an update)

Because an update installs into a *new* versions/ directory, the running
version is never overwritten; activation is a single ``rename()`` of the
symlink, and rollback is the same operation pointing back.
"""

from __future__ import annotations

import logging
import os
import shutil
import time

from mfruitos.paths import is_protected, is_within

log = logging.getLogger("mfruitos.updater.rollback")

MAX_DATA_BACKUP_BYTES = 200 * 1024 * 1024


class UnsafePathError(Exception):
    pass


def safe_rmtree(path: str, allowed_root: str) -> None:
    """Delete ``path`` only if it is strictly inside ``allowed_root``."""
    if not path or not allowed_root:
        raise UnsafePathError("empty path")
    absolute = os.path.abspath(path)
    if os.path.islink(absolute):
        # Remove the link itself (never its target), if the link lives under the root.
        parent = os.path.realpath(os.path.dirname(absolute))
        if parent != os.path.realpath(allowed_root) and not is_within(parent, allowed_root):
            raise UnsafePathError(f"refusing to unlink {absolute}")
        log.info("Removing symlink %s", absolute)
        os.unlink(absolute)
        return
    if not os.path.exists(absolute):
        return
    if is_protected(absolute) or is_protected(allowed_root):
        raise UnsafePathError(f"refusing to delete protected path {absolute}")
    if not is_within(absolute, allowed_root):
        raise UnsafePathError(f"refusing to delete {absolute}: outside {allowed_root}")
    log.info("Deleting %s", absolute)
    shutil.rmtree(absolute)


def current_target(root: str) -> str | None:
    """Absolute path of the active version directory, or None."""
    link = os.path.join(root, "current")
    if not os.path.islink(link):
        return None
    target = os.path.realpath(link)
    return target if os.path.isdir(target) else None


def switch_current(root: str, version_dir: str) -> None:
    """Atomically point ``root/current`` at ``version_dir``."""
    if not is_within(version_dir, os.path.join(root, "versions")):
        raise UnsafePathError(f"{version_dir} is not a version of {root}")
    relative = os.path.relpath(version_dir, root)
    tmp = os.path.join(root, f".current-{os.getpid()}-{int(time.time() * 1000)}")
    os.symlink(relative, tmp)
    try:
        os.replace(tmp, os.path.join(root, "current"))
    except OSError:
        os.unlink(tmp)
        raise
    log.info("Activated %s", relative)


def tree_size(path: str, limit: int) -> int:
    total = 0
    for base, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                continue
            if total > limit:
                return total
    return total


def snapshot_data(root: str, label: str) -> str | None:
    """Copy ``root/data`` to ``root/backups/data-<label>``; None if nothing to back up."""
    data = os.path.join(root, "data")
    if not os.path.isdir(data) or not os.listdir(data):
        return None
    if tree_size(data, MAX_DATA_BACKUP_BYTES) > MAX_DATA_BACKUP_BYTES:
        log.warning("Data of %s is over %d MB; not snapshotting it", root,
                    MAX_DATA_BACKUP_BYTES // 1048576)
        return None
    backups = os.path.join(root, "backups")
    os.makedirs(backups, exist_ok=True)
    target = os.path.join(backups, f"data-{label}")
    if os.path.exists(target):
        safe_rmtree(target, backups)
    shutil.copytree(data, target, symlinks=True)
    log.info("Backed up app data to %s", target)
    return target


def restore_data(root: str, snapshot: str | None) -> None:
    if not snapshot or not os.path.isdir(snapshot):
        return
    data = os.path.join(root, "data")
    if os.path.exists(data):
        safe_rmtree(data, root)
    shutil.copytree(snapshot, data, symlinks=True)
    log.info("Restored app data from %s", snapshot)


def prune_versions(root: str, keep: int, protect: list[str]) -> list[str]:
    """Delete old version directories beyond ``keep``, never those in ``protect``."""
    versions = os.path.join(root, "versions")
    try:
        entries = [os.path.join(versions, e) for e in os.listdir(versions)]
    except FileNotFoundError:
        return []
    protected = {os.path.realpath(p) for p in protect if p}
    candidates = sorted((e for e in entries if os.path.isdir(e) and not os.path.islink(e)),
                        key=lambda e: os.path.getmtime(e), reverse=True)
    removed = []
    kept = 0
    for path in candidates:
        if os.path.realpath(path) in protected:
            kept += 1
            continue
        if kept < keep:
            kept += 1
            continue
        safe_rmtree(path, versions)
        removed.append(path)
    return removed
