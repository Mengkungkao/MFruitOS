"""PiSugar board drivers against register-level fakes (no hardware)."""

from __future__ import annotations

import ctypes
import datetime as dt
import errno
import os
import tempfile
import unittest
from unittest import mock

from mfruitos.hosts.pisugar import base, detect, i2c, pisugar2, pisugar3, sd3078
from mfruitos.hosts.pisugar.fake import (FakeBus, FakeIP5209, FakeIP5312, FakePiSugar3,
                                         FakeSD3078)
from mfruitos.hosts.pisugar.rtc import local_to_utc_alarm, shift_weekdays

UTC = dt.timezone.utc


class SMBusTests(unittest.TestCase):
    def test_missing_bus_is_an_oserror_with_a_clear_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError) as ctx:
                i2c.SMBus(7, dev_dir=tmp)
        self.assertEqual(ctx.exception.errno, errno.ENOENT)
        self.assertIn("not enabled", i2c.explain(ctx.exception, 7))

    def test_explain_names_the_i2c_group_and_kernel_driver_conflicts(self):
        self.assertIn("i2c group", i2c.explain(OSError(errno.EACCES, "denied"), 1))
        self.assertIn("kernel driver", i2c.explain(OSError(errno.EBUSY, "busy"), 1, 0x57))
        self.assertIn("no answer", i2c.explain(OSError(errno.EREMOTEIO, "x"), 1, 0x57))

    def test_transfers_build_the_kernel_structures(self):
        """read/write go through I2C_SLAVE once per address, then I2C_SMBUS."""
        calls = []

        def fake_ioctl(fd, request, arg):
            if request == i2c.I2C_SLAVE:
                calls.append(("slave", arg))
                return 0
            self.assertEqual(request, i2c.I2C_SMBUS)
            data = arg.data.contents
            calls.append(("smbus", arg.read_write, arg.command, arg.size))
            if arg.read_write == i2c.I2C_SMBUS_READ and arg.size == i2c.I2C_SMBUS_BYTE_DATA:
                data.byte = 0xA5
            elif arg.read_write == i2c.I2C_SMBUS_READ:
                for k in range(data.block[0]):
                    data.block[k + 1] = k + 1
            elif arg.size == i2c.I2C_SMBUS_BYTE_DATA:
                calls.append(("value", data.byte))
            else:
                calls.append(("block", [data.block[k + 1] for k in range(data.block[0])]))
            return 0

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "i2c-1"), "wb").close()
            with mock.patch.object(i2c.fcntl, "ioctl", fake_ioctl):
                bus = i2c.SMBus(1, dev_dir=tmp)
                self.assertEqual(bus.read_byte_data(0x57, 0x22), 0xA5)
                bus.write_byte_data(0x57, 0x0B, 0x29)
                self.assertEqual(bus.read_i2c_block_data(0x32, 0x00, 3), [1, 2, 3])
                bus.write_i2c_block_data(0x32, 0x07, [9, 8])
                bus.close()
        self.assertEqual(calls[0], ("slave", 0x57))
        self.assertEqual([c for c in calls if c[0] == "slave"], [("slave", 0x57), ("slave", 0x32)])
        self.assertIn(("smbus", i2c.I2C_SMBUS_READ, 0x22, i2c.I2C_SMBUS_BYTE_DATA), calls)
        self.assertIn(("value", 0x29), calls)
        self.assertIn(("block", [9, 8]), calls)
        self.assertIsInstance(ctypes.sizeof(i2c._Args), int)

    def test_invalid_addresses_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "i2c-1"), "wb").close()
            bus = i2c.SMBus(1, dev_dir=tmp)
            with self.assertRaises(ValueError):
                bus.read_byte_data(0x80, 0)
            bus.close()


