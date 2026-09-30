"""Install the offline Wi-Fi component and establish a reversible initial menu."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time

from mfruitos import __version__
from mfruitos.apps.registry import AppRegistry
from mfruitos.paths import Paths, package_root
from mfruitos.system.settings import Settings, atomic_write_json
from mfruitos.updater.installer import Installer, InstallRequest

STARTER_APPS = ['whisplay-jump', 'whisplay-flappy-bird']
log = logging.getLogger('mfruitos.provision')


def provision(paths: Paths, whisplay: str, first_install: bool = False) -> None:
    """Add missing offline components without resetting an existing installation.

    The installer detects a new installation before creating settings/current.
    A completion marker also prevents a repeated first-install invocation from
    resetting subsequent user choices.
    """
    paths.ensure()
    marker = Path(paths.state_dir) / 'provisioned.json'
    initialise_menu = first_install and not os.path.lexists(marker)
    settings = Settings(paths.settings_file)
    settings.load()
    if settings.load_errors:
        raise ValueError('Resolve the reported settings errors before provisioning')
    registrations = AppRegistry(paths, settings, __version__).daemon_registrations()
    # Preserve managed versions, app data, and adopted/local Wi-Fi installations.
    # Even an incomplete app directory may contain data that needs recovery.
    existing_wifi = (os.path.lexists(paths.app_root('connectwifi'))
                     or 'connectwifi' in registrations
                     or os.path.lexists(Path(paths.home) / 'adopted/connectwifi'))
    if not existing_wifi:
        source = Path(package_root()) / 'bundled/connectwifi'
        with tempfile.TemporaryDirectory(prefix='mfruit-wifi-') as temp:
            package = Path(temp) / 'connectwifi'
            shutil.copytree(source, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copytree(Path(package_root()) / 'mfruitos/sdk', package / 'mfruit_sdk',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            Installer(paths, __version__, settings).run(
                InstallRequest(repository='', local_path=str(package), app_id='connectwifi'))
    # Register the two shipped Whisplay games if the daemon hasn't done so yet.
    # Existing registrations and adopted launch commands are deliberately kept.
    starter_apps = []
    for app_id in STARTER_APPS if initialise_menu else []:
        target = Path(paths.daemon_apps_dir) / (app_id + '.json')
        template = Path(whisplay) / 'daemon/default_apps' / (app_id + '.json')
        if app_id in registrations or os.path.isdir(paths.app_root(app_id)):
            starter_apps.append(app_id)
        elif not os.path.lexists(target) and template.is_file():
            try:
                example = json.dumps(str(Path(whisplay) / 'example'))[1:-1]
                raw = json.loads(template.read_text(encoding='utf-8').replace('__EXAMPLE_DIR__', example))
                if not isinstance(raw, dict) or raw.get('app_id') != app_id:
                    raise ValueError('app_id does not match the starter app')
            except (OSError, ValueError) as exc:
                log.warning('Skipping starter app %s: %s', app_id, exc)
                continue
            atomic_write_json(str(target), raw)
            starter_apps.append(app_id)
    if initialise_menu:
        backup = None
        if os.path.isfile(paths.settings_file):
            backups = Path(paths.home) / 'backups'
            backups.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix='first-install-' + time.strftime('%Y%m%d-%H%M%S') + '-',
                                          dir=str(backups)))
            shutil.copy2(paths.settings_file, backup / 'settings.json')
        settings.set('apps.clean_menu', True)
        settings.set('apps.installed_ids', starter_apps + ['connectwifi'])
        settings.set('apps.order', starter_apps)
        settings.set('apps.default_app', '')
        settings.set('system.show_system_pages_on_home', False)
        for app_id in starter_apps + ['connectwifi']:
            settings.set_app_flag(app_id, 'autostart', False)
            settings.set_app_flag(app_id, 'enabled', True)
            settings.set_app_flag(app_id, 'hidden', app_id == 'connectwifi')
        if not settings.save() and settings.dirty:
            raise OSError('Could not save initial app settings')
        print('Initial Apps menu configured; available starter games:', len(starter_apps))
        if backup:
            print('Previous settings:', backup)
    try:
        with open(Path(paths.state_dir) / 'launch-policy', 'x', encoding='utf-8') as fp:
            fp.write('gate\n')
    except FileExistsError:
        pass  # Preserve an existing launch policy, including the developer mode.
    if not os.path.lexists(marker):
        atomic_write_json(str(marker), {'schema': 1})
    print('Offline Wi-Fi provisioning complete; existing apps and preferences preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    parser.add_argument('--daemon-home', required=True)
    parser.add_argument('--whisplay', required=True)
    parser.add_argument('--first-install', action='store_true')
    args = parser.parse_args()
    provision(Paths(args.home, args.daemon_home), args.whisplay, args.first_install)
