"""Power configuration: ``~/.whisplay-os/config/power.json``.

The power service is the only writer (single owner). The launcher and
``mfruitctl`` change values through the service's socket, which validates,
applies and saves them. Loading follows the settings rules
(docs/platform/CONFIGURATION.md): a broken file is kept as
``power.json.broken-<timestamp>`` and safe defaults are used; one invalid
entry falls back to its default; writes are atomic.

Chip settings (power_restore, soft_poweroff, anti_mistouch, battery_protect)
default to None: mFruit OS leaves the board as it is until the user chooses.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable

from mfruitos.hosts.pisugar.base import validate_curve
from mfruitos.hosts.pisugar.detect import MODEL_CHOICES
from mfruitos.system.settings import Invalid, atomic_write_json

log = logging.getLogger("mfruitos.power.config")

SCHEMA_VERSION = 1
BUTTON_ACTIONS = ("none", "home", "screen", "power_menu")
TAP_NAMES = ("single", "double", "long")
SHUTDOWN_LEVELS = (0, 3, 5, 10, 15, 20)
SHUTDOWN_DELAYS = (10, 30, 60, 120)
CHARGING_RANGES = ((60, 90), (70, 90), (80, 100), (40, 80))
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _boolean(value):
    if isinstance(value, bool):
        return value
    raise Invalid("expected true/false")


def _optional(check):
    def wrapped(value):
        return None if value is None else check(value)
    return wrapped


def _int_range(lo: int, hi: int):
    def check(value):
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise Invalid(f"expected an integer {lo}..{hi}")
        return value
    return check


def _choice(*options):
    def check(value):
        if isinstance(value, bool) or value not in options:
            raise Invalid(f"expected one of {options}")
        return value
    return check


def _hhmm(value):
    if not isinstance(value, str) or not _TIME.match(value):
        raise Invalid("expected a time HH:MM (24 h)")
    return value


def _charging_range(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in value)):
        raise Invalid("expected [start %, stop %]")
    low, high = value
    if not 0 <= low < high <= 100:
        raise Invalid("expected 0 <= start < stop <= 100")
    return [low, high]


def _curve(value):
    try:
        return [list(point) for point in validate_curve(value)]
    except ValueError as exc:
        raise Invalid(str(exc)) from exc


def _hooks(value):
    if not isinstance(value, dict):
        raise Invalid("expected {single|double|long: {enabled, shell}}")
    clean = {}
    for name in TAP_NAMES:
        hook = value.get(name, {})
        if not isinstance(hook, dict):
            raise Invalid(f"tap hook {name} must be an object")
        enabled, shell = hook.get("enabled", False), hook.get("shell", "")
        if not isinstance(enabled, bool) or not isinstance(shell, str) or len(shell) > 512:
            raise Invalid(f"tap hook {name}: enabled true/false, shell up to 512 characters")
        clean[name] = {"enabled": enabled, "shell": shell}
    return clean


def default_hooks() -> dict:
    return {name: {"enabled": False, "shell": ""} for name in TAP_NAMES}


# key -> (default, validator)
SCHEMA: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "model": ("auto", _choice(*MODEL_CHOICES)),
    "i2c_bus": (1, _int_range(0, 31)),
    "i2c_address": (None, _optional(_int_range(0x03, 0x77))),
    "safe_shutdown_level": (5, _int_range(0, 30)),
    "safe_shutdown_delay": (30, _int_range(0, 120)),
    "button_double": ("none", _choice(*BUTTON_ACTIONS)),
    "button_long": ("none", _choice(*BUTTON_ACTIONS)),
    "soft_poweroff": (None, _optional(_boolean)),
    "anti_mistouch": (None, _optional(_boolean)),
    "power_restore": (None, _optional(_boolean)),
    "battery_protect": (None, _optional(_boolean)),
    "charging_range": (None, _optional(_charging_range)),
    "full_charge_duration": (300, _int_range(0, 3600)),
    "wake_time": (None, _optional(_hhmm)),
    "wake_days": (0x7F, _int_range(1, 0x7F)),
    "rtc_sync": (True, _boolean),
    "battery_curve": (None, _optional(_curve)),
    "compat_socket": (True, _boolean),
    "power_off_at_shutdown": (True, _boolean),
    "tap_hooks": (default_hooks(), _hooks),
}

# Values the board stores itself; the service writes them to the chip.
CHIP_KEYS = ("power_restore", "soft_poweroff", "anti_mistouch", "battery_protect")


def defaults() -> dict:
    data = {key: copy.deepcopy(default) for key, (default, _) in SCHEMA.items()}
    data["schema"] = SCHEMA_VERSION
    return data


class PowerConfig:
    def __init__(self, path: str | None):
        self.path = path
        self._lock = threading.RLock()
        self._data = defaults()
        self.load_errors: list[str] = []

    def load(self) -> None:
        self.load_errors = []
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                raw = json.load(fp)
            if not isinstance(raw, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError) as exc:
            preserved = self._preserve_broken()
            message = f"power settings unreadable ({exc}); kept as {preserved}; using defaults"
            log.error(message)
            self.load_errors.append(message)
            return
        data = defaults()
        for key, (default, check) in SCHEMA.items():
            if key not in raw:
                continue
            try:
                data[key] = check(raw[key])
            except Invalid as exc:
                message = f"invalid power setting {key}={raw[key]!r}: {exc}; using {default!r}"
                log.warning(message)
                self.load_errors.append(message)
        with self._lock:
            self._data = data

    def _preserve_broken(self) -> str:
        target = f"{self.path}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(self.path, target)
        except OSError as exc:
            log.error("Could not keep the broken power settings file: %s", exc)
            return self.path
        return target

    def save(self) -> None:
        if not self.path:
            return
        with self._lock:
            data = copy.deepcopy(self._data)
        atomic_write_json(self.path, data)

    def get(self, key: str) -> Any:
        with self._lock:
            return copy.deepcopy(self._data[key])

    def as_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def set(self, key: str, value: Any, save: bool = True) -> bool:
        """Validate and store; True if the value changed. Raises KeyError/Invalid."""
        if key not in SCHEMA:
            raise KeyError(key)
        value = SCHEMA[key][1](value)
        with self._lock:
            if self._data[key] == value:
                return False
            self._data[key] = value
        if save:
            self.save()
        return True


# ---------------------------------------------------------------- migration
PISUGAR_CONFIG = "/etc/pisugar-server/config.json"
PISUGAR_DEFAULTS = "/etc/default/pisugar-server"
PISUGAR_MODELS = {"PiSugar 3": "pisugar3", "PiSugar 2 (4-LEDs)": "pisugar2-4led",
                  "PiSugar 2 (2-LEDs)": "pisugar2-2led", "PiSugar 2 Pro": "pisugar2-pro"}


def pisugar_settings(config_path: str = PISUGAR_CONFIG,
                     defaults_path: str = PISUGAR_DEFAULTS) -> dict:
    """Settings of an existing PiSugar power manager, in power.json terms.

    Used once, when power.json does not exist yet, so a device that ran
    PiSugar's pisugar-server keeps its choices. Unknown or invalid values are
    skipped. Credentials (web login) are never imported.
    """
    result: dict = {}
    try:
        with open(defaults_path, encoding="utf-8") as fp:
            match = re.search(r"--model\s+'([^']+)'", fp.read())
        if match and match.group(1) in PISUGAR_MODELS:
            result["model"] = PISUGAR_MODELS[match.group(1)]
    except OSError:
        pass
    try:
        with open(config_path, encoding="utf-8") as fp:
            raw = json.load(fp)
    except (OSError, ValueError):
        return result
    if not isinstance(raw, dict):
        return result

    def take(key, value):
        try:
            result[key] = SCHEMA[key][1](value)
        except (Invalid, KeyError, TypeError, ValueError):
            log.info("PiSugar setting not imported: %s=%r", key, value)

    if isinstance(raw.get("i2c_bus"), int):
        take("i2c_bus", raw["i2c_bus"])
    if raw.get("i2c_addr") is not None:
        take("i2c_address", raw["i2c_addr"])
    level = raw.get("auto_shutdown_level")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        take("safe_shutdown_level", max(0, min(30, int(round(level)))))
    delay = raw.get("auto_shutdown_delay")
    if isinstance(delay, (int, float)) and not isinstance(delay, bool):
        take("safe_shutdown_delay", max(0, min(120, int(round(delay)))))
    for theirs, ours in (("auto_power_on", "power_restore"), ("soft_poweroff", "soft_poweroff"),
                         ("anti_mistouch", "anti_mistouch"), ("bat_protect", "battery_protect")):
        if isinstance(raw.get(theirs), bool):
            take(ours, raw[theirs])
    span = raw.get("auto_charging_range")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        try:
            take("charging_range", [int(round(float(span[0]))), int(round(float(span[1])))])
        except (TypeError, ValueError):
            pass
    if isinstance(raw.get("full_charge_duration"), int):
        take("full_charge_duration", raw["full_charge_duration"])
    if raw.get("battery_curve"):
        take("battery_curve", raw["battery_curve"])
    wake, repeat = raw.get("auto_wake_time"), raw.get("auto_wake_repeat")
    if isinstance(wake, str) and isinstance(repeat, int) and repeat & 0x7F:
        try:
            import datetime as _dt
            local = _dt.datetime.fromisoformat(wake).astimezone()
            take("wake_time", f"{local.hour:02d}:{local.minute:02d}")
            take("wake_days", repeat & 0x7F)
        except ValueError:
            pass
    hooks = default_hooks()
    for name in TAP_NAMES:
        enabled, shell = raw.get(f"{name}_tap_enable"), raw.get(f"{name}_tap_shell")
        if isinstance(enabled, bool) and isinstance(shell, str):
            hooks[name] = {"enabled": enabled, "shell": shell[:512]}
    if hooks != default_hooks():
        take("tap_hooks", hooks)
    return result


def first_load(config: "PowerConfig", import_from=pisugar_settings) -> list:
    """Load power.json, or create it (importing PiSugar's settings when found).

    Returns the imported keys (empty when the file already existed).
    """
    if config.path and os.path.exists(config.path):
        config.load()
        return []
    imported = import_from() or {}
    for key, value in imported.items():
        config.set(key, value, save=False)
    config.save()
    if imported:
        log.info("Imported PiSugar power settings: %s", ", ".join(sorted(imported)))
    return sorted(imported)