class CurveTests(unittest.TestCase):
    def test_interpolation_and_clamping(self):
        curve = base.CURVE_IP5312
        self.assertEqual(base.level_from_voltage(4.2, curve), 100.0)
        self.assertEqual(base.level_from_voltage(3.0, curve), 0.0)
        self.assertAlmostEqual(base.level_from_voltage(3.75, curve), 71.0, places=3)
        self.assertAlmostEqual(base.level_from_voltage(3.90, curve), 88.0)

    def test_user_curves_must_rise_with_voltage(self):
        good = base.validate_curve([[3.2, 5], [3.3, 20], [3.5, 60], [4.0, 100]])
        self.assertEqual(good[0], (3.2, 5.0))
        for bad in ([[3.2, 50], [3.3, 20]], [[3.2, 5], [3.2, 10]], [[3.2, 5]], [[9, 5], [3.3, 9]],
                    [[3.2, True], [3.3, 20]], "x"):
            with self.assertRaises(ValueError):
                base.validate_curve(bad)


class PiSugar3Tests(unittest.TestCase):
    def setUp(self):
        self.board = FakePiSugar3(volts=3.912, plugged=True, temperature=33)
        self.bus = FakeBus({0x57: self.board})
        self.chip = pisugar3.PiSugar3(self.bus, 1)

    def test_identify(self):
        self.assertEqual(pisugar3.identify(self.bus), "ok")
        self.board.regs[pisugar3.REG_MODE] = pisugar3.MODE_BOOTLOADER
        self.assertEqual(pisugar3.identify(self.bus), "bootloader")
        self.board.regs[pisugar3.REG_VERSION] = 2
        self.assertIsNone(pisugar3.identify(self.bus))

    def test_sample(self):
        self.board.set_battery(3.912, current=0.31, percent=72)
        sample = self.chip.sample()
        self.assertAlmostEqual(sample.voltage, 3.912)
        self.assertAlmostEqual(sample.current, 0.31)
        self.assertTrue(sample.plugged)
        self.assertTrue(sample.allow_charging)
        self.assertEqual(sample.temperature, 33)
        self.assertEqual(sample.extra["firmware_percent"], 72)

    def test_settings_open_the_write_protection(self):
        for setter, getter, register, mask in (
                (self.chip.set_power_restore, self.chip.get_power_restore,
                 pisugar3.REG_CTRL1, pisugar3.POWER_RESTORE),
                (self.chip.set_anti_mistouch, self.chip.get_anti_mistouch,
                 pisugar3.REG_CTRL1, pisugar3.ANTI_MISTOUCH),
                (self.chip.set_battery_protect, self.chip.get_battery_protect,
                 pisugar3.REG_BAT_CTRL, pisugar3.BATTERY_PROTECT),
                (self.chip.set_soft_poweroff, self.chip.get_soft_poweroff,
                 pisugar3.REG_CTRL2, pisugar3.SOFT_POWEROFF_ENABLED)):
            setter(True)
            self.assertTrue(getter())
            self.assertTrue(self.board.bit(register, mask))
            setter(False)
            self.assertFalse(getter())
        self.assertEqual(self.board.ignored_writes, 0)
        # Protection is closed again after every write.
        self.assertEqual(self.board.regs[pisugar3.REG_WRITE_PROTECT], pisugar3.WRITE_CLOSED)

    def test_negative_control_writes_without_opening_protection_are_lost(self):
        """Proves the fake models firmware 1.24+: a plain write changes nothing."""
        self.bus.write_byte_data(0x57, pisugar3.REG_CTRL1,
                                 self.board.regs[pisugar3.REG_CTRL1] | pisugar3.POWER_RESTORE)
        self.assertFalse(self.board.bit(pisugar3.REG_CTRL1, pisugar3.POWER_RESTORE))
        self.assertEqual(self.board.ignored_writes, 1)

    def test_external_power_bit_survives_writes(self):
        self.chip.set_allow_charging(False)
        self.assertTrue(self.board.bit(pisugar3.REG_CTRL1, pisugar3.PLUGGED))
        self.assertFalse(self.chip.get_allow_charging())
        self.assertTrue(self.board.output_on)

    def test_presses_are_read_once_and_cleared(self):
        self.assertEqual(self.chip.poll_taps(), [])
        self.board.press("double")
        self.assertEqual(self.chip.poll_taps(), ["double"])
        self.assertEqual(self.chip.poll_taps(), [])
        self.board.press("long")
        self.assertEqual(self.chip.poll_taps(), ["long"])

    def test_soft_shutdown_handshake(self):
        self.board.hold_power_button()
        self.assertFalse(self.chip.poll_soft_poweroff())   # not enabled: no request
        self.chip.set_soft_poweroff(True)
        self.board.hold_power_button()
        self.assertTrue(self.chip.poll_soft_poweroff())
        self.assertFalse(self.chip.poll_soft_poweroff())   # cleared after reading
        self.assertTrue(self.chip.get_soft_poweroff())

    def test_init_applies_only_explicit_settings_and_reads_firmware(self):
        self.chip.init({"power_restore": None, "anti_mistouch": True, "soft_poweroff": None,
                        "battery_protect": False})
        self.assertTrue(self.chip.get_anti_mistouch())
        self.assertFalse(self.chip.get_power_restore())
        self.assertEqual(self.chip.firmware(), "1.2.4")
        writes = {reg for reg, _ in self.bus.writes(0x57)} - {pisugar3.REG_WRITE_PROTECT}
        self.assertEqual(writes, {pisugar3.REG_CTRL1})   # battery_protect already off: no write

    def test_clock_round_trip_and_alarm(self):
        rtc = self.chip.rtc
        when = dt.datetime(2027, 1, 31, 23, 59, 58, tzinfo=UTC)
        rtc.write_time(when)
        self.assertEqual(rtc.read_time(), when)
        self.assertEqual(self.board.ignored_writes, 0)
        rtc.set_alarm(6, 45, 0, 0b0111110)
        alarm = rtc.read_alarm()
        self.assertEqual((alarm.hour, alarm.minute, alarm.second, alarm.weekdays, alarm.enabled),
                         (6, 45, 0, 0b0111110, True))
        rtc.disable_alarm()
        self.assertFalse(rtc.read_alarm().enabled)
        with self.assertRaises(ValueError):
            rtc.set_alarm(24, 0, 0, 1)
        with self.assertRaises(ValueError):
            rtc.set_alarm(6, 0, 0, 0)

    def test_clock_rollover_while_reading_is_read_again(self):
        rtc = self.chip.rtc
        self.board.set_clock(dt.datetime(2026, 10, 10, 8, 30, 59, tzinfo=UTC))
        reads = {"n": 0}
        original = self.board.read

        def read(register):
            if register == pisugar3.REG_RTC_YEAR + 6:
                reads["n"] += 1
                if reads["n"] == 2:   # the second rolls over between the two reads
                    self.board.set_clock(dt.datetime(2026, 10, 10, 8, 31, 0, tzinfo=UTC))
            return original(register)
        self.board.read = read
        self.assertEqual(rtc.read_time(), dt.datetime(2026, 10, 10, 8, 31, 0, tzinfo=UTC))


