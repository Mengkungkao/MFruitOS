"""Catalogue apps queued for installation by the device installer.

``scripts/install.sh --radio`` queues the Fruit Store apps that need the
radio, so the device ends up with them without a visit to the Store. The
launcher installs them one at a time through the same job as the Store's
Install (``ScreenServices.install_pending_apps``): after it starts, after
each update check and on its update timer, once the app's device
requirements are met.

``<home>/state/pending-installs.json``: ``{"apps": {"<id>": {"attempts": n}}}``.
An app leaves the queue when it is installed or no longer in the catalogue;
after ``MAX_ATTEMPTS`` failed installs it is kept but not tried again (the
Store's Install still works).

    python3 -m mfruitos.updater.autoinstall add --requires radio [--home DIR]
    python3 -m mfruitos.updater.autoinstall add <app_id>... [--home DIR]
    python3 -m mfruitos.updater.autoinstall list [--home DIR]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from mfruitos.paths import is_valid_app_id, resolve_paths
from mfruitos.system.settings import atomic_write_json
from mfruitos.updater import catalog

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


def queue_file(home: str) -> str:
    return os.path.join(home, "state", "pending-installs.json")


def load(home: str) -> dict:
    """{app id: failed attempts so far}; empty when nothing is queued."""
    try:
        with open(queue_file(home), encoding="utf-8") as fp:
            apps = json.load(fp).get("apps", {})
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError) as exc:
        log.warning("Ignoring the install queue %s: %s", queue_file(home), exc)
        return {}
    if not isinstance(apps, dict):
        return {}
    return {app_id: int(info.get("attempts", 0)) if isinstance(info, dict) else 0
            for app_id, info in apps.items() if is_valid_app_id(app_id)}


def _save(home: str, apps: dict) -> None:
    path = queue_file(home)
    if not apps:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    atomic_write_json(path, {"apps": {app_id: {"attempts": n} for app_id, n in apps.items()}})


def add(home: str, app_ids) -> list:
    apps = load(home)
    added = []
    for app_id in app_ids:
        if is_valid_app_id(app_id) and app_id not in apps:
            apps[app_id] = 0
            added.append(app_id)
    _save(home, apps)
    return added


def remove(home: str, app_id: str) -> None:
    apps = load(home)
    if apps.pop(app_id, None) is not None:
        _save(home, apps)


def note_attempt(home: str, app_id: str) -> int:
    apps = load(home)
    apps[app_id] = apps.get(app_id, 0) + 1
    _save(home, apps)
    return apps[app_id]


def needing(requirement: str, home: str | None = None) -> list:
    """Catalogue apps that need ``requirement`` (e.g. ``radio``)."""
    return [item["id"] for item in catalog.entries(home)
            if requirement in catalog.requirements(item)]


def next_app(home: str, installed) -> tuple:
    """(the next app to install or None, ids to drop from the queue).
    The requirement check may run ldconfig: call it off the UI thread."""
    drop = []
    for app_id, attempts in load(home).items():
        if app_id in installed:
            drop.append(app_id)
            continue
        if attempts >= MAX_ATTEMPTS:
            continue
        try:
            item = catalog.get(app_id, home)
        except catalog.CatalogError:
            log.warning("Queued app %s is not in the Fruit Store list; dropping it", app_id)
            drop.append(app_id)
            continue
        missing = catalog.missing_requirements(item, home)
        if missing:
            log.info("Queued app %s waits for: %s", app_id, "; ".join(missing))
            continue
        return app_id, drop
    return None, drop


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m mfruitos.updater.autoinstall",
                                     description="Queue Fruit Store apps for installation")
    sub = parser.add_subparsers(dest="command", required=True)
    add_cmd = sub.add_parser("add", help="queue apps by id or by device requirement")
    add_cmd.add_argument("app_ids", nargs="*")
    add_cmd.add_argument("--requires", choices=sorted(catalog.REQUIREMENTS))
    add_cmd.add_argument("--home")
    list_cmd = sub.add_parser("list", help="show the queue")
    list_cmd.add_argument("--home")
    args = parser.parse_args(argv)
    home = resolve_paths(args.home).home
    if args.command == "list":
        print(json.dumps(load(home), indent=2))
        return 0
    ids = list(args.app_ids) + (needing(args.requires, home) if args.requires else [])
    unknown = [a for a in ids if not any(i["id"] == a for i in catalog.entries(home))]
    if unknown:
        print(f"not in the Fruit Store list: {' '.join(unknown)}", file=sys.stderr)
        return 2
    add(home, ids)
    names = {i["id"]: i["name"] for i in catalog.entries(home)}
    print(", ".join(names[a] for a in ids) if ids else "nothing to queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
