"""PiSugar 2: an IP5209 (PiSugar 2) or IP5312 (PiSugar 2 Pro) power chip at
I2C 0x75, plus an SD3078 clock at 0x32 (``sd3078.py``).

The chips report the battery voltage and current; charge is estimated from
the voltage. The tap button is a GPIO input of the power chip that has to be
sampled every 100 ms, so presses are recognised from the sampled pattern.

Register use (from the chips' published interface):

IP5209   0xA2/0xA3 voltage (low, high)   0xA4/0xA5 current (low, high)
         0x55 GPIO levels: bit4 button (4-LED board), bit1 button (2-LED
         board), bit4 external power (2-LED), bit2 charging blocked (2-LED)
         0x0C/0x04/0x02 light-load shutdown, 0x01 bit2 cleared = power off
IP5312   0xD0/0xD1 voltage (low, high)   0xD2/0xD3 current (low, high)
         0x58 GPIO levels: bit1 button, bit2 charging blocked
         0xDD == 0x1F: external power   0xC9/0x06/0x03/0x13 light-load
         shutdown, 0x30 boost current, 0x01 bit2 cleared = power off

Light-load shutdown lets the board switch itself off once the Pi has halted
(the load drops below about 110 mA for 8 s); it is off while "power on when
plugged in" is on, because that mode keeps the board awake.
"""

from __future__ import annotations

from collections import deque

from mfruitos.hosts.pisugar import base
from mfruitos.hosts.pisugar.base import Chip, Sample

ADDRESS = 0x75

# Press patterns over 100 ms samples (1 = pressed), oldest first.
LONG_PATTERN = "111111110"
DOUBLE_PATTERNS = ("1010", "10010", "10110", "100110", "101110", "1001110")
SINGLE_PATTERN = "1000"
HISTORY = 30


class TapDetector:
    """Recognises single, double and long presses from 100 ms samples."""

    def __init__(self):
        self.history: deque = deque(maxlen=HISTORY)

    def feed(self, pressed: bool) -> str | None:
        self.history.append("1" if pressed else "0")
        text = "".join(self.history)
        if LONG_PATTERN in text:
            self.history.clear()
            return "long"
        if any(pattern in text for pattern in DOUBLE_PATTERNS):
            self.history.clear()
            return "double"
        if SINGLE_PATTERN in text:
            self.history.clear()
            return "single"
        return None


def _signed_14(low: int, high: int) -> int:
    """The chips' 14-bit two's-complement reading (bit 13 of high is the sign)."""
    if high & 0x20:
        value = ((high | 0xC0) << 8) | low
        return value - 0x10000
    return ((high & 0x1F) << 8) | low


def ip5209_millivolts(low: int, high: int) -> float:
    raw = _signed_14(low, high)
    return 2600.0 - raw * 0.26855 if raw < 0 else 2600.0 + raw * 0.26855


def ip5312_millivolts(low: int, high: int) -> float | None:
    if low == 0 and high == 0:
        return None
    return 2600.0 + (((high & 0x3F) << 8) | low) * 0.26855


def probe_ip5312(bus, addr: int = ADDRESS) -> float | None:
    millivolts = ip5312_millivolts(bus.read_byte_data(addr, 0xD0), bus.read_byte_data(addr, 0xD1))
    return millivolts / 1000.0 if millivolts is not None else None


def probe_ip5209(bus, addr: int = ADDRESS) -> float:
    return ip5209_millivolts(bus.read_byte_data(addr, 0xA2), bus.read_byte_data(addr, 0xA3)) / 1000.0


