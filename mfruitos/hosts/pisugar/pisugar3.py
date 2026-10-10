"""PiSugar 3: one microcontroller at I2C 0x57 for battery, button and clock.

Register map (from the board's published interface):

  0x00 version (3)          0x01 mode (0x0F application, 0xF0 bootloader)
  0x02 control 1: bit7 external power (read-only), bit6 allow charging,
       bit5 output on, bit4 power on when power returns, bit3 anti-mistouch,
       bit0 power button held (raw)
  0x03 control 2: bit4 soft shutdown enabled, bit3 soft shutdown requested
  0x04 temperature + 40 (°C)
  0x08 press latch, bits 0-1: 1 single, 2 double, 3 long
  0x0B write protection: 0x29 opens it, 0x00 closes it (firmware 1.24+)
  0x20 battery control: bit7 battery protection (charging limit)
  0x22/0x23 battery mV (high, low)   0x26/0x27 output mA (high, low)
  0x2A charge % (firmware estimate)
  0x31..0x37 clock: year, month, day, weekday, hour, minute, second (BCD)
  0x40 alarm control: bit7 enabled   0x44 alarm weekday mask
  0x45..0x47 alarm hour, minute, second (BCD)
  0xE2.. firmware version, NUL-terminated (up to 15 bytes)

Every write opens the write protection and closes it again afterwards.
"""

from __future__ import annotations

import datetime as _dt

from mfruitos.hosts.pisugar import base
from mfruitos.hosts.pisugar.base import Chip, Sample, bcd_to_int, int_to_bcd
from mfruitos.hosts.pisugar.rtc import Alarm, Rtc, utc, validate_alarm, weekday_sunday0

ADDRESS = 0x57
REG_VERSION = 0x00
REG_MODE = 0x01
REG_CTRL1 = 0x02
REG_CTRL2 = 0x03
REG_TEMPERATURE = 0x04
REG_TAP = 0x08
REG_WRITE_PROTECT = 0x0B
REG_BAT_CTRL = 0x20
REG_VOLT_H = 0x22
REG_VOLT_L = 0x23
REG_CURRENT_H = 0x26
REG_CURRENT_L = 0x27
REG_PERCENT = 0x2A
REG_RTC_YEAR = 0x31          # then month, day, weekday, hour, minute, second
REG_ALARM_CTRL = 0x40
REG_ALARM_WEEKDAYS = 0x44
REG_ALARM_HOUR = 0x45
REG_ALARM_MINUTE = 0x46
REG_ALARM_SECOND = 0x47
REG_FIRMWARE = 0xE2
FIRMWARE_MAX = 15

VERSION = 3
MODE_APPLICATION = 0x0F
MODE_BOOTLOADER = 0xF0
WRITE_OPEN = 0x29
WRITE_CLOSED = 0x00

PLUGGED = 1 << 7
ALLOW_CHARGING = 1 << 6
OUTPUT_ON = 1 << 5
POWER_RESTORE = 1 << 4
ANTI_MISTOUCH = 1 << 3
SOFT_POWEROFF_ENABLED = 1 << 4
SOFT_POWEROFF_REQUESTED = 1 << 3
BATTERY_PROTECT = 1 << 7
ALARM_ENABLED = 1 << 7

TAPS = {1: "single", 2: "double", 3: "long"}


def identify(bus, addr: int = ADDRESS) -> str | None:
    """"ok" for a PiSugar 3 in application mode, "bootloader" while it is being
    updated, None when the address does not answer like a PiSugar 3."""
    version = bus.read_byte_data(addr, REG_VERSION)
    mode = bus.read_byte_data(addr, REG_MODE)
    if version != VERSION:
        return None
    if mode == MODE_APPLICATION:
        return "ok"
    if mode == MODE_BOOTLOADER:
        return "bootloader"
    return None


