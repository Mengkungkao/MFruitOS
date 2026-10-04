import os
import queue
import shutil
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from mfruitos.system import bluetooth as bt_module
from mfruitos.system.bluetooth import Bluetooth, BtDevice, named, parse_info, sort_key


class FakeRfkill:
    """A /sys/class/rfkill tree and a /dev/rfkill stand-in that applies written events."""

    def __init__(self, test, bluetooth_soft="1", bluetooth_hard="0", writable=True):
        self.root = tempfile.mkdtemp(prefix="mfruit-rfkill-")
        test.addCleanup(shutil.rmtree, self.root, True)
        self.sysfs = os.path.join(self.root, "sys")
        for name, kind, soft, hard in (("rfkill0", "bluetooth", bluetooth_soft, bluetooth_hard),
                                       ("rfkill1", "wlan", "0", "0")):
            os.makedirs(os.path.join(self.sysfs, name))
            for field, value in (("type", kind), ("soft", soft), ("hard", hard)):
                with open(os.path.join(self.sysfs, name, field), "w") as fp:
                    fp.write(value + "\n")
        self.device = os.path.join(self.root, "rfkill")
        open(self.device, "wb").close()
        if not writable:
            os.chmod(self.device, 0o444)
        patches = [patch.object(bt_module, "RFKILL_SYSFS", self.sysfs),
                   patch.object(bt_module, "RFKILL_DEVICE", self.device),
                   patch.object(bt_module, "rfkill_unblock", side_effect=self.unblock)]
        for p in patches:
            p.start()
            test.addCleanup(p.stop)
        self.events = []

    def unblock(self, device=None):
        ok = _real_rfkill_unblock(self.device)
        if ok:
            with open(self.device, "rb") as fp:
                self.events.append(fp.read())
            # The kernel would clear the soft block of every Bluetooth radio.
            with open(os.path.join(self.sysfs, "rfkill0", "soft"), "w") as fp:
                fp.write("0\n")
        return ok


_real_rfkill_unblock = bt_module.rfkill_unblock


class RfkillTests(unittest.TestCase):
    def service(self, powers_itself=False):
        self.commands = []

        def run(args, timeout):
            self.commands.append(tuple(args[1:]))
            if args[1:] == ["show"]:
                return "Powered: yes" if powers_itself else "Powered: no"
            return "Changing power on succeeded"
        with patch("mfruitos.system.bluetooth._load_dbus", return_value=None), \
                patch.object(bt_module, "POWER_SETTLE_SEC", 0.2):
            bt = Bluetooth(run=run)
        patcher = patch.object(bt_module, "POWER_SETTLE_SEC", 0.2)
        patcher.start()
        self.addCleanup(patcher.stop)
        return bt

    def test_after_an_unblock_bluez_powering_on_itself_is_not_raced(self):
        # Pi Zero 2 W, 2026-10-04: asking BlueZ to power on while it was already
        # doing so after the unblock answered org.bluez.Error.Busy.
        FakeRfkill(self, bluetooth_soft="1")
        self.service(powers_itself=True).set_powered(True)
        self.assertNotIn(("power", "on"), self.commands)

    def test_after_an_unblock_power_is_requested_if_bluez_does_not(self):
        FakeRfkill(self, bluetooth_soft="1")
        self.service(powers_itself=False).set_powered(True)
        self.assertIn(("power", "on"), self.commands)

    def test_state_reads_only_bluetooth_radios(self):
        fake = FakeRfkill(self, bluetooth_soft="1")
        self.assertEqual(bt_module.rfkill_blocked(), (True, False))
        with open(os.path.join(fake.sysfs, "rfkill0", "soft"), "w") as fp:
            fp.write("0\n")
        self.assertEqual(bt_module.rfkill_blocked(), (False, False))
        self.assertEqual(bt_module.rfkill_blocked(os.path.join(fake.root, "missing")), (False, False))

    def test_turning_on_lifts_a_soft_block_first(self):
        fake = FakeRfkill(self, bluetooth_soft="1")
        self.service().set_powered(True)
        # rfkill_event: idx 0, type BLUETOOTH (2), op CHANGE_ALL (3), soft 0, hard 0.
        self.assertEqual(fake.events, [struct.pack("=IBBBB", 0, 2, 3, 0, 0)])
        self.assertEqual(bt_module.rfkill_blocked(), (False, False))

    def test_not_blocked_writes_nothing(self):
        fake = FakeRfkill(self, bluetooth_soft="0")
        self.service().set_powered(True)
        self.assertEqual(fake.events, [])

    def test_turning_off_never_touches_rfkill(self):
        fake = FakeRfkill(self, bluetooth_soft="1")
        bt = self.service()
        bt._run = lambda args, timeout: "Changing power off succeeded"
        bt.set_powered(False)
        self.assertEqual(fake.events, [])

    def test_no_permission_explains_what_to_do(self):
        if os.geteuid() == 0:
            self.skipTest("root can write anything")
        FakeRfkill(self, bluetooth_soft="1", writable=False)
        with self.assertRaises(RuntimeError) as caught:
            self.service().set_powered(True)
        self.assertIn("rfkill unblock bluetooth", str(caught.exception))

    def test_hard_block_is_reported_as_such(self):
        fake = FakeRfkill(self, bluetooth_soft="0", bluetooth_hard="1")
        with self.assertRaises(RuntimeError) as caught:
            self.service().set_powered(True)
        self.assertIn("hardware switch", str(caught.exception))
        self.assertEqual(fake.events, [])


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
