"""Wi-Fi from a phone: PiSugar's sugar-wifi-conf installed and run by mFruit OS.

The tool is replaced by a fake process; Bluetooth by a recorder. Nothing
touches a real adapter or the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import helpers
from helpers import ROOT, TempHomeTestCase
from mfruitos.system import wifi_setup
from mfruitos.system.bluetooth import Bluetooth
from mfruitos.system.settings import Invalid, Settings

BINARY = b"#!/bin/sh\necho fake sugar-wifi-conf\n"
DIGEST = hashlib.sha256(BINARY).hexdigest()


class Loop:
    """post/call_later for the service, pumped by the test on its own thread."""

    def __init__(self):
        self.queue = queue.Queue()
        self.timers = []

    def post(self, fn):
        self.queue.put(fn)

    def call_later(self, delay, fn):
        timer = Mock()
        timer.fn, timer.delay = fn, delay
        self.timers.append(timer)
        return timer

    def pump(self, until=lambda: False, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.queue.get(timeout=0.02)()
            except queue.Empty:
                if until():
                    return True
        return until()

    def fire_timers(self):
        timers, self.timers = self.timers, []
        for timer in timers:
            if not timer.cancel.called:
                timer.fn()


class FakeProcess:
    def __init__(self, argv, lines):
        self.argv = argv
        self._lines = queue.Queue()
        for line in lines:
            self._lines.put(line)
        self.returncode = None
        self.signals = []
        self.stdout = iter(self._lines.get, None)

    def feed(self, line):
        self._lines.put(line)

    def exit(self, code):
        self.returncode = code
        self._lines.put(None)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        deadline = time.monotonic() + (timeout or 5)
        while self.returncode is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        self.exit(-sig)

    def kill(self):
        self.exit(-9)


class FakeBluetooth:
    def __init__(self, powered=True, pairable=True, alias="pizero"):
        self.state = {"powered": powered, "pairable": pairable, "alias": alias}
        self.calls = []

    def settings(self):
        self.calls.append(("settings",))
        return dict(self.state)

    def set_powered(self, on):
        self.calls.append(("powered", on))
        self.state["powered"] = on

    def set_pairable(self, on):
        self.calls.append(("pairable", on))
        self.state["pairable"] = on


TEST_PICK = wifi_setup.Pick("9.9.9", "f" * 40, "sugar-wifi-conf-test", DIGEST, (2, 30))


class AssetTests(TempHomeTestCase):
    def test_the_newest_build_that_runs_on_this_glibc(self):
        new = wifi_setup.choose("aarch64", (2, 41))
        self.assertEqual((new.version, new.asset), ("2.3.0", "sugar-wifi-conf-aarch64"))
        self.assertEqual(wifi_setup.choose("arm64", (2, 39)).version, "2.3.0")
        older = wifi_setup.choose("aarch64", (2, 35))            # Ubuntu 22.04
        self.assertEqual((older.version, older.commit[:7]), ("2.2.3", "2c578f1"))
        self.assertEqual(wifi_setup.choose("armv7l", (2, 36)).version, "2.2.3")   # Bookworm
        self.assertEqual(wifi_setup.choose("armv6l", (2, 36)).version, "2.3.0")
        self.assertIsNone(wifi_setup.choose("aarch64", (2, 29)))
        with patch.object(wifi_setup, "glibc", return_value=None):   # musl, not glibc
            self.assertIsNone(wifi_setup.choose("aarch64"))
        self.assertIsNone(wifi_setup.choose("x86_64", (2, 41)))
        self.assertEqual(wifi_setup.download_url(older),
                         "https://github.com/PiSugar/sugar-wifi-conf/releases/download/v2.2.3/"
                         "sugar-wifi-conf-aarch64")
        for _version, commit, assets in wifi_setup.RELEASES:
            self.assertRegex(commit, r"^[0-9a-f]{40}$")
            for name, digest, minimum in assets.values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$", name)

    def test_glibc_is_read_from_the_system(self):
        with patch("os.confstr", return_value="glibc 2.35"):
            self.assertEqual(wifi_setup.glibc(), (2, 35))
        with patch("os.confstr", side_effect=ValueError):
            self.assertIsNone(wifi_setup.glibc())
        with patch("os.confstr", return_value="glibc 2.29"), \
                patch("platform.machine", return_value="aarch64"):
            self.assertIn("2.30 or newer", wifi_setup.unavailable_reason())

    def test_a_32_bit_system_on_a_64_bit_kernel_gets_the_32_bit_build(self):
        with patch("platform.machine", return_value="aarch64"), \
                patch.object(wifi_setup, "userland_bits", return_value=32):
            self.assertEqual(wifi_setup.machine(), "armv7l")
        with patch("platform.machine", return_value="aarch64"), \
                patch.object(wifi_setup, "userland_bits", return_value=64):
            self.assertEqual(wifi_setup.machine(), "aarch64")
        with patch("platform.machine", return_value="armv7l"), \
                patch.object(wifi_setup, "userland_bits", return_value=32):
            self.assertEqual(wifi_setup.machine(), "armv7l")
        self.assertIn(wifi_setup.userland_bits(), (32, 64))

    def test_offline_file_key_matches_the_shell_helper(self):
        url = wifi_setup.download_url(wifi_setup.choose("aarch64", (2, 41)))
        shell = subprocess.run(["bash", "-c", f"source {ROOT}/scripts/offline.sh; "
                                f"offline_file_key '{url}'"], capture_output=True, text=True)
        self.assertEqual(shell.stdout.strip(), wifi_setup.offline_file_key(url))


class InstallTests(TempHomeTestCase):
    def opener(self, payload):
        def opener(request, timeout):
            self.assertTrue(request.full_url.startswith("https://github.com/PiSugar/"))
            return io.BytesIO(payload)
        return opener

    def test_download_is_checked_and_made_executable(self):
        path = wifi_setup.install(self.paths, opener=self.opener(BINARY), pick=TEST_PICK)
        self.assertEqual(path, wifi_setup.tool_path(self.paths, TEST_PICK))
        self.assertTrue(os.access(path, os.X_OK))
        with open(os.path.join(wifi_setup.tool_dir(self.paths, TEST_PICK), "NOTICE")) as fp:
            notice = fp.read()
        self.assertIn("GNU General Public License v3.0", notice)
        self.assertIn("f" * 40, notice)
        with patch.object(wifi_setup, "choose", return_value=TEST_PICK):
            self.assertTrue(wifi_setup.installed(self.paths))

    def test_checksum_mismatch_installs_nothing(self):
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            wifi_setup.install(self.paths, opener=self.opener(b"tampered"), pick=TEST_PICK)
        directory = wifi_setup.tool_dir(self.paths, TEST_PICK)
        self.assertEqual([n for n in os.listdir(directory) if n.startswith("sugar-wifi-conf")], [])

    def test_offline_pack_is_used_first(self):
        pack = os.path.join(self.tmp, "pack")
        os.makedirs(os.path.join(pack, "files"))
        key = wifi_setup.offline_file_key(wifi_setup.download_url(TEST_PICK))
        with open(os.path.join(pack, "files", key), "wb") as fp:
            fp.write(BINARY)

        def no_network(request, timeout):
            raise AssertionError("must not download")
        wifi_setup.install(self.paths, [pack], opener=no_network, pick=TEST_PICK)
        self.assertTrue(os.access(wifi_setup.tool_path(self.paths, TEST_PICK), os.X_OK))

    def test_other_versions_are_pruned_and_reinstall_is_a_no_op(self):
        old = os.path.join(self.paths.system_dir, "tools", wifi_setup.NAME, "2.0.0")
        os.makedirs(old)
        wifi_setup.install(self.paths, opener=self.opener(BINARY), pick=TEST_PICK)
        self.assertFalse(os.path.exists(old))

        def no_network(request, timeout):
            raise AssertionError("already installed")
        wifi_setup.install(self.paths, opener=no_network, pick=TEST_PICK)

    def test_no_build_runs_here(self):
        with patch.object(wifi_setup, "choose", return_value=None), \
                patch.object(wifi_setup, "unavailable_reason", return_value="No build for sparc"):
            with self.assertRaisesRegex(ValueError, "No build for sparc"):
                wifi_setup.install(self.paths)


class ConfigTests(TempHomeTestCase):
    def test_default_config_fits_one_ble_packet_per_label(self):
        config = wifi_setup.validate_config(wifi_setup.default_config(self.paths))
        for item in config["info"] + config["commands"]:
            self.assertLessEqual(len(item["label"].encode()), wifi_setup.LABEL_MAX_BYTES)
        commands = {c["label"]: c["command"] for c in config["commands"]}
        self.assertIn("power shutdown", commands["Shut down"])   # safe shutdown first
        self.assertIn("sudo -n systemctl poweroff", commands["Shut down"])
        self.assertNotIn("Restart", [i["label"] for i in config["info"]])

    def test_validation(self):
        for bad in ({"info": [{"label": "x" * 21, "command": "true"}]},
                    {"info": [{"label": "ok", "command": " "}]},
                    {"info": [{"label": "ok", "command": "true", "interval": 0}]},
                    {"commands": [{"label": "", "command": "true"}]}, [], {"info": "x"}):
            with self.assertRaises(ValueError):
                wifi_setup.validate_config(bad)

    def test_the_users_own_file_wins_when_valid(self):
        own = {"info": [{"label": "Hello", "command": "echo hi", "interval": 5}], "commands": []}
        self.write_json(wifi_setup.user_config_path(self.paths), own)
        path = wifi_setup.write_config(self.paths)
        with open(path) as fp:
            self.assertEqual(json.load(fp), own)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.write_json(wifi_setup.user_config_path(self.paths), {"info": [{"label": "x" * 40}]})
        with open(wifi_setup.write_config(self.paths)) as fp:
            self.assertEqual(json.load(fp)["commands"][0]["label"], "Restart mFruit OS")

    def test_keys(self):
        key = wifi_setup.new_key()
        self.assertEqual(len(key), wifi_setup.KEY_LENGTH)
        self.assertTrue(set(key) <= set(wifi_setup.KEY_ALPHABET))
        self.assertTrue(wifi_setup.valid_key(key))
        self.assertFalse(wifi_setup.valid_key("pis"))
        settings = Settings(None)
        settings.set("wifi_setup.key", key)
        with self.assertRaises(Invalid):
            settings.set("wifi_setup.key", "has space")


class LogTests(unittest.TestCase):
    def test_what_a_phone_typed_is_never_kept(self):
        line = "[2026-10-10T01:00:00Z INFO  sugar_wifi_conf::ble::input_notify] Input write request: pisugar%&%Home%&%hunter22"
        self.assertNotIn("hunter22", wifi_setup.redact(line))
        self.assertNotIn("Home", wifi_setup.redact(line))
        self.assertIn("[hidden]", wifi_setup.redact(line))
        self.assertNotIn("abcd", wifi_setup.redact("... CustomCommand input write: abcd%&%0001"))

    def test_log_lines_become_states(self):
        cases = {
            "INFO sugar-wifi-conf starting": wifi_setup.STARTING,
            "INFO Waiting 10 seconds for Bluetooth to stabilize...": wifi_setup.STARTING,
            "INFO Advertising as 'pizero' started": wifi_setup.WAITING,
            "INFO Advertising via Linux MGMT fallback started": wifi_setup.WAITING,
            "INFO WifiName subscriber connected": wifi_setup.PHONE,
            "INFO NotifyMessage subscriber disconnected": wifi_setup.WAITING,
            "INFO NotifyMessage sending: Successfully connected to Wi-Fi: Connection successfully activated": wifi_setup.DONE,
            "INFO SSH_CTRL command: CONNECT": wifi_setup.PHONE,
            "Error: Bluetooth adapter not found": wifi_setup.FAILED,
        }
        for line, state in cases.items():
            self.assertEqual(wifi_setup.parse(line)[0], state, line)
        self.assertEqual(wifi_setup.parse("INFO NotifyMessage sending: Invalid key."),
                         (wifi_setup.PHONE, "The phone used a wrong key"))
        self.assertIn("Failed to connect",
                      wifi_setup.parse("INFO NotifyMessage sending: Failed to connect: x")[1])
        self.assertIsNone(wifi_setup.parse("DEBUG CustomInfo label read"))


class ServiceTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        chooser = patch.object(wifi_setup, "choose", return_value=TEST_PICK)
        chooser.start()
        self.addCleanup(chooser.stop)
        os.makedirs(wifi_setup.tool_dir(self.paths))
        with open(wifi_setup.tool_path(self.paths), "wb") as fp:
            fp.write(BINARY)
        os.chmod(wifi_setup.tool_path(self.paths), 0o755)
        self.settings = Settings(None)
        self.loop = Loop()
        self.bt = FakeBluetooth(powered=False, pairable=True)
        self.procs = []
        self.lines = ["INFO Waiting 10 seconds for Bluetooth to stabilize...",
                      "INFO Advertising as 'pizero' started"]
        self.service = wifi_setup.WifiSetupService(self.paths, self.settings, self.loop.post,
                                                   self.loop.call_later, self.bt, spawn=self.spawn)
        self.changes = []
        self.service.on_change = lambda: self.changes.append(self.service.state)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.service.close()

    def spawn(self, argv, **kwargs):
        self.assertEqual(kwargs["env"]["RUST_LOG"], "info")
        proc = FakeProcess(argv, self.lines)
        self.procs.append(proc)
        return proc

    def started(self, count=1):
        return self.loop.pump(lambda: len(self.procs) >= count
                              and self.service.state == wifi_setup.WAITING)

    def test_runs_while_wanted_and_puts_bluetooth_back(self):
        self.service.want("screen")
        self.assertTrue(self.started())
        argv = self.procs[0].argv
        self.assertEqual(argv[0], wifi_setup.tool_path(self.paths))
        self.assertEqual(argv[argv.index("--name") + 1], "pizero")       # the controller's own name
        key = argv[argv.index("--key") + 1]
        self.assertEqual(key, self.settings.get("wifi_setup.key"))
        self.assertNotEqual(key, "pisugar")
        self.assertIn(("powered", True), self.bt.calls)                 # it was off
        self.assertEqual(self.service.advertised, "pizero")
        self.bt.state["pairable"] = False                               # the tool's guard
        self.service.unwant("screen")
        self.assertTrue(self.loop.pump(lambda: self.service.state == wifi_setup.OFF))
        self.assertTrue(self.procs[0].signals)                           # SIGTERM
        self.assertEqual(self.bt.calls[-2:], [("pairable", True), ("powered", False)])

    def test_status_follows_the_log_and_hides_the_password(self):
        self.service.want("screen")
        self.assertTrue(self.started())
        self.procs[0].feed("INFO Input write request: k%&%Home%&%hunter22")
        self.procs[0].feed("INFO NotifyMessage sending: Successfully connected to Wi-Fi: ok")
        self.assertTrue(self.loop.pump(lambda: self.service.state == wifi_setup.DONE))
        with open(os.path.join(self.paths.logs_dir, "wifi-setup.log")) as fp:
            text = fp.read()
        self.assertIn("Advertising as", text)
        self.assertNotIn("hunter22", text)

    def test_a_crash_is_restarted_then_reported(self):
        self.service.want("always")
        self.assertTrue(self.started())
        for attempt in range(len(wifi_setup.RESTART_DELAYS)):
            self.procs[-1].exit(1)
            self.assertTrue(self.loop.pump(lambda: self.loop.timers))
            self.loop.fire_timers()
            self.assertTrue(self.started(attempt + 2))
        self.procs[-1].exit(1)
        self.assertTrue(self.loop.pump(lambda: self.service.state == wifi_setup.FAILED))
        self.assertIn("exit 1", self.service.detail)
        self.loop.pump(timeout=0.3)
        self.assertEqual(self.service.state, wifi_setup.FAILED)   # still shown while wanted
        self.service.unwant("always")
        self.assertEqual(self.service.state, wifi_setup.OFF)

    def test_paused_while_bluetooth_devices_are_paired(self):
        self.service.want("screen")
        self.assertTrue(self.started())
        self.service.pause("bluetooth")
        self.assertTrue(self.loop.pump(lambda: self.procs[0].returncode is not None
                                       and self.service.detail.startswith("Paused")))
        self.assertEqual(self.service.state, wifi_setup.OFF)
        self.service.resume("bluetooth")
        self.assertTrue(self.started(2))

    def test_a_new_key_restarts_it(self):
        self.service.want("screen")
        self.assertTrue(self.started())
        old = self.settings.get("wifi_setup.key")
        new = self.service.renew_key()
        self.assertNotEqual(old, new)
        self.assertTrue(self.started(2))
        self.assertIn(new, self.procs[1].argv)

    def test_not_installed_is_reported(self):
        os.unlink(wifi_setup.tool_path(self.paths))
        self.service.want("screen")
        self.assertEqual(self.service.state, wifi_setup.UNAVAILABLE)
        self.assertIn("install.sh", self.service.detail)
        self.assertEqual(self.procs, [])


class RuntimeWifiSetupTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        from mfruitos.launcher.runtime import Runtime
        self.rt = Runtime(self.paths, ROOT, socket_path=self.tmp + "/none.sock",
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.router.set_root(self.rt.home_screen)
        self.service = Mock(state="off", detail="", advertised="", wanted=set(), paused=set())
        self.service.available.return_value = (True, "")
        self.service.key.return_value = "k7m2xq9p"
        self.service.name.return_value = ""
        self.rt.wifi_setup = self.service

    def test_screen_and_bluetooth_pages_steer_it(self):
        from mfruitos.launcher.ui.screens.bluetooth import BluetoothScreen
        from mfruitos.launcher.ui.screens.phone_setup import PhoneSetupScreen
        self.rt.bluetooth = Mock()
        screen = PhoneSetupScreen(self.rt)
        self.rt.push(screen)
        self.service.want.assert_called_with("screen")
        self.rt.push(BluetoothScreen(self.rt))
        self.service.pause.assert_called_with("bluetooth")
        self.rt.pop()
        self.service.resume.assert_called_with("bluetooth")
        self.rt.pop()
        self.service.unwant.assert_called_with("screen")

    def test_modes(self):
        self.rt.settings.set("wifi_setup.mode", "always")
        self.service.want.assert_called_with("always")
        with patch("mfruitos.system.system_info.has_default_route", return_value=False):
            self.rt.settings.set("wifi_setup.mode", "offline")
        self.service.want.assert_called_with("offline")
        self.service.unwant.assert_any_call("always")
        with patch("mfruitos.system.system_info.has_default_route", return_value=True):
            self.rt._refresh_status()
        self.service.unwant.assert_called_with("offline")

    def test_control_command(self):
        from mfruitos.launcher.ctl_handlers import handle
        response = handle(self.rt, "wifi-setup", {"action": "start"})
        self.service.want.assert_called_with("remote")
        self.assertEqual(response["key"], "k7m2xq9p")
        handle(self.rt, "wifi-setup", {"action": "stop"})
        self.service.unwant.assert_called_with("remote")
        self.assertFalse(handle(self.rt, "wifi-setup", {"action": "explode"})["ok"])

    def test_phone_setup_lives_in_the_wifi_page(self):
        from mfruitos.launcher.ui.screens.phone_setup import PhoneSetupScreen
        from mfruitos.launcher.ui.screens.settings import SettingsScreen, WifiScreen
        self.rt.bluetooth = Mock()
        settings = SettingsScreen(self.rt)
        labels = [i.resolve("label") for i in settings.items()]
        self.assertNotIn("Wi-Fi from phone", labels)
        next(i for i in settings.items() if i.label == "Wi-Fi").action()
        wifi = self.rt.router.top
        self.assertIsInstance(wifi, WifiScreen)          # not straight into Connect WiFi
        row = next(i for i in wifi.items() if i.label == "Phone Setup")
        self.assertEqual(row.resolve("subtitle"), "With the PiSugar app")
        row.action()
        self.assertIsInstance(self.rt.router.top, PhoneSetupScreen)
        self.assertEqual(self.rt.router.top.title, "Phone Setup")
        self.service.want.assert_called_with("screen")

    def test_phone_setup_screen_rows(self):
        from mfruitos.launcher.ui.screens.phone_setup import PhoneSetupScreen
        screen = PhoneSetupScreen(self.rt)
        labels = [i.resolve("label") for i in screen.items()]
        for wanted in ("Open the PiSugar app", "Or in Chrome", "Device", "Key", "Status",
                       "Wi-Fi", "Run it", "New key", "Back"):
            self.assertIn(wanted, labels)
        self.service.available.return_value = (False, "Not installed: run scripts/install.sh")
        labels = [i.resolve("label") for i in screen.items()]
        self.assertIn("Not installed", labels)
        self.assertNotIn("Key", labels)


class BluetoothAdapterSettingsTests(unittest.TestCase):
    def test_bluetoothctl_fallback(self):
        answers = {("show",): "Controller AA\n\tAlias: pizero\n\tPowered: yes\n\tPairable: no\n"}
        calls = []

        def run(args, timeout):
            calls.append(tuple(args[1:]))
            return answers.get(tuple(args[1:]), "")
        with patch("mfruitos.system.bluetooth._load_dbus", return_value=None):
            bt = Bluetooth(run=run)
        self.assertEqual(bt.adapter_settings(), {"powered": True, "pairable": False,
                                                 "alias": "pizero"})
        bt.set_pairable(True)
        self.assertIn(("pairable", "on"), calls)


if __name__ == "__main__":
    unittest.main()
