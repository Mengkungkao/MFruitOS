"""SD3078 real-time clock of the PiSugar 2 boards (I2C 0x32).

Register use (from the chip's published interface):

  0x00..0x06 time: second, minute, hour (bit7 = 24 h mode), weekday, day,
             month, year (BCD)
  0x07..0x0D alarm, same layout; 0x0E alarm match enables (0x0F: weekday,
             hour, minute, second)
  0x0F CTR1: bits 4/5 alarm fired flags; bits 7 and 2 = write enable 2/3
  0x10 CTR2: bit7 write enable 1; interrupt source and enables
  0x11 CTR3: frequency output select
  0x18 backup cell charging (0x82 on, 0x02 off)
  0x1A flags: bit0 backup cell low, bit1 backup cell full

The 2 Hz "frequency alarm" keeps the power chip awake; PiSugar 2 uses it
for "power on when plugged in".
"""

from __future__ import annotations

import datetime as _dt

from mfruitos.hosts.pisugar.base import bcd_to_int, int_to_bcd
from mfruitos.hosts.pisugar.rtc import Alarm, Rtc, utc, validate_alarm, weekday_sunday0

ADDRESS = 0x32
CTR1 = 0x0F
CTR2 = 0x10
CTR3 = 0x11
ALARM_ENABLE = 0x0E
CHARGE = 0x18
FLAGS = 0x1A


class SD3078(Rtc):
    name = "SD3078 clock"

    def __init__(self, bus, addr: int = ADDRESS):
        self.bus = bus
        self.addr = addr

    def read(self, register: int) -> int:
        return self.bus.read_byte_data(self.addr, register)

    def write(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.addr, register, value & 0xFF)

    def _update(self, register: int, clear: int = 0, set_bits: int = 0) -> None:
        value = self.read(register)
        self.write(register, (value & ~clear & 0xFF) | set_bits)

    def _unlocked(self, work) -> None:
        """Run ``work`` with the three write-enable bits set, then clear them."""
        self._update(CTR2, set_bits=0b1000_0000)
        self._update(CTR1, set_bits=0b1000_0100)
        try:
            work()
        finally:
            self._update(CTR1, clear=0b1000_0100)
            self._update(CTR2, clear=0b1000_0000)

    # ------------------------------------------------------------ time
    def read_time(self) -> _dt.datetime:
        raw = self.bus.read_i2c_block_data(self.addr, 0x00, 7)
        second, minute = bcd_to_int(raw[0] & 0x7F), bcd_to_int(raw[1] & 0x7F)
        hour_byte = raw[2]
        if hour_byte & 0x80:                       # 24 h mode
            hour = bcd_to_int(hour_byte & 0x3F)
        else:                                      # 12 h mode: bit5 = PM
            hour = bcd_to_int(hour_byte & 0x1F) % 12 + (12 if hour_byte & 0x20 else 0)
        day, month, year = bcd_to_int(raw[4] & 0x3F), bcd_to_int(raw[5] & 0x1F), bcd_to_int(raw[6])
        return _dt.datetime(2000 + year, month, day, hour, minute, second,
                            tzinfo=_dt.timezone.utc)

    def write_time(self, when: _dt.datetime) -> None:
        when = utc(when)
        raw = [int_to_bcd(when.second), int_to_bcd(when.minute),
               int_to_bcd(when.hour) | 0x80, int_to_bcd(weekday_sunday0(when)),
               int_to_bcd(when.day), int_to_bcd(when.month), int_to_bcd(when.year - 2000)]
        self._unlocked(lambda: self.bus.write_i2c_block_data(self.addr, 0x00, raw))

    # ------------------------------------------------------------ alarm
    def read_alarm(self) -> Alarm:
        raw = self.bus.read_i2c_block_data(self.addr, 0x07, 7)
        enabled = bool(self.read(ALARM_ENABLE) & 0x07) and bool(self.read(CTR2) & 0b0000_0010)
        return Alarm(hour=bcd_to_int(raw[2] & 0x3F), minute=bcd_to_int(raw[1] & 0x7F),
                     second=bcd_to_int(raw[0] & 0x7F), weekdays=raw[3] & 0x7F, enabled=enabled)

    def set_alarm(self, hour: int, minute: int, second: int, weekdays: int) -> None:
        validate_alarm(hour, minute, second, weekdays)
        raw = [int_to_bcd(second), int_to_bcd(minute), int_to_bcd(hour), weekdays & 0x7F,
               0x01, 0x01, 0x00]

        def work():
            self.bus.write_i2c_block_data(self.addr, 0x07, raw)
            self._update(CTR2, clear=0b0010_0101, set_bits=0b0101_0010)  # alarm interrupt
            self.write(ALARM_ENABLE, 0b0000_1111)
        self._unlocked(work)

    def disable_alarm(self) -> None:
        def work():
            self._update(CTR2, clear=0b0010_0000, set_bits=0b0101_0010)
            self.write(ALARM_ENABLE, 0)
        self._unlocked(work)

    def clear_alarm_flag(self) -> None:
        if self.read(CTR1) & 0b0011_0000:
            self._unlocked(lambda: self._update(CTR1, clear=0b0011_0000))

    # ------------------------------------------------------------ 2 Hz alarm
    def frequency_alarm_enabled(self) -> bool:
        return (self.read(CTR2) & 0b0011_0001) == 0b0010_0001

    def enable_frequency_alarm(self) -> None:
        def work():
            self._update(CTR3, clear=0b0000_0100, set_bits=0b0000_1011)   # 1/2 Hz
            self._update(CTR2, clear=0b0001_0110, set_bits=0b0010_0001)
        self._unlocked(work)

    def disable_frequency_alarm(self) -> None:
        self._unlocked(lambda: self._update(CTR2, clear=0b0010_0001, set_bits=0b0001_0000))

    # ------------------------------------------------------------ backup cell
    def housekeeping(self) -> None:
        flags = self.read(FLAGS)
        if flags & 0b01:
            self._unlocked(lambda: self.write(CHARGE, 0x82))
        elif flags & 0b10:
            self._unlocked(lambda: self.write(CHARGE, 0x02))
