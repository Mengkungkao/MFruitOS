"""End-to-end: the real Runtime against the fake daemon, driven via the control socket."""

import json
import logging
import os
import threading
import time
import unittest

from helpers import ROOT, TempHomeTestCase
from fake_daemon import FakeDaemon
from mfruitos.launcher.control import send
from mfruitos.launcher.runtime import Runtime

logging.getLogger("mfruitos").setLevel(logging.CRITICAL)


class RuntimeEndToEndTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.daemon = FakeDaemon().start()
        for app_id in ("demo", "crashy"):
            self.daemon.handle({"cmd": "app.register",
                                "payload": {"app_id": app_id, "display_name": app_id.title()}}, None)
            self.write_json(os.path.join(self.paths.daemon_apps_dir, f"{app_id}.json"),
                            {"app_id": app_id, "display_name": app_id.title(),
                             "launch_command": "./run.sh", "cwd": self.tmp})
        self.daemon.behaviour["crashy"] = "crash"
        self.rt = Runtime(self.paths, ROOT, socket_path=self.daemon.socket_path)
        self.rt.settings.set("button.click_gap_ms", 150)
        self.thread = threading.Thread(target=self.rt.run, daemon=True)
        self.thread.start()
        self.wait(lambda: self.status().get("screens") == ["HomeScreen"], "home screen", 15)

    def tearDown(self):
        self.rt.loop.post(self.rt.shutdown, 0)
        self.thread.join(5)
        self.daemon.stop()
        super().tearDown()

    def status(self):
        try:
            return send(self.paths.control_socket, "status", timeout=5)
        except OSError:
            return {}

    def wait(self, condition, what, timeout=6.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}: {self.status()}")

    def click(self):
        self.daemon.press()
        time.sleep(0.05)
        self.daemon.release()

    def test_boot_registers_and_draws(self):
        registration = self.daemon.apps["mfruit-os"]
        self.assertEqual(registration["exit_gesture"], "none")
        self.assertIn("mfruitctl", registration["launch_command"])
        self.assertEqual(self.daemon.foreground, "mfruit-os")
        frame = self.daemon.read_frame("mfruit-os")
        self.assertTrue(frame and any(frame), "framebuffer should contain the home screen")
        for helper in ("mfruit-run", "mfruitctl", "boot-guard.sh"):
            self.assertTrue(os.access(os.path.join(self.paths.bin_dir, helper), os.X_OK))
        with open(os.path.join(self.paths.bin_dir, "mfruitctl")) as fp:
            self.assertNotIn("@MFRUIT_ROOT@", fp.read())

    def test_physical_button_navigation(self):
        start = self.rt.home_screen.selected
        self.click()
        self.wait(lambda: self.rt.home_screen.selected == start + 1, "next item")
        self.click()
        time.sleep(0.05)
        self.click()  # double click -> previous
        self.wait(lambda: self.rt.home_screen.selected == start, "previous item")
        # long press opens the selected entry
        self.rt.loop.post(self.rt.home_screen.focus_key, "os.settings")
        time.sleep(0.1)
        self.daemon.press()
        self.wait(lambda: self.status().get("screens", [])[-1:] == ["SettingsScreen"], "settings")
        self.daemon.release()
        for _ in range(4):
            self.click()
            time.sleep(0.03)
        self.wait(lambda: self.status().get("screens") == ["HomeScreen"], "quad click back")

    def test_launch_and_return(self):
        self.assertTrue(send(self.paths.control_socket, "launch", {"app_id": "demo"})["ok"])
        self.wait(lambda: self.daemon.foreground == "demo", "demo foreground")
        self.daemon.app_exits("demo")
        self.wait(lambda: self.daemon.foreground == "mfruit-os"
                  and self.status()["focus"]["has_focus"], "back home")
        self.assertEqual(self.status()["focus"]["mode"], "home")

    def test_launch_failure_shows_error(self):
        send(self.paths.control_socket, "launch", {"app_id": "crashy"})
        self.wait(lambda: self.status().get("screens", [])[-1:] == ["MessageScreen"], "error screen")
        self.assertEqual(self.daemon.foreground, "mfruit-os")

    def test_disable_app_persists_and_hides(self):
        self.rt.loop.post(self.rt.settings.set_app_flag, "demo", "enabled", False)
        self.wait(lambda: "demo" not in [e.key for e in self.rt.home_screen.entries()], "hidden")
        self.rt.loop.post(self.rt.flush_settings)
        self.wait(lambda: os.path.exists(self.paths.settings_file), "settings saved")
        with open(self.paths.settings_file) as fp:
            self.assertFalse(json.load(fp)["applications"]["demo"]["enabled"])

    def test_screenshot_and_gesture_commands(self):
        path = os.path.join(self.tmp, "shot.png")
        self.assertTrue(send(self.paths.control_socket, "screenshot", {"path": path})["ok"])
        self.assertGreater(os.path.getsize(path), 1000)
        self.assertFalse(send(self.paths.control_socket, "gesture", {"name": "bogus"})["ok"])
        self.assertFalse(send(self.paths.control_socket, "nonsense")["ok"])

    def test_autostart_launches_once_per_boot(self):
        self.rt.loop.post(self.rt.shutdown, 0)
        self.thread.join(5)
        self.rt.settings.set_app_flag("demo", "autostart", True)
        self.rt.settings.save()
        # setUp's runtime already used this boot's autostart turn; simulate a reboot.
        os.remove(os.path.join(self.paths.state_dir, "autostart_boot_id"))
        for expected in (True, False):  # second start = same boot: no autostart
            self.daemon.handle({"cmd": "app.focus.acquire", "payload": {"app_id": "mfruit-os"}}, None)
            self.daemon.app_releases("mfruit-os")
            rt = Runtime(self.paths, ROOT, socket_path=self.daemon.socket_path)
            thread = threading.Thread(target=rt.run, daemon=True)
            thread.start()
            try:
                if expected:
                    self.wait(lambda: self.daemon.foreground == "demo", "autostarted demo", 15)
                    self.daemon.app_exits("demo")
                else:
                    self.wait(lambda: self.daemon.foreground == "mfruit-os", "home", 15)
                    time.sleep(1.5)
                    self.assertEqual(self.daemon.foreground, "mfruit-os")
            finally:
                rt.loop.post(rt.shutdown, 0)
                thread.join(5)
        self.rt = rt
        self.thread = thread

    def test_shutdown_releases_screen(self):
        self.rt.loop.post(self.rt.shutdown, 0)
        self.thread.join(5)
        self.assertIsNone(self.daemon.foreground)


if __name__ == "__main__":
    unittest.main()
