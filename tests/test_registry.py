import json
import os
import unittest

from helpers import TempHomeTestCase, make_package
from mfruitos.apps.registry import AppRegistry
from mfruitos.system.settings import Settings


class RegistryTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.settings = Settings(None)
        self.registry = AppRegistry(self.paths, self.settings, "1.0.0")

    def install_os_app(self, app_id, version="1.0.0", **kw):
        root = self.paths.app_root(app_id)
        version_dir = os.path.join(root, "versions", f"{version}-t")
        make_package(version_dir, app_id=app_id, version=version, **kw)
        os.symlink(os.path.join("versions", f"{version}-t"), os.path.join(root, "current"))
        self.write_json(os.path.join(root, "app.json"),
                        {"installed_version": version, "name": app_id.title()})
        return root

    def daemon_app(self, app_id, cwd=None, command="python3 main.py", **extra):
        data = {"app_id": app_id, "display_name": app_id.upper(), "icon": "X",
                "launch_command": command, "cwd": cwd or self.tmp, "priority": 0}
        data.update(extra)
        self.write_json(os.path.join(self.paths.daemon_apps_dir, f"{app_id}.json"), data)

    def test_discovers_all_sources_and_excludes_os_itself(self):
        self.install_os_app("weather")
        self.daemon_app("legacy")
        self.daemon_app("mfruit-os")
        live = [{"app_id": "legacy", "display_name": "Legacy", "running": True},
                {"app_id": "weather", "display_name": "Weather"},
                {"app_id": "mfruit-os", "display_name": "MFruit OS"},
                {"app_id": "whisplay-wifi", "display_name": "WiFi"}]
        self.registry.refresh(live)
        ids = {e.id: e.kind for e in self.registry.all()}
        self.assertEqual(ids, {"weather": "os", "legacy": "daemon", "whisplay-wifi": "system"})
        self.assertTrue(self.registry.get("legacy").running)
        self.assertTrue(self.registry.get("weather").registered)
        self.assertEqual([e.id for e in self.registry.launcher_entries()], ["legacy", "weather"])

    def test_offline_daemon_uses_files_and_hides_system_pages(self):
        self.daemon_app("legacy")
        self.registry.refresh(None)
        self.assertEqual([e.id for e in self.registry.all()], ["legacy"])
        self.assertFalse(self.registry.daemon_online)

    def test_disabled_and_hidden_not_in_launcher(self):
        self.daemon_app("a")
        self.daemon_app("b")
        self.daemon_app("c")
        self.settings.set_app_flag("a", "enabled", False)
        self.settings.set_app_flag("b", "hidden", True)
        self.registry.refresh(None)
        self.assertEqual([e.id for e in self.registry.launcher_entries()], ["c"])
        self.assertEqual(self.registry.get("a").status(), "disabled")
        self.assertEqual(len(self.registry.apps()), 3)  # still installed

    def test_broken_manifest_does_not_block_others(self):
        self.install_os_app("good")
        root = self.install_os_app("bad")
        with open(os.path.join(root, "current", "manifest.json"), "w") as fp:
            fp.write("{broken")
        os.makedirs(os.path.join(self.paths.apps_dir, "Invalid Name"))
        self.registry.refresh([])
        self.assertEqual(self.registry.get("good").broken, "")
        self.assertIn("Invalid manifest", self.registry.get("bad").broken)
        self.assertEqual(self.registry.get("bad").status(), "broken")
        self.assertIsNone(self.registry.get("Invalid Name"))

    def test_manifest_id_mismatch_is_broken(self):
        root = self.install_os_app("alpha")
        path = os.path.join(root, "current", "manifest.json")
        with open(path) as fp:
            data = json.load(fp)
        data["id"] = "beta"
        with open(path, "w") as fp:
            json.dump(data, fp)
        self.registry.refresh([])
        self.assertIn("does not match", self.registry.get("alpha").broken)

    def test_broken_daemon_apps(self):
        self.daemon_app("nocmd", command="")
        self.daemon_app("nocwd", cwd=os.path.join(self.tmp, "missing"))
        self.daemon_app("orphan", command="/home/x/.whisplay-os/bin/mfruit-run orphan")
        self.registry.refresh(None)
        self.assertEqual(self.registry.get("nocmd").broken, "No launch command")
        self.assertEqual(self.registry.get("nocwd").broken, "Working directory missing")
        self.assertIn("missing", self.registry.get("orphan").broken)

    def test_duplicate_daemon_files_first_wins(self):
        self.write_json(os.path.join(self.paths.daemon_apps_dir, "a1.json"),
                        {"app_id": "dup", "display_name": "First", "launch_command": "x"})
        self.write_json(os.path.join(self.paths.daemon_apps_dir, "a2.json"),
                        {"app_id": "dup", "display_name": "Second", "launch_command": "x"})
        self.registry.refresh(None)
        self.assertEqual(self.registry.get("dup").name, "First")

    def test_order_and_move(self):
        for app_id, prio in (("a", 0), ("b", 50), ("c", 10)):
            self.daemon_app(app_id, priority=prio)
        self.registry.refresh(None)
        self.assertEqual([e.id for e in self.registry.apps()], ["b", "c", "a"])  # priority
        self.assertTrue(self.registry.move("a", -1))
        self.registry.refresh(None)
        self.assertEqual([e.id for e in self.registry.apps()], ["b", "a", "c"])
        self.assertFalse(self.registry.move("b", -1))

    def test_update_badge_only_for_managed(self):
        self.install_os_app("weather")
        self.daemon_app("legacy")
        self.registry.refresh(None)
        self.registry.set_latest_versions({"weather": "2.0.0", "legacy": "9.9.9"})
        self.assertEqual(self.registry.get("weather").status(), "update")
        self.assertFalse(self.registry.get("legacy").update_available)


if __name__ == "__main__":
    unittest.main()
