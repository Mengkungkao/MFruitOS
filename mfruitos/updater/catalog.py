"""Small offline catalogue of reviewed, checksum-pinned app source packages."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import shlex
import shutil

from mfruitos.paths import package_root


@lru_cache(maxsize=1)
def entries() -> list[dict]:
    with open(Path(package_root()) / 'config/catalog.json', encoding='utf-8') as fp:
        return json.load(fp)


def get(app_id: str) -> dict:
    return next(item for item in entries() if item['id'] == app_id)


def prepare(directory: str, item: dict) -> None:
    """Replace standalone system installers with package-local dependency setup."""
    root = Path(directory)
    # Only used after verifying the exact source archive pinned in our catalogue.
    for name in ['install.sh', 'update.sh', 'uninstall.sh', 'run.sh', 'test.sh', 'manifest.json']:
        path = root / name
        if path.exists() or path.is_symlink():
            path.unlink()
    sdk = root / 'mfruit_sdk'
    if sdk.is_symlink():
        sdk.unlink()
    elif sdk.exists():
        shutil.rmtree(sdk)
    shutil.copytree(Path(package_root()) / 'mfruitos/sdk', sdk,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    manifest = dict(id=item['id'], name=item['name'], description=item['description'],
                    version='1.0.0', repository=item['repository'], entrypoint='run.sh',
                    min_os_version='1.4.0', exit_gesture='none', disable_esc_exit_key=True,
                    persist=['config.yaml', '.env', 'models'], test='test.sh')
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (root / 'install.sh').write_text('#!/bin/sh\nset -eu\n'
        'python3 -m venv --system-site-packages .venv\n'
        '.venv/bin/python -m pip install --disable-pip-version-check ' +
        ' '.join(shlex.quote(d) for d in item['dependencies']) + '\n')
    (root / 'run.sh').write_text('#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\n'
        'exec .venv/bin/python ' + item['entry'] + ' "$@"\n')
    (root / 'test.sh').write_text('#!/bin/sh\nset -eu\n'
        '.venv/bin/python -m compileall -q . -x "[/]\\.venv[/]"\n'
        '.venv/bin/python -c "import PIL, yaml, mfruit_sdk"\n')
    for name in ['install.sh', 'run.sh', 'test.sh']:
        (root / name).chmod(0o755)
