"""The bundled Wi-Fi app as mFruit OS packages it: opened from Settings >
Wi-Fi > Choose a network, it is that page's network chooser, not a second
Wi-Fi page. The app's own suite lives in its repository (SOURCE.md)."""

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401
from mfruitos.updater import bundled


def done(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


def nmcli(args, timeout):
    """NetworkManager with two networks in its cache, no sudo."""
    if args[:2] == ["sudo", "-n"]:
        return done(returncode=1)
    if "DEVICE,TYPE" in args:
        return done("wlan0:wifi\n")
    if "general" in args:
        return done("org.freedesktop.NetworkManager.wifi.scan:yes\n")
    if "IN-USE,SSID,SIGNAL,SECURITY" in args:
        return done("*:Home:70:WPA2\n :Cafe:65:\n")
    if "ACTIVE,SSID" in args:
        return done("yes:Home\n")
    return done()


class Board:
    LCD_WIDTH, LCD_HEIGHT = 240, 280

    def __init__(self):
        self.frames = 0

    def on_button_press(self, callback):
        pass

    def on_button_release(self, callback):
        pass

    def draw_image(self, x, y, width, height, data):
        self.frames += 1

    def cleanup(self):
        pass


class BundledWifiAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        package = bundled.package("connectwifi", cls.temp.name)
        sys.path.insert(0, package)
        cls.app = importlib.import_module("connectwifi.app")
        cls.system = importlib.import_module("connectwifi.system")
        cls.input = importlib.import_module("mfruit_sdk.input")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(os.path.join(cls.temp.name, "connectwifi"))
        for name in [n for n in sys.modules if n.split(".")[0] in ("connectwifi", "mfruit_sdk")]:
            del sys.modules[name]
        cls.temp.cleanup()

    def start(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            if "MFRUIT_HOME" not in env:
                os.environ.pop("MFRUIT_HOME", None)
            app = self.app.ConnectWifiApp(
                Board(), commands=self.system.Commands(nmcli), keyboard_paths=lambda: [],
                input_factory=lambda *a, **kw: self.input.InputController(
                    *a, **kw, keyboard=False, threaded=False))
        queued = []
        app._start_thread = queued.append
        app.running = False
        app.run()                       # first frame, then the start-up work
        queued.pop()()
        app._start_thread = lambda target: target()
        app.running = True
        return app

    def test_from_settings_it_opens_on_the_network_list_and_back_returns(self):
        app = self.start({"MFRUIT_HOME": "/home/pi/.whisplay-os"})
        self.assertEqual(app.mode, "scan")
        self.assertEqual([n.ssid for n in app.networks], ["Home", "Cafe"])
        app.handle_key("cancel")
        self.assertFalse(app.running)

    def test_on_its_own_it_keeps_its_menu(self):
        app = self.start({})
        self.assertEqual(app.mode, "menu")
        self.assertEqual(app.networks, [])


if __name__ == "__main__":
    unittest.main()
