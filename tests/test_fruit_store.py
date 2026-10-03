"""Fruit Store: an app's page, and uninstall -> delete data as two questions.

Runs the real screens, services, installer and registry on a temporary home;
only the daemon (lifecycle) and the update checker are fakes.
"""

import json
import os
from unittest.mock import Mock

from helpers import TempHomeTestCase, make_package
from mfruitos.apps.registry import AppRegistry
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.tasks import TaskRunner
from mfruitos.launcher.ui.screens.dialogs import MessageScreen
from mfruitos.launcher.ui.screens.store import StoreAppScreen
from mfruitos.launcher.ui.screens.updater import InstallAppScreen
from mfruitos.system.settings import Settings
from mfruitos.updater.installer import Installer, InstallRequest


class FruitStoreTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        os_ = self.os = ScreenServices()
        os_.paths = self.paths
        os_.settings = Settings(None)
        os_.registry = AppRegistry(self.paths, os_.settings, "1.4.0")
        os_.installer = Installer(self.paths, "1.4.0", os_.settings, register=lambda m: None)
        os_.lifecycle = Mock()
        os_.lifecycle.unregister.return_value = True
        os_.updater = Mock()
        os_.updater.info.return_value = None
        os_.tasks = TaskRunner(lambda fn, *a: fn(*a))      # not started: runs inline
        os_.screens = []
        os_.push = os_.screens.append
        os_.pop = lambda: os_.screens.pop() if os_.screens else None
        os_.toast = Mock()
        os_.flush_settings = Mock()
        os_.refresh_registry = lambda query_daemon=False: os_.registry.refresh(None)
        os_.launch_app = Mock()
        os_.router_top = lambda: os_.screens[-1] if os_.screens else None

    def install_weather(self, data=True):
        src = make_package(os.path.join(self.tmp, "src"), app_id="weather")
        self.os.installer.run(InstallRequest(repository="", local_path=src))
        if data:
            with open(os.path.join(self.paths.app_root("weather"), "data", "notes.txt"), "w") as fp:
                fp.write("mine")
        self.os.settings.set("apps.installed_ids", ["weather"])
        self.os.refresh_registry()

    def page(self, app_id="weather"):
        screen = StoreAppScreen(self.os, app_id)
        screen.on_show()
        return screen

    def choose(self, screen, label):
        row = next(i for i in screen.items() if i.label == label)
        row.action()
        return self.os.screens[-1] if self.os.screens else None

    def answer(self, dialog, label):
        self.assertIsInstance(dialog, MessageScreen)
        next(i for i in dialog.items() if i.label == label).action()

    def test_an_installed_apps_page_offers_every_store_action(self):
        self.install_weather()
        labels = [i.label for i in self.page().items()]
        self.assertEqual(labels, ["Status", "Open", "Roll back", "Updates and versions",
                                  "Reset app", "Uninstall", "Back"])

    def test_uninstall_then_delete_are_two_separate_questions(self):
        self.install_weather()
        page = self.page()
        question = self.choose(page, "Uninstall")
        self.assertEqual(question.heading, "Uninstall Weather?")
        self.assertEqual([i.label for i in question.items()], ["Cancel", "Uninstall"])
        self.assertTrue(os.path.isdir(self.paths.app_root("weather")), "nothing before yes")
        self.answer(question, "Uninstall")
        # Gone from the device, data kept, and the second question asked.
        self.assertIsNone(self.os.registry.get("weather"))
        self.assertEqual([i.id for i in self.os.registry.leftovers()], ["weather"])
        self.os.lifecycle.unregister.assert_called_once_with("weather", "Weather")
        self.assertNotIn("weather", self.os.settings.get("apps.installed_ids"))
        second = self.os.screens[-1]
        self.assertEqual(second.heading, "Delete Weather data?")
        self.assertEqual([i.label for i in second.items()], ["Keep data", "Delete data"])
        self.os.screens[:] = [page, second]         # as the router has them
        self.answer(second, "Delete data")
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))
        self.assertEqual(self.os.registry.leftovers(), [])
        self.assertEqual(self.os.screens, [], "the app's page closes once it is gone")

    def test_keeping_the_data_leaves_it_in_the_store_to_delete_later(self):
        self.install_weather()
        self.answer(self.choose(self.page(), "Uninstall"), "Uninstall")
        self.os.screens.clear()                         # "Keep data"
        rows = InstallAppScreen(self.os).items()
        kept = next(i for i in rows if i.label == "Weather")
        self.assertEqual(kept.value, "Data kept")
        kept.action()
        page = self.os.screens[-1]
        page.on_show()
        self.assertEqual([i.label for i in page.items()], ["Status", "Delete data", "Back"])
        self.answer(self.choose(page, "Delete data"), "Delete data")
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))

    def test_an_app_without_data_is_not_asked_about_data(self):
        self.install_weather(data=False)
        self.answer(self.choose(self.page(), "Uninstall"), "Uninstall")
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))
        self.assertFalse(any(getattr(s, "heading", "") == "Delete Weather data?"
                             for s in self.os.screens))

    def test_reset_asks_then_empties_the_data_and_keeps_the_app(self):
        self.install_weather()
        question = self.choose(self.page(), "Reset app")
        self.assertEqual(os.listdir(os.path.join(self.paths.app_root("weather"), "data")),
                         ["notes.txt"], "nothing before yes")
        self.answer(question, "Reset")
        self.assertEqual(os.listdir(os.path.join(self.paths.app_root("weather"), "data")), [])
        self.assertIsNotNone(self.os.registry.get("weather"))

    def test_a_daemon_app_is_unregistered_and_its_own_files_are_never_touched(self):
        own = os.path.join(self.tmp, "example")
        os.makedirs(own)
        open(os.path.join(own, "wifi_config_app.py"), "w").close()
        registration = os.path.join(self.paths.daemon_apps_dir, "wifi.json")
        os.makedirs(self.paths.daemon_apps_dir, exist_ok=True)
        with open(registration, "w") as fp:
            json.dump({"app_id": "wifi", "display_name": "WiFi Config",
                       "launch_command": "python3 wifi_config_app.py", "cwd": own}, fp)
        adopted = os.path.join(self.paths.home, "adopted", "wifi")
        os.makedirs(adopted)
        with open(os.path.join(adopted, "registration.json"), "w") as fp:
            json.dump({"app_id": "wifi", "display_name": "WiFi Config"}, fp)
        self.os.lifecycle.unregister.side_effect = lambda app_id, name: os.remove(registration) or True
        self.os.refresh_registry()
        page = self.page("wifi")
        self.assertEqual([i.label for i in page.items()],
                         ["Status", "Open", "Updates and versions", "Uninstall", "Back"])
        question = self.choose(page, "Uninstall")
        self.assertIn("files in example stay", question.message)
        self.answer(question, "Uninstall")
        self.assertIsNone(self.os.registry.get("wifi"))
        self.answer(self.os.screens[-1], "Delete data")
        self.assertFalse(os.path.exists(adopted))
        self.assertTrue(os.path.isfile(os.path.join(own, "wifi_config_app.py")))

    def test_a_daemon_that_refuses_leaves_the_app_installed(self):
        os.makedirs(self.paths.daemon_apps_dir, exist_ok=True)
        open(os.path.join(self.tmp, "main.py"), "w").close()
        with open(os.path.join(self.paths.daemon_apps_dir, "game.json"), "w") as fp:
            json.dump({"app_id": "game", "display_name": "Game",
                       "launch_command": "python3 main.py", "cwd": self.tmp}, fp)
        self.os.lifecycle.unregister.return_value = False
        self.os.show_message = Mock()
        self.os.refresh_registry()
        self.answer(self.choose(self.page("game"), "Uninstall"), "Uninstall")
        self.assertIsNotNone(self.os.registry.get("game"))
        self.os.show_message.assert_called_once()


