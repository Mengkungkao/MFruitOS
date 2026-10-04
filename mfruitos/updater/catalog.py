"""Small offline catalogue of reviewed, checksum-pinned app source packages.

Two kinds of entry:

* **adopted** (default): an app that is not a native MFruit OS package. Its
  own installers are replaced by generated ``manifest.json``, ``install.sh``
  (a venv with ``dependencies``), ``run.sh`` and ``test.sh`` (``prepare``).
* **native** (``"native": true``): an MFruit OS package with its own manifest
  and hooks, installed exactly as published. The pinned source must carry
  the entry's ``id`` and ``version``; nothing in it is rewritten.

The list itself comes from two places. ``config/catalog.json`` ships with
this OS version; the Fruit Store also downloads the same file from the
default branch of ``system.repository`` (``updater.online_catalog``) and keeps
it in ``<home>/cache/catalog.json``, so new apps appear without an OS update.
Every entry is validated on load; one this OS version cannot install (unknown
requirement, newer ``min_os_version``, malformed) is left out and logged.
"""
from __future__ import annotations

from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import threading
import time

from mfruitos import __version__
from mfruitos.apps.manifest import ManifestError, is_safe_relative_path, normalize_repository
from mfruitos.paths import is_valid_app_id, package_root
from mfruitos.system.settings import atomic_write_json
from mfruitos.updater import rollback
from mfruitos.updater.github import GitHubError, check_url
from mfruitos.updater.version import parse_version

log = logging.getLogger(__name__)

CATALOG_PATH = "config/catalog.json"     # in the package and in the online repository
ONLINE_MAX_AGE = 300.0                   # seconds before the Store downloads it again
MAX_BYTES = 256 * 1024


class CatalogError(ValueError):
    pass


# Device capabilities a catalogue app can need, and who sets them up.
REQUIREMENTS = {"radio": "LoRa radio (scripts/setup-radio.sh)"}

_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def check_entry(item: object) -> dict:
    """Raise CatalogError unless this OS version can list and install ``item``."""
    if not isinstance(item, dict):
        raise CatalogError("entry is not an object")
    if not is_valid_app_id(item.get("id")):
        raise CatalogError(f"invalid id {item.get('id')!r}")
    for key, limit, required in (("name", 60, True), ("description", 200, False)):
        value = item.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (required and not value):
            raise CatalogError(f"invalid {key}")
    try:
        normalize_repository(item.get("repository"))
        check_url(item.get("url") if isinstance(item.get("url"), str) else "")
    except (ManifestError, GitHubError, TypeError) as exc:
        raise CatalogError(str(exc)) from exc
    if not isinstance(item.get("ref"), str) or not _HEX40.fullmatch(item["ref"]):
        raise CatalogError("ref must be a full commit id")
    if not isinstance(item.get("sha256"), str) or not _HEX64.fullmatch(item["sha256"]):
        raise CatalogError("sha256 must be 64 hex digits")
    if not isinstance(item.get("native", False), bool):
        raise CatalogError("native must be true or false")
    if is_native(item):
        if parse_version(item.get("version")) is None:
            raise CatalogError("a native entry needs a semantic version")
    else:
        dependencies = item.get("dependencies")
        if not isinstance(item.get("entry"), str) or not isinstance(dependencies, list) or \
                not all(isinstance(d, str) and 0 < len(d) <= 200 for d in dependencies):
            raise CatalogError("an adopted entry needs entry and dependencies")
    needs = item.get("requires", [])
    if not isinstance(needs, list) or not all(isinstance(n, str) for n in needs):
        raise CatalogError("requires must be a list of names")
    unknown = [n for n in needs if n not in REQUIREMENTS]
    if unknown:
        raise CatalogError(f"needs {unknown!r}, unknown to MFruit OS {__version__}")
    min_os = item.get("min_os_version")
    if min_os is not None:
        required = parse_version(min_os)
        if required is None:
            raise CatalogError(f"min_os_version {min_os!r} is not a semantic version")
        if required > parse_version(__version__):
            raise CatalogError(f"needs MFruit OS {min_os} (running {__version__})")
    return item


def valid_entries(data: object, source: str, report: bool = True) -> list[dict]:
    """The entries of ``data`` this OS version can use; the others are logged."""
    if not isinstance(data, list):
        raise CatalogError(f"{source} is not a list")
    items, seen = [], set()
    for item in data:
        try:
            check_entry(item)
            if item["id"] in seen:
                raise CatalogError("duplicate id")
        except CatalogError as exc:
            name = item.get("id") if isinstance(item, dict) else None
            if report:
                log.warning("%s: leaving out %r: %s", source, name, exc)
            continue
        seen.add(item["id"])
        items.append(item)
    return items


@lru_cache(maxsize=1)
def bundled() -> list[dict]:
    """The list that ships with this OS version."""
    with open(Path(package_root()) / CATALOG_PATH, encoding='utf-8') as fp:
        return valid_entries(json.load(fp), "bundled catalogue")


def online_file(home: str) -> str:
    return os.path.join(home, "cache", "catalog.json")


_online_lock = threading.Lock()
_online_cache: dict = {}        # path -> ((mtime_ns, size), entries or None)


def online(home: str | None) -> dict | None:
    """The downloaded list as {"fetched_at", "entries"}, or None."""
    if not home:
        return None
    path = online_file(home)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    with _online_lock:
        cached = _online_cache.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        result = {"fetched_at": float(data.get("fetched_at", 0)),
                  "entries": valid_entries(data.get("entries"), "online catalogue")}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        log.warning("Ignoring the downloaded catalogue %s: %s", path, exc)
        result = None
    with _online_lock:
        _online_cache[path] = (key, result)
    return result


