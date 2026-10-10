"""What every battery board offers the power service, and shared helpers.

A *chip* object drives one board model. The power service
(``mfruitos/power``) only uses the members of :class:`Chip`; a board that
lacks a capability says so in ``features`` and raises :class:`Unsupported`
when asked for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Feature names (Chip.features). The power service and the Settings screen
# offer an option only when the board has the matching feature.
CHARGING_CONTROL = "charging_control"   # turn charging on/off (charging range)
POWER_RESTORE = "power_restore"         # power on by itself when power returns
SOFT_POWEROFF = "soft_poweroff"         # power button asks Linux to shut down
ANTI_MISTOUCH = "anti_mistouch"         # power button needs a deliberate hold
BATTERY_PROTECT = "battery_protect"     # hardware charging limit (longer life)
TEMPERATURE = "temperature"
TAPS = "taps"                           # single/double/long press events
RTC = "rtc"                             # real-time clock and wake alarm
CURRENT = "current"                     # output current reading

# Battery voltage (V) -> charge (%). Measured curves for the boards' cells,
# as published with PiSugar's power manager; PiSugar 3 uses the IP5312 curve.
CURVE_IP5209 = ((4.16, 100.0), (4.05, 95.0), (4.00, 80.0), (3.92, 65.0), (3.86, 40.0),
                (3.79, 25.5), (3.66, 10.0), (3.52, 6.5), (3.49, 3.2), (3.10, 0.0))
CURVE_IP5312 = ((4.10, 100.0), (4.05, 95.0), (3.90, 88.0), (3.80, 77.0), (3.70, 65.0),
                (3.62, 55.0), (3.58, 49.0), (3.49, 25.6), (3.32, 4.5), (3.10, 0.0))

# A reading outside this range means no cell (or a broken reading).
PLAUSIBLE_VOLTS = (2.8, 4.6)


class Unsupported(Exception):
    """The board does not have this capability."""


@dataclass
class Sample:
    """One reading of the board, in SI units. None: the board cannot tell."""
    voltage: float | None = None          # battery voltage, V
    current: float | None = None          # output current, A
    plugged: bool | None = None           # external power connected
    allow_charging: bool | None = None    # charging permitted by the board
    temperature: int | None = None        # chip temperature, °C
    extra: dict = field(default_factory=dict)


def plausible(volts: float | None) -> bool:
    return volts is not None and PLAUSIBLE_VOLTS[0] <= volts <= PLAUSIBLE_VOLTS[1]


def level_from_voltage(volts: float, curve) -> float:
    """Charge (%) for ``volts`` by linear interpolation on ``curve``.

    ``curve`` lists (volts, percent) points; any order is accepted. Above the
    top point the top percentage applies, below the bottom point 0.
    """
    points = sorted(((float(v), float(p)) for v, p in curve), reverse=True)
    if not points:
        raise ValueError("empty battery curve")
    if volts >= points[0][0]:
        return points[0][1]
    for (v_high, p_high), (v_low, p_low) in zip(points, points[1:]):
        if volts >= v_low:
            span = v_high - v_low
            return p_low + (volts - v_low) / span * (p_high - p_low) if span else p_low
    return 0.0


def validate_curve(curve) -> tuple:
    """A user curve as sorted (volts, percent) pairs, or ValueError.

    Higher voltage must mean more charge: voltages distinct, percentages
    strictly rising with voltage, percentages 0..100, voltages plausible.
    """
    if not isinstance(curve, (list, tuple)) or len(curve) < 2:
        raise ValueError("a battery curve needs at least two [volts, percent] points")
    points = []
    for point in curve:
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in point)):
            raise ValueError("each curve point must be [volts, percent]")
        volts, percent = float(point[0]), float(point[1])
        if not 2.5 <= volts <= 4.6:
            raise ValueError(f"curve voltage {volts} V is outside 2.5..4.6")
        if not 0.0 <= percent <= 100.0:
            raise ValueError(f"curve percentage {percent} is outside 0..100")
        points.append((volts, percent))
    points.sort()
    for (v1, p1), (v2, p2) in zip(points, points[1:]):
        if v1 == v2 or p2 <= p1:
            raise ValueError("curve percentages must rise with voltage")
    return tuple(points)


def bcd_to_int(value: int) -> int:
    return (value >> 4) * 10 + (value & 0x0F)


def int_to_bcd(value: int) -> int:
    if not 0 <= value <= 99:
        raise ValueError(f"{value} does not fit in two BCD digits")
    return ((value // 10) << 4) | (value % 10)


class Chip:
    """Base class of the board drivers. Subclasses fill in the hardware."""

    key = ""                    # config value, e.g. "pisugar3"
    model = ""                  # display name, e.g. "PiSugar 3"
    features: frozenset = frozenset()
    curve = CURVE_IP5312
    poll_interval = 1.0         # seconds between battery samples
    tap_interval: float | None = None   # faster sampling while taps are wanted

    def __init__(self, bus, bus_number: int, addr: int):
        self.bus = bus
        self.bus_number = bus_number
        self.addr = addr
        self.rtc = None         # an Rtc, when the board has a clock

    # -- lifecycle
    def init(self, settings: dict) -> None:
        """Apply the explicit chip settings (keys whose value is not None)."""

    def firmware(self) -> str:
        return ""

    # -- readings and events
    def sample(self) -> Sample:
        raise NotImplementedError

    def poll_taps(self) -> list:
        """Presses since the last call: "single", "double" or "long"."""
        return []

    def poll_soft_poweroff(self) -> bool:
        """True once when the power button asked for a shutdown."""
        return False

    # -- settings (current value from the chip; Unsupported when absent)
    def _unsupported(self, what: str):
        raise Unsupported(f"{what} is not available on {self.model}")

    def get_allow_charging(self) -> bool:
        self._unsupported("charging control")

    def set_allow_charging(self, on: bool) -> None:
        self._unsupported("charging control")

    def get_power_restore(self) -> bool:
        self._unsupported("power on when plugged in")

    def set_power_restore(self, on: bool) -> None:
        self._unsupported("power on when plugged in")

    def get_soft_poweroff(self) -> bool:
        self._unsupported("soft shutdown")

    def set_soft_poweroff(self, on: bool) -> None:
        self._unsupported("soft shutdown")

    def get_anti_mistouch(self) -> bool:
        self._unsupported("anti-mistouch")

    def set_anti_mistouch(self, on: bool) -> None:
        self._unsupported("anti-mistouch")

    def get_battery_protect(self) -> bool:
        self._unsupported("battery protection")

    def set_battery_protect(self, on: bool) -> None:
        self._unsupported("battery protection")

    def describe(self) -> dict:
        return {"model": self.model, "key": self.key, "bus": self.bus_number,
                "address": f"0x{self.addr:02x}", "features": sorted(self.features)}
