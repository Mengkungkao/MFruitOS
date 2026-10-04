"""An app keeps running in the background with the screen held bright (SDK 1.4.0, ADR 0009).

With a LoRa HAT on stock jumpers the backlight pin is the radio's M0: any
dimming (PWM) or screen-off deafens the radio (measured: 0/20 packets at
80% and 15%, 40/40 at 100%; KI-11). An app such as RadioConnect asks, through
the SDK, to keep running and to keep the screen bright; MFruit OS then holds
the backlight at 100% only while that app runs in the background.
"""

import json
import os
import socket
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import helpers
from fake_daemon import FakeDaemon
from helpers import ROOT, TempHomeTestCase
from mfruitos.apps.registry import AppEntry
from mfruitos.launcher import ctl_handlers
from mfruitos.launcher.control import send
from mfruitos.launcher.runtime import Runtime
from mfruitos.sdk import background
from mfruitos.system.hardware import BacklightController
from mfruitos.system.settings import Settings


class FakeClient:
    def __init__(self):
        self.levels = []

    def set_backlight(self, level):
        self.levels.append(level)


class BacklightHold(unittest.TestCase):
    def controller(self):
        settings = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
        settings.set("display.brightness", 80)
        settings.set("display.dim_level", 15)
        client = FakeClient()
        return BacklightController(client, settings), client

    def test_without_a_hold_the_user_settings_apply(self):
        bl, client = self.controller()
        bl.wake()
        bl.dim()
        bl.off()
        self.assertEqual(client.levels, [80, 15, 0])

    def test_a_hold_keeps_full_brightness_through_dim_and_off(self):
        bl, client = self.controller()
        self.assertTrue(bl.set_hold(True))
        self.assertFalse(bl.set_hold(True))
        bl.wake()
        bl.dim()
        bl.off()
        self.assertEqual(client.levels, [100])  # dim and off change nothing
        self.assertEqual(bl.state, "on")
        self.assertTrue(bl.set_hold(False))
        bl.wake()
        self.assertEqual(client.levels, [100, 80])


class FakeRegistry:
    def __init__(self, entries):
        self.entries = {e.id: e for e in entries}

    def get(self, app_id):
        return self.entries.get(app_id)

    def all(self):
        return list(self.entries.values())

    def apps(self):
        return self.all()


