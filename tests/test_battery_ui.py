"""The launcher's side of power management: PowerLink, Settings > Battery,
the low-battery warning, the power menu and board button actions."""

from unittest.mock import Mock, PropertyMock, patch

import helpers
from helpers import ROOT, TempHomeTestCase
from mfruitos import power
from mfruitos.launcher.focus import APP, HOME, ForegroundManager
from mfruitos.launcher.navigation.router import Router
from mfruitos.launcher.power_link import PowerLink
from mfruitos.launcher.runtime import Runtime
from mfruitos.launcher.ui.screens.base import Screen
from mfruitos.launcher.ui.screens.battery import (BatteryScreen, LowBatteryScreen,
                                                  PowerMenuScreen, WakeAlarmScreen, days_label)
from mfruitos.launcher.ui.screens.dialogs import MessageScreen
from mfruitos.launcher.ui.screens.settings import GeneralScreen, SettingsScreen

STATUS = {
    "present": True, "model": "PiSugar 3", "key": "pisugar3", "firmware": "1.2.4",
    "level": 82, "voltage": 4.02, "plugged": True, "charging": True, "temperature": 31,
    "error": "", "features": ["anti_mistouch", "battery_protect", "charging_control",
                              "power_restore", "rtc", "soft_poweroff", "taps", "temperature"],
    "config": {"safe_shutdown_level": 5, "safe_shutdown_delay": 30, "button_double": "none",
               "button_long": "none", "wake_time": None, "wake_days": 127},
    "board": {"power_restore": False, "soft_poweroff": False, "anti_mistouch": True,
              "battery_protect": False},
}


def labels(items):
    return [item.resolve("label") for item in items]


class PowerLinkTests(TempHomeTestCase):
    def test_events_update_the_link(self):
        posted = []
        link = PowerLink(self.tmp + "/power.sock", lambda fn, *args: posted.append((fn, args)))
        seen = []
        link.listener = seen.append
        self.assertIsNone(link.battery())
        link._event({"event": "_connected"})
        link._event({"event": power.STATE, "state": {"present": True, "level": 40,
                                                     "charging": False}})
        self.assertEqual(link.battery(), (40, False))
        link._event({"event": power.STATE, "state": {"present": False, "level": None}})
        self.assertEqual(link.battery(), (None, False))
        link._event({"event": power.CONFIG, "config": {"button_long": "screen"}})
        self.assertEqual(link.button_action("long"), "screen")
        self.assertEqual(link.button_action("single"), "none")    # whisplay-daemon's Home
        link._event({"event": "_disconnected"})
        self.assertIsNone(link.battery())
        self.assertEqual(len(seen), 5)


class RuntimePowerTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.rt = Runtime(self.paths, ROOT, socket_path=self.tmp + "/none.sock",
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.router.set_root(self.rt.home_screen)
        self.rt.led = Mock()
        self.rt.backlight = Mock(state="on")
        self.rt.power.client = Mock()
        self.rt.power.client.status.return_value = dict(STATUS)
        self.focus = patch.object(ForegroundManager, "has_focus", new_callable=PropertyMock,
                                  return_value=True)
        self.focus.start()
        self.addCleanup(self.focus.stop)
        self.rt.focus.mode = HOME

    def event(self, **event):
        self.rt.power._event(event)

    def drain(self):
        for _ in range(5):
            self.rt.loop.run_once()

    def connect(self, **state):
        self.event(event="_connected")
        self.event(event=power.STATE, state=dict({"present": True, "level": 60,
                                                  "charging": False}, **state))

    def test_status_bar_follows_the_power_service(self):
        self.connect(level=61, charging=True)
        self.assertEqual((self.rt.status.battery, self.rt.status.charging), (61, True))
        with patch("mfruitos.system.hardware.read_battery") as read:
            self.rt._refresh_status()
        read.assert_not_called()
        self.event(event="_disconnected")
        with patch("mfruitos.system.hardware.read_battery", return_value=(33, False)) as read, \
                patch.object(self.rt, "_output", return_value=object()):
            self.rt._refresh_status()
        read.assert_called_once()                       # PiSugar's own server, as before
        self.assertEqual(self.rt.status.battery, 33)

    def test_low_battery_countdown_and_cancel(self):
        self.connect(level=4)
        self.event(event=power.LOW_BATTERY, level=4, seconds_left=30)
        top = self.rt.router.top
        self.assertIsInstance(top, LowBatteryScreen)
        self.assertIn("30 s", top.message)
        self.rt.led.show.assert_called_with("error", force=True)
        self.event(event=power.LOW_BATTERY, level=3, seconds_left=10)
        self.assertIs(self.rt.router.top, top)          # updated, not stacked twice
        self.assertIn("10 s", top.message)
        self.event(event=power.LOW_BATTERY_CANCELLED, reason="plugged")
        self.assertIs(self.rt.router.top, self.rt.home_screen)
        self.rt.led.show.assert_called_with("idle", force=True)
        self.assertEqual(self.rt._toast[0], "Power connected")

    def test_low_battery_over_an_app_only_lights_the_led(self):
        self.rt.focus.mode = APP
        self.event(event=power.LOW_BATTERY, level=4, seconds_left=30)
        self.assertIs(self.rt.router.top, self.rt.home_screen)
        self.rt.led.show.assert_called_with("error", force=True)

    def test_shutting_down_blocks_navigation(self):
        self.event(event=power.SHUTTING_DOWN, reason="battery", reboot=False)
        top = self.rt.router.top
        self.assertIsInstance(top, MessageScreen)
        self.assertTrue(top.modal)
        self.assertEqual(top.heading, "Shutting down")

    def test_board_button_actions(self):
        self.connect()
        self.event(event=power.CONFIG, config={"button_long": "power_menu",
                                               "button_double": "screen"})
        self.event(event=power.BUTTON, tap="single")
        self.assertIs(self.rt.router.top, self.rt.home_screen)   # the daemon's Home
        self.event(event=power.BUTTON, tap="long")
        self.assertIsInstance(self.rt.router.top, PowerMenuScreen)
        self.event(event=power.BUTTON, tap="double")
        self.rt.backlight.off.assert_called_once()
        self.rt.backlight.state = "off"
        self.event(event=power.BUTTON, tap="double")
        self.rt.backlight.wake.assert_called()

    def test_home_press_asks_a_running_app_to_leave(self):
        self.connect()
        self.event(event=power.CONFIG, config={"button_long": "home"})
        self.rt.focus.mode = APP
        self.rt.apps.request_stop = Mock(return_value=True)
        self.event(event=power.BUTTON, tap="long")
        self.rt.apps.request_stop.assert_called_once_with(reason="battery-button")

    def test_power_menu_shuts_down_through_the_service(self):
        self.connect()
        self.rt.open_power_menu()
        menu = self.rt.router.top
        self.assertEqual(labels(menu.items()), ["Lock screen", "Restart", "Shut down", "Back"])
        menu.items()[2].action()                         # Shut down -> confirmation
        confirm = self.rt.router.top
        self.assertEqual(labels(confirm.items())[0], "Cancel")   # the safe choice first
        confirm.items()[1].action()
        self.drain()
        self.rt.power.client.shutdown.assert_called_once_with(reboot=False, reason="menu")

    def test_without_the_service_the_daemon_power_page_is_used(self):
        self.rt.open_system_page = Mock()
        with patch.object(self.rt, "system_page_available", return_value=True):
            self.rt.open_power_menu()
        self.rt.open_system_page.assert_called_once_with("whisplay-system")

    def test_settings_rows(self):
        battery = next(i for i in SettingsScreen(self.rt).items() if i.label == "Battery")
        self.assertEqual(battery.resolve("subtitle"), "Power service off")
        self.connect(level=82, charging=True)
        battery = next(i for i in SettingsScreen(self.rt).items() if i.label == "Battery")
        self.assertEqual(battery.resolve("subtitle"), "82% · Charging")
        power_row = next(i for i in GeneralScreen(self.rt).items() if i.label == "Power")
        power_row.action()
        self.assertIsInstance(self.rt.router.top, PowerMenuScreen)

    def test_battery_page(self):
        screen = BatteryScreen(self.rt)
        self.rt.push(screen)
        self.drain()
        rows = labels(screen.items())
        for wanted in ("Level", "Status", "Voltage", "Board", "Shut down at", "Countdown",
                       "Double press", "Long press", "Hold to shut down safely", "Anti-mistouch",
                       "Power on when plugged in", "Battery protection", "Wake up",
                       "Save time to battery clock", "Back"):
            self.assertIn(wanted, rows)
        self.assertNotIn("Charging range", rows)          # PiSugar 3: battery protection
        double = next(i for i in screen.items() if i.label == "Double press")
        self.assertFalse(double.enabled)                  # each PiSugar 3 press is Home
        # Each switch sends the opposite of its own board value (a closure
        # bug once made every switch use the last row's value).
        for label, key in (("Hold to shut down safely", "soft_poweroff"),
                           ("Anti-mistouch", "anti_mistouch"),
                           ("Power on when plugged in", "power_restore"),
                           ("Battery protection", "battery_protect")):
            toggle = next(i for i in screen.items() if i.label == label)
            self.assertEqual(toggle.value, STATUS["board"][key], label)
            toggle.action()
            self.drain()
            self.rt.power.client.set.assert_called_with(key, not STATUS["board"][key])

    def test_battery_page_without_service_or_board(self):
        self.rt.power.client.status.side_effect = OSError("no socket")
        screen = BatteryScreen(self.rt)
        screen.refresh()
        self.drain()
        self.assertIn("The power service is not running", labels(screen.items()))
        self.rt.power.client.status.side_effect = None
        self.rt.power.client.status.return_value = {"present": False,
                                                    "error": "no PiSugar battery board found"}
        screen.refresh()
        self.drain()
        rows = screen.items()
        self.assertEqual(rows[0].label, "No battery board")
        self.assertEqual(rows[0].resolve("subtitle"), "no PiSugar battery board found")
        rows[0].action()                                   # the whole reason
        self.assertEqual(self.rt.router.top.message, "no PiSugar battery board found")
        self.rt.pop()
        rows[1].action()                                   # Look again
        self.drain()
        self.rt.power.client.probe.assert_called_once()

    def test_wake_alarm_flow(self):
        screen = BatteryScreen(self.rt)
        self.rt.push(screen)
        self.drain()
        wake = WakeAlarmScreen(self.rt, screen)
        self.rt.push(wake)
        wake.items()[2].action()                           # Weekdays -> hour
        hour = self.rt.router.top
        hour.value = 6
        hour.handle("select")
        self.drain()                   # minute screen pushed after the pop
        minute = self.rt.router.top
        minute.value = 45
        minute.handle("select")
        self.drain()
        calls = [c.args for c in self.rt.power.client.set.call_args_list]
        self.assertIn(("wake_days", 0b0111110), calls)
        self.assertIn(("wake_time", "06:45"), calls)
        self.assertIsInstance(self.rt.router.top, BatteryScreen)
        self.assertEqual(days_label(0b0111110), "Mon–Fri")


class RouterRemoveTests(TempHomeTestCase):
    def test_remove_from_anywhere_but_the_root(self):
        router = Router()
        root, a, b = (Screen(Mock()) for _ in range(3))
        router.set_root(root)
        router.push(a)
        router.push(b)
        self.assertTrue(router.remove(a))
        self.assertEqual(list(router), [root, b])
        self.assertTrue(router.remove(b))
        self.assertIs(router.top, root)
        self.assertFalse(router.remove(root))


class MfruitctlPowerTests(TempHomeTestCase):
    def test_power_subcommand_uses_the_power_cli(self):
        from mfruitos import ctl
        with patch("mfruitos.power.__main__.main", return_value=0) as power_main:
            self.assertEqual(ctl.main(["power"]), 0)
            self.assertEqual(ctl.main(["power", "set", "safe_shutdown_level", "10"]), 0)
        self.assertEqual(power_main.call_args_list[0].args[0], ["status"])
        self.assertEqual(power_main.call_args_list[1].args[0],
                         ["set", "safe_shutdown_level", "10"])
