"""The power service's state and decisions. No sockets here (``server.py``).

Everything runs on the server's loop thread: ``tick(now)`` samples the board
when due and applies the policies; command results from worker threads come
back through ``post``. Time sources, the board opener, the command runner and
the clock setter are injected so tests can drive every path without hardware.

Policies (docs/platform/ADR/0012-own-power-management.md):

* **Safe shutdown at low battery.** Below ``safe_shutdown_level`` % while not
  on external power, a countdown of ``safe_shutdown_delay`` seconds starts and
  is announced; external power or a recovered level cancels it. At zero the
  system powers off through ``sudo -n systemctl poweroff`` (the sudoers rule
  installed with mFruit OS). Off when the level is 0.
* **Soft shutdown.** With the board's soft shutdown on (PiSugar 3), holding
  the power button asks the service to power the system off safely.
* **Charging range** (boards that can switch charging, except PiSugar 3,
  which has its hardware "battery protection" instead).
* **Clock.** At start, when the system clock is not synchronised and the
  board's clock is ahead by more than a minute, the system clock is moved
  forward from it (never backwards). Once systemd-timesyncd reports
  synchronisation, the board's clock is set from the system clock.
* **Wake alarm.** A local "HH:MM" and weekday mask, written to the board in
  UTC (re-applied every few hours to follow daylight-saving changes).
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from typing import Callable

from mfruitos import power
from mfruitos.hosts.pisugar import base, detect
from mfruitos.hosts.pisugar.base import Unsupported
from mfruitos.hosts.pisugar.rtc import local_to_utc_alarm
from mfruitos.power.config import CHIP_KEYS, SCHEMA, PowerConfig
from mfruitos.system.settings import Invalid

log = logging.getLogger("mfruitos.power")

WINDOW = 30                        # samples averaged for the level
ERROR_RETRY_SEC = 5.0
ERRORS_BEFORE_REPORT = 3
PROBE_RETRY_SEC = (5.0, 15.0, 60.0)   # I2C can appear late at boot; then give up
HOUSEKEEPING_SEC = 60.0
RTC_CHECK_SEC = 6 * 3600.0
RTC_SET_MARGIN_SEC = 60.0
RTC_MIN_YEAR = 2025
SHUTDOWN_RETRY_SEC = 60.0
LEVEL_EVENT_MIN_SEC = 10.0
NTP_FLAG = "/run/systemd/timesync/synchronized"


def ntp_synchronized() -> bool:
    return os.path.exists(NTP_FLAG)


def set_system_clock(when: _dt.datetime) -> None:
    """Needs CAP_SYS_TIME (the service unit grants it)."""
    time.clock_settime(time.CLOCK_REALTIME, when.timestamp())


class CommandRunner:
    """Runs a command on a worker thread and reports (returncode, output)."""

    def __init__(self, post: Callable[[Callable], None]):
        self.post = post

    def run(self, argv: list, done: Callable[[int, str], None], timeout: float = 60.0) -> None:
        def work():
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                      stdin=subprocess.DEVNULL, preexec_fn=drop_ambient_caps)
                result = (proc.returncode, (proc.stderr or proc.stdout or "").strip())
            except (OSError, subprocess.SubprocessError) as exc:
                result = (127, str(exc))
            self.post(lambda: done(*result))
        threading.Thread(target=work, name="power-command", daemon=True).start()


class DryRunner:
    """Development and tests: records commands instead of running them."""

    def __init__(self, post: Callable[[Callable], None] | None = None, returncode: int = 0,
                 output: str = ""):
        self.post = post or (lambda fn: fn())
        self.returncode = returncode
        self.output = output
        self.commands: list = []

    def run(self, argv: list, done: Callable[[int, str], None], timeout: float = 60.0) -> None:
        self.commands.append(list(argv))
        log.warning("dry run: would run %s", " ".join(argv))
        self.post(lambda: done(self.returncode, self.output))


def drop_ambient_caps() -> None:
    """Child processes must not inherit the service's CAP_SYS_TIME."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(47, 4, 0, 0, 0)   # PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL
    except (OSError, AttributeError):
        pass