class _PiSugar2(Chip):
    leds = 4
    poll_interval = 1.0
    tap_interval = 0.1

    def __init__(self, bus, bus_number: int, addr: int = ADDRESS, rtc=None):
        super().__init__(bus, bus_number, addr)
        self.rtc = rtc
        self.taps = TapDetector()

    def read(self, register: int) -> int:
        return self.bus.read_byte_data(self.addr, register)

    def write(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.addr, register, value & 0xFF)

    def update(self, register: int, clear: int = 0, set_bits: int = 0) -> None:
        value = self.read(register)
        self.write(register, (value & ~clear & 0xFF) | set_bits)

    # power-restore lives in the clock (a 2 Hz alarm keeps the board awake)
    def get_power_restore(self) -> bool:
        if self.rtc is None:
            self._unsupported("power on when plugged in")
        return self.rtc.frequency_alarm_enabled()

    def set_power_restore(self, on: bool) -> None:
        if self.rtc is None:
            self._unsupported("power on when plugged in")
        if on:
            self.rtc.enable_frequency_alarm()
            self.disable_light_load_shutdown()
        else:
            self.rtc.disable_frequency_alarm()
            self.enable_light_load_shutdown()

    def init(self, settings: dict) -> None:
        self.init_gpio()
        restore = settings.get("power_restore")
        if restore is None and self.rtc is not None:
            restore = self.rtc.frequency_alarm_enabled()
        if restore:
            self.disable_light_load_shutdown()
        else:
            self.enable_light_load_shutdown()
        if settings.get("power_restore") is not None and self.rtc is not None:
            self.set_power_restore(bool(settings["power_restore"]))

    def poll_taps(self) -> list:
        tap = self.taps.feed(self.button_pressed())
        return [tap] if tap else []

    # implemented per chip
    def init_gpio(self) -> None:
        raise NotImplementedError

    def button_pressed(self) -> bool:
        raise NotImplementedError

    def enable_light_load_shutdown(self) -> None:
        raise NotImplementedError

    def disable_light_load_shutdown(self) -> None:
        raise NotImplementedError


class IP5209Board(_PiSugar2):
    """PiSugar 2 with the IP5209; ``leds`` is 4 or 2 (two board revisions)."""

    curve = base.CURVE_IP5209

    def __init__(self, bus, bus_number: int, addr: int = ADDRESS, rtc=None, leds: int = 4):
        super().__init__(bus, bus_number, addr, rtc)
        if leds not in (2, 4):
            raise ValueError("a PiSugar 2 has 2 or 4 LEDs")
        self.leds = leds
        self.key = "pisugar2-4led" if leds == 4 else "pisugar2-2led"
        self.model = f"PiSugar 2 ({leds}-LEDs)"
        features = {base.TAPS, base.CURRENT}
        if leds == 2:
            features.add(base.CHARGING_CONTROL)
        if rtc is not None:
            features |= {base.RTC, base.POWER_RESTORE}
        self.features = frozenset(features)

    def init_gpio(self) -> None:
        if self.leds == 4:
            self.update(0x26, clear=0b0100_0000)
            self.update(0x52, clear=0b0000_1000, set_bits=0b0000_0100)
            self.update(0x53, set_bits=0b0001_0000)
            return
        self.update(0x51, clear=0b0000_1100, set_bits=0b0000_0100)   # GPIO1 = button
        self.update(0x53, set_bits=0b0000_0010)
        self.update(0x51, clear=0b0011_0000, set_bits=0b0001_0000)   # GPIO2 = charge control
        self.update(0x26, clear=0b0100_1111)
        self.update(0x52, clear=0b0000_1100, set_bits=0b0000_0100)   # GPIO4 = power sense
        self.update(0x53, clear=0b0001_0000, set_bits=0b0001_0000)
        self.set_allow_charging(True)

    def sample(self) -> Sample:
        volts = ip5209_millivolts(self.read(0xA2), self.read(0xA3)) / 1000.0
        raw = _signed_14(self.read(0xA4), self.read(0xA5))
        sample = Sample(voltage=volts, current=raw * 0.745985 / 1000.0)
        if self.leds == 2:
            gpio = self.read(0x55)
            sample.plugged = bool(gpio & 0b0001_0000)
            sample.allow_charging = not gpio & 0b0000_0100
        return sample

    def button_pressed(self) -> bool:
        gpio = self.read(0x55)
        return bool(gpio & (0b0000_0010 if self.leds == 2 else 0b0001_0000))

    def get_allow_charging(self) -> bool:
        if self.leds != 2:
            self._unsupported("charging control")
        return not self.read(0x55) & 0b0000_0100

    def set_allow_charging(self, on: bool) -> None:
        if self.leds != 2:
            self._unsupported("charging control")
        self.update(0x54, clear=0b0000_0100)                     # GPIO2 output off
        self.update(0x55, clear=0b0000_0100, set_bits=0 if on else 0b0000_0100)
        self.update(0x54, set_bits=0b0000_0100)                  # GPIO2 output on

    def enable_light_load_shutdown(self) -> None:
        threshold = min(0b1_1111, int(110 / 12))                  # x * 12 mA
        self.update(0x0C, clear=0b1111_1000, set_bits=threshold << 3)
        self.update(0x04, clear=0b1100_0000)                     # 8 s
        self.update(0x02, set_bits=0b0000_0011)

    def disable_light_load_shutdown(self) -> None:
        self.update(0x02, clear=0b0000_0010)


