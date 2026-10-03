"""Catalogue navigation and restoration without a running hardware daemon."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from helpers import TempHomeTestCase
from mfruitos.apps.registry import AppEntry, AppRegistry
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.ui.screens.apps import AppDetailScreen
from mfruitos.launcher.ui.screens.home import HomeScreen
from mfruitos.launcher.ui.screens.settings import WifiScreen
from mfruitos.launcher.ui.screens.store import StoreAppScreen
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

    def test_broken_catalogue_app_is_offered_for_repair_not_shown_installed(self):
        # The registration exists but the app's folder is gone (seen on the Pi):
        # "Installed" was a dead end; Repair reinstalls from the pinned source.
        self.saved(broken="Working directory missing")
        self.os.settings.set("apps.installed_ids", ["demo"])
        row = self.rows()[0]
        self.assertEqual(row.value, "Repair")
        row.action()
        dialog = self.os.push.call_args.args[0]
        self.assertNotIsInstance(dialog, AppDetailScreen)
        self.assertEqual([i.label for i in dialog.items()], ["Cancel", "Repair"])
        dialog.items()[1].action()
        progress = Mock()
        self.os.start_job.call_args.args[1](progress)
        self.os.updater.install_catalog.assert_called_once_with("demo", progress)

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
        self.assertIsInstance(self.os.push.call_args.args[0], StoreAppScreen)
        self.os.start_job.assert_not_called()

    def test_restore_rechecks_missing_or_broken_files(self):
        for entry in (None, self.saved(broken="Working directory missing")):
            with self.subTest(entry=entry):
                self.os.registry._entries = {"demo": entry} if entry else {}
                self.os.restore_catalog_app("demo")
                self.assertEqual(self.os.settings.get("apps.installed_ids"), [])
        self.os.flush_settings.assert_not_called()
        self.os.start_job.assert_not_called()

    def test_store_lists_every_app_on_the_device_except_settings_apps(self):
        # No app IDs are special-cased: a leftover daemon app (WiFi Config) or a
        # broken one is listed, so it can be uninstalled from its page.
        self.saved("custom")
        for app_id in ("connectwifi", "whisplay-wifi-config"):
            self.saved(app_id)
        self.saved("broken", broken="App files missing (wifi_config_app.py)")
        rows = self.rows()
        labels = [i.label for i in rows]
        self.assertEqual(labels, ["Demo", "Broken", "Custom", "Whisplay-Wifi-Config",
                                  "Update apps", "More sources", "Local packages", "Back"])
        broken = rows[labels.index("Broken")]
        self.assertEqual((broken.value, broken.subtitle),
                         ("Problem", "App files missing (wifi_config_app.py)"))
        broken.action()
        self.assertIsInstance(self.os.push.call_args.args[0], StoreAppScreen)
        next(i for i in self.rows() if i.label == "Update apps").action()
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


class CatalogControlTests(TempHomeTestCase):
    """``mfruitctl catalog``: the App installer's Install/Repair from a shell."""

    def setUp(self):
        super().setUp()
        from mfruitos.launcher import ctl_handlers
        self.handle = ctl_handlers.handle
        self.rt = SimpleNamespace(registry=Mock(), tasks=Mock(), router=Mock(),
                                  install_catalog_app=Mock())
        self.rt.tasks.busy.return_value = False
        self.rt.tasks.active = {}
        items = [dict(id="demo", name="Demo", description=""), dict(id="other", name="Other", description="")]
        self.catalog = patch("mfruitos.updater.catalog.entries", return_value=items)
        self.catalog.start()
        self.addCleanup(self.catalog.stop)
        self.entries = {"demo": AppEntry("demo", "Demo", "daemon", broken="Working directory missing")}
        self.rt.registry.get.side_effect = self.entries.get

    def test_lists_status_of_each_catalogue_app(self):
        rows = self.handle(self.rt, "catalog", {})["catalog"]
        self.assertEqual([(r["id"], r["status"]) for r in rows], [("demo", "broken"), ("other", "available")])

    def test_installs_or_repairs_through_the_same_job_as_the_screen(self):
        self.assertTrue(self.handle(self.rt, "catalog", {"app_id": "demo"})["ok"])
        self.rt.install_catalog_app.assert_called_once_with("demo")

    def test_refuses_unknown_running_or_busy(self):
        self.assertFalse(self.handle(self.rt, "catalog", {"app_id": "nope"})["ok"])
        self.entries["other"] = AppEntry("other", "Other", "os", running=True)
        self.assertFalse(self.handle(self.rt, "catalog", {"app_id": "other"})["ok"])
        self.rt.tasks.busy.return_value = True
        self.assertFalse(self.handle(self.rt, "catalog", {"app_id": "demo"})["ok"])
        self.rt.install_catalog_app.assert_not_called()


class RadioRequirementTests(AppInstallerScreenTests):
    """Catalogue apps that need the LoRa radio say so before installing."""

    def setUp(self):
        super().setUp()
        self.item["requires"] = ["radio"]
        self.os.run_task = lambda name, fn, done, error=None, lane="quick": done(fn())

    def screen(self, problems):
        with patch("mfruitos.updater.catalog.missing_requirements", return_value=problems):
            screen = InstallAppScreen(self.os)
            screen.redraw = Mock()
            screen.on_show()
        return screen

    def test_missing_radio_setup_is_shown_and_explained_before_install(self):
        screen = self.screen(["The radio is not set up"])
        row = screen.items()[0]
        self.assertEqual((row.value, row.subtitle), ("Download", "Needs radio setup first"))
        row.action()
        dialog = self.os.push.call_args.args[0]
        self.assertIn("LoRa radio", dialog.message)
        self.assertEqual(dialog.items()[1].label, "Install")     # still installable

    def test_ready_radio_shows_the_normal_description(self):
        row = self.screen([]).items()[0]
        self.assertEqual(row.subtitle, "Example app")

    def test_shipped_catalogue_requirements_are_known(self):
        from mfruitos.updater import catalog
        self.catalog.stop()
        try:
            catalog.entries.cache_clear()
            needs = {item["id"]: catalog.requirements(item) for item in catalog.entries()}
        finally:
            self.catalog.start()
        self.assertEqual(needs["whisplay-lora-walkie"], ["radio"])
        self.assertEqual(needs["whisplay-lora-messenger"], ["radio"])
        self.assertEqual(needs["whisplay-crypto-dashboard"], [])
        with self.assertRaises(catalog.CatalogError):
            catalog.requirements({"id": "x", "requires": ["jetpack"]})