def power_command(reboot: bool) -> list:
    systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
    return ["sudo", "-n", systemctl, "reboot" if reboot else "poweroff"]


class PowerService:
    def __init__(self, config: PowerConfig, *, open_board=detect.open_board,
                 monotonic: Callable[[], float] = time.monotonic,
                 wallclock: Callable[[], _dt.datetime] | None = None,
                 runner=None, set_clock: Callable[[_dt.datetime], None] = set_system_clock,
                 ntp_synced: Callable[[], bool] = ntp_synchronized,
                 post: Callable[[Callable], None] | None = None):
        self.config = config
        self.open_board = open_board
        self.monotonic = monotonic
        self.wallclock = wallclock or (lambda: _dt.datetime.now().astimezone())
        self.post = post or (lambda fn: fn())
        self.runner = runner or CommandRunner(self.post)
        self.set_clock = set_clock
        self.ntp_synced = ntp_synced
        self.on_event: Callable[[dict], None] = lambda event: None
        self.extra_tap_listeners = 0        # compat hooks that want presses

        self.bus = None
        self.chip = None
        self.error = ""
        self._probe_attempt = 0
        self._next_probe: float | None = None
        self._next_sample = 0.0
        self._next_tap = 0.0
        self._next_housekeeping = 0.0
        self._next_rtc_check = 0.0
        self._failures = 0
        self._voltages: deque = deque(maxlen=WINDOW)
        self._currents: deque = deque(maxlen=WINDOW)
        self.sample: base.Sample | None = None
        self.low_since: float | None = None
        self._low_notice_at = 0.0
        self.shutting_down = ""
        self._shutdown_retry_at: float | None = None
        self._full_at: float | None = None
        self._rtc_written_at: float | None = None
        self._clock_checked = False
        self._last_view: dict | None = None
        self._last_level_event = -1e9

    # ================================================================ board
    def start(self) -> None:
        self.probe()

    def probe(self) -> bool:
        """(Re)detect the board and apply its settings. True if one is in use."""
        self.close_board()
        model = self.config.get("model")
        if model == detect.NONE:
            self._board_missing("power management is turned off (model: none)", retry=False)
            return False
        try:
            self.bus, self.chip = self.open_board(self.config.get("i2c_bus"), model,
                                                  self.config.get("i2c_address"))
            self.chip.init({key: self.config.get(key) for key in CHIP_KEYS})
        except detect.NotFound as exc:
            self._board_missing(str(exc), retry=model != detect.NONE)
            return False
        except OSError as exc:
            from mfruitos.hosts.pisugar.i2c import explain
            self._board_missing(explain(exc, self.config.get("i2c_bus")), retry=True)
            return False
        self.error = ""
        self._probe_attempt = 0
        self._next_probe = None
        log.info("Battery board: %s on I2C bus %s%s", self.chip.model, self.chip.bus_number,
                 f" (firmware {self.chip.firmware()})" if self.chip.firmware() else "")
        now = self.monotonic()
        self._next_sample = self._next_tap = now
        self._next_housekeeping = now + HOUSEKEEPING_SEC
        self._next_rtc_check = now
        self._apply_wake_alarm(report=False)
        self._emit_state(force=True)
        return True

    def _board_missing(self, reason: str, retry: bool) -> None:
        self.close_board()
        self.error = reason
        if retry and self._probe_attempt < len(PROBE_RETRY_SEC):
            delay = PROBE_RETRY_SEC[self._probe_attempt]
            self._probe_attempt += 1
            self._next_probe = self.monotonic() + delay
            log.info("No battery board yet (%s); trying again in %.0f s", reason, delay)
        else:
            self._next_probe = None
            log.info("No battery board: %s", reason)
        self._emit_state(force=True)

    def close_board(self) -> None:
        if self.bus is not None:
            try:
                self.bus.close()
            except OSError:
                pass
        self.bus = self.chip = None
        self.sample = None
        self._voltages.clear()
        self._currents.clear()
        self._failures = 0

    # ================================================================ timing
    def taps_wanted(self) -> bool:
        if self.chip is None or base.TAPS not in self.chip.features:
            return False
        actions = (self.config.get("button_double"), self.config.get("button_long"))
        return self.extra_tap_listeners > 0 or any(a != "none" for a in actions)

    def due(self) -> float | None:
        """Monotonic time of the next tick, or None when nothing is scheduled."""
        times = [t for t in (self._next_probe, self._shutdown_retry_at) if t is not None]
        if self.chip is not None:
            times.append(self._next_sample)
            if self.chip.tap_interval and self.taps_wanted():
                times.append(self._next_tap)
        return min(times) if times else None

    def tick(self, now: float | None = None) -> None:
        now = self.monotonic() if now is None else now
        if self._next_probe is not None and now >= self._next_probe and self.chip is None:
            self.probe()
        if self.chip is None:
            self._retry_shutdown(now)
            return
        try:
            if self.chip.tap_interval and self.taps_wanted() and now >= self._next_tap:
                self._next_tap = now + self.chip.tap_interval
                self._taps(self.chip.poll_taps())
            if now >= self._next_sample:
                self._sample(now)
            if now >= self._next_housekeeping:
                self._next_housekeeping = now + HOUSEKEEPING_SEC
                if self.chip.rtc is not None:
                    self.chip.rtc.housekeeping()
            if now >= self._next_rtc_check:
                self._next_rtc_check = now + RTC_CHECK_SEC
                self._rtc_check(now)
        except OSError as exc:
            self._read_failed(now, exc)
        self._retry_shutdown(now)

    def _read_failed(self, now: float, exc: OSError) -> None:
        self._failures += 1
        self._next_sample = now + ERROR_RETRY_SEC
        self._next_tap = now + ERROR_RETRY_SEC
        if self._failures == ERRORS_BEFORE_REPORT:
            from mfruitos.hosts.pisugar.i2c import explain
            self.error = explain(exc, self.chip.bus_number, self.chip.addr)
            log.warning("Battery board not answering: %s", self.error)
            self.sample = None
            self._voltages.clear()
            self._emit_state(force=True)

    # ================================================================ sampling
    def _sample(self, now: float) -> None:
        self._next_sample = now + self.chip.poll_interval
        sample = self.chip.sample()
        if self._failures >= ERRORS_BEFORE_REPORT:
            log.info("Battery board answers again")
            self.error = ""
        self._failures = 0
        self.sample = sample
        if base.plausible(sample.voltage):
            self._voltages.append(sample.voltage)
        if sample.current is not None:
            self._currents.append(sample.current)
        if not self.chip.tap_interval:
            self._taps(self.chip.poll_taps())
        if self.chip.poll_soft_poweroff():
            log.warning("Power button asked for a shutdown (soft shutdown)")
            self.request_shutdown(reason="power-button")
        self._charging_range(now)
        self._low_battery(now)
        self._emit_state()

    def voltage(self) -> float | None:
        return sum(self._voltages) / len(self._voltages) if self._voltages else None

    def current(self) -> float | None:
        return sum(self._currents) / len(self._currents) if self._currents else None

    def level(self) -> float | None:
        volts = self.voltage()
        if volts is None or self.chip is None:
            return None
        curve = self.config.get("battery_curve") or self.chip.curve
        return base.level_from_voltage(volts, curve)

    def plugged(self) -> bool | None:
        return self.sample.plugged if self.sample is not None else None

    def charging(self) -> bool | None:
        if self.sample is None:
            return None
        if self.sample.plugged is not None:
            return bool(self.sample.plugged and self.sample.allow_charging is not False)
        # Boards that cannot sense external power: a rising voltage means charging.
        if len(self._voltages) < 3:
            return False
        mean = self.voltage()
        return self._voltages[0] < mean < self._voltages[-1]

    # ================================================================ events
    def _taps(self, taps: list) -> None:
        for tap in taps:
            log.info("Battery board button: %s press", tap)
            self.on_event({"event": power.BUTTON, "tap": tap})

    def view(self) -> dict:
        level = self.level()
        low = None
        if self.low_since is not None:
            left = self.config.get("safe_shutdown_delay") - (self.monotonic() - self.low_since)
            low = {"level": round(level) if level is not None else None,
                   "seconds_left": max(0, math.ceil(left))}
        return {"present": self.chip is not None,
                "model": self.chip.model if self.chip else "",
                "level": round(level) if level is not None else None,
                "plugged": self.plugged(), "charging": self.charging(),
                "error": self.error, "low_battery": low,
                "shutting_down": self.shutting_down or None}

    def _emit_state(self, force: bool = False) -> None:
        view = self.view()
        last = self._last_view
        if last is not None and not force:
            same_but_level = {k: v for k, v in view.items() if k not in ("level", "low_battery")}
            last_but_level = {k: v for k, v in last.items() if k not in ("level", "low_battery")}
            if same_but_level == last_but_level:
                if view["level"] == last["level"]:
                    return
                if self.monotonic() - self._last_level_event < LEVEL_EVENT_MIN_SEC:
                    return
        if view.get("level") != (last or {}).get("level"):
            self._last_level_event = self.monotonic()
        self._last_view = view
        self.on_event({"event": power.STATE, "state": view})

    # ================================================================ policies
    def _low_battery(self, now: float) -> None:
        threshold = self.config.get("safe_shutdown_level")
        level = self.level()
        external = self.plugged() or self.charging()
        low = (threshold > 0 and level is not None and not external and level < threshold
               and not self.shutting_down)
        if not low:
            if self.low_since is not None:
                reason = ("plugged" if external else "disabled" if threshold == 0
                          else "shutting down" if self.shutting_down else "recovered")
                self.low_since = None
                log.info("Low-battery shutdown cancelled (%s)", reason)
                self.on_event({"event": power.LOW_BATTERY_CANCELLED, "reason": reason})
                self._emit_state(force=True)
            return
        delay = self.config.get("safe_shutdown_delay")
        if self.low_since is None:
            self.low_since = now
            self._low_notice_at = now
            log.warning("Battery at %.0f %% (below %s %%): shutting down in %s s unless "
                        "power is connected", level, threshold, delay)
            self.on_event({"event": power.LOW_BATTERY, "level": round(level),
                           "seconds_left": delay})
            self._emit_state(force=True)
        left = delay - (now - self.low_since)
        if left <= 0:
            self.request_shutdown(reason="battery")
            return
        interval = 1.0 if left <= 10 else 5.0
        if now - self._low_notice_at >= interval:
            self._low_notice_at = now
            self.on_event({"event": power.LOW_BATTERY, "level": round(level),
                           "seconds_left": math.ceil(left)})

    def _charging_range(self, now: float) -> None:
        span = self.config.get("charging_range")
        chip = self.chip
        if (not span or chip is None or base.CHARGING_CONTROL not in chip.features
                or chip.key == "pisugar3"):
            return
        level = self.level()
        if level is None:
            return
        start, stop = span
        allowed = chip.get_allow_charging()
        if level < start and not allowed:
            self._full_at = None
            chip.set_allow_charging(True)
            log.info("Battery %.0f %% < %s %%: charging on", level, start)
        elif allowed and (level >= stop or level >= 99.9):
            if self._full_at is None:
                self._full_at = now
            elif now - self._full_at > self.config.get("full_charge_duration"):
                chip.set_allow_charging(False)
                log.info("Battery %.0f %% >= %s %%: charging off", level, stop)

    # ================================================================ shutdown
    def request_shutdown(self, reboot: bool = False, reason: str = "request") -> None:
        if self.shutting_down:
            return
        self.shutting_down = reason
        self._shutdown_retry_at = None
        self.low_since = None
        log.warning("%s (reason: %s)", "Rebooting" if reboot else "Powering off", reason)
        self.on_event({"event": power.SHUTTING_DOWN, "reason": reason, "reboot": reboot})
        self._emit_state(force=True)

        def done(code: int, output: str) -> None:
            if code == 0:
                return
            log.error("Could not %s: %s", "reboot" if reboot else "power off", output or code)
            self.on_event({"event": power.SHUTDOWN_FAILED,
                           "error": output or f"exit status {code}"})
            self.shutting_down = ""
            if reason == "battery":
                self._shutdown_retry_at = self.monotonic() + SHUTDOWN_RETRY_SEC
            self._emit_state(force=True)
        self.runner.run(power_command(reboot), done)

    def _retry_shutdown(self, now: float) -> None:
        if self._shutdown_retry_at is not None and now >= self._shutdown_retry_at:
            self._shutdown_retry_at = None
            self.request_shutdown(reason="battery")

    # ================================================================ clock
    def _rtc_check(self, now: float) -> None:
        rtc = self.chip.rtc if self.chip else None
        if rtc is None:
            return
        if self.config.get("wake_time"):
            self._apply_wake_alarm(report=False)   # follows daylight-saving changes
        if not self.config.get("rtc_sync"):
            return
        if self.ntp_synced():
            self.save_clock()
            return
        if self._clock_checked:
            return
        self._clock_checked = True
        board = rtc.read_time()
        system = self.wallclock()
        if board.year < RTC_MIN_YEAR:
            log.info("Battery board clock not set (%s); left alone", board.isoformat())
            return
        ahead = (board - system).total_seconds()
        if ahead > RTC_SET_MARGIN_SEC:
            try:
                self.set_clock(board)
                log.info("System clock set from the battery board: %s (was %.0f s behind)",
                         board.isoformat(), ahead)
            except OSError as exc:
                log.warning("Could not set the system clock from the battery board: %s", exc)

    def save_clock(self) -> str:
        """Write the system time to the board's clock. Returns the time written."""
        rtc = self.chip.rtc if self.chip else None
        if rtc is None:
            raise Unsupported("this board has no clock")
        when = self.wallclock().astimezone(_dt.timezone.utc).replace(microsecond=0)
        rtc.write_time(when)
        self._rtc_written_at = self.monotonic()
        log.info("Battery board clock set to %s", when.isoformat())
        return when.isoformat()

    def load_clock(self) -> str:
        """Set the system clock from the board's clock (any direction)."""
        rtc = self.chip.rtc if self.chip else None
        if rtc is None:
            raise Unsupported("this board has no clock")
        board = rtc.read_time()
        if board.year < RTC_MIN_YEAR:
            raise ValueError(f"the board's clock is not set ({board.isoformat()})")
        self.set_clock(board)
        log.info("System clock set from the battery board: %s", board.isoformat())
        return board.isoformat()

    def _apply_wake_alarm(self, report: bool = True) -> None:
        rtc = self.chip.rtc if self.chip else None
        if rtc is None:
            if report and self.config.get("wake_time"):
                raise Unsupported("this board has no clock for a wake alarm")
            return
        wake = self.config.get("wake_time")
        try:
            if not wake:
                rtc.disable_alarm()
                return
            if self.config.get("power_restore"):
                raise Invalid("turn off 'Power on when plugged in' to use a wake alarm")
            hour, minute = (int(part) for part in wake.split(":"))
            utc_hour, utc_minute, days = local_to_utc_alarm(hour, minute,
                                                             self.config.get("wake_days"),
                                                             self.wallclock())
            rtc.set_alarm(utc_hour, utc_minute, 0, days)
            log.info("Wake alarm %s local (%02d:%02d UTC, days 0x%02x)", wake, utc_hour,
                     utc_minute, days)
        except Invalid:
            if report:
                raise
            log.warning("Wake alarm not set: 'power on when plugged in' is on")

    # ================================================================ settings
    def chip_settings(self) -> dict:
        """Board settings as the board reports them (I2C reads)."""
        result = {}
        if self.chip is None:
            return result
        getters = {"power_restore": self.chip.get_power_restore,
                   "soft_poweroff": self.chip.get_soft_poweroff,
                   "anti_mistouch": self.chip.get_anti_mistouch,
                   "battery_protect": self.chip.get_battery_protect,
                   "allow_charging": self.chip.get_allow_charging}
        for key, getter in getters.items():
            try:
                result[key] = getter()
            except Unsupported:
                continue
        return result

    def set_option(self, key: str, value) -> None:
        """Validate, apply to the board where needed, then save.

        Raises KeyError, Invalid (bad value), Unsupported or OSError; on a
        board failure nothing is saved.
        """
        if key not in SCHEMA:
            raise KeyError(key)
        value = SCHEMA[key][1](value)
        if key in CHIP_KEYS and value is not None:
            if self.chip is None:
                raise Unsupported("no battery board")
            setter = {"power_restore": self.chip.set_power_restore,
                      "soft_poweroff": self.chip.set_soft_poweroff,
                      "anti_mistouch": self.chip.set_anti_mistouch,
                      "battery_protect": self.chip.set_battery_protect}[key]
            if key == "power_restore" and value and self.config.get("wake_time"):
                raise Invalid("turn off the wake alarm to use 'Power on when plugged in'")
            setter(bool(value))
        if key == "charging_range" and value is not None:
            if self.chip is None or base.CHARGING_CONTROL not in self.chip.features \
                    or self.chip.key == "pisugar3":
                raise Unsupported("this board cannot switch charging by level")
        previous = self.config.get(key)
        changed = self.config.set(key, value, save=False)
        if key in ("wake_time", "wake_days"):
            try:
                self._apply_wake_alarm(report=True)
            except Exception:
                self.config.set(key, previous, save=False)
                raise
        if key == "charging_range" and value is None and self.chip is not None \
                and base.CHARGING_CONTROL in self.chip.features and self.chip.key != "pisugar3":
            self.chip.set_allow_charging(True)
        if changed:
            self.config.save()
            self.on_event({"event": power.CONFIG, "config": self.public_config()})
        if key in ("model", "i2c_bus", "i2c_address"):
            self._probe_attempt = 0
            self.probe()
        elif key in ("safe_shutdown_level", "safe_shutdown_delay") and self.chip is not None:
            self._low_battery(self.monotonic())

    def public_config(self) -> dict:
        data = self.config.as_dict()
        data.pop("schema", None)
        return data

    # ================================================================ status
    def status(self, details: bool = False) -> dict:
        view = self.view()
        sample = self.sample
        volts, amps = self.voltage(), self.current()
        result = dict(view)
        result.update({
            "key": self.chip.key if self.chip else "",
            "firmware": self.chip.firmware() if self.chip else "",
            "features": sorted(self.chip.features) if self.chip else [],
            "bus": self.chip.bus_number if self.chip else self.config.get("i2c_bus"),
            "level_exact": round(self.level(), 1) if self.level() is not None else None,
            "voltage": round(volts, 3) if volts is not None else None,
            "current": round(amps, 3) if amps is not None else None,
            "allow_charging": sample.allow_charging if sample else None,
            "temperature": sample.temperature if sample else None,
            "config": self.public_config(),
        })
        if details and self.chip is not None:
            try:
                result["board"] = self.chip_settings()
                if self.chip.rtc is not None:
                    alarm = self.chip.rtc.read_alarm()
                    result["clock"] = {"board_time": self.chip.rtc.read_time().isoformat(),
                                       "alarm_enabled": alarm.enabled}
            except OSError as exc:
                result["board_error"] = str(exc)
        return result
