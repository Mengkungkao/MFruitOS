import unittest
from unittest.mock import Mock, patch

from mfruitos.system.bluetooth import Bluetooth, BtDevice, named, parse_info, sort_key


class BluetoothTests(unittest.TestCase):
    def service(self, answers):
        def run(args, timeout):
            return answers.get(tuple(args[1:]), "")
        with patch("mfruitos.system.bluetooth._load_dbus", return_value=None):
            return Bluetooth(run=run)

    def test_info_and_named_devices(self):
        d = parse_info("AA:BB:CC:DD:EE:FF", "\x1b[0mAlias: Keyboard\nPaired: yes\n"
                       "Connected: yes\nTrusted: yes\nIcon: input-keyboard\nRSSI: 0xffffffb0 (-80)")
        self.assertEqual((d.name, d.kind, d.rssi), ("Keyboard", "Keyboard", -80))
        self.assertTrue(d.connected and d.paired and d.trusted and named(d))
        self.assertFalse(named(BtDevice(d.address, "AA-BB-CC-DD-EE-FF")))
        self.assertFalse(named(BtDevice(d.address, "")))

    def test_sort_connected_then_paired_then_signal(self):
        devices = [BtDevice("1", "Far", rssi=-90), BtDevice("2", "Saved", paired=True),
                   BtDevice("3", "Live", paired=True, connected=True), BtDevice("4", "Near", rssi=-30)]
        self.assertEqual([d.name for d in sorted(devices, key=sort_key)], ["Live", "Saved", "Near", "Far"])

    def test_old_bluetoothctl_devices_uses_info(self):
        bt = self.service({("devices",): "Device AA:BB:CC:DD:EE:FF Keys\n",
                           ("info", "AA:BB:CC:DD:EE:FF"): "Paired: yes\nConnected: no"})
        self.assertEqual(bt.devices()[0].name, "Keys")
        self.assertTrue(bt.devices()[0].paired)

    def test_failed_pair_does_not_trust_or_connect(self):
        bt = self.service({})
        bt._run = Mock(return_value="Failed to pair: org.bluez.Error.AlreadyInProgress")
        self.assertFalse(bt.pair("AA")[0])
        self.assertEqual(bt._run.call_count, 1)

    def test_pair_connect_failure_is_not_reported_as_connected(self):
        bt = self.service({("pair", "AA"): "Pairing successful", ("trust", "AA"): "trust succeeded",
                           ("connect", "AA"): "Failed to connect"})
        ok, message = bt.pair("AA")
        self.assertTrue(ok)
        self.assertIn("Paired;", message)
        self.assertNotEqual(message, "Connected")

    def test_fallback_actions_report_errors(self):
        bt = self.service({("connect", "AA"): "Connection successful",
                           ("disconnect", "AA"): "Successful disconnected",
                           ("remove", "AA"): "Device has been removed"})
        self.assertTrue(bt.connect("AA")[0])
        self.assertTrue(bt.disconnect("AA")[0])
        self.assertTrue(bt.forget("AA")[0])
        self.assertFalse(bt.connect("BB")[0])
        with self.assertRaises(RuntimeError):
            bt.set_powered(True)

    def test_query_bus_is_reused_and_closed(self):
        with patch("mfruitos.system.bluetooth._load_dbus") as load:
            bt = Bluetooth()
            bus = load.return_value.SystemBus.return_value
            self.assertIs(bt._bus(), bt._bus())
            load.return_value.SystemBus.assert_called_once_with(private=True)
            bt.close()
            bus.close.assert_called_once()

    def test_confirmation_reply_is_exactly_once(self):
        bt = self.service({})
        bt._glib = Mock()
        reply, error = Mock(), Mock()
        bt._confirmation = (reply, error)
        bt._confirmation_timer = 42
        bt._resolve_confirmation(True)
        bt._resolve_confirmation(True)
        reply.assert_called_once_with()
        error.assert_not_called()
        bt._glib.source_remove.assert_called_once_with(42)
