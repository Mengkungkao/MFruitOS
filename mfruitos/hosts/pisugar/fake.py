"""Register-level stand-ins for the PiSugar boards (tests and development).

``FakeBus`` answers I2C transfers like ``i2c.SMBus``; each fake chip keeps
256 registers and models the behaviour the drivers depend on: the PiSugar 3
write protection and read-only bits, the press latch, the soft-shutdown
handshake, the PiSugar 2 GPIO levels and the SD3078 write-enable bits.

    python3 -m mfruitos.power serve --fake pisugar3

runs the power service against a simulated board, without hardware.
"""

from __future__ import annotations

import datetime as _dt
import errno

from mfruitos.hosts.pisugar import pisugar3 as p3
from mfruitos.hosts.pisugar.base import int_to_bcd


class FakeBus:
    def __init__(self, devices: dict | None = None, bus: int = 1):
        self.bus = bus
        self.devices = dict(devices or {})
        self.closed = False
        self.fail = 0              # fail the next N transfers with EIO
        self.log: list = []        # (op, addr, register, value)

    def _device(self, addr: int):
        if self.closed:
            raise OSError(errno.EBADF, "bus closed")
        if self.fail:
            self.fail -= 1
            raise OSError(errno.EIO, "Input/output error")
        device = self.devices.get(addr)
        if device is None:
            raise OSError(errno.EREMOTEIO, "Remote I/O error")
        return device

    def read_byte_data(self, addr: int, register: int) -> int:
        value = self._device(addr).read(register & 0xFF)
        self.log.append(("r", addr, register, value))
        return value

    def write_byte_data(self, addr: int, register: int, value: int) -> None:
        self._device(addr).write(register & 0xFF, value & 0xFF)
        self.log.append(("w", addr, register, value & 0xFF))

    def read_i2c_block_data(self, addr: int, register: int, length: int) -> list:
        device = self._device(addr)
        return [device.read((register + i) & 0xFF) for i in range(length)]

    def write_i2c_block_data(self, addr: int, register: int, values) -> None:
        device = self._device(addr)
        for i, value in enumerate(values):
            device.write((register + i) & 0xFF, value & 0xFF)
        self.log.append(("wb", addr, register, list(values)))

    def close(self) -> None:
        self.closed = True

    def writes(self, addr: int) -> list:
        return [(reg, val) for op, a, reg, val in self.log if op == "w" and a == addr]


class Registers:
    def __init__(self):
        self.regs = bytearray(256)

    def read(self, register: int) -> int:
        return self.regs[register]

    def write(self, register: int, value: int) -> None:
        self.regs[register] = value


def _bcd_clock(when: _dt.datetime) -> list:
    """year, month, day, weekday (0 = Sunday), hour, minute, second as BCD."""
    return [int_to_bcd(when.year - 2000), int_to_bcd(when.month), int_to_bcd(when.day),
            int_to_bcd((when.weekday() + 1) % 7), int_to_bcd(when.hour),
            int_to_bcd(when.minute), int_to_bcd(when.second)]


class FakePiSugar3(Registers):
    """Firmware 1.24+ behaviour: writes need the write protection opened."""

    def __init__(self, volts: float = 3.95, plugged: bool = False, firmware: str = "1.2.4",
                 temperature: int = 31, write_protect: bool = True):
        super().__init__()
        self.write_protect = write_protect
        self.ignored_writes = 0
        self.regs[p3.REG_VERSION] = p3.VERSION
        self.regs[p3.REG_MODE] = p3.MODE_APPLICATION
        self.regs[p3.REG_CTRL1] = p3.ALLOW_CHARGING | p3.OUTPUT_ON
        for i, byte in enumerate(firmware.encode("ascii")[:p3.FIRMWARE_MAX]):
            self.regs[p3.REG_FIRMWARE + i] = byte
        self.set_battery(volts, plugged=plugged, current=0.25)
        self.set_temperature(temperature)
        self.set_clock(_dt.datetime(2026, 10, 10, 8, 30, 0, tzinfo=_dt.timezone.utc))

    # -- test controls
    def set_battery(self, volts: float, plugged: bool | None = None,
                    current: float | None = None, percent: int | None = None) -> None:
        millivolts = int(round(volts * 1000))
        self.regs[p3.REG_VOLT_H], self.regs[p3.REG_VOLT_L] = millivolts >> 8, millivolts & 0xFF
        if current is not None:
            milliamps = int(round(current * 1000))
            self.regs[p3.REG_CURRENT_H], self.regs[p3.REG_CURRENT_L] = milliamps >> 8, milliamps & 0xFF
        if plugged is not None:
            if plugged:
                self.regs[p3.REG_CTRL1] |= p3.PLUGGED
            else:
                self.regs[p3.REG_CTRL1] &= ~p3.PLUGGED & 0xFF
        if percent is not None:
            self.regs[p3.REG_PERCENT] = percent

    def set_temperature(self, celsius: int) -> None:
        self.regs[p3.REG_TEMPERATURE] = celsius + 40

    def press(self, tap: str) -> None:
        code = {"single": 1, "double": 2, "long": 3}[tap]
        self.regs[p3.REG_TAP] = (self.regs[p3.REG_TAP] & 0xFC) | code

    def hold_power_button(self) -> None:
        """A long hold with soft shutdown enabled raises the request flag."""
        if self.regs[p3.REG_CTRL2] & p3.SOFT_POWEROFF_ENABLED:
            self.regs[p3.REG_CTRL2] |= p3.SOFT_POWEROFF_REQUESTED

    def set_clock(self, when: _dt.datetime) -> None:
        for i, value in enumerate(_bcd_clock(when.astimezone(_dt.timezone.utc))):
            self.regs[p3.REG_RTC_YEAR + i] = value

    @property
    def output_on(self) -> bool:
        return bool(self.regs[p3.REG_CTRL1] & p3.OUTPUT_ON)

    def bit(self, register: int, mask: int) -> bool:
        return bool(self.regs[register] & mask)

    # -- bus side
    def write(self, register: int, value: int) -> None:
        if register == p3.REG_WRITE_PROTECT:
            self.regs[register] = value
            return
        if self.write_protect and self.regs[p3.REG_WRITE_PROTECT] != p3.WRITE_OPEN:
            self.ignored_writes += 1
            return
        if register == p3.REG_CTRL1:      # bit 7 (external power) is read-only
            value = (value & ~p3.PLUGGED & 0xFF) | (self.regs[register] & p3.PLUGGED)
        self.regs[register] = value


