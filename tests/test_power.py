"""mFruit OS power service: policies, settings, PiSugar protocol, sockets.

Boards are register-level fakes (mfruitos/hosts/pisugar/fake.py); time is a
fake clock; commands are recorded, never run.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from mfruitos import power
from mfruitos.hosts.pisugar import detect, pisugar3
from mfruitos.hosts.pisugar.fake import FakeBus, FakeIP5209, FakePiSugar3, FakeSD3078
from mfruitos.power import config as pconfig
from mfruitos.power.client import PowerClient, PowerError, PowerEvents
from mfruitos.power.compat import Compat
from mfruitos.power.server import PowerServer
from mfruitos.power.service import (ERRORS_BEFORE_REPORT, PROBE_RETRY_SEC, SHUTDOWN_RETRY_SEC,
                                    DryRunner, PowerService)
from mfruitos.system.settings import Invalid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTC = dt.timezone.utc


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


def make_service(board=None, devices=None, config_path=None, ntp=False, wall=None, rc=0,
                 model="auto", **settings):
    board = board if board is not None else FakePiSugar3()
    if devices is None:
        devices = {pisugar3.ADDRESS: board} if isinstance(board, FakePiSugar3) else {0x75: board}
    bus = FakeBus(devices)
    cfg = pconfig.PowerConfig(config_path)
    cfg.set("model", model, save=False)
    for key, value in settings.items():
        cfg.set(key, value, save=False)
    clock = Clock()
    clock_sets = []
    events = []
    runner = DryRunner(returncode=rc, output="sudo: a password is required" if rc else "")
    wall = wall or (lambda: dt.datetime(2026, 10, 10, 9, 0, tzinfo=UTC))

    def open_board(bus_number, model_name, addr):
        return bus, detect.build(bus, bus_number, model_name, addr)
    service = PowerService(cfg, open_board=open_board, monotonic=clock, wallclock=wall,
                           runner=runner, set_clock=clock_sets.append, ntp_synced=lambda: ntp)
    service.on_event = events.append
    service.start()
    return service, board, clock, events, runner, clock_sets


def names(events):
    return [e["event"] for e in events]


class LevelTests(unittest.TestCase):
    def test_level_is_the_mean_of_recent_samples(self):
        service, board, clock, events, *_ = make_service()
        service.tick()
        self.assertEqual(service.view()["level"], round(service.level()))
        board.set_battery(3.70)
        for _ in range(29):
            clock.advance(1.0)
            service.tick()
        self.assertAlmostEqual(service.voltage(), (3.95 + 29 * 3.70) / 30, places=4)
        self.assertEqual(names(events)[0], power.STATE)
        self.assertTrue(events[0]["state"]["present"])

    def test_custom_curve_replaces_the_default(self):
        service, board, *_ = make_service(battery_curve=[[3.5, 0], [4.0, 100]])
        board.set_battery(3.75)
        service.tick()
        self.assertAlmostEqual(service.level(), 50.0)

    def test_implausible_voltage_is_ignored(self):
        service, board, *_ = make_service()
        board.set_battery(0.2)
        service.tick()
        self.assertIsNone(service.level())


class LowBatteryTests(unittest.TestCase):
    def test_countdown_then_poweroff(self):
        service, board, clock, events, runner, _ = make_service()
        board.set_battery(3.30, plugged=False)            # about 4 %
        service.tick()
        self.assertIn(power.LOW_BATTERY, names(events))
        first = next(e for e in events if e["event"] == power.LOW_BATTERY)
        self.assertEqual(first["seconds_left"], 30)
        self.assertEqual(service.view()["low_battery"]["seconds_left"], 30)
        for _ in range(29):
            clock.advance(1.0)
            service.tick()
        self.assertEqual(runner.commands, [])
        clock.advance(1.0)
        service.tick()
        self.assertEqual(len(runner.commands), 1)
        self.assertEqual(runner.commands[0][:2], ["sudo", "-n"])
        self.assertEqual(runner.commands[0][-1], "poweroff")
        shutting = [e for e in events if e["event"] == power.SHUTTING_DOWN]
        self.assertEqual(shutting[0]["reason"], "battery")
        # further ticks do not run the command again
        clock.advance(5)
        service.tick()
        self.assertEqual(len(runner.commands), 1)

    def test_external_power_cancels(self):
        service, board, clock, events, runner, _ = make_service()
        board.set_battery(3.30, plugged=False)
        service.tick()
        clock.advance(10)
        board.set_battery(3.30, plugged=True)
        service.tick()
        cancelled = [e for e in events if e["event"] == power.LOW_BATTERY_CANCELLED]
        self.assertEqual(cancelled[0]["reason"], "plugged")
        clock.advance(60)
        service.tick()
        self.assertEqual(runner.commands, [])

    def test_never_while_plugged_in(self):
        service, board, clock, events, runner, _ = make_service()
        board.set_battery(3.30, plugged=True)
        for _ in range(60):
            clock.advance(1)
            service.tick()
        self.assertNotIn(power.LOW_BATTERY, names(events))
        self.assertEqual(runner.commands, [])

    def test_level_zero_turns_it_off(self):
        service, board, clock, events, runner, _ = make_service(safe_shutdown_level=0)
        board.set_battery(3.15)
        for _ in range(60):
            clock.advance(1)
            service.tick()
        self.assertEqual(runner.commands, [])

    def test_turning_it_off_during_the_countdown_cancels(self):
        service, board, clock, events, runner, _ = make_service()
        board.set_battery(3.30)
        service.tick()
        service.set_option("safe_shutdown_level", 0)
        self.assertEqual(events[-1]["event"] if events[-1]["event"] != power.STATE
                         else [e for e in events if e["event"] == power.LOW_BATTERY_CANCELLED][0]
                         ["event"], power.LOW_BATTERY_CANCELLED)
        clock.advance(60)
        service.tick()
        self.assertEqual(runner.commands, [])

    def test_failed_poweroff_is_reported_and_retried(self):
        service, board, clock, events, runner, _ = make_service(rc=1, safe_shutdown_delay=0)
        board.set_battery(3.30)
        service.tick()
        self.assertEqual(len(runner.commands), 1)
        failed = [e for e in events if e["event"] == power.SHUTDOWN_FAILED]
        self.assertIn("password", failed[0]["error"])
        self.assertEqual(service.shutting_down, "")
        clock.advance(SHUTDOWN_RETRY_SEC + 1)
        service.tick()
        self.assertGreaterEqual(len(runner.commands), 2)


class BoardEventTests(unittest.TestCase):
    def test_soft_shutdown_powers_off(self):
        service, board, clock, events, runner, _ = make_service()
        service.set_option("soft_poweroff", True)
        self.assertTrue(board.bit(pisugar3.REG_CTRL2, pisugar3.SOFT_POWEROFF_ENABLED))
        board.hold_power_button()
        clock.advance(1)
        service.tick()
        self.assertEqual(runner.commands[-1][-1], "poweroff")
        self.assertEqual([e for e in events if e["event"] == power.SHUTTING_DOWN][0]["reason"],
                         "power-button")

    def test_presses_become_button_events(self):
        service, board, clock, events, *_ = make_service()
        board.press("long")
        clock.advance(1)
        service.tick()
        self.assertIn({"event": power.BUTTON, "tap": "long"}, events)

    def test_pisugar2_samples_the_button_only_when_presses_are_wanted(self):
        board, rtc = FakeIP5209(leds=2), FakeSD3078()
        service, board, clock, events, *_ = make_service(
            board=board, devices={0x75: board, 0x32: rtc}, model="pisugar2-2led")
        clock.advance(1)
        service.tick()
        self.assertEqual(service.due(), clock.now + 1.0)       # no 100 ms sampling
        service.set_option("button_double", "screen")
        service.tick()
        self.assertAlmostEqual(service.due(), clock.now + 0.1)
        for level in "0101000":
            board.button(level == "1")
            clock.advance(0.1)
            service.tick()
        self.assertIn({"event": power.BUTTON, "tap": "double"}, events)

    def test_read_failures_are_reported_then_cleared(self):
        service, board, clock, events, *_ = make_service()
        service.tick()
        service.bus.fail = ERRORS_BEFORE_REPORT * 3
        for _ in range(ERRORS_BEFORE_REPORT):
            clock.advance(5)
            service.tick()
        self.assertIn("no answer", service.view()["error"])
        self.assertIsNone(service.view()["level"])
        service.bus.fail = 0
        clock.advance(5)
        service.tick()
        self.assertEqual(service.view()["error"], "")


class ProbeTests(unittest.TestCase):
    def test_missing_board_is_retried_a_few_times_then_left(self):
        cfg = pconfig.PowerConfig(None)
        clock = Clock()
        calls = []

        def open_board(*args):
            calls.append(args)
            raise detect.NotFound("no PiSugar battery board found on I2C bus 1")
        service = PowerService(cfg, open_board=open_board, monotonic=clock, runner=DryRunner())
        service.start()
        self.assertIn("no PiSugar", service.view()["error"])
        for delay in PROBE_RETRY_SEC:
            clock.advance(delay)
            service.tick()
        self.assertEqual(len(calls), 1 + len(PROBE_RETRY_SEC))
        self.assertIsNone(service.due())
        clock.advance(3600)
        service.tick()
        self.assertEqual(len(calls), 1 + len(PROBE_RETRY_SEC))

    def test_model_none_does_not_touch_the_bus(self):
        cfg = pconfig.PowerConfig(None)
        cfg.set("model", "none", save=False)
        service = PowerService(cfg, open_board=detect.open_board, runner=DryRunner())
        with mock.patch.object(detect, "SMBus") as smbus:
            service.start()
        self.assertIn("turned off", service.error)
        self.assertIsNone(service.due())
        self.assertEqual(smbus.call_count, 0)   # the bus is not even opened


class SettingsTests(unittest.TestCase):
    def test_chip_settings_are_written_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "power.json")
            service, board, *_ = make_service(config_path=path)
            service.set_option("power_restore", True)
            self.assertTrue(board.bit(pisugar3.REG_CTRL1, pisugar3.POWER_RESTORE))
            service.set_option("anti_mistouch", True)
            with open(path) as fp:
                saved = json.load(fp)
            self.assertTrue(saved["power_restore"])
            self.assertTrue(saved["anti_mistouch"])
            self.assertEqual(service.chip_settings()["power_restore"], True)

    def test_invalid_values_change_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "power.json")
            service, *_ = make_service(config_path=path)
            for key, value in (("safe_shutdown_level", 50), ("button_long", "explode"),
                               ("wake_time", "25:00"), ("charging_range", [90, 60])):
                with self.assertRaises(Invalid):
                    service.set_option(key, value)
            with self.assertRaises(KeyError):
                service.set_option("nonsense", 1)
            self.assertFalse(os.path.exists(path))

    def test_unsupported_board_features(self):
        board = FakeIP5209(leds=4)
        service, *_ = make_service(board=board, model="pisugar2-4led")
        with self.assertRaises(power_unsupported()):
            service.set_option("battery_protect", True)
        service, *_ = make_service()
        with self.assertRaises(power_unsupported()):
            service.set_option("charging_range", [60, 90])   # PiSugar 3: battery protection

    def test_charging_range_on_a_pisugar2(self):
        board, rtc = FakeIP5209(leds=2, volts=3.6), FakeSD3078()
        service, board, clock, events, *_ = make_service(
            board=board, devices={0x75: board, 0x32: rtc}, model="pisugar2-2led",
            full_charge_duration=10)
        service.chip.set_allow_charging(False)
        service.set_option("charging_range", [60, 90])
        clock.advance(1)
        service.tick()
        self.assertTrue(service.chip.get_allow_charging())      # below 60 %: charging on
        board.set_battery(4.16)
        for _ in range(40):
            clock.advance(1)
            service.tick()
        self.assertFalse(service.chip.get_allow_charging())     # full + 10 s: charging off
        service.set_option("charging_range", None)
        self.assertTrue(service.chip.get_allow_charging())      # range removed: charging on

    def test_wake_alarm_is_written_in_utc(self):
        tz = dt.timezone(dt.timedelta(hours=11))
        service, board, *_ = make_service(wall=lambda: dt.datetime(2026, 10, 10, 9, 0, tzinfo=tz))
        service.set_option("wake_days", 0b0111110)               # Monday..Friday
        service.set_option("wake_time", "07:30")
        alarm = service.chip.rtc.read_alarm()
        # 07:30 local in UTC+11 is 20:30 UTC on the previous day.
        self.assertEqual((alarm.hour, alarm.minute, alarm.enabled), (20, 30, True))
        self.assertEqual(alarm.weekdays, 0b0011111)
        service.set_option("wake_time", None)
        self.assertFalse(service.chip.rtc.read_alarm().enabled)

    def test_wake_alarm_and_power_restore_exclude_each_other(self):
        service, *_ = make_service()
        service.set_option("power_restore", True)
        with self.assertRaises(Invalid):
            service.set_option("wake_time", "06:00")
        self.assertIsNone(service.config.get("wake_time"))
        service.set_option("power_restore", False)
        service.set_option("wake_time", "06:00")
        with self.assertRaises(Invalid):
            service.set_option("power_restore", True)


class ClockTests(unittest.TestCase):
    def test_system_clock_moves_forward_from_the_board(self):
        board = FakePiSugar3()
        board.set_clock(dt.datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
        service, _, clock, _, _, sets = make_service(
            board=board, wall=lambda: dt.datetime(2026, 10, 10, 9, 0, tzinfo=UTC))
        service.tick()
        self.assertEqual(sets, [dt.datetime(2026, 10, 10, 12, 0, tzinfo=UTC)])

    def test_never_backwards_never_from_an_unset_board(self):
        for board_time in (dt.datetime(2026, 10, 10, 8, 0, tzinfo=UTC),
                           dt.datetime(2000, 1, 1, 0, 0, tzinfo=UTC)):
            board = FakePiSugar3()
            board.set_clock(board_time)
            service, _, _, _, _, sets = make_service(board=board)
            service.tick()
            self.assertEqual(sets, [], board_time)

    def test_synchronised_system_clock_is_saved_to_the_board(self):
        board = FakePiSugar3()
        board.set_clock(dt.datetime(2026, 1, 1, tzinfo=UTC))
        service, *_ = make_service(board=board, ntp=True)
        service.tick()
        self.assertEqual(service.chip.rtc.read_time(), dt.datetime(2026, 10, 10, 9, 0, tzinfo=UTC))

    def test_rtc_sync_can_be_turned_off(self):
        board = FakePiSugar3()
        board.set_clock(dt.datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
        service, _, _, _, _, sets = make_service(board=board, rtc_sync=False)
        service.tick()
        self.assertEqual(sets, [])


def power_unsupported():
    from mfruitos.hosts.pisugar.base import Unsupported
    return Unsupported


class ConfigFileTests(unittest.TestCase):
    def test_broken_file_is_kept_and_defaults_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "power.json")
            with open(path, "w") as fp:
                fp.write("{not json")
            cfg = pconfig.PowerConfig(path)
            cfg.load()
            self.assertEqual(cfg.get("safe_shutdown_level"), 5)
            self.assertTrue(any(name.startswith("power.json.broken-") for name in os.listdir(tmp)))

    def test_one_bad_entry_falls_back_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "power.json")
            with open(path, "w") as fp:
                json.dump({"safe_shutdown_level": 99, "safe_shutdown_delay": 60}, fp)
            cfg = pconfig.PowerConfig(path)
            cfg.load()
            self.assertEqual(cfg.get("safe_shutdown_level"), 5)
            self.assertEqual(cfg.get("safe_shutdown_delay"), 60)
            self.assertEqual(len(cfg.load_errors), 1)

    def test_pisugar_settings_are_imported_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            theirs = os.path.join(tmp, "config.json")
            defaults = os.path.join(tmp, "pisugar-server")
            with open(theirs, "w") as fp:
                json.dump({"auth_user": "admin", "auth_password": "secret", "i2c_bus": 1,
                           "auto_shutdown_level": 10.0, "auto_shutdown_delay": 45.0,
                           "auto_power_on": True, "soft_poweroff": True, "anti_mistouch": None,
                           "bat_protect": False, "auto_charging_range": [60.0, 90.0],
                           "auto_wake_time": "2026-01-01T07:15:00+11:00", "auto_wake_repeat": 62,
                           "long_tap_enable": True, "long_tap_shell": "echo hi",
                           "battery_curve": [[3.2, 5], [4.1, 100]]}, fp)
            with open(defaults, "w") as fp:
                fp.write("OPTS=\"--model 'PiSugar 2 (2-LEDs)' --config config.json\"\n")
            got = pconfig.pisugar_settings(theirs, defaults)
            self.assertEqual(got["model"], "pisugar2-2led")
            self.assertEqual(got["safe_shutdown_level"], 10)
            self.assertEqual(got["safe_shutdown_delay"], 45)
            self.assertTrue(got["power_restore"])
            self.assertTrue(got["soft_poweroff"])
            self.assertFalse(got["battery_protect"])
            self.assertNotIn("anti_mistouch", got)
            self.assertEqual(got["charging_range"], [60, 90])
            self.assertEqual(got["wake_days"], 62)
            self.assertEqual(got["tap_hooks"]["long"], {"enabled": True, "shell": "echo hi"})
            self.assertNotIn("auth_password", json.dumps(got))
            path = os.path.join(tmp, "power.json")
            cfg = pconfig.PowerConfig(path)
            self.assertEqual(pconfig.first_load(cfg, lambda: got)[0], "battery_curve")
            self.assertTrue(os.path.exists(path))
            # second start: the file exists, nothing is imported again
            self.assertEqual(pconfig.first_load(pconfig.PowerConfig(path), lambda: got), [])


class CompatTests(unittest.TestCase):
    def setUp(self):
        self.service, self.board, self.clock, self.events, *_ = make_service()
        self.service.tick()
        self.compat = Compat(self.service)

    def ask(self, line):
        return self.compat.handle(line)

    def test_values_in_pisugar_format(self):
        self.assertRegex(self.ask("get battery"), r"^battery: \d+(\.\d)?$")
        self.assertEqual(self.ask("get model"), "model: PiSugar 3")
        self.assertEqual(self.ask("get battery_charging"), "battery_charging: false")
        self.assertEqual(self.ask("get battery_led_amount"), "battery_led_amount: 4")
        self.assertEqual(self.ask("get safe_shutdown_level"), "safe_shutdown_level: 5")
        self.assertTrue(self.ask("get rtc_time").startswith("rtc_time: 2026-"))
        self.assertIn("unknown value", self.ask("get nonsense"))
        self.assertIn("unknown command", self.ask("explode"))

    def test_settings_through_the_protocol(self):
        self.assertEqual(self.ask("set_safe_shutdown_level 12"), "set_safe_shutdown_level: done")
        self.assertEqual(self.service.config.get("safe_shutdown_level"), 12)
        self.assertEqual(self.ask("set_safe_shutdown_level 80"), "set_safe_shutdown_level: done")
        self.assertEqual(self.service.config.get("safe_shutdown_level"), 30)   # PiSugar's cap
        self.assertEqual(self.ask("set_auto_power_on true"), "set_auto_power_on: done")
        self.assertTrue(self.board.bit(pisugar3.REG_CTRL1, pisugar3.POWER_RESTORE))
        self.assertEqual(self.ask("get auto_power_on"), "auto_power_on: true")
        self.assertIn("weekday", self.ask("rtc_alarm_set 2026-01-01T07:00:00+00:00 0"))

    def test_power_cutting_commands_are_refused(self):
        for command in ("force_shutdown", "set_battery_output false", "set_rtc_addr 50",
                        "set_auth admin admin", "rtc_web"):
            self.assertIn("not supported", self.ask(command))
        self.assertTrue(self.board.output_on)

    def test_no_board_answers_with_the_reason(self):
        self.service.close_board()
        self.service.error = "no PiSugar battery board found on I2C bus 1"
        self.assertEqual(self.ask("get battery"), "battery: no PiSugar battery board found on I2C bus 1")


class SocketTests(unittest.TestCase):
    """The real server loop on Unix sockets, with a simulated PiSugar 3."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mfp-")
        self.board = FakePiSugar3()
        bus = FakeBus({pisugar3.ADDRESS: self.board})
        cfg = pconfig.PowerConfig(os.path.join(self.tmp, "power.json"))
        self.service = PowerService(cfg, runner=DryRunner(), ntp_synced=lambda: False,
                                    set_clock=lambda when: None,
                                    open_board=lambda n, m, a: (bus, detect.build(bus, n, m, a)))
        self.hooks = []
        self.api = os.path.join(self.tmp, "power.sock")
        self.compat_path = os.path.join(self.tmp, "pisugar-server.sock")
        self.server = PowerServer(self.service, self.api, self.compat_path,
                                  run_hook=lambda shell, tap: self.hooks.append((shell, tap)))
        self.assertEqual(self.server.bind(), [])
        self.service.start()
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self.client = PowerClient(self.api)

    def tearDown(self):
        self.server.stop()
        self.thread.join(timeout=5)
        self.server.close()
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_status_set_and_errors(self):
        self.assertTrue(self.wait_for(lambda: self.client.status()["level"] is not None))
        status = self.client.status(details=True)
        self.assertEqual(status["model"], "PiSugar 3")
        self.assertIn("board", status)
        config = self.client.set("safe_shutdown_delay", 60)
        self.assertEqual(config["safe_shutdown_delay"], 60)
        with self.assertRaises(PowerError):
            self.client.set("safe_shutdown_delay", 999)
        with self.assertRaises(PowerError):
            self.client.set("tap_hooks", {})      # hooks only through the PiSugar protocol
        self.assertEqual(oct(os.stat(self.api).st_mode & 0o777), "0o600")
        self.assertEqual(self.client.request("ping")["ok"], True)
        self.assertFalse(self.client.request("explode")["ok"])

    def test_events_presses_and_hooks(self):
        received = []
        events = PowerEvents(self.api, received.append)
        events.start()
        try:
            self.assertTrue(self.wait_for(lambda: any(e["event"] == "_connected" for e in received)))
            self.assertTrue(self.wait_for(lambda: any(e["event"] == power.STATE for e in received)))
            with socket.socket(socket.AF_UNIX) as compat:
                compat.connect(self.compat_path)
                compat.sendall(b"set_button_enable single 1\nset_button_shell single echo pressed\n")
                compat.settimeout(3)
                answers = b""
                while answers.count(b"\n") < 2:
                    answers += compat.recv(1024)
                self.assertIn(b"set_button_shell: done", answers)
                self.board.press("single")
                self.assertTrue(self.wait_for(
                    lambda: {"event": power.BUTTON, "tap": "single"} in received))
                pushed = compat.recv(1024)
                self.assertIn(b"single", pushed)
            self.assertTrue(self.wait_for(lambda: ("echo pressed", "single") in self.hooks))
        finally:
            events.stop()

    def test_bundled_daemon_pisugar_client_works_against_the_compat_socket(self):
        """whisplay-daemon's own PiSugar code (unmodified, drivers/whisplay) as a client."""
        daemon_dir = os.path.join(ROOT, "drivers", "whisplay", "daemon")
        sys.path.insert(0, daemon_dir)
        try:
            daemon_pisugar = importlib.import_module("daemon_pisugar")
        finally:
            sys.path.remove(daemon_dir)
        manager = daemon_pisugar.PiSugarManager()
        self.assertTrue(self.wait_for(lambda: self.client.status()["level"] is not None))
        with mock.patch.object(daemon_pisugar, "PISUGAR_SOCKET_CANDIDATES", (self.compat_path,)):
            self.assertEqual(manager.socket_path(), self.compat_path)
            level = manager.probe_battery_level()
            self.assertEqual(level, int(self.service.level()))
            self.assertIs(manager.has_custom_button_event(self.compat_path, "single"), False)
            self.assertTrue(manager.setup_button_hook(self.compat_path, "single"))
            hooks = self.service.config.get("tap_hooks")
            self.assertTrue(hooks["single"]["enabled"])
            self.assertIn(daemon_pisugar.PISUGAR_TRIGGER_FILE, hooks["single"]["shell"])
            # the daemon's start-up clean-up recognises and removes its own hook
            manager.cleanup_daemon_managed_hooks(self.compat_path)
            self.assertFalse(self.service.config.get("tap_hooks")["single"]["enabled"])

    def test_sdk_and_launcher_battery_reads(self):
        from mfruitos.sdk import status as sdk_status
        from mfruitos.system import hardware
        self.assertTrue(self.wait_for(lambda: self.client.status()["level"] is not None))
        with mock.patch.object(sdk_status, "PISUGAR_SOCKETS", (self.compat_path,)), \
                mock.patch.object(hardware, "PISUGAR_SOCKETS", (self.compat_path,)):
            self.assertEqual(sdk_status.read_battery(), (int(self.service.level()), False))
            self.assertEqual(hardware.read_battery(), (int(self.service.level()), False))

    def test_another_server_on_the_compat_socket_is_left_alone(self):
        other_dir = tempfile.mkdtemp(prefix="mfq-")
        try:
            path = os.path.join(other_dir, "pisugar-server.sock")
            busy = socket.socket(socket.AF_UNIX)
            busy.bind(path)
            busy.listen(1)
            server = PowerServer(self.service, os.path.join(other_dir, "power.sock"), path)
            warnings = server.bind()
            self.assertTrue(any("another program" in w for w in warnings))
            self.assertTrue(os.path.exists(path))
            server.close()
            busy.close()
        finally:
            for name in os.listdir(other_dir):
                os.unlink(os.path.join(other_dir, name))
            os.rmdir(other_dir)