def entries(home: str | None = None) -> list[dict]:
    """The Fruit Store list: the one last downloaded when there is one,
    otherwise the one shipped with this OS version."""
    downloaded = online(home)
    return bundled() if downloaded is None else downloaded["entries"]


def source(home: str | None = None) -> str:
    return "bundled" if online(home) is None else "online"


def refresh(home: str, fetch, max_age: float = ONLINE_MAX_AGE) -> bool:
    """Download the online list with ``fetch()`` (bytes) and keep it when it
    is usable; a failure keeps the previous list. True when the list changed.
    Network and disk: call it off the UI thread."""
    path = online_file(home)
    try:
        if max_age and time.time() - os.stat(path).st_mtime < max_age:
            return False
    except OSError:
        pass
    raw = fetch()
    if len(raw) > MAX_BYTES:
        raise CatalogError("online catalogue is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CatalogError(f"online catalogue is not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CatalogError("online catalogue is not a list")
    if data and not valid_entries(data, "online catalogue", report=False):
        raise CatalogError("online catalogue has no entry this MFruit OS can use")
    previous = online(home)
    atomic_write_json(path, {"fetched_at": time.time(), "entries": data})
    changed = previous is None or previous["entries"] != entries(home)
    if changed:
        log.info("Fruit Store list updated from the online catalogue (%d apps)", len(entries(home)))
    return changed


def forget(home: str) -> bool:
    """Drop the downloaded list (online catalogue turned off). True when one existed."""
    try:
        os.remove(online_file(home))
    except FileNotFoundError:
        return False
    return True


def requirements(item: dict) -> list:
    needs = item.get("requires") or []
    unknown = [n for n in needs if n not in REQUIREMENTS]
    if unknown:
        raise CatalogError(f"Unknown requirement {unknown!r} for {item.get('id')!r}")
    return list(needs)


def missing_requirements(item: dict, home: str | None = None) -> list:
    """What the device still lacks for ``item`` (empty when ready). The
    radio check may run ldconfig: call it off the UI thread."""
    problems = []
    if "radio" in requirements(item):
        from mfruitos.hosts.lora.readiness import radio_status
        problems += radio_status(home)["problems"]
    return problems


def is_native(item: dict) -> bool:
    return bool(item.get("native"))


def _check_native(root: Path, item: dict) -> None:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"Native catalogue package has no readable manifest: {exc}")
    for key in ("id", "version"):
        if manifest.get(key) != item.get(key):
            raise CatalogError(f"Native catalogue package {key} is {manifest.get(key)!r}, "
                               f"expected {item.get(key)!r}")


def get(app_id: str, home: str | None = None) -> dict:
    for item in entries(home):
        if item['id'] == app_id:
            return item
    raise CatalogError(f"Unknown catalogue app: {app_id!r}")


def _entry_command(root: Path, entry: str) -> str:
    """Check the Python target as well as the run.sh wrapper we generate."""
    args = shlex.split(entry)
    if len(args) == 2 and args[0] == '-m' and re.fullmatch(
            r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', args[1]):
        module = args[1].replace('.', '/')
        candidates = [root / (module + '.py'), root / module / '__main__.py']
    elif len(args) == 1 and is_safe_relative_path(args[0]) and args[0].endswith('.py'):
        candidates = [root / args[0]]
    else:
        raise CatalogError(f"Invalid catalogue entry: {entry!r}")
    for path in candidates:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if path.is_file():
            return ' '.join(shlex.quote(arg) for arg in args)
    raise CatalogError(f"Catalogue entry is missing or outside the package: {entry!r}")


def _write_text(path: Path, text: str) -> None:
    # A package prepared on Windows must still contain runnable Linux scripts.
    with path.open('w', encoding='utf-8', newline='\n') as fp:
        fp.write(text)


def prepare(directory: str, item: dict) -> None:
    """Replace standalone system installers with package-local dependency setup.
    A native package is only checked: its own manifest and hooks are used."""
    root = Path(directory)
    if is_native(item):
        _check_native(root, item)
        return
    command = _entry_command(root, item['entry'])
    # Only used after verifying the exact source archive pinned in our catalogue.
    for name in ['install.sh', 'update.sh', 'uninstall.sh', 'run.sh', 'test.sh', 'manifest.json']:
        path = root / name
        if path.exists() or path.is_symlink():
            path.unlink()
    sdk = root / 'mfruit_sdk'
    if sdk.is_symlink():
        sdk.unlink()
    elif sdk.exists():
        rollback.safe_rmtree(str(sdk), str(root))
    shutil.copytree(Path(package_root()) / 'mfruitos/sdk', sdk,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    manifest = dict(id=item['id'], name=item['name'], description=item['description'],
                    version='1.0.0', repository=item['repository'], entrypoint='run.sh',
                    min_os_version='1.4.0', exit_gesture='none', disable_esc_exit_key=True,
                    persist=['config.yaml', '.env', 'models'], test='test.sh')
    _write_text(root / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    _write_text(root / 'install.sh', '#!/bin/sh\nset -eu\n'
        'python3 -m venv --system-site-packages .venv\n'
        '.venv/bin/python -m pip install --disable-pip-version-check ' +
        ' '.join(shlex.quote(d) for d in item['dependencies']) + '\n')
    _write_text(root / 'run.sh', '#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\n'
        'exec .venv/bin/python ' + command + ' "$@"\n')
    _write_text(root / 'test.sh', '#!/bin/sh\nset -eu\n'
        '.venv/bin/python -m compileall -q . -x "[/]\\.venv[/]"\n'
        '.venv/bin/python -c "import PIL, yaml, mfruit_sdk"\n')
    for name in ['install.sh', 'run.sh', 'test.sh']:
        (root / name).chmod(0o755)