class StoreControlTests(TempHomeTestCase):
    """``mfruitctl uninstall|delete|reset|rollback`` call the same services."""

    def setUp(self):
        super().setUp()
        from types import SimpleNamespace
        from mfruitos.apps.registry import AppEntry
        from mfruitos.launcher import ctl_handlers
        self.handle = ctl_handlers.handle
        self.entries = {"demo": AppEntry("demo", "Demo", "os", previous_version="0.9")}
        self.kept = {}
        self.rt = SimpleNamespace(registry=Mock(), tasks=Mock(), router=Mock(),
                                  uninstall_app=Mock(return_value=True),
                                  delete_app_data=Mock(return_value=True),
                                  reset_app=Mock(return_value=True),
                                  rollback_app=Mock(return_value=True))
        self.rt.registry.get.side_effect = self.entries.get
        self.rt.registry.leftover.side_effect = self.kept.get
        self.rt.tasks.busy.return_value = False
        self.rt.tasks.active = {}

    def test_each_command_reaches_its_service(self):
        for command, service in (("uninstall", self.rt.uninstall_app),
                                 ("reset", self.rt.reset_app),
                                 ("rollback", self.rt.rollback_app)):
            with self.subTest(command=command):
                self.assertTrue(self.handle(self.rt, command, {"app_id": "demo"})["ok"])
                service.assert_called_once_with("demo")
        self.kept["gone"] = object()
        self.assertTrue(self.handle(self.rt, "delete", {"app_id": "gone"})["ok"])
        self.rt.delete_app_data.assert_called_once_with("gone")

    def test_refusals(self):
        self.assertFalse(self.handle(self.rt, "uninstall", {"app_id": "nope"})["ok"])
        self.assertFalse(self.handle(self.rt, "delete", {"app_id": "demo"})["ok"],
                         "installed: uninstall first")
        self.assertFalse(self.handle(self.rt, "delete", {"app_id": "nope"})["ok"],
                         "nothing kept")
        self.entries["new"] = type(self.entries["demo"])("new", "New", "os")
        self.assertFalse(self.handle(self.rt, "rollback", {"app_id": "new"})["ok"])
        self.rt.rollback_app.return_value = False      # refused (e.g. the app is open)
        self.assertFalse(self.handle(self.rt, "rollback", {"app_id": "demo"})["ok"])
        self.rt.tasks.busy.return_value = True
        self.assertFalse(self.handle(self.rt, "uninstall", {"app_id": "demo"})["ok"])
        self.rt.uninstall_app.assert_not_called()
        self.rt.delete_app_data.assert_not_called()
