"""Small offline catalogue of reviewed, checksum-pinned app source packages.

Two kinds of entry:

* **adopted** (default): an app that is not a native MFruit OS package. Its
  own installers are replaced by generated ``manifest.json``, ``install.sh``
  (a venv with ``dependencies``), ``run.sh`` and ``test.sh`` (``prepare``).
* **native** (``"native": true``): an MFruit OS package with its own manifest
  and hooks, installed exactly as published. The pinned source must carry
  the entry's ``id`` and ``version``; nothing in it is rewritten.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
import shlex
import shutil

from mfruitos.apps.manifest import is_safe_relative_path
from mfruitos.paths import package_root
from mfruitos.updater import rollback


class CatalogError(ValueError):
    pass


@lru_cache(maxsize=1)
def entries() -> list[dict]:
    with open(Path(package_root()) / 'config/catalog.json', encoding='utf-8') as fp:
        return json.load(fp)


# Device capabilities a catalogue app can need, and who sets them up.
REQUIREMENTS = {"radio": "LoRa radio (scripts/setup-radio.sh)"}


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


def get(app_id: str) -> dict:
    for item in entries():
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
