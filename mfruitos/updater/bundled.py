"""Apps shipped inside mFruit OS (``bundled/<id>/``, today the Wi-Fi app).

Provisioning installs a bundled app when the device has none
(``mfruitos/provision.py``). A System update only swaps the OS code, so
without this module an installed bundled app would stay at the version it
was first installed with. The launcher brings it up to the version the
running OS ships (``ScreenServices.update_bundled_apps``), through the same
installer job as any update: the previous version is kept, its data is
snapshotted, a failure rolls back.

An installed copy follows the bundle only when it came from a local package
(no repository: provisioning or a sideload), is older than the bundled
version, and was not rolled back from the bundled version or a newer one.
The launcher tries each bundled version once (``state/bundled-updates.json``):
a failure leaves the previous version working, and only a later bundled
version is tried again.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from mfruitos.paths import Paths, is_valid_app_id, package_root
from mfruitos.apps.registry import UNINSTALLED_FILE
from mfruitos.system.settings import atomic_write_json
from mfruitos.updater.installer import InstallRequest
from mfruitos.updater.version import parse_version

log = logging.getLogger(__name__)


def bundle_dir() -> Path:
    return Path(package_root()) / "bundled"


def versions() -> dict[str, str]:
    """``{app_id: version}`` of the apps this OS version ships."""
    found = {}
    try:
        folders = sorted(bundle_dir().iterdir())
    except OSError:
        return found
    for folder in folders:
        try:
            with open(folder / "manifest.json", encoding="utf-8") as fp:
                manifest = json.load(fp)
        except (OSError, ValueError):
            continue
        app_id = manifest.get("id") if isinstance(manifest, dict) else None
        if app_id == folder.name and is_valid_app_id(app_id) and parse_version(manifest.get("version")):
            found[app_id] = manifest["version"]
    return found


def package(app_id: str, workdir: str) -> str:
    """Copy the bundled app and the mFruit App SDK it needs into a package
    folder under ``workdir``; returns its path."""
    target = Path(workdir) / app_id
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(bundle_dir() / app_id, target, ignore=ignore)
    shutil.copytree(Path(package_root()) / "mfruitos/sdk", target / "mfruit_sdk", ignore=ignore)
    return str(target)


def install_request(app_id: str, package_path: str) -> InstallRequest:
    return InstallRequest(repository="", local_path=package_path, app_id=app_id)


def _record(paths: Paths, app_id: str) -> dict:
    try:
        with open(os.path.join(paths.app_root(app_id), "app.json"), encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def updates_due(paths: Paths) -> dict[str, str]:
    """``{app_id: bundled version}`` for installed copies that should follow."""
    due = {}
    for app_id, version in versions().items():
        root = paths.app_root(app_id)
        if not os.path.isdir(os.path.join(root, "current")) or \
                os.path.exists(os.path.join(root, UNINSTALLED_FILE)):
            continue
        record = _record(paths, app_id)
        if record.get("repository") or record.get("source") != "local":
            continue                      # installed from GitHub: its releases update it
        bundled = parse_version(version)
        installed = parse_version(record.get("installed_version"))
        if installed is None or installed >= bundled:
            continue
        rolled_back_from = parse_version(record.get("previous_version"))
        if rolled_back_from is not None and rolled_back_from >= bundled:
            continue                      # the user went back from this version
        due[app_id] = version
    return due


def _tried_file(paths: Paths) -> str:
    return os.path.join(paths.state_dir, "bundled-updates.json")


def tried(paths: Paths, app_id: str, version: str) -> bool:
    try:
        with open(_tried_file(paths), encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get(app_id) == version


def note_tried(paths: Paths, app_id: str, version: str) -> None:
    try:
        with open(_tried_file(paths), encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[app_id] = version
    atomic_write_json(_tried_file(paths), data)
