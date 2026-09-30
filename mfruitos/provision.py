"""Install the offline Wi-Fi component and establish a reversible initial menu."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from mfruitos import __version__
from mfruitos.paths import Paths, package_root
from mfruitos.system.settings import Settings, atomic_write_json
from mfruitos.updater.installer import Installer, InstallRequest

STARTER_APPS = ['whisplay-jump', 'whisplay-flappy-bird']


def provision(paths: Paths, whisplay: str) -> None:
    paths.ensure()
    settings = Settings(paths.settings_file)
    settings.load()
    backup = Path(paths.home) / 'backups' / ('first-install-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, exist_ok=True)
    if os.path.isfile(paths.settings_file):
        shutil.copy2(paths.settings_file, backup / 'settings.json')
    source = Path(package_root()) / 'bundled/connectwifi'
    with tempfile.TemporaryDirectory(prefix='mfruit-wifi-') as temp:
        package = Path(temp) / 'connectwifi'
        shutil.copytree(source, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(Path(package_root()) / 'mfruitos/sdk', package / 'mfruit_sdk',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        Installer(paths, __version__, settings).run(InstallRequest(repository='', local_path=str(package)))
    # Register the two shipped Whisplay games if the daemon hasn't done so yet.
    # Existing registrations and adopted launch commands are deliberately kept.
    for app_id in STARTER_APPS:
        target = Path(paths.daemon_apps_dir) / (app_id + '.json')
        template = Path(whisplay) / 'daemon/default_apps' / (app_id + '.json')
        if not target.exists() and template.is_file():
            raw = template.read_text().replace('__EXAMPLE_DIR__', str(Path(whisplay) / 'example'))
            atomic_write_json(str(target), json.loads(raw))
    settings.set('apps.clean_menu', True)
    settings.set('apps.installed_ids', STARTER_APPS + ['connectwifi'])
    settings.set('apps.order', STARTER_APPS)
    settings.set('apps.default_app', '')
    settings.set('system.show_system_pages_on_home', False)
    for app_id in list(settings.section('applications')) + STARTER_APPS + ['connectwifi']:
        settings.set_app_flag(app_id, 'autostart', False)
        if app_id in STARTER_APPS + ['connectwifi']:
            settings.set_app_flag(app_id, 'enabled', True)
            settings.set_app_flag(app_id, 'hidden', app_id == 'connectwifi')
    settings.save()
    (Path(paths.state_dir) / 'launch-policy').write_text('gate\n')
    print('Wi-Fi installed; initial Apps menu: Jump Game, Flappy Bird, App installer, Settings.')
    print('Existing files/data preserved. Previous settings:', backup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    parser.add_argument('--daemon-home', required=True)
    parser.add_argument('--whisplay', required=True)
    args = parser.parse_args()
    provision(Paths(args.home, args.daemon_home), args.whisplay)
