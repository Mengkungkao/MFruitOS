"""Apps shipped inside mFruit OS follow the OS version (updater/bundled.py)."""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import helpers
from helpers import ROOT, TempHomeTestCase
from mfruitos import __version__
from mfruitos.apps.registry import UNINSTALLED_FILE, AppRegistry
from mfruitos.launcher.runtime import Runtime
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.tasks import TaskRunner
from mfruitos.launcher.ui.screens.settings import SettingsScreen, WifiScreen
from mfruitos.system import system_info
from mfruitos.system.settings import Settings
from mfruitos.updater import bundled, rollback
from mfruitos.updater.installer import Installer

WIFI = "connectwifi"
SHIPPED = json.loads((Path(ROOT) / "bundled" / WIFI / "manifest.json").read_text())["version"]


class BundledAppsTestCase(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.settings = Settings(None)
        self.installer = Installer(self.paths, __version__, self.settings)

    def install_bundled_as(self, version):
        """The bundled Wi-Fi app as provisioning installed it, at ``version``."""
        with tempfile.TemporaryDirectory() as temp:
            package = bundled.package(WIFI, temp)
            manifest_path = os.path.join(package, "manifest.json")
            with open(manifest_path, encoding="utf-8") as fp:
                manifest = json.load(fp)
            manifest["version"] = version
            with open(manifest_path, "w", encoding="utf-8") as fp:
                json.dump(manifest, fp)
            return self.installer.run(bundled.install_request(WIFI, package))

    def record(self):
        return self.installer.read_record(self.paths.app_root(WIFI))

    def edit_record(self, **changes):
        record = self.record()
        record.update(changes)
        self.write_json(self.installer.record_path(self.paths.app_root(WIFI)), record)


class DueTests(BundledAppsTestCase):
    def test_the_shipped_wifi_app_is_listed_with_its_manifest_version(self):
        self.assertEqual(bundled.versions().get(WIFI), SHIPPED)

    def test_the_package_carries_the_sdk(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(bundled.package(WIFI, temp))
            self.assertTrue((package / "manifest.json").is_file())
            self.assertTrue((package / "mfruit_sdk" / "__init__.py").is_file())
            self.assertFalse(list(package.rglob("__pycache__")))

    def test_an_older_copy_from_the_bundle_is_due(self):
        self.install_bundled_as("1.0.0")
        self.assertEqual(bundled.updates_due(self.paths), {WIFI: SHIPPED})

    def test_an_up_to_date_copy_is_not(self):
        self.install_bundled_as(SHIPPED)
        self.assertEqual(bundled.updates_due(self.paths), {})

    def test_missing_github_rolled_back_or_uninstalled_copies_are_not(self):
        self.assertEqual(bundled.updates_due(self.paths), {})            # not installed
        self.install_bundled_as("1.0.0")
        self.assertEqual(bundled.updates_due(self.paths), {WIFI: SHIPPED})
        for changes in ({"repository": "https://github.com/someone/ConnectWifi", "source": "github"},
                        {"previous_version": SHIPPED},                  # rolled back from it
                        {"installed_version": "not a version"}):
            with self.subTest(changes=changes):
                before = self.record()
                self.edit_record(**changes)
                self.assertEqual(bundled.updates_due(self.paths), {})
                self.write_json(self.installer.record_path(self.paths.app_root(WIFI)), before)
        Path(self.paths.app_root(WIFI), UNINSTALLED_FILE).write_text("{}")
        self.assertEqual(bundled.updates_due(self.paths), {})


class LauncherUpdateTests(BundledAppsTestCase):
    def setUp(self):
        super().setUp()
        os_ = self.os = ScreenServices()
        os_.paths = self.paths
        os_.settings = self.settings
        os_.registry = AppRegistry(self.paths, self.settings, __version__)
        os_.installer = self.installer
        os_.tasks = TaskRunner(lambda fn, *a: fn(*a))      # not started: runs inline
        os_._app_in_use = Mock(return_value=False)
        os_.loop = Mock()
        os_.led = Mock()
        os_.backlight = Mock()
        os_.push = Mock()
        os_.toast = Mock()
        os_.refresh_registry = Mock()
        os_.request_render = Mock()

    def test_an_older_copy_is_updated_in_place_keeping_data_menu_place_and_the_previous_version(self):
        self.install_bundled_as("1.0.0")
        old_dir = rollback.current_target(self.paths.app_root(WIFI))
        data = Path(self.paths.app_root(WIFI), "data", "saved.txt")
        data.write_text("keep me")
        self.settings.set_app_flag(WIFI, "hidden", True)
        self.os.update_bundled_apps()
        record = self.record()
        self.assertEqual(record["installed_version"], SHIPPED)
        self.assertEqual(record["previous_version"], "1.0.0")
        self.assertEqual(record["previous_dir"], old_dir)
        self.assertTrue(os.path.isdir(old_dir))
        self.assertEqual(data.read_text(), "keep me")
        self.assertTrue(self.settings.app_flags(WIFI)["hidden"])
        self.assertEqual(self.os.push.call_count, 1)                   # one progress screen
        self.assertEqual(bundled.updates_due(self.paths), {})
        self.os.update_bundled_apps()
        self.assertEqual(self.os.push.call_count, 1)

    def test_not_over_an_open_app_or_another_job_and_once_per_version(self):
        self.install_bundled_as("1.0.0")
        self.os._app_in_use.return_value = True
        self.os.update_bundled_apps()
        self.os.tasks.active["jobs"] = "Install app"
        self.os._app_in_use.return_value = False
        self.os.update_bundled_apps()
        self.os.push.assert_not_called()
        self.assertEqual(self.record()["installed_version"], "1.0.0")
        del self.os.tasks.active["jobs"]
        bundled.note_tried(self.paths, WIFI, SHIPPED)     # this version failed before
        self.os.update_bundled_apps()
        self.os.push.assert_not_called()
        bundled.note_tried(self.paths, WIFI, "0.0.1")      # an older attempt does not count
        self.os.update_bundled_apps()
        self.assertEqual(self.record()["installed_version"], SHIPPED)


class WifiPageAfterChooseANetworkTests(TempHomeTestCase):
    """The Wi-Fi app opens without an Opening screen; when it closes, the
    Wi-Fi page reads the network again instead of showing the old one."""

    def test_the_wifi_page_reads_the_network_again_when_the_app_closes(self):
        rt = Runtime(self.paths, ROOT, socket_path=self.tmp + "/none.sock",
                     input_dir=helpers.NO_INPUT_DEVICES)
        rt.run_task = lambda name, fn, done=None, failed=None, lane="quick": done(fn())
        rt.refresh_registry = Mock()
        rt.bluetooth = Mock(available=Mock(return_value=False))
        network = {"ssid": "", "ip": ""}
        system_info_patch = [("wifi_ssid", lambda *a, **k: network["ssid"]),
                             ("local_ip", lambda *a, **k: network["ip"])]
        originals = {name: getattr(system_info, name) for name, _ in system_info_patch}
        for name, fake in system_info_patch:
            setattr(system_info, name, fake)
        self.addCleanup(lambda: [setattr(system_info, n, f) for n, f in originals.items()])
        rt.router.set_root(rt.home_screen)
        rt.router.push(SettingsScreen(rt))
        wifi = WifiScreen(rt)
        rt.router.push(wifi)
        self.assertEqual(wifi.ssid, "")
        network.update(ssid="Home", ip="192.168.0.130")            # joined in the app
        rt.on_session_ended(SimpleNamespace(app_id=WIFI, id="s1", kind="app", outcome="exited",
                                            detail="", pid=None))
        self.assertIs(rt.router.top, wifi)
        self.assertEqual((wifi.ssid, wifi.ip), ("Home", "192.168.0.130"))
