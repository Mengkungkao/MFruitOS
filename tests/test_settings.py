import json
import os
import unittest

from helpers import ROOT, TempHomeTestCase
from mfruitos.system.settings import Invalid, Settings, defaults_tree


class SettingsTests(TempHomeTestCase):
    def new(self):
        settings = Settings(self.paths.settings_file)
        settings.load()
        return settings

    def test_defaults_when_missing(self):
        settings = self.new()
        self.assertEqual(settings.get("display.brightness"), 80)
        self.assertEqual(settings.load_errors, [])

    def test_persistence_survives_reload(self):
        settings = self.new()
        settings.set("display.brightness", 40)
        settings.set_app_flag("bitcoin", "enabled", False)
        self.assertTrue(settings.save())
        again = self.new()
        self.assertEqual(again.get("display.brightness"), 40)
        self.assertFalse(again.app_flags("bitcoin")["enabled"])
        self.assertTrue(again.app_flags("unknown")["enabled"])

    def test_corrupt_file_preserved_and_defaults_used(self):
        with open(self.paths.settings_file, "w") as fp:
            fp.write("{broken json")
        settings = self.new()
        self.assertEqual(settings.get("display.brightness"), 80)
        self.assertTrue(settings.load_errors)
        broken = [n for n in os.listdir(self.paths.config_dir) if ".broken-" in n]
        self.assertEqual(len(broken), 1)
        with open(os.path.join(self.paths.config_dir, broken[0])) as fp:
            self.assertEqual(fp.read(), "{broken json")

    def test_one_bad_entry_does_not_reset_others(self):
        self.write_json(self.paths.settings_file, {
            "display": {"brightness": 999, "theme": "light"},
            "applications": {"ok-app": {"enabled": False}, "../bad": {"enabled": False}},
        })
        settings = self.new()
        self.assertEqual(settings.get("display.brightness"), 80)
        self.assertEqual(settings.get("display.theme"), "light")
        self.assertFalse(settings.app_flags("ok-app")["enabled"])
        self.assertEqual(len(settings.load_errors), 2)

    def test_validation_on_set(self):
        settings = self.new()
        with self.assertRaises(Invalid):
            settings.set("display.brightness", 0)
        with self.assertRaises(Invalid):
            settings.set("display.theme", "neon")
        with self.assertRaises(KeyError):
            settings.set("display.nope", 1)

    def test_button_map_cannot_lock_user_out(self):
        settings = self.new()
        with self.assertRaises(Invalid):
            settings.set("button.long_press", "none")  # nothing left mapped to select
        settings.set("button.double_click", "select")
        settings.set("button.long_press", "back")    # fine: select still reachable
        self.assertEqual(settings.get("button.long_press"), "back")

    def test_invalid_button_map_on_disk_restored(self):
        self.write_json(self.paths.settings_file, {"button": {"long_press": "none"}})
        settings = self.new()
        self.assertEqual(settings.get("button.long_press"), "select")

    def test_single_autostart(self):
        settings = self.new()
        settings.set_app_flag("a", "autostart", True)
        settings.set_app_flag("b", "autostart", True)
        self.assertFalse(settings.app_flags("a")["autostart"])
        self.assertTrue(settings.app_flags("b")["autostart"])

    def test_forget_app(self):
        settings = self.new()
        settings.set_app_flag("a", "hidden", True)
        settings.set("apps.order", ["a", "b"])
        settings.set("apps.default_app", "a")
        settings.forget_app("a")
        self.assertEqual(settings.get("apps.order"), ["b"])
        self.assertEqual(settings.get("apps.default_app"), "")

    def test_autosave_hook_called(self):
        calls = []
        settings = Settings(self.paths.settings_file, autosave=lambda: calls.append(1))
        settings.set("display.theme", "light")
        settings.set("display.theme", "light")  # unchanged -> no extra call
        self.assertEqual(len(calls), 1)

    def test_shipped_default_json_matches_schema(self):
        with open(os.path.join(ROOT, "config", "default.json")) as fp:
            shipped = json.load(fp)
        self.assertEqual(shipped, defaults_tree())


if __name__ == "__main__":
    unittest.main()