class FakeIP5209(Registers):
    def __init__(self, leds: int = 4, volts: float = 3.95, plugged: bool = False):
        super().__init__()
        self.leds = leds
        self.set_battery(volts, plugged=plugged)
        self.regs[0x01] = 0b0000_0100          # boost on
        self.regs[0x0C] = 0b0000_0011

    def set_battery(self, volts: float, plugged: bool | None = None, current: float = 0.3) -> None:
        raw = int(round((volts * 1000 - 2600) / 0.26855))
        self.regs[0xA2], self.regs[0xA3] = raw & 0xFF, (raw >> 8) & 0x1F
        craw = int(round(current * 1000 / 0.745985))
        self.regs[0xA4], self.regs[0xA5] = craw & 0xFF, (craw >> 8) & 0x1F
        if plugged is not None and self.leds == 2:
            if plugged:
                self.regs[0x55] |= 0b0001_0000
            else:
                self.regs[0x55] &= ~0b0001_0000 & 0xFF

    def button(self, pressed: bool) -> None:
        mask = 0b0000_0010 if self.leds == 2 else 0b0001_0000
        if pressed:
            self.regs[0x55] |= mask
        else:
            self.regs[0x55] &= ~mask & 0xFF

    @property
    def powered_off(self) -> bool:
        return not self.regs[0x01] & 0b0000_0100


class FakeIP5312(Registers):
    def __init__(self, volts: float = 3.95, plugged: bool = False):
        super().__init__()
        self.set_battery(volts, plugged=plugged)
        self.regs[0x01] = 0b0000_0100

    def set_battery(self, volts: float, plugged: bool | None = None, current: float = 0.4) -> None:
        raw = int(round((volts * 1000 - 2600) / 0.26855))
        self.regs[0xD0], self.regs[0xD1] = raw & 0xFF, (raw >> 8) & 0x3F
        craw = int(round(current * 1000 / 2.68554))
        self.regs[0xD2], self.regs[0xD3] = craw & 0xFF, (craw >> 8) & 0x1F
        if plugged is not None:
            self.regs[0xDD] = 0x1F if plugged else 0x00

    def button(self, pressed: bool) -> None:
        if pressed:
            self.regs[0x58] |= 0b0000_0010
        else:
            self.regs[0x58] &= ~0b0000_0010 & 0xFF

    @property
    def powered_off(self) -> bool:
        return not self.regs[0x01] & 0b0000_0100


class FakeSD3078(Registers):
    """Time and alarm registers are writable only with WRTC1-3 set."""

    def __init__(self, when: _dt.datetime | None = None):
        super().__init__()
        self.ignored_writes = 0
        self.set_clock(when or _dt.datetime(2026, 10, 10, 8, 30, 0, tzinfo=_dt.timezone.utc))

    def set_clock(self, when: _dt.datetime) -> None:
        when = when.astimezone(_dt.timezone.utc)
        self.regs[0x00] = int_to_bcd(when.second)
        self.regs[0x01] = int_to_bcd(when.minute)
        self.regs[0x02] = int_to_bcd(when.hour) | 0x80
        self.regs[0x03] = int_to_bcd((when.weekday() + 1) % 7)
        self.regs[0x04] = int_to_bcd(when.day)
        self.regs[0x05] = int_to_bcd(when.month)
        self.regs[0x06] = int_to_bcd(when.year - 2000)

    @property
    def unlocked(self) -> bool:
        return bool(self.regs[0x10] & 0x80) and (self.regs[0x0F] & 0b1000_0100) == 0b1000_0100

    def write(self, register: int, value: int) -> None:
        if register in (0x0F, 0x10) or self.unlocked:
            self.regs[register] = value
        else:
            self.ignored_writes += 1


def simulated_bus(model: str = "pisugar3") -> tuple:
    """(bus, board) with a simulated board for ``python3 -m mfruitos.power serve --fake``."""
    if model == "pisugar3":
        board = FakePiSugar3()
        return FakeBus({p3.ADDRESS: board}), board
    if model in ("pisugar2-4led", "pisugar2-2led"):
        board = FakeIP5209(leds=4 if model.endswith("4led") else 2)
        return FakeBus({0x75: board, 0x32: FakeSD3078()}), board
    if model == "pisugar2-pro":
        board = FakeIP5312()
        return FakeBus({0x75: board, 0x32: FakeSD3078()}), board
    raise ValueError(f"no simulation for {model!r}")
