"""Find the battery board on an I2C bus and build its driver.

Detection only reads: a PiSugar 3 answers at 0x57 with version 3 in
application mode; at 0x75 an IP5312 or IP5209 returns a plausible battery
voltage (PiSugar 2 Pro is tried first, as PiSugar's own driver does).
Nothing is written until the board is identified.
"""

from __future__ import annotations

import errno
import logging

from mfruitos.hosts.pisugar import base, pisugar2, pisugar3, sd3078
from mfruitos.hosts.pisugar.i2c import SMBus, explain

log = logging.getLogger("mfruitos.power.detect")

# config "model" values
AUTO = "auto"
NONE = "none"
MODELS = {
    "pisugar3": "PiSugar 3",
    "pisugar2-4led": "PiSugar 2 (4-LEDs)",
    "pisugar2-2led": "PiSugar 2 (2-LEDs)",
    "pisugar2-pro": "PiSugar 2 Pro",
}
MODEL_CHOICES = (AUTO, NONE) + tuple(MODELS)


class NotFound(Exception):
    """No usable board; the message says why, for the user."""


class BatteryChipSilent(NotFound):
    """A PiSugar 2 is on the bus (its clock answers) but its battery chip gives
    no reading. Nothing can be read until it does, which may start at any time
    (battery plugged back in, board switched on or reseated)."""

    def __init__(self, message: str, board: str = "PiSugar 2"):
        super().__init__(message)
        self.board = board


def _rtc(bus):
    """The PiSugar 2 clock, if it answers."""
    try:
        bus.read_byte_data(sd3078.ADDRESS, sd3078.CTR1)
    except OSError:
        return None
    return sd3078.SD3078(bus)


def build(bus, bus_number: int, model: str = AUTO, p3_addr: int | None = None):
    """The driver for ``model`` (or the detected board) on an open bus.

    Raises NotFound with a user-facing reason.
    """
    p3_addr = p3_addr or pisugar3.ADDRESS
    if model == NONE:
        raise NotFound("power management is turned off (model: none)")
    if model == "pisugar3":
        return pisugar3.PiSugar3(bus, bus_number, p3_addr)
    if model in ("pisugar2-4led", "pisugar2-2led"):
        return pisugar2.IP5209Board(bus, bus_number, rtc=_rtc(bus),
                                    leds=4 if model == "pisugar2-4led" else 2)
    if model == "pisugar2-pro":
        return pisugar2.IP5312Board(bus, bus_number, rtc=_rtc(bus))
    if model != AUTO:
        raise NotFound(f"unknown model {model!r}")

    try:
        state = pisugar3.identify(bus, p3_addr)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY):
            raise NotFound(explain(exc, bus_number, p3_addr)) from exc
        state = None
    if state == "ok":
        return pisugar3.PiSugar3(bus, bus_number, p3_addr)
    if state == "bootloader":
        raise NotFound("the PiSugar 3 is in firmware-update (bootloader) mode")

    try:
        volts = pisugar2.probe_ip5312(bus)
        if base.plausible(volts):
            return pisugar2.IP5312Board(bus, bus_number, rtc=_rtc(bus))
        if base.plausible(pisugar2.probe_ip5209(bus)):
            # The LED count decides how the chip's pins are used and cannot be
            # read; until it is chosen in Settings the board is only read.
            return pisugar2.UnknownPiSugar2(bus, bus_number, rtc=_rtc(bus))
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY):
            raise NotFound(explain(exc, bus_number, pisugar2.ADDRESS)) from exc
    if _rtc(bus) is not None:
        raise BatteryChipSilent(
            f"a PiSugar 2 is on I2C bus {bus_number} (its clock answers) but its battery "
            "chip gives no reading. Check that the battery is plugged into the PiSugar "
            "and that it is switched on; if it stays silent, reseat the PiSugar")
    raise NotFound(f"no PiSugar battery board found on I2C bus {bus_number}")


def open_board(bus_number: int, model: str = AUTO, p3_addr: int | None = None,
               opener=None):
    """Open the bus and return (bus, chip); raises NotFound.

    With ``model`` "none" the bus is not even opened.
    """
    if model == NONE:
        raise NotFound("power management is turned off (model: none)")
    opener = opener or SMBus
    try:
        bus = opener(bus_number)
    except OSError as exc:
        raise NotFound(explain(exc, bus_number)) from exc
    try:
        return bus, build(bus, bus_number, model, p3_addr)
    except BaseException:
        bus.close()
        raise
