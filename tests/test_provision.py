import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from helpers import TempHomeTestCase
from mfruitos.apps.registry import AppRegistry
from mfruitos.provision import STARTER_APPS, provision
from mfruitos.system.settings import Settings
from mfruitos.updater.installer import InstallError


class ProvisionTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.whisplay = Path(self.tmp) / 'Whisplay example'
        self.marker = Path(self.paths.state_dir) / 'provisioned.json'
        self.settings = Settings(self.paths.settings_file)
        self.settings.save()
        install_patch = patch('mfruitos.provision.Installer.run', side_effect=self.install_wifi)
        self.install = install_patch.start()
        self.addCleanup(install_patch.stop)
        print_patch = patch('builtins.print')
        print_patch.start()
        self.addCleanup(print_patch.stop)

    def install_wifi(self, request):
        package = Path(request.local_path)
        self.assertEqual(request.app_id, 'connectwifi')
        self.assertTrue((package / 'manifest.json').is_file())
        self.assertTrue((package / 'mfruit_sdk/__init__.py').is_file())
        # Model the installer's completed activation without running shell scripts
        # or requiring symlink privileges on the host running these unit tests.
        root = Path(self.paths.app_root('connectwifi'))
        root.mkdir()
        (root / 'installed.txt').write_text('bundled Wi-Fi', encoding='utf-8')

    def reload_settings(self):
        settings = Settings(self.paths.settings_file)
        settings.load()
        return settings

    def template(self, app_id):
        return self.write_json(str(self.whisplay / 'daemon/default_apps' / (app_id + '.json')), {
            'app_id': app_id, 'display_name': app_id, 'cwd': '__EXAMPLE_DIR__',
            'launch_command': 'python3 "__EXAMPLE_DIR__/game.py"',
        })

    def registration(self, app_id, filename=None):
        return self.write_json(os.path.join(self.paths.daemon_apps_dir, filename or app_id + '.json'), {
            'app_id': app_id, 'display_name': app_id,
            'cwd': self.tmp, 'launch_command': 'custom-command ' + app_id,
        })

    def test_first_install_adds_available_starters_and_offline_wifi(self):
        original = Path(self.paths.settings_file).read_bytes()
        for app_id in STARTER_APPS:
            self.template(app_id)
        self.registration('unrelated')
        provision(self.paths, str(self.whisplay), first_install=True)
        settings = self.reload_settings()
        self.assertTrue(settings.get('apps.clean_menu'))
        self.assertEqual(settings.get('apps.installed_ids'), STARTER_APPS + ['connectwifi'])
        self.assertEqual(settings.get('apps.order'), STARTER_APPS)
        self.assertTrue(settings.app_flags('connectwifi')['hidden'])
        for app_id in STARTER_APPS + ['connectwifi']:
            self.assertTrue(settings.app_flags(app_id)['enabled'])
            self.assertFalse(settings.app_flags(app_id)['autostart'])
        self.assertEqual(self.install.call_count, 1)
        self.assertTrue(self.marker.is_file())
        self.assertEqual((Path(self.paths.state_dir) / 'launch-policy').read_text(), 'gate\n')
        backups = list((Path(self.paths.home) / 'backups').glob('first-install-*/settings.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        for app_id in STARTER_APPS:
            raw = json.loads((Path(self.paths.daemon_apps_dir) / (app_id + '.json')).read_text())
            self.assertEqual(raw['cwd'], str(self.whisplay / 'example'))
        registry = AppRegistry(self.paths, settings, '1.4.0')
        registry.refresh(None)
        self.assertFalse(registry.get('unrelated').enabled)

    def test_repeat_first_install_preserves_user_preferences_and_app_data(self):
        self.template(STARTER_APPS[0])
        provision(self.paths, str(self.whisplay), first_install=True)
        settings = self.reload_settings()
        settings.set('apps.installed_ids', ['weather', 'connectwifi'])
        settings.set('apps.order', ['weather'])
        settings.set('apps.default_app', 'weather')
        settings.set('system.show_system_pages_on_home', True)
        settings.set_app_flag('weather', 'autostart', True)
        settings.set_app_flag('connectwifi', 'enabled', False)
        settings.set_app_flag('connectwifi', 'hidden', False)
        settings.save()
        original = Path(self.paths.settings_file).read_bytes()
        root = Path(self.paths.app_root('connectwifi'))
        (root / 'installed.txt').write_text('newer local Wi-Fi', encoding='utf-8')
        (root / 'data').mkdir()
        (root / 'data/networks.json').write_text('private user data', encoding='utf-8')
        policy = Path(self.paths.state_dir) / 'launch-policy'
        policy.write_text('desktop\n', encoding='utf-8')
        (Path(self.paths.daemon_apps_dir) / (STARTER_APPS[0] + '.json')).unlink()
        provision(self.paths, str(self.whisplay), first_install=True)
        self.assertEqual(self.install.call_count, 1)
        self.assertEqual(Path(self.paths.settings_file).read_bytes(), original)
        self.assertEqual((root / 'installed.txt').read_text(), 'newer local Wi-Fi')
        self.assertEqual((root / 'data/networks.json').read_text(), 'private user data')
        self.assertEqual(policy.read_text(), 'desktop\n')
        self.assertFalse((Path(self.paths.daemon_apps_dir) / (STARTER_APPS[0] + '.json')).exists())

    def test_upgrade_installs_missing_wifi_without_resetting_settings(self):
        self.settings.set('apps.order', ['weather'])
        self.settings.set('apps.default_app', 'weather')
        self.settings.set_app_flag('weather', 'autostart', True)
        self.settings.save()
        original = Path(self.paths.settings_file).read_bytes()
        self.template(STARTER_APPS[0])
        provision(self.paths, str(self.whisplay))
        self.assertEqual(self.install.call_count, 1)
        self.assertEqual(Path(self.paths.settings_file).read_bytes(), original)
        self.assertEqual(list(Path(self.paths.daemon_apps_dir).iterdir()), [])
        self.assertFalse((Path(self.paths.home) / 'backups').exists())

    def test_upgrade_preserves_existing_daemon_wifi_with_nonstandard_filename(self):
        registration = Path(self.registration('connectwifi', 'legacy-wifi.json'))
        original = registration.read_bytes()
        provision(self.paths, str(self.whisplay))
        self.install.assert_not_called()
        self.assertEqual(registration.read_bytes(), original)
        self.assertFalse(Path(self.paths.app_root('connectwifi')).exists())

    def test_upgrade_preserves_adopted_wifi_and_incomplete_managed_data(self):
        for location in (Path(self.paths.home) / 'adopted/connectwifi',
                         Path(self.paths.app_root('connectwifi'))):
            with self.subTest(location=location):
                location.mkdir(parents=True)
                data = location / 'preferences.json'
                data.write_text('keep this', encoding='utf-8')
                provision(self.paths, str(self.whisplay))
                self.assertEqual(data.read_text(), 'keep this')
                data.unlink()
                location.rmdir()
        self.install.assert_not_called()

    def test_wifi_registration_whose_folder_is_gone_gets_the_bundled_app(self):
        # Orange Pi, 2026-10-04: adopted ConnectWifi checkout removed, Wi-Fi app broken.
        gone = os.path.join(self.tmp, 'ConnectWifi')
        registration = Path(self.write_json(os.path.join(self.paths.daemon_apps_dir, 'connectwifi.json'), {
            'app_id': 'connectwifi', 'display_name': 'Connect WiFi', 'cwd': gone,
            'launch_command': '/home/user/.whisplay-os/bin/mfruit-run connectwifi'}))
        adopted = Path(self.paths.home) / 'adopted/connectwifi'
        adopted.mkdir(parents=True)
        (adopted / 'cwd').write_text(gone, encoding='utf-8')
        (adopted / 'registration.json').write_text('{"cwd": "%s"}' % gone, encoding='utf-8')
        provision(self.paths, str(self.whisplay))
        self.assertEqual(self.install.call_count, 1)
        # The records themselves are left alone (uninstall restores them; KI-8).
        self.assertTrue(registration.is_file())
        self.assertTrue((adopted / 'registration.json').is_file())

    def test_wifi_registration_whose_folder_exists_is_kept(self):
        folder = os.path.join(self.tmp, 'ConnectWifi')
        os.makedirs(folder)
        self.write_json(os.path.join(self.paths.daemon_apps_dir, 'connectwifi.json'), {
            'app_id': 'connectwifi', 'display_name': 'Connect WiFi', 'cwd': folder,
            'launch_command': folder + '/run.sh'})
        adopted = Path(self.paths.home) / 'adopted/connectwifi'
        adopted.mkdir(parents=True)
        (adopted / 'cwd').write_text(folder, encoding='utf-8')
        provision(self.paths, str(self.whisplay))
        self.install.assert_not_called()

    def test_first_install_preserves_existing_starter_registration(self):
        self.template(STARTER_APPS[0])
        registration = Path(self.registration(STARTER_APPS[0], 'adopted-game.json'))
        original = registration.read_bytes()
        provision(self.paths, str(self.whisplay), first_install=True)
        self.assertEqual(registration.read_bytes(), original)
        self.assertFalse((Path(self.paths.daemon_apps_dir) / (STARTER_APPS[0] + '.json')).exists())
        self.assertEqual(self.reload_settings().get('apps.installed_ids'), [STARTER_APPS[0], 'connectwifi'])

    def test_missing_or_invalid_starters_are_not_added_to_menu(self):
        bad = Path(self.template(STARTER_APPS[0]))
        bad.write_text('{broken', encoding='utf-8')
        provision(self.paths, str(self.whisplay), first_install=True)
        self.assertEqual(self.reload_settings().get('apps.installed_ids'), ['connectwifi'])
        self.assertEqual(self.reload_settings().get('apps.order'), [])
        self.assertEqual(list(Path(self.paths.daemon_apps_dir).iterdir()), [])

    def test_wrong_starter_id_is_not_registered(self):
        target = self.template(STARTER_APPS[0])
        self.write_json(target, {'app_id': 'unexpected'})
        provision(self.paths, str(self.whisplay), first_install=True)
        self.assertEqual(self.reload_settings().get('apps.installed_ids'), ['connectwifi'])
        self.assertEqual(list(Path(self.paths.daemon_apps_dir).iterdir()), [])

    def test_install_failure_keeps_settings_and_allows_retry(self):
        original = Path(self.paths.settings_file).read_bytes()
        self.install.side_effect = InstallError('install', 'test failure')
        with self.assertRaises(InstallError):
            provision(self.paths, str(self.whisplay), first_install=True)
        self.assertEqual(Path(self.paths.settings_file).read_bytes(), original)
        self.assertFalse(self.marker.exists())

    def test_settings_save_failure_does_not_mark_setup_complete(self):
        with patch('mfruitos.provision.Settings.save', return_value=False):
            with self.assertRaises(OSError):
                provision(self.paths, str(self.whisplay), first_install=True)
        self.assertFalse(self.marker.exists())

    def test_invalid_settings_do_not_get_replaced_by_provisioning(self):
        self.write_json(self.paths.settings_file, {'apps': {'installed_ids': ['../bad']}})
        original = Path(self.paths.settings_file).read_bytes()
        with self.assertRaises(ValueError):
            provision(self.paths, str(self.whisplay), first_install=True)
        self.install.assert_not_called()
        self.assertEqual(Path(self.paths.settings_file).read_bytes(), original)
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