class CommandLineTests(unittest.TestCase):
    def test_an_update_is_seen_through_the_current_link(self):
        """The service runs with the resolved version as its working directory;
        only the system/current link changes when mFruit OS is updated."""
        from mfruitos.paths import Paths
        from mfruitos.power.__main__ import active_code
        with tempfile.TemporaryDirectory() as tmp:
            paths = Paths(os.path.join(tmp, "os"), os.path.join(tmp, "daemon"))
            for version in ("a", "b"):
                os.makedirs(os.path.join(paths.system_dir, "versions", version))
            link = os.path.join(paths.system_dir, "current")
            os.symlink(os.path.join(paths.system_dir, "versions", "a"), link)
            before = active_code(paths)
            os.unlink(link)
            os.symlink(os.path.join(paths.system_dir, "versions", "b"), link)
            self.assertNotEqual(active_code(paths), before)
            self.assertTrue(active_code(paths).endswith(os.path.join("versions", "b")))

    def test_client_commands_report_a_stopped_service(self):
        from mfruitos.power.__main__ import main
        with tempfile.TemporaryDirectory(prefix="mfp-") as tmp:
            with mock.patch("sys.stderr") as err:
                self.assertEqual(main(["--home", tmp, "status"]), 1)
            self.assertIn("not running", "".join(c.args[0] for c in err.write.call_args_list))

    def test_power_command_uses_sudo_without_password(self):
        from mfruitos.power.service import power_command
        self.assertEqual(power_command(False)[:2], ["sudo", "-n"])
        self.assertEqual(power_command(True)[-1], "reboot")


if __name__ == "__main__":
    unittest.main()
