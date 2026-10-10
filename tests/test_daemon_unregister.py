"""Removing an app from the REAL whisplay-daemon (Fruit Store uninstall).

whisplay-daemon has no unregister command. With mFruit OS's daemon wrapper,
``mfruit.app.unregister`` removes the app from the daemon's list and its JSON
file at once. Without the wrapper the daemon answers "unknown command" and the
launcher falls back to the old trick (an empty, non-persistent "(removed)"
entry), which the registry hides.
"""

import logging
import os
import shutil
import time
import unittest

import helpers  # noqa: F401
from real_daemon import RealDaemon, find_whisplay_src, new_home
from mfruitos.apps.registry import AppRegistry
from mfruitos.daemon.client import DaemonRequestError, WhisplayDaemonClient
from mfruitos.launcher.app_manager.lifecycle import AppLifecycle
from mfruitos.paths import Paths
from mfruitos.system.settings import Settings

WHISPLAY_SRC = find_whisplay_src()


@unittest.skipIf(WHISPLAY_SRC is None, "Whisplay source not found (set WHISPLAY_SRC)")
class DaemonUnregisterTests(unittest.TestCase):
    def start(self, wrapped: bool):
        logging.getLogger("mfruitos").setLevel(logging.CRITICAL)
        self.home = new_home()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.daemon = RealDaemon(self.home)
        self.daemon.add_app("game", 20)
        self.daemon.add_app("busy", 10, "--linger")
        self.paths = Paths(os.path.join(self.home, "os"), os.path.join(self.home, ".whisplay-daemon"))
        lock = os.path.join(self.paths.state_dir, "launcher.lock") if wrapped else ""
        self.daemon.start(WHISPLAY_SRC, mfruit_lock=lock)
        self.addCleanup(self.daemon.stop)
        self.client = WhisplayDaemonClient(self.daemon.socket_path)
        self.lifecycle = AppLifecycle(self.client, self.paths)

    def listed(self):
        return {app["app_id"]: app for app in self.client.list_apps()}

    def file(self, app_id):
        return os.path.join(self.daemon.apps_dir, f"{app_id}.json")

    def test_with_the_wrapper_the_app_is_gone_from_the_list_and_disk(self):
        self.start(wrapped=True)
        self.assertIn("game", self.listed())
        self.assertTrue(self.lifecycle.unregister("game", "Game"))
        self.assertNotIn("game", self.listed())
        self.assertFalse(os.path.exists(self.file("game")))
        self.assertTrue(os.path.exists(self.file("busy")), "only that app")

    def test_the_wrapper_refuses_unknown_builtin_and_running_apps(self):
        self.start(wrapped=True)
        with self.assertRaisesRegex(DaemonRequestError, "unknown app"):
            self.client.unregister_app("nothing")
        builtin = next(app_id for app_id in self.listed() if app_id.startswith("whisplay-"))
        with self.assertRaisesRegex(DaemonRequestError, "cannot be unregistered"):
            self.client.unregister_app(builtin)
        self.client.launch_app("busy")
        deadline = time.monotonic() + 10
        while not self.listed()["busy"]["running"]:
            self.assertLess(time.monotonic(), deadline, "busy never started")
            time.sleep(0.05)
        with self.assertRaisesRegex(DaemonRequestError, "is running"):
            self.client.unregister_app("busy")
        self.assertFalse(self.lifecycle.unregister("busy", "Busy"))
        self.assertIn("busy", self.listed())
        self.assertTrue(os.path.exists(self.file("busy")))

    def test_a_plain_daemon_falls_back_and_the_registry_hides_the_leftover(self):
        self.start(wrapped=False)
        with self.assertRaisesRegex(DaemonRequestError, "^unknown command"):
            self.client.unregister_app("game")
        self.assertTrue(self.lifecycle.unregister("game", "Game"))
        self.assertFalse(os.path.exists(self.file("game")))
        self.assertEqual(self.listed()["game"]["display_name"], "Game (removed)",
                         "a plain daemon keeps it in memory until it restarts")
        registry = AppRegistry(self.paths, Settings(None), "1.4.0")
        registry.refresh(self.client.list_apps())
        self.assertIsNone(registry.get("game"))
        self.assertIsNotNone(registry.get("busy"))


if __name__ == "__main__":
    unittest.main()
