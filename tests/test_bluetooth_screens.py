import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from mfruitos.launcher.navigation.router import Router
from mfruitos.launcher.ui.screens.base import Screen
from mfruitos.launcher.ui.screens.bluetooth import BtDeviceScreen, PairingScreen
from mfruitos.system.bluetooth import BtDevice, Prompt


class BluetoothScreenLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.os = SimpleNamespace(bluetooth=Mock(), loop=Mock(), run_task=Mock(),
                                  request_render=Mock(), toast=Mock(), router=Router())
        self.os.router_top = lambda: self.os.router.top
        self.os.push, self.os.pop = self.os.router.push, self.os.router.pop
        self.os.router.set_root(Screen(self.os))
        self.device = BtDeviceScreen(self.os, BtDevice("AA", "Keys", paired=True))
        self.os.push(self.device)

    def complete_task(self):
        _, work, done, failed = self.os.run_task.call_args.args
        try:
            result = work()
        except Exception as exc:
            failed(exc)
        else:
            done(result)

    def test_forget_success_does_not_depend_on_status_lookup(self):
        self.os.bluetooth.forget.return_value = True, "Forgotten"
        self.os.bluetooth.devices.side_effect = RuntimeError("Controller removed")
        self.device.operate("forget")
        self.complete_task()
        self.assertEqual(self.os.router.depth, 1)
        self.os.bluetooth.devices.assert_not_called()
        self.assertFalse(self.device.busy)

    def test_successful_action_survives_failed_status_lookup(self):
        self.os.bluetooth.devices.side_effect = RuntimeError("Status unavailable")
        for action, connected in (("connect", True), ("disconnect", False)):
            with self.subTest(action=action):
                message = "Connected" if connected else "Disconnected"
                getattr(self.os.bluetooth, action).return_value = True, message
                self.device.operate(action)
                self.complete_task()
                self.assertEqual(self.device.device.connected, connected)
                self.assertFalse(self.device.busy)
                self.assertIn("status unavailable", self.device.status)
                self.os.toast.assert_called_with(message, "success")

    def test_pair_keeps_partial_success_when_status_is_unavailable(self):
        self.device.device.paired = False
        self.os.bluetooth.pair.return_value = True, "Paired; Could not connect"
        self.os.bluetooth.devices.side_effect = RuntimeError("Status unavailable")
        self.device.operate("pair")
        self.complete_task()
        self.assertTrue(self.device.device.paired)
        self.assertFalse(self.device.device.connected)

    def test_old_prompt_cannot_replace_or_close_new_operation_prompt(self):
        self.device.operate("pair")
        old_callback = self.os.bluetooth.on_prompt
        self.device.finish()
        self.device.operate("pair")
        self.device.on_prompt(Prompt("confirm", "123456", "AA"))
        current = self.os.router.top
        self.assertIsInstance(current, PairingScreen)
        for kind in ("passkey", "done"):
            old_callback(Prompt(kind, "654321", "AA"))
            callback, *args = self.os.loop.post.call_args.args
            callback(*args)
            self.assertIs(self.os.router.top, current)
        self.os.bluetooth.answer.assert_not_called()

    def test_late_forget_completion_does_not_pop_another_screen(self):
        self.os.bluetooth.forget.return_value = True, "Forgotten"
        self.device.operate("forget")
        self.os.router.home()
        replacement = Screen(self.os)
        self.os.push(replacement)
        self.complete_task()
        self.assertIs(self.os.router.top, replacement)