class PiSugar3(Chip):
    key = "pisugar3"
    model = "PiSugar 3"
    features = frozenset({base.CHARGING_CONTROL, base.POWER_RESTORE, base.SOFT_POWEROFF,
                          base.ANTI_MISTOUCH, base.BATTERY_PROTECT, base.TEMPERATURE,
                          base.TAPS, base.RTC, base.CURRENT})
    curve = base.CURVE_IP5312
    poll_interval = 1.0
    tap_interval = None      # the board latches presses; the normal poll is enough

    def __init__(self, bus, bus_number: int, addr: int = ADDRESS):
        super().__init__(bus, bus_number, addr)
        self._firmware = ""
        self.rtc = PiSugar3Clock(self)

    # ------------------------------------------------------------ registers
    def read(self, register: int) -> int:
        return self.bus.read_byte_data(self.addr, register)

    def write(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.addr, REG_WRITE_PROTECT, WRITE_OPEN)
        try:
            self.bus.write_byte_data(self.addr, register, value & 0xFF)
        finally:
            self.bus.write_byte_data(self.addr, REG_WRITE_PROTECT, WRITE_CLOSED)

    def _set_bit(self, register: int, mask: int, on: bool) -> None:
        value = self.read(register)
        new = (value | mask) if on else (value & ~mask & 0xFF)
        if new != value:
            self.write(register, new)

    # ------------------------------------------------------------ lifecycle
    def init(self, settings: dict) -> None:
        for key, setter in (("power_restore", self.set_power_restore),
                            ("soft_poweroff", self.set_soft_poweroff),
                            ("anti_mistouch", self.set_anti_mistouch),
                            ("battery_protect", self.set_battery_protect)):
            value = settings.get(key)
            if value is not None:
                setter(bool(value))
        self._firmware = self._read_firmware()

    def _read_firmware(self) -> str:
        raw = bytearray()
        for offset in range(FIRMWARE_MAX):
            byte = self.read(REG_FIRMWARE + offset)
            if byte == 0:
                break
            raw.append(byte)
        return raw.decode("ascii", "replace").strip()

    def firmware(self) -> str:
        return self._firmware

    # ------------------------------------------------------------ readings
    def sample(self) -> Sample:
        ctrl1 = self.read(REG_CTRL1)
        millivolts = (self.read(REG_VOLT_H) << 8) | self.read(REG_VOLT_L)
        milliamps = (self.read(REG_CURRENT_H) << 8) | self.read(REG_CURRENT_L)
        temperature = self.read(REG_TEMPERATURE) - 40
        return Sample(voltage=millivolts / 1000.0, current=milliamps / 1000.0,
                      plugged=bool(ctrl1 & PLUGGED), allow_charging=bool(ctrl1 & ALLOW_CHARGING),
                      temperature=temperature,
                      extra={"firmware_percent": self.read(REG_PERCENT)})

    def poll_taps(self) -> list:
        value = self.read(REG_TAP)
        tap = TAPS.get(value & 0x03)
        if tap is None:
            return []
        self.write(REG_TAP, value & 0xFC)
        return [tap]

    def poll_soft_poweroff(self) -> bool:
        ctrl2 = self.read(REG_CTRL2)
        requested = ctrl2 & (SOFT_POWEROFF_ENABLED | SOFT_POWEROFF_REQUESTED)
        if requested != (SOFT_POWEROFF_ENABLED | SOFT_POWEROFF_REQUESTED):
            return False
        self.write(REG_CTRL2, ctrl2 & ~SOFT_POWEROFF_REQUESTED & 0xFF)
        return True

    # ------------------------------------------------------------ settings
    def get_allow_charging(self) -> bool:
        return bool(self.read(REG_CTRL1) & ALLOW_CHARGING)

    def set_allow_charging(self, on: bool) -> None:
        self._set_bit(REG_CTRL1, ALLOW_CHARGING, on)

    def get_power_restore(self) -> bool:
        return bool(self.read(REG_CTRL1) & POWER_RESTORE)

    def set_power_restore(self, on: bool) -> None:
        self._set_bit(REG_CTRL1, POWER_RESTORE, on)

    def get_soft_poweroff(self) -> bool:
        return bool(self.read(REG_CTRL2) & SOFT_POWEROFF_ENABLED)

    def set_soft_poweroff(self, on: bool) -> None:
        # Bits 5-7 are kept; the request flag and the low bits are cleared,
        # as the board's own software does.
        ctrl2 = self.read(REG_CTRL2)
        new = (ctrl2 & 0b1110_0000) | (SOFT_POWEROFF_ENABLED if on else 0)
        if new != ctrl2:
            self.write(REG_CTRL2, new)

    def get_anti_mistouch(self) -> bool:
        return bool(self.read(REG_CTRL1) & ANTI_MISTOUCH)

    def set_anti_mistouch(self, on: bool) -> None:
        self._set_bit(REG_CTRL1, ANTI_MISTOUCH, on)

    def get_battery_protect(self) -> bool:
        return bool(self.read(REG_BAT_CTRL) & BATTERY_PROTECT)

    def set_battery_protect(self, on: bool) -> None:
        self._set_bit(REG_BAT_CTRL, BATTERY_PROTECT, on)


class PiSugar3Clock(Rtc):
    name = "PiSugar 3 clock"

    def __init__(self, chip: PiSugar3):
        self.chip = chip

    def _fields(self) -> list:
        return [bcd_to_int(self.chip.read(REG_RTC_YEAR + i)) for i in range(7)]

    def read_time(self) -> _dt.datetime:
        fields = self._fields()
        if bcd_to_int(self.chip.read(REG_RTC_YEAR + 6)) < fields[6]:
            fields = self._fields()   # the minute rolled over while reading
        year, month, day, _weekday, hour, minute, second = fields
        return _dt.datetime(2000 + year, month, day, hour, minute, second,
                            tzinfo=_dt.timezone.utc)

    def write_time(self, when: _dt.datetime) -> None:
        when = utc(when)
        values = [when.second, when.minute, when.hour, weekday_sunday0(when), when.day,
                  when.month, when.year - 2000]
        # Seconds first, year last, as the board's own software writes them.
        for offset, value in zip((6, 5, 4, 3, 2, 1, 0), values):
            self.chip.write(REG_RTC_YEAR + offset, int_to_bcd(value))

    def read_alarm(self) -> Alarm:
        return Alarm(hour=bcd_to_int(self.chip.read(REG_ALARM_HOUR)),
                     minute=bcd_to_int(self.chip.read(REG_ALARM_MINUTE)),
                     second=bcd_to_int(self.chip.read(REG_ALARM_SECOND)),
                     weekdays=self.chip.read(REG_ALARM_WEEKDAYS) & 0x7F,
                     enabled=bool(self.chip.read(REG_ALARM_CTRL) & ALARM_ENABLED))

    def set_alarm(self, hour: int, minute: int, second: int, weekdays: int) -> None:
        validate_alarm(hour, minute, second, weekdays)
        self.chip.write(REG_ALARM_HOUR, int_to_bcd(hour))
        self.chip.write(REG_ALARM_MINUTE, int_to_bcd(minute))
        self.chip.write(REG_ALARM_SECOND, int_to_bcd(second))
        self.chip.write(REG_ALARM_WEEKDAYS, weekdays & 0x7F)
        self.chip._set_bit(REG_ALARM_CTRL, ALARM_ENABLED, True)

    def disable_alarm(self) -> None:
        self.chip._set_bit(REG_ALARM_CTRL, ALARM_ENABLED, False)