class ControlCommand(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
        self.registry = FakeRegistry([AppEntry("radioconnect", "RadioConnect", "os"),
                                      AppEntry("whisplay-wifi", "WiFi", "system")])
        self.refreshes = 0

        def refresh(query_daemon=True):
            self.refreshes += 1
            for entry in self.registry.all():
                flags = self.settings.app_flags(entry.id)
                entry.background, entry.screen_bright = flags["background"], flags["screen_bright"]
        self.rt = types.SimpleNamespace(registry=self.registry, settings=self.settings,
                                        refresh_registry=refresh)

    def call(self, **args):
        return ctl_handlers.handle(self.rt, "app.background", args)

    def test_read_then_set_both_switches(self):
        self.assertEqual(self.call(app_id="radioconnect"),
                         {"ok": True, "app_id": "radioconnect", "keep_running": False, "screen_bright": False})
        self.assertEqual(self.refreshes, 0)
        answer = self.call(app_id="radioconnect", keep_running=True, screen_bright=True)
        self.assertEqual((answer["keep_running"], answer["screen_bright"]), (True, True))
        self.assertEqual(self.settings.app_flag_explicit("radioconnect", "background"), True)
        self.assertEqual(self.settings.app_flag_explicit("radioconnect", "screen_bright"), True)
        self.assertEqual(self.refreshes, 1)
        answer = self.call(app_id="radioconnect", keep_running=False)
        self.assertEqual((answer["keep_running"], answer["screen_bright"]), (False, True))

    def test_only_these_two_flags_and_only_real_apps(self):
        self.assertFalse(self.call(app_id="nobody")["ok"])
        self.assertFalse(self.call(app_id="whisplay-wifi", keep_running=True)["ok"])
        self.assertFalse(self.call(app_id=None)["ok"])
        self.assertFalse(self.call(app_id="radioconnect", keep_running="yes")["ok"])
        self.call(app_id="radioconnect", enabled=False, autostart=True, hidden=True)
        flags = self.settings.app_flags("radioconnect")
        self.assertEqual((flags["enabled"], flags["autostart"], flags["hidden"]), (True, False, False))


class SdkClient(unittest.TestCase):
    def serve(self, reply):
        """A one-shot control socket that records the request and answers ``reply``."""
        path = os.path.join(tempfile.mkdtemp(), "control.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        self.addCleanup(server.close)
        seen = {}

        def run():
            conn, _ = server.accept()
            with conn:
                seen["request"] = json.loads(conn.makefile("rb").readline())
                conn.sendall((json.dumps(reply) + "\n").encode())
        threading.Thread(target=run, daemon=True).start()
        return path, seen

    def test_set_sends_only_what_changes_and_names_the_app(self):
        path, seen = self.serve({"ok": True, "keep_running": True, "screen_bright": False})
        with patch.dict(os.environ, {"MFRUIT_CONTROL_SOCKET": path, "WHISPLAY_APP_ID": "radioconnect"}):
            state = background.set(keep_running=True)
        self.assertEqual(state, background.State(True, False))
        self.assertEqual(seen["request"], {"cmd": "app.background",
                                           "args": {"app_id": "radioconnect", "keep_running": True}})

    def test_an_older_mfruit_os_or_none_at_all_reads_as_unavailable(self):
        path, _ = self.serve({"ok": False, "error": "unknown command 'app.background'"})
        with patch.dict(os.environ, {"MFRUIT_CONTROL_SOCKET": path, "WHISPLAY_APP_ID": "radioconnect"}):
            self.assertIsNone(background.get())
        with patch.dict(os.environ, {"MFRUIT_CONTROL_SOCKET": "/nonexistent/control.sock",
                                     "WHISPLAY_APP_ID": "radioconnect"}):
            self.assertIsNone(background.get())
        with patch.dict(os.environ, {"WHISPLAY_APP_ID": ""}):
            self.assertIsNone(background.get())


class EndToEnd(TempHomeTestCase):
    """The SDK call through the real control socket and Runtime, against the fake daemon."""

    def setUp(self):
        super().setUp()
        self.daemon = FakeDaemon().start()
        self.daemon.handle({"cmd": "app.register",
                            "payload": {"app_id": "radio", "display_name": "Radio"}}, None)
        self.write_json(os.path.join(self.paths.daemon_apps_dir, "radio.json"),
                        {"app_id": "radio", "display_name": "Radio",
                         "launch_command": "./run.sh", "cwd": self.tmp})
        open(os.path.join(self.tmp, "run.sh"), "a").close()
        self.rt = Runtime(self.paths, ROOT, socket_path=self.daemon.socket_path,
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.settings.set("display.brightness", 80)
        self.thread = threading.Thread(target=self.rt.run, daemon=True)
        self.thread.start()
        self.wait(lambda: self.status().get("screens") == ["HomeScreen"], "home screen", 15)
        env = patch.dict(os.environ, {"MFRUIT_CONTROL_SOCKET": self.paths.control_socket,
                                      "WHISPLAY_APP_ID": "radio"})
        env.start()
        self.addCleanup(env.stop)

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

    def on_loop(self, fn):
        """Run ``fn`` on the runtime's loop and wait until it has run."""
        done = threading.Event()

        def run():
            try:
                fn()
            finally:
                done.set()
        self.rt.loop.post(run)
        self.assertTrue(done.wait(5), "the loop did not run the call")

    def refresh(self):
        self.on_loop(lambda: self.rt.refresh_registry(query_daemon=True))

    def test_held_only_while_that_app_runs_in_the_background(self):
        self.wait(lambda: self.daemon.backlight == 80, "the user's brightness at Home")
        self.assertEqual(background.set(keep_running=True, screen_bright=True),
                         background.State(True, True))
        self.daemon.running.add("radio")          # left, still running in the background
        self.refresh()
        self.wait(lambda: self.status().get("backlight_hold") is True, "the hold")
        self.wait(lambda: self.daemon.backlight == 100, "full brightness")
        self.on_loop(self.rt._dim)
        self.on_loop(self.rt._screen_off)
        self.assertEqual(self.status().get("backlight"), "on")
        self.assertEqual(self.daemon.backlight, 100, "no dimming or screen-off while held")
        self.daemon.running.discard("radio")      # the app stopped: back to the user's level
        self.refresh()
        self.wait(lambda: self.status().get("backlight_hold") is False, "the hold to end")
        self.wait(lambda: self.daemon.backlight == 80, "the user's brightness again")

    def test_keep_running_alone_does_not_hold_the_screen(self):
        self.wait(lambda: self.daemon.backlight == 80, "the user's brightness at Home")
        self.assertEqual(background.set(keep_running=True), background.State(True, False))
        self.daemon.running.add("radio")
        self.refresh()
        self.assertFalse(self.status().get("backlight_hold"))
        self.assertEqual(self.daemon.backlight, 80)


if __name__ == "__main__":
    unittest.main()