class PiSugar2Tests(unittest.TestCase):
    def test_ip5209_four_leds(self):
        board = FakeIP5209(leds=4, volts=3.86)
        bus = FakeBus({0x75: board})
        chip = pisugar2.IP5209Board(bus, 1, leds=4)
        chip.init({})
        self.assertEqual(chip.model, "PiSugar 2 (4-LEDs)")
        sample = chip.sample()
        self.assertAlmostEqual(sample.voltage, 3.86, places=2)
        self.assertIsNone(sample.plugged)          # 4-LED boards cannot tell
        self.assertNotIn(base.CHARGING_CONTROL, chip.features)
        with self.assertRaises(base.Unsupported):
            chip.set_allow_charging(False)
        # light-load shutdown enabled (no power restore)
        self.assertTrue(board.regs[0x02] & 0b10)
        self.assertEqual(board.regs[0x0C] >> 3, 9)

    def test_ip5209_two_leds_charging_control_and_power_sense(self):
        board = FakeIP5209(leds=2, volts=4.0, plugged=True)
        chip = pisugar2.IP5209Board(FakeBus({0x75: board}), 1, leds=2)
        chip.init({})
        self.assertTrue(chip.sample().plugged)
        chip.set_allow_charging(False)
        self.assertFalse(chip.get_allow_charging())
        self.assertFalse(chip.sample().allow_charging)
        chip.set_allow_charging(True)
        self.assertTrue(chip.get_allow_charging())

    def test_ip5312_pro(self):
        board = FakeIP5312(volts=3.7, plugged=False)
        chip = pisugar2.IP5312Board(FakeBus({0x75: board}), 1)
        chip.init({})
        sample = chip.sample()
        self.assertAlmostEqual(sample.voltage, 3.7, places=2)
        self.assertFalse(sample.plugged)
        board.set_battery(3.7, plugged=True)
        self.assertTrue(chip.sample().plugged)
        self.assertEqual(board.regs[0x30] & 0x3F, 0x3F)   # boost current set
        self.assertTrue(board.regs[0x03] & 0b0010_0000)   # light-load shutdown on

    def test_taps_from_sampled_button_levels(self):
        board = FakeIP5312()
        chip = pisugar2.IP5312Board(FakeBus({0x75: board}), 1)

        def play(levels):
            seen = []
            for level in levels:
                board.button(level == "1")
                seen += chip.poll_taps()
            return seen
        self.assertEqual(play("0110000"), ["single"])
        self.assertEqual(play("0101000"), ["double"])
        self.assertEqual(play("01111111110"), ["long"])
        self.assertEqual(play("00000"), [])

    def test_power_restore_uses_the_clock_frequency_alarm(self):
        board, clock = FakeIP5209(leds=2), FakeSD3078()
        bus = FakeBus({0x75: board, 0x32: clock})
        chip = pisugar2.IP5209Board(bus, 1, rtc=sd3078.SD3078(bus), leds=2)
        self.assertIn(base.POWER_RESTORE, chip.features)
        chip.set_power_restore(True)
        self.assertTrue(chip.get_power_restore())
        self.assertFalse(board.regs[0x02] & 0b10)          # light-load shutdown off
        chip.set_power_restore(False)
        self.assertFalse(chip.get_power_restore())
        self.assertTrue(board.regs[0x02] & 0b10)
        self.assertFalse(clock.unlocked)                  # write enable closed again

    def test_unknown_pisugar2_only_reads(self):
        board = FakeIP5209(leds=4, volts=3.9)
        bus = FakeBus({0x75: board})
        chip = pisugar2.UnknownPiSugar2(bus, 1)
        chip.init({"power_restore": True})
        self.assertAlmostEqual(chip.sample().voltage, 3.9, places=2)
        self.assertEqual(chip.poll_taps(), [])
        self.assertEqual(bus.writes(0x75), [])


