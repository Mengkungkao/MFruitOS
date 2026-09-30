"""Catalogue navigation and restoration without a running hardware daemon."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from helpers import TempHomeTestCase
from mfruitos.apps.registry import AppEntry, AppRegistry
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.ui.screens.apps import AppDetailScreen
from mfruitos.launcher.ui.screens.home import HomeScreen
from mfruitos.launcher.ui.screens.settings import WifiScreen
from mfruitos.launcher.ui.screens.updater import InstallAppScreen, UpdaterScreen
from mfruitos.system.settings import Settings


class AppInstallerScreenTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.os = ScreenServices()
        self.os.settings = Settings(None)
        self.os.settings.set("apps.clean_menu", True)
        self.os.registry = AppRegistry(self.paths, self.os.settings, "1.4.0")
        self.os.push = Mock()
        self.os.pop = Mock()
        self.os.toast = Mock()
        self.os.flush_settings = Mock()
        self.os.refresh_registry = Mock()
        self.os.updater = Mock()
        self.os.home_screen = HomeScreen(self.os)
        self.os.home_screen.focus_key = Mock()
        self.os.start_job = Mock()
        self.item = dict(id="demo", name="Demo", description="Example app")
        self.catalog = patch("mfruitos.updater.catalog.entries", return_value=[self.item])
        self.catalog.start()
        self.addCleanup(self.catalog.stop)

    def saved(self, app_id="demo", **kwargs):
        entry = AppEntry(app_id, app_id.title(), "daemon", **kwargs)
        self.os.registry._entries[app_id] = entry
        return entry

    def rows(self):
        return InstallAppScreen(self.os).items()

    def test_home_opens_installer_without_starting_an_install(self):
        entry = next(e for e in self.os.home_screen.entries() if e.key == "os.installer")
        self.os.open_home_entry(entry)
        self.assertIsInstance(self.os.push.call_args.args[0], InstallAppScreen)
        self.os.start_job.assert_not_called()

    def test_download_requires_confirmation_and_success_adds_app(self):
        row = self.rows()[0]
        self.assertEqual(row.value, "Download")
        row.action()
        self.os.start_job.assert_not_called()
        dialog = self.os.push.call_args.args[0]
        self.assertEqual([i.label for i in dialog.items()], ["Cancel", "Install"])
        dialog.items()[1].action()
        call = self.os.start_job.call_args
        self.assertEqual(self.os.settings.get("apps.installed_ids"), [])
        progress = Mock()
        call.args[1](progress)
        self.os.updater.install_catalog.assert_called_once_with("demo", progress)
        call.kwargs["on_success"](SimpleNamespace(app_id="demo", version="1.0.0"))
        self.assertEqual(self.os.settings.get("apps.installed_ids"), ["demo"])
        self.os.updater.mark_installed.assert_called_once_with("demo", "1.0.0")
        self.os.refresh_registry.assert_called_once_with(query_daemon=True)

    def test_saved_app_is_restored_without_downloading_or_autostart(self):
        self.saved(enabled=False)
        self.os.settings.set("apps.order", ["other", "demo"])
        self.os.settings.set("apps.installed_ids", ["other"])
        self.os.settings.set_app_flag("demo", "hidden", True)
        self.os.settings.set_app_flag("demo", "autostart", True)
        row = self.rows()[0]
        self.assertEqual(row.value, "On device")
        row.action()
        dialog = self.os.push.call_args.args[0]
        self.assertEqual(dialog.items()[1].label, "Add")
        self.assertEqual(self.os.settings.get("apps.installed_ids"), ["other"])
        dialog.items()[1].action()
        self.os.restore_catalog_app("demo")  # Repeated requests do not duplicate IDs.
        self.assertEqual(self.os.settings.get("apps.installed_ids"), ["other", "demo"])
        self.assertEqual(self.os.settings.get("apps.order"), ["other", "demo"])
        flags = self.os.settings.app_flags("demo")
        self.assertTrue(flags["enabled"])
        self.assertFalse(flags["hidden"])
        self.assertFalse(flags["autostart"])
        self.os.start_job.assert_not_called()

    def test_installed_app_opens_management(self):
        self.saved()
        self.os.settings.set("apps.installed_ids", ["demo"])
        row = self.rows()[0]
        self.assertEqual(row.value, "Installed")
        row.action()
        self.assertIsInstance(self.os.push.call_args.args[0], AppDetailScreen)
        self.os.start_job.assert_not_called()

    def test_restore_rechecks_missing_or_broken_files(self):
        for entry in (None, self.saved(broken="Working directory missing")):
            with self.subTest(entry=entry):
                self.os.registry._entries = {"demo": entry} if entry else {}
                self.os.restore_catalog_app("demo")
                self.assertEqual(self.os.settings.get("apps.installed_ids"), [])
        self.os.flush_settings.assert_not_called()
        self.os.start_job.assert_not_called()

    def test_catalogue_keeps_saved_apps_and_hides_internal_helpers(self):
        self.saved("custom")
        for app_id in ("connectwifi", "whisplay-wifi-config", "whisplay-run-test"):
            self.saved(app_id)
        self.saved("broken", broken="Missing files")
        labels = [i.label for i in self.rows()]
        self.assertEqual(labels, ["Demo", "Custom", "More sources", "Local packages", "Updates", "Back"])
        next(i for i in self.rows() if i.label == "Updates").action()
        self.assertIsInstance(self.os.push.call_args.args[0], UpdaterScreen)

    def test_wifi_uses_connectwifi_or_reports_missing_install(self):
        self.os.launch_app = Mock()
        self.os.open_system_page = Mock()
        self.os.show_message = Mock()
        screen = WifiScreen(self.os)
        self.saved("connectwifi")
        screen.choose_network()
        self.os.launch_app.assert_called_once_with("connectwifi", source="settings")
        self.os.registry._entries.clear()
        screen.choose_network()
        self.os.show_message.assert_called_once_with(
            "Wi-Fi", "Install Connect WiFi to choose a network.")
        self.os.open_system_page.assert_not_called()
