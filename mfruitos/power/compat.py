"""PiSugar's text protocol, served on ``/tmp/pisugar-server.sock``.

whisplay-daemon (bundled, unmodified) reads the battery level and installs
its PiSugar home-button hook through this protocol; apps' status bars
(mfruit_sdk.status) and users' scripts use it too. One request per line,
one answer per line, ``<name>: <value>`` as PiSugar's server answers. Presses
are pushed to every connected client as ``single``/``double``/``long``
lines, and enabled tap hooks run ``/bin/sh -c <shell>`` as the service user.

Commands that would cut the power at once, change the board's I2C address,
flash firmware or set web credentials are refused: mFruit OS powers off
safely through systemd and has no web interface.
"""

from __future__ import annotations

import datetime as _dt
import logging
import shlex

from mfruitos import __version__
from mfruitos.hosts.pisugar import base
from mfruitos.hosts.pisugar.base import Unsupported
from mfruitos.power.config import TAP_NAMES
from mfruitos.system.settings import Invalid

log = logging.getLogger("mfruitos.power.compat")

REFUSED = {"force_shutdown", "set_battery_output", "set_rtc_addr", "set_auth", "rtc_test_wake",
           "set_soft_poweroff_shell", "set_battery_keep_input", "rtc_adjust_ppm",
           "rtc_clear_flag", "rtc_web"}
REFUSED_REASON = {
    "force_shutdown": "mFruit OS shuts down safely through systemd",
    "set_battery_output": "mFruit OS cuts the power only after a safe shutdown",
    "rtc_web": "the clock follows systemd-timesyncd",
    "set_auth": "mFruit power has no web interface",
}


class CompatError(Exception):
    pass


def _bool(word: str) -> bool:
    text = word.strip().lower()
    if text in ("true", "on", "yes"):
        return True
    if text in ("false", "off", "no"):
        return False
    try:
        return int(text) != 0
    except ValueError:
        raise CompatError(f"expected true/false, got {word!r}") from None


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))
    return str(value)


def _rfc3339(when: _dt.datetime) -> str:
    return when.astimezone().isoformat(timespec="milliseconds")