class SD3078Tests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeSD3078()
        self.bus = FakeBus({0x32: self.clock})
        self.rtc = sd3078.SD3078(self.bus)

    def test_time_needs_the_write_enables(self):
        when = dt.datetime(2026, 12, 24, 18, 5, 9, tzinfo=UTC)
        self.rtc.write_time(when)
        self.assertEqual(self.rtc.read_time(), when)
        self.assertEqual(self.clock.ignored_writes, 0)
        self.assertFalse(self.clock.unlocked)
        # negative control: a locked chip ignores time writes
        self.bus.write_byte_data(0x32, 0x00, 0x11)
        self.assertEqual(self.clock.ignored_writes, 1)

    def test_twelve_hour_mode_is_converted(self):
        self.clock.regs[0x02] = 0x20 | 0x12       # 12 PM in 12 h mode = noon
        self.assertEqual(self.rtc.read_time().hour, 12)
        self.clock.regs[0x02] = 0x12              # 12 AM = midnight
        self.assertEqual(self.rtc.read_time().hour, 0)

    def test_alarm_and_backup_cell(self):
        self.rtc.set_alarm(7, 30, 0, 0b0011111)
        alarm = self.rtc.read_alarm()
        self.assertEqual((alarm.hour, alarm.minute, alarm.weekdays, alarm.enabled),
                         (7, 30, 0b0011111, True))
        self.rtc.disable_alarm()
        self.assertFalse(self.rtc.read_alarm().enabled)
        self.clock.regs[sd3078.FLAGS] = 0b01
        self.rtc.housekeeping()
        self.assertEqual(self.clock.regs[sd3078.CHARGE], 0x82)
        self.clock.regs[sd3078.FLAGS] = 0b10
        self.rtc.housekeeping()
        self.assertEqual(self.clock.regs[sd3078.CHARGE], 0x02)


