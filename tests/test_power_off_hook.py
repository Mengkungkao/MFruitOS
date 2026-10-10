"""The shutdown hook that switches the PiSugar off (scripts/mfruit-power-off)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest

from mfruitos.hosts.pisugar import pisugar3, sd3078
from mfruitos.hosts.pisugar.fake import FakeBus, FakeIP5209, FakeIP5312, FakePiSugar3, FakeSD3078

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "scripts", "mfruit-power-off")


def load_hook():
    loader = importlib.machinery.SourceFileLoader("mfruit_power_off", HOOK)
    spec = importlib.util.spec_from_loader("mfruit_power_off", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PowerOffHookTests(unittest.TestCase):
    def setUp(self):
        self.hook = load_hook()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.tmp.name, "power.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, bus, action="poweroff", **settings):
        if settings:
            with open(self.config, "w") as fp:
                json.dump(settings, fp)
        opened = []

        def opener(number):
            opened.append(number)
            return bus
        code = self.hook.main(["mfruit-power-off", action], opener=opener, config=self.config)
        self.assertEqual(code, 0)
        return opened

    def test_pisugar3_output_is_switched_off_on_poweroff_only(self):
        board = FakePiSugar3()
        self.run_hook(FakeBus({0x57: board}), "reboot")
        self.assertTrue(board.output_on)
        self.run_hook(FakeBus({0x57: board}), "halt")
        self.assertTrue(board.output_on)
        self.run_hook(FakeBus({0x57: board}))
        self.assertFalse(board.output_on)
        self.assertEqual(board.ignored_writes, 0)          # inside the write protection
        self.assertEqual(board.regs[pisugar3.REG_WRITE_PROTECT], pisugar3.WRITE_CLOSED)
        self.assertTrue(board.bit(pisugar3.REG_CTRL1, pisugar3.ALLOW_CHARGING))

    def test_settings_choose_bus_address_and_can_disable_it(self):
        board = FakePiSugar3()
        opened = self.run_hook(FakeBus({0x58: board}), i2c_bus=3, i2c_address=0x58)
        self.assertEqual(opened, [3])
        self.assertFalse(board.output_on)
        board = FakePiSugar3()
        self.assertEqual(self.run_hook(FakeBus({0x57: board}), power_off_at_shutdown=False), [])
        self.assertTrue(board.output_on)
        self.assertEqual(self.run_hook(FakeBus({0x57: board}), model="none"), [])
        self.assertTrue(board.output_on)

    def test_pisugar2_boards_are_switched_off_and_the_wakeup_stopped(self):
        for chip in (FakeIP5209(leds=4), FakeIP5312()):
            clock = FakeSD3078()
            clock.regs[sd3078.CTR2] = 0b0010_0001             # 2 Hz wake-up on
            self.run_hook(FakeBus({0x75: chip, 0x32: clock}))
            self.assertTrue(chip.powered_off, type(chip).__name__)
            self.assertFalse(sd3078.SD3078(FakeBus({0x32: clock})).frequency_alarm_enabled())
            self.assertFalse(clock.unlocked)

    def test_nothing_found_or_unreadable_settings_never_fail(self):
        with open(self.config, "w") as fp:
            fp.write("{broken")
        self.run_hook(FakeBus({}))

        def failing_opener(number):
            raise OSError(2, "No such file")
        self.assertEqual(self.hook.main(["x", "poweroff"], opener=failing_opener,
                                        config=self.config), 0)


if __name__ == "__main__":
    unittest.main()