class Compat:
    def __init__(self, service):
        self.service = service

    # ------------------------------------------------------------ helpers
    def _chip(self):
        if self.service.chip is None:
            raise CompatError(self.service.error or "I2C not connected")
        return self.service.chip

    def _hooks(self) -> dict:
        return self.service.config.get("tap_hooks")

    def hooks_wanting_taps(self) -> int:
        return sum(1 for hook in self._hooks().values() if hook["enabled"] and hook["shell"])

    def _set(self, key: str, value) -> None:
        try:
            self.service.set_option(key, value)
        except (Invalid, Unsupported, KeyError) as exc:
            raise CompatError(str(exc)) from exc

    # ------------------------------------------------------------ requests
    def handle(self, line: str) -> str:
        line = line.strip()
        if not line:
            return ""
        try:
            words = shlex.split(line)
        except ValueError as exc:
            return f"invalid request: {exc}"
        name = words[0]
        try:
            if name == "help":
                return self._help()
            if name == "get":
                if len(words) < 2:
                    raise CompatError("usage: get <name>")
                return self._get(words[1], words[2:])
            if name in REFUSED:
                reason = REFUSED_REASON.get(name, "not supported by mFruit power")
                return f"{name}: not supported ({reason})"
            handler = getattr(self, f"_cmd_{name}", None)
            if handler is None:
                return f"unknown command {name!r}; send 'help' for the list"
            result = handler(words[1:])
            return f"{name}: {result if result is not None else 'done'}"
        except (CompatError, Unsupported, Invalid, ValueError) as exc:
            label = words[1] if name == "get" and len(words) > 1 else name
            return f"{label}: {exc}"
        except OSError as exc:
            return f"{name}: I2C error: {exc}"

    def _help(self) -> str:
        gets = " ".join(sorted(n[5:] for n in dir(self) if n.startswith("_get_")))
        sets = " ".join(sorted(n[5:] for n in dir(self) if n.startswith("_cmd_")))
        return f"mFruit power (PiSugar protocol). get: {gets}. commands: {sets}"

    def _get(self, what: str, args: list) -> str:
        getter = getattr(self, f"_get_{what}", None)
        if getter is None:
            raise CompatError(f"unknown value {what!r}")
        value = getter(args)
        return f"{what}: {value}"

    # ------------------------------------------------------------ get
    def _get_version(self, args):
        return f"mfruit-power {__version__}"

    def _get_model(self, args):
        return self._chip().model

    def _get_firmware_version(self, args):
        return self._chip().firmware()

    def _get_battery(self, args):
        self._chip()
        level = self.service.level()
        if level is None:
            raise CompatError(self.service.error or "no battery reading yet")
        return _fmt(round(level, 1))

    def _get_battery_v(self, args):
        self._chip()
        volts = self.service.voltage()
        if volts is None:
            raise CompatError("no battery reading yet")
        return _fmt(round(volts, 3))

    def _get_battery_i(self, args):
        chip = self._chip()
        amps = self.service.current()
        if amps is None or base.CURRENT not in chip.features:
            raise CompatError("current is not available")
        return _fmt(round(amps, 3))

    def _get_battery_charging(self, args):
        self._chip()
        return _fmt(bool(self.service.charging()))

    def _get_battery_power_plugged(self, args):
        self._chip()
        plugged = self.service.plugged()
        if plugged is None:
            plugged = bool(self.service.charging())
        return _fmt(plugged)

    def _get_battery_allow_charging(self, args):
        chip = self._chip()
        try:
            return _fmt(chip.get_allow_charging())
        except Unsupported:
            return "true"

    def _get_battery_charging_range(self, args):
        span = self.service.config.get("charging_range")
        return f"{span[0]},{span[1]}" if span else ""

    def _get_battery_led_amount(self, args):
        chip = self._chip()
        return "2" if getattr(chip, "leds", 4) == 2 else "4"

    def _get_battery_input_protect_enabled(self, args):
        return _fmt(self._chip().get_battery_protect())

    _get_input_protect = _get_battery_input_protect_enabled

    def _get_battery_output_enabled(self, args):
        self._chip()
        return "true"

    def _get_full_charge_duration(self, args):
        return str(self.service.config.get("full_charge_duration"))

    def _get_system_time(self, args):
        return _rfc3339(self.service.wallclock())

    def _get_rtc_time(self, args):
        chip = self._chip()
        if chip.rtc is None:
            raise CompatError("this board has no clock")
        return _rfc3339(chip.rtc.read_time())

    def _get_rtc_alarm_enabled(self, args):
        chip = self._chip()
        if chip.rtc is None:
            raise CompatError("this board has no clock")
        return _fmt(chip.rtc.read_alarm().enabled)

    def _get_rtc_alarm_time(self, args):
        chip = self._chip()
        if chip.rtc is None:
            raise CompatError("this board has no clock")
        alarm = chip.rtc.read_alarm()
        today = _dt.datetime.now(_dt.timezone.utc).replace(
            hour=alarm.hour, minute=alarm.minute, second=alarm.second, microsecond=0)
        return _rfc3339(today)

    def _get_alarm_repeat(self, args):
        return str(self.service.config.get("wake_days") if self.service.config.get("wake_time")
                   else 0)

    def _get_safe_shutdown_level(self, args):
        return str(self.service.config.get("safe_shutdown_level"))

    def _get_safe_shutdown_delay(self, args):
        return str(self.service.config.get("safe_shutdown_delay"))

    def _get_button_enable(self, args):
        mode = self._mode(args)
        return f"{mode} {_fmt(self._hooks()[mode]['enabled'])}"

    def _get_button_shell(self, args):
        mode = self._mode(args)
        return f"{mode} {self._hooks()[mode]['shell']}".rstrip()

    def _get_auto_power_on(self, args):
        try:
            return _fmt(self._chip().get_power_restore())
        except Unsupported:
            return "false"

    def _get_auth_username(self, args):
        return ""

    def _get_anti_mistouch(self, args):
        return _fmt(self._chip().get_anti_mistouch())

    def _get_soft_poweroff(self, args):
        try:
            return _fmt(self._chip().get_soft_poweroff())
        except Unsupported:
            return "false"

    def _get_soft_poweroff_shell(self, args):
        return ""

    def _get_temperature(self, args):
        self._chip()
        sample = self.service.sample
        if sample is None or sample.temperature is None:
            raise CompatError("temperature is not available")
        return str(sample.temperature)

    # ------------------------------------------------------------ commands
    @staticmethod
    def _mode(args) -> str:
        if not args or args[0] not in TAP_NAMES:
            raise CompatError(f"expected one of {', '.join(TAP_NAMES)}")
        return args[0]

    def _cmd_set_button_enable(self, args):
        mode = self._mode(args)
        if len(args) < 2:
            raise CompatError("usage: set_button_enable <single|double|long> <0|1>")
        hooks = self._hooks()
        hooks[mode]["enabled"] = _bool(args[1])
        self._set("tap_hooks", hooks)

    def _cmd_set_button_shell(self, args):
        mode = self._mode(args)
        hooks = self._hooks()
        hooks[mode]["shell"] = " ".join(args[1:])
        self._set("tap_hooks", hooks)

    def _cmd_set_safe_shutdown_level(self, args):
        level = float(args[0]) if args else 0.0
        self._set("safe_shutdown_level", max(0, min(30, int(round(level)))))

    def _cmd_set_safe_shutdown_delay(self, args):
        delay = float(args[0]) if args else 0.0
        self._set("safe_shutdown_delay", max(0, min(120, int(round(delay)))))

    def _cmd_set_auto_power_on(self, args):
        self._set("power_restore", _bool(args[0] if args else ""))

    def _cmd_set_anti_mistouch(self, args):
        self._set("anti_mistouch", _bool(args[0] if args else ""))

    def _cmd_set_soft_poweroff(self, args):
        self._set("soft_poweroff", _bool(args[0] if args else ""))

    def _cmd_set_battery_input_protect(self, args):
        self._set("battery_protect", _bool(args[0] if args else ""))

    _cmd_set_input_protect = _cmd_set_battery_input_protect

    def _cmd_set_battery_charging_range(self, args):
        text = ",".join(args).replace(" ", "")
        if not text:
            self._set("charging_range", None)
            return
        parts = [p for p in text.split(",") if p]
        if len(parts) != 2:
            raise CompatError("usage: set_battery_charging_range <start>,<stop>")
        self._set("charging_range", [int(round(float(parts[0]))), int(round(float(parts[1])))])

    def _cmd_set_full_charge_duration(self, args):
        self._set("full_charge_duration", int(args[0]) if args else 0)

    def _cmd_set_allow_charging(self, args):
        self._chip().set_allow_charging(_bool(args[0] if args else ""))

    def _cmd_rtc_pi2rtc(self, args):
        self.service.save_clock()

    def _cmd_rtc_rtc2pi(self, args):
        try:
            self.service.load_clock()
        except PermissionError as exc:
            raise CompatError(f"cannot set the system clock: {exc}") from exc

    def _cmd_rtc_alarm_set(self, args):
        if len(args) < 2:
            raise CompatError("usage: rtc_alarm_set <ISO 8601 time> <weekday mask>")
        when = _dt.datetime.fromisoformat(args[0].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.astimezone()
        local = when.astimezone()
        days = int(args[1]) & 0x7F
        if not days:
            raise CompatError("choose at least one day (weekday mask 1..127)")
        self._set("wake_days", days)
        self._set("wake_time", f"{local.hour:02d}:{local.minute:02d}")

    def _cmd_rtc_alarm_disable(self, args):
        self._set("wake_time", None)
