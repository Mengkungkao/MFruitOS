import queue
import sys
import threading
import types
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

    def test_fallback_search_reports_failure_and_no_response(self):
        for output in ("Failed to start discovery: org.bluez.Error.NotReady", ""):
            with self.subTest(output=output):
                bt = self.service({("--timeout", "8", "scan", "on"): output})
                with self.assertRaises(RuntimeError):
                    bt.search()

    def test_short_fallback_search_still_has_a_timeout(self):
        bt = self.service({})
        bt._run = Mock(return_value="Discovery started")
        bt.search(0.5)
        bt._run.assert_called_once_with(["bluetoothctl", "--timeout", "1", "scan", "on"], 5.5)

    def test_timed_out_agent_start_reuses_in_flight_thread(self):
        bt = self.service({})
        bt._dbus = Mock()
        release = threading.Event()
        entered = threading.Event()

        def agent_loop(ready):
            entered.set()
            release.wait(5)

        bt._agent_loop = Mock(side_effect=agent_loop)
        try:
            with patch.object(bt._agent_ready, "wait", return_value=False):
                self.assertFalse(bt.start_agent())
                self.assertTrue(entered.wait(1))
                first_thread = bt._agent_thread
                self.assertFalse(bt.start_agent())
                self.assertIs(bt._agent_thread, first_thread)
            bt._agent_loop.assert_called_once_with(bt._agent_ready)
        finally:
            release.set()
            bt._agent_thread.join(2)
        self.assertFalse(bt._agent_thread.is_alive())

    def test_closed_service_does_not_start_an_agent(self):
        bt = self.service({})
        bt._dbus = Mock()
        bt.close()
        with patch("mfruitos.system.bluetooth.threading.Thread") as thread:
            self.assertFalse(bt.start_agent())
        thread.assert_not_called()

    def test_agent_bus_failure_signals_startup_completion(self):
        bt = self.service({})
        dbus = types.ModuleType("dbus")
        dbus.SystemBus = Mock(side_effect=RuntimeError("System bus unavailable"))
        dbus.service = types.ModuleType("dbus.service")
        mainloop = types.ModuleType("dbus.mainloop.glib")
        mainloop.DBusGMainLoop = Mock()
        gi = types.ModuleType("gi.repository")
        gi.GLib = Mock()
        ready = threading.Event()
        with patch.dict(sys.modules, {"dbus": dbus, "dbus.service": dbus.service,
                                      "dbus.mainloop.glib": mainloop,
                                      "gi.repository": gi}):
            bt._agent_loop(ready)
        self.assertTrue(ready.is_set())
        self.assertIsNone(bt._agent)
        self.assertIsNone(bt._agent_bus)

    def test_close_cancels_in_flight_pair_and_releases_waiter(self):
        bt = self.service({})
        bt._dbus = Mock()
        bt._glib = Mock()
        bt._agent_bus = Mock()
        bt._mainloop = Mock()
        bt.start_agent = Mock(return_value=True)
        bt._device_path = Mock(return_value="/org/bluez/hci0/dev_AA")
        bt._set_device = Mock()
        bt.connect = Mock()
        callbacks = queue.Queue()
        bt._glib.idle_add.side_effect = lambda callback, *args: callbacks.put((callback, args))
        device = bt._dbus.Interface.return_value
        result = []
        with patch("mfruitos.system.bluetooth.PAIR_TIMEOUT_SEC", 0.1):
            worker = threading.Thread(target=lambda: result.append(bt.pair("AA")), daemon=True)
            worker.start()
            try:
                callback, args = callbacks.get(timeout=1)
                callback(*args)  # Start the pending asynchronous Pair call.
                device.Pair.assert_called_once()
                bt.close()
                worker.join(0.5)
                self.assertFalse(worker.is_alive(), "Shutdown left pairing waiting for its timeout")
                while not callbacks.empty():
                    callback, args = callbacks.get_nowait()
                    callback(*args)
                device.CancelPairing.assert_called_once()
                self.assertEqual(bt._device_path.call_count, 1)
                self.assertEqual(result, [(False, "Pairing was cancelled")])
                bt._set_device.assert_not_called()
                bt.connect.assert_not_called()
            finally:
                worker.join(3)

    def test_close_before_queued_pair_does_not_start_pairing(self):
        bt = self.service({})
        bt._dbus = Mock()
        bt._glib = Mock()
        bt._agent_bus = Mock()
        bt.start_agent = Mock(return_value=True)
        bt._device_path = Mock(return_value="/org/bluez/hci0/dev_AA")
        bt._set_device = Mock()
        bt.connect = Mock()
        callbacks = queue.Queue()
        bt._glib.idle_add.side_effect = lambda callback, *args: callbacks.put((callback, args))
        result = []
        with patch("mfruitos.system.bluetooth.PAIR_TIMEOUT_SEC", 0.1):
            worker = threading.Thread(target=lambda: result.append(bt.pair("AA")), daemon=True)
            worker.start()
            try:
                callback, args = callbacks.get(timeout=1)
                bt.close()
                callback(*args)
                bt._dbus.Interface.return_value.Pair.assert_not_called()
                worker.join(0.5)
                self.assertEqual(result, [(False, "Pairing was cancelled")])
                bt._set_device.assert_not_called()
                bt.connect.assert_not_called()
            finally:
                worker.join(3)