class IP5312Board(_PiSugar2):
    """PiSugar 2 Pro (IP5312, two LEDs)."""

    key = "pisugar2-pro"
    model = "PiSugar 2 Pro"
    curve = base.CURVE_IP5312
    leds = 2

    def __init__(self, bus, bus_number: int, addr: int = ADDRESS, rtc=None):
        super().__init__(bus, bus_number, addr, rtc)
        features = {base.TAPS, base.CURRENT, base.CHARGING_CONTROL}
        if rtc is not None:
            features |= {base.RTC, base.POWER_RESTORE}
        self.features = frozenset(features)

    def init_gpio(self) -> None:
        self.update(0x52, set_bits=0b0000_0010)                   # GPIO1 = button
        self.update(0x54, set_bits=0b0000_0010)
        self.update(0x52, set_bits=0b0000_0100)                   # GPIO2 = charge control
        self.update(0x29, clear=0b0100_0000)
        self.update(0x52, clear=0b0110_0000, set_bits=0b0100_0000)
        self.update(0xC2, set_bits=0b0001_0000)
        self.update(0x30, clear=0b0011_1111, set_bits=0x3F)        # boost current 3 A
        self.set_allow_charging(True)

    def sample(self) -> Sample:
        millivolts = ip5312_millivolts(self.read(0xD0), self.read(0xD1))
        if millivolts is None:
            raise OSError("IP5312 returned no voltage")
        raw = _signed_14(self.read(0xD2), self.read(0xD3))
        gpio = self.read(0x58)
        return Sample(voltage=millivolts / 1000.0, current=raw * 2.68554 / 1000.0,
                      plugged=self.read(0xDD) == 0x1F,
                      allow_charging=not gpio & 0b0000_0100)

    def button_pressed(self) -> bool:
        return bool(self.read(0x58) & 0b0000_0010)

    def get_allow_charging(self) -> bool:
        return not self.read(0x58) & 0b0000_0100

    def set_allow_charging(self, on: bool) -> None:
        self.update(0x56, clear=0b0000_0100)
        self.update(0x58, clear=0b0000_0100, set_bits=0 if on else 0b0000_0100)
        self.update(0x56, set_bits=0b0000_0100)

    def enable_light_load_shutdown(self) -> None:
        threshold = min(0b11_1111, int(200 / 4.3))                 # x * 4.3 mA
        self.update(0xC9, clear=0b0011_1111, set_bits=threshold)
        self.update(0x06, clear=0b1100_0000)                     # 8 s
        self.update(0x03, set_bits=0b0010_0000)
        self.update(0x13, clear=0b0011_0000, set_bits=0b0001_0000)  # battery low 2.76-2.84 V

    def disable_light_load_shutdown(self) -> None:
        self.update(0x03, clear=0b0010_0000)


class UnknownPiSugar2(_PiSugar2):
    """An IP5209 board whose LED count is not configured yet: battery
    readings only, and nothing is written to the chip."""

    key = "pisugar2"
    model = "PiSugar 2"
    curve = base.CURVE_IP5209
    features = frozenset({base.CURRENT})
    tap_interval = None

    def init(self, settings: dict) -> None:
        pass

    def sample(self) -> Sample:
        volts = ip5209_millivolts(self.read(0xA2), self.read(0xA3)) / 1000.0
        raw = _signed_14(self.read(0xA4), self.read(0xA5))
        return Sample(voltage=volts, current=raw * 0.745985 / 1000.0)

    def poll_taps(self) -> list:
        return []
