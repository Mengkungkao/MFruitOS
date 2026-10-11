"""Update offers follow the version actually installed, not a stale check.

Found on the Orange Pi Zero 2W (2026-10-12): after updating mFruit OS 1.4.0
to 1.5.1 from Settings > System update, the screen showed Current 1.5.1,
Latest 1.5.1 and still offered "Update now", because the cached check (made
on 1.4.0) said an update was available and nothing refreshed it.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

from helpers import TempHomeTestCase
from mfruitos import OS_APP_ID, __version__
from mfruitos.apps.registry import AppEntry, AppRegistry
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.ui.screens.store import StoreAppScreen
from mfruitos.launcher.ui.screens.updater import SystemUpdateScreen
from mfruitos.system.settings import Settings
from mfruitos.updater.service import UpdateService


def cached(paths, installed, latest, available=True):
    os.makedirs(paths.cache_dir, exist_ok=True)
    with open(os.path.join(paths.cache_dir, "updates.json"), "w", encoding="utf-8") as fp:
        json.dump({"checked_at": 1.0, "online": True, "error": "",
                   "apps": {OS_APP_ID: {"app_id": OS_APP_ID, "name": "mFruit OS",
                                        "channel": "system", "installed": installed,
                                        "latest": latest, "update_available": available,
                                        "repository": "https://github.com/Mengkungkao/MFruitOS"}}},
                  fp)


class CachedSystemStateTests(TempHomeTestCase):
    def service(self, os_version):
        return UpdateService(self.paths, Settings(None), Mock(), Mock(), os_version)

    def test_after_a_system_update_the_cache_no_longer_offers_it(self):
        cached(self.paths, "1.4.0", "1.5.1")
        service = self.service("1.5.1")
        info = service.info(OS_APP_ID)
        self.assertEqual((info.installed, info.update_available), ("1.5.1", False))
        self.assertEqual(service.update_count(), 0)

    def test_after_a_roll_back_the_update_is_offered_again(self):
        cached(self.paths, "1.5.1", "1.5.1", available=False)
        service = self.service("1.4.0")
        self.assertTrue(service.info(OS_APP_ID).update_available)


class OfferedUpdateScreenTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.os = ScreenServices()
        self.os.settings = Settings(None)
        self.os.paths = self.paths
        self.os.updater = Mock()
        self.os.installer = Mock()
        self.os.installer.read_record.return_value = {}
        self.os.push = Mock()
        self.os.registry = AppRegistry(self.paths, self.os.settings, "1.5.1")

    def labels(self, screen):
        return [item.label for item in screen.items()]

    def test_system_screen_offers_only_a_newer_version_than_the_running_one(self):
        self.os.updater.info.return_value = SimpleNamespace(
            latest=__version__, update_available=True, error="", notes="")   # stale cache
        self.assertNotIn("Update now", self.labels(SystemUpdateScreen(self.os)))
        self.os.updater.info.return_value = SimpleNamespace(
            latest="99.0.0", update_available=False, error="", notes="")
        self.assertIn("Update now", self.labels(SystemUpdateScreen(self.os)))

    def test_an_apps_store_page_offers_only_a_newer_version_than_the_installed_one(self):
        self.os.registry._entries["demo"] = AppEntry("demo", "Demo", "os", version="1.1.0")
        self.os.updater.info.return_value = SimpleNamespace(latest="1.1.0", update_available=True)
        page = StoreAppScreen(self.os, "demo")
        page.catalog_item = None
        self.assertNotIn("Update to 1.1.0", self.labels(page))
        self.os.updater.info.return_value = SimpleNamespace(latest="1.2.0", update_available=False)
        self.assertIn("Update to 1.2.0", self.labels(page))
