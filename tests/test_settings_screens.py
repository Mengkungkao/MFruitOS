from unittest.mock import Mock, patch

import helpers
from helpers import ROOT, TempHomeTestCase
from mfruitos.launcher.runtime import Runtime
from mfruitos.launcher.ui.screens.settings import SettingsScreen, WifiScreen, GeneralScreen
from mfruitos.launcher.ui.screens.bluetooth import BluetoothScreen, BtDeviceScreen, PairingScreen
from mfruitos.launcher.ui.components import Item, selectable, draw_list
from mfruitos.system.bluetooth import BtDevice, Prompt


class SettingsScreensTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.rt = Runtime(self.paths, ROOT, socket_path=self.tmp + "/none.sock",
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.bluetooth = Mock()
        self.rt.bluetooth.available.return_value = True
        self.rt.bluetooth.powered.return_value = True
        self.rt.bluetooth.devices.return_value = []
        self.rt.router.set_root(self.rt.home_screen)

    def drain(self):
        for _ in range(5):
            self.rt.loop.run_once(timeout=0)

    def test_settings_has_uniform_rows_in_both_directions(self):
        screen = SettingsScreen(self.rt)
        items = screen.items()
        self.assertFalse(any(i.kind == "section" for i in items))
        from mfruitos.launcher.ui.components import row_height
        self.assertEqual({row_height(i) for i in items}, {46})
        self.assertEqual(items[0].label, "Wi-Fi")
        for direction in ("next", "previous"):
            for _ in range(len(items) * 2):
                screen.handle(direction)
                self.assertTrue(selectable(screen.current_items()[screen.selected]))

    def test_wifi_uses_connectwifi_and_explains_when_missing(self):
        wifi = WifiScreen(self.rt)
        self.rt.launch_app = Mock()
        self.rt.open_system_page = Mock()
        self.rt.show_message = Mock()
        with patch.object(self.rt.registry, "get", return_value=object()):
            wifi.choose_network()
        self.rt.launch_app.assert_called_once_with("connectwifi", source="settings")
        with patch.object(self.rt, "system_page_available", return_value=True):
            wifi.choose_network()
        self.rt.open_system_page.assert_not_called()
        self.rt.show_message.assert_called_once_with(
            "Wi-Fi", "Install Connect WiFi to choose a network.")

    def test_wifi_does_not_call_a_default_route_internet_access(self):
        wifi = WifiScreen(self.rt)
        self.assertEqual(wifi.internet, "Not checked")
        self.rt.run_task = Mock()
        wifi.check_internet()
        self.rt.run_task.call_args.args[2](Mock(ok=False))
        self.assertEqual(wifi.internet, "Unavailable")

    def test_bluetooth_filters_unnamed_and_groups_saved_devices(self):
        screen = BluetoothScreen(self.rt)
        screen.powered = True
        screen.devices = [BtDevice("A", "Keys", paired=True), BtDevice("B", "Speaker"),
                          BtDevice("C", "AA-BB-CC-DD-EE-FF")]
        labels = [i.label for i in screen.items()]
        self.assertLess(labels.index("My devices"), labels.index("Keys"))
        self.assertLess(labels.index("Other devices"), labels.index("Speaker"))
        self.assertNotIn("AA-BB-CC-DD-EE-FF", labels)

    def test_departed_screen_does_not_start_scan(self):
        screen = BluetoothScreen(self.rt)
        self.rt.run_task = Mock()
        screen.refresh(search=True)
        self.rt.run_task.call_args.args[2]((True, True, []))
        self.rt.bluetooth.search.assert_not_called()

    def test_pairing_done_closes_prompt_and_duplicate_actions_are_ignored(self):
        device = BtDeviceScreen(self.rt, BtDevice("A", "Keys"))
        self.rt.push(device)
        self.rt.run_task = Mock()
        device.operate("pair")
        device.operate("pair")
        self.assertEqual(self.rt.run_task.call_count, 1)
        device.on_prompt(Prompt("confirm", "012345", "A"))
        self.assertIsInstance(self.rt.router.top, PairingScreen)
        self.assertEqual(self.rt.router.top.items()[0].label, "No")
        device.on_prompt(Prompt("done"))
        self.assertIs(self.rt.router.top, device)

    def test_general_contains_about_updates_and_diagnostics(self):
        labels = [i.label for i in GeneralScreen(self.rt).items()]
        for label in ("About", "Software Update", "System info", "Diagnostics", "Restart launcher"):
            self.assertIn(label, labels)

    def test_scrolled_lists_never_draw_partial_rows(self):
        from mfruitos.launcher.ui.painter import Painter
        from mfruitos.launcher.ui.theme import DARK
        painter = Painter(DARK, self.rt.fonts)
        rows = [Item(str(i), subtitle="Details") for i in range(12)]
        with patch("mfruitos.launcher.ui.components._draw_row") as draw:
            draw_list(painter, rows, 8)
        self.assertGreater(draw.call_count, 0)
        for call in draw.call_args_list:
            y, height = call.args[2:4]
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y + height, 208)

    def test_boot_is_logo_only_even_in_light_theme(self):
        self.rt.settings.set("display.theme", "light")
        self.rt.router.set_root(self.rt.boot_screen)
        first = self.rt.compose()
        self.rt.boot_screen.set_step(0, "done")
        self.rt.boot_screen.ready = True
        self.assertEqual(first.tobytes(), self.rt.compose().tobytes())
        self.assertEqual(first.getpixel((0, 0)), (10, 12, 16))
