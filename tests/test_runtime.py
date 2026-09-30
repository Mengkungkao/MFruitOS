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
from mfruitos.sdk.keys import DOWN, REPEAT, UP, KeyEvent

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
        # a hold arms at 0.7 s and opens the selected entry on release (RC1)
        self.rt.loop.post(self.rt.home_screen.focus_key, "os.settings")
        time.sleep(0.1)
        self.daemon.press()
        time.sleep(1.0)
        self.assertEqual(self.status().get("screens"), ["HomeScreen"], "nothing opens while held")
        self.daemon.release()
        self.wait(lambda: self.status().get("screens", [])[-1:] == ["SettingsScreen"], "settings")
        for _ in range(4):
            self.click()
            time.sleep(0.03)
        self.wait(lambda: self.status().get("screens") == ["HomeScreen"], "quad click back")

    def key(self, name, action=DOWN):
        codes = {"down": 108, "up": 103, "enter": 28, "escape": 1, "tab": 15}
        self.rt.loop.post(self.rt._on_key, KeyEvent("key", name, action, codes[name]))

    def test_keyboard_navigation(self):
        self.assertTrue(self.daemon.apps["mfruit-os"]["disable_esc_exit_key"],
                        "Esc must be MFruit OS's back key, not the daemon's close key")
        start = self.rt.home_screen.selected
        self.key("down")
        self.wait(lambda: self.rt.home_screen.selected == start + 1, "next item")
        self.key("up")
        self.wait(lambda: self.rt.home_screen.selected == start, "previous item")
        self.rt.loop.post(self.rt.home_screen.focus_key, "os.settings")
        self.key("enter")
        self.wait(lambda: self.status().get("screens", [])[-1:] == ["SettingsScreen"], "settings")
        self.key("escape")
        self.wait(lambda: self.status().get("screens") == ["HomeScreen"], "back home")

    def test_key_command_types_through_the_keyboard_path(self):
        start = self.rt.home_screen.selected
        self.assertTrue(send(self.paths.control_socket, "key", {"name": "down"})["ok"])
        self.wait(lambda: self.rt.home_screen.selected == start + 1, "next item")
        self.assertFalse(send(self.paths.control_socket, "key", {"name": "f13"})["ok"])
        self.assertIn("keyboards", self.status())

    def test_keys_that_went_down_elsewhere_do_nothing(self):
        self.rt.loop.post(self.rt.home_screen.focus_key, "os.settings")
        # e.g. the Enter that opened an app, released after MFruit OS is back
        self.key("enter", REPEAT)
        self.key("enter", UP)
        time.sleep(0.3)
        self.assertEqual(self.status().get("screens"), ["HomeScreen"])
        self.assertTrue(send(self.paths.control_socket, "launch", {"app_id": "demo"})["ok"])
        self.wait(lambda: self.daemon.foreground == "demo", "demo foreground")
        self.key("down")                 # typed into the app, not into MFruit OS
        self.key("enter")
        self.daemon.app_exits("demo")
        self.wait(lambda: self.daemon.foreground == "mfruit-os"
                  and self.status()["focus"]["has_focus"], "back home")
        self.key("enter", REPEAT)
        time.sleep(0.3)
        self.assertEqual(self.status().get("screens"), ["HomeScreen"])
        self.assertEqual(self.daemon.foreground, "mfruit-os")

    def hub_client(self, app_id):
        """An app listening on MFruit OS's key hub, as the SDK connects."""
        import socket as socket_module
        sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
        sock.connect(self.paths.keys_socket)
        sock.sendall(json.dumps({"app_id": app_id}).encode() + b"\n")
        self.addCleanup(sock.close)
        self.wait(lambda: self.rt.keyhub.connected(app_id), "app on the key hub")
        sock.settimeout(0.3)
        return sock

    def received(self, sock):
        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        except OSError:
            pass
        return [json.loads(line) for line in data.splitlines() if line.strip()]

    def hardware_key(self, name, action=DOWN):
        codes = {"down": 108, "up": 103, "enter": 28, "escape": 1, "space": 57}
        self.rt.loop.post(self.rt._on_hardware_key, KeyEvent("key", name, action, codes[name]))

    def test_keys_go_to_whoever_owns_the_screen(self):
        app = self.hub_client("demo")
        start = self.rt.home_screen.selected
        self.hardware_key("down")                     # Home: MFruit OS moves
        self.hardware_key("down", UP)
        self.wait(lambda: self.rt.home_screen.selected == start + 1, "next item")
        self.assertEqual([m for m in self.received(app) if m["type"] == "key"], [])
        self.assertTrue(send(self.paths.control_socket, "launch", {"app_id": "demo"})["ok"])
        self.wait(lambda: self.daemon.foreground == "demo", "demo foreground")
        self.hardware_key("space")                    # the app's, not MFruit OS's
        time.sleep(0.2)
        keys = [m for m in self.received(app) if m["type"] == "key"]
        self.assertEqual([(k["value"], k["action"]) for k in keys], [("space", 1)])
        self.daemon.app_exits("demo")
        self.wait(lambda: self.status()["focus"]["has_focus"], "back home")
        self.hardware_key("space", UP)                # its release follows its press
        self.hardware_key("down")                     # a new press is MFruit OS's again
        self.wait(lambda: self.rt.home_screen.selected == start + 2, "next item")
        keys = [m for m in self.received(app) if m["type"] == "key"]
        self.assertEqual([(k["value"], k["action"]) for k in keys], [("space", 0)])

    def test_the_keyboards_are_held_exclusively(self):
        self.assertTrue(self.rt.keyboard.grab)
        self.rt.loop.post(self.rt.yield_to_desktop)   # Developer -> Daemon desktop
        self.wait(lambda: not self.rt.keyboard.grab, "grab released for the daemon")
        send(self.paths.control_socket, "summon")
        self.wait(lambda: self.rt.keyboard.grab and self.status()["focus"]["has_focus"],
                  "grab back with the screen")

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