class DetectTests(unittest.TestCase):
    def test_auto_finds_each_board(self):
        self.assertIsInstance(detect.build(FakeBus({0x57: FakePiSugar3()}), 1), pisugar3.PiSugar3)
        chip = detect.build(FakeBus({0x75: FakeIP5312(), 0x32: FakeSD3078()}), 1)
        self.assertIsInstance(chip, pisugar2.IP5312Board)
        self.assertIsNotNone(chip.rtc)
        bus = FakeBus({0x75: FakeIP5209()})
        self.assertIsInstance(detect.build(bus, 1), pisugar2.UnknownPiSugar2)
        self.assertEqual([op for op in bus.log if op[0] != "r"], [])   # detection only reads

    def test_configured_model_skips_detection(self):
        chip = detect.build(FakeBus({0x75: FakeIP5209(leds=2)}), 1, "pisugar2-2led")
        self.assertEqual(chip.model, "PiSugar 2 (2-LEDs)")

    def test_reasons_when_nothing_is_usable(self):
        with self.assertRaisesRegex(detect.NotFound, "no PiSugar battery board found on I2C bus 1"):
            detect.build(FakeBus({}), 1)
        board = FakePiSugar3()
        board.regs[pisugar3.REG_MODE] = pisugar3.MODE_BOOTLOADER
        with self.assertRaisesRegex(detect.NotFound, "bootloader"):
            detect.build(FakeBus({0x57: board}), 1)
        with self.assertRaisesRegex(detect.NotFound, "turned off"):
            detect.build(FakeBus({}), 1, "none")

    def test_permission_problem_is_reported_not_hidden(self):
        def opener(bus):
            raise OSError(errno.EACCES, "Permission denied")
        with self.assertRaisesRegex(detect.NotFound, "i2c group"):
            detect.open_board(1, opener=opener)

        class DeniedBus(FakeBus):
            def read_byte_data(self, addr, register):
                raise OSError(errno.EBUSY, "busy")
        with self.assertRaisesRegex(detect.NotFound, "kernel driver"):
            detect.build(DeniedBus({}), 1)


class AlarmTimeTests(unittest.TestCase):
    def test_weekday_masks_rotate(self):
        self.assertEqual(shift_weekdays(0b1000000, 1), 0b0000001)   # Saturday -> Sunday
        self.assertEqual(shift_weekdays(0b0000001, -1), 0b1000000)
        self.assertEqual(shift_weekdays(0x7F, 3), 0x7F)

    def test_local_alarm_crossing_midnight_moves_the_days(self):
        tz = dt.timezone(dt.timedelta(hours=10))
        now = dt.datetime(2026, 10, 10, 12, 0, tzinfo=tz)
        # 06:30 local on Mondays in UTC+10 is 20:30 UTC on Sundays.
        self.assertEqual(local_to_utc_alarm(6, 30, 0b0000010, now), (20, 30, 0b0000001))
        tz = dt.timezone(dt.timedelta(hours=-5))
        now = dt.datetime(2026, 10, 10, 12, 0, tzinfo=tz)
        self.assertEqual(local_to_utc_alarm(22, 0, 0b0000010, now), (3, 0, 0b0000100))


if __name__ == "__main__":
    unittest.main()
