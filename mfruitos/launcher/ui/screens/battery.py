"""Settings > Battery and the low-battery warning.

The screens show the power service's state (``os.power``) and change its
settings through tasks; they never touch the battery board themselves.
"""

from __future__ import annotations

import math
import time

from mfruitos import power
from mfruitos.launcher.ui.components import Item, back_item, section
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import (ChoiceScreen, MessageScreen, RangeScreen,
                                                 confirm)
from mfruitos.power.config import BUTTON_ACTIONS, CHARGING_RANGES, SHUTDOWN_DELAYS, SHUTDOWN_LEVELS

ACTION_LABELS = {"none": "Nothing", "home": "Home", "screen": "Screen on/off",
                 "power_menu": "Power menu"}
EVERY_DAY, WEEKDAYS, WEEKENDS = 0x7F, 0b0111110, 0b1000001
DAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def days_label(mask: int) -> str:
    if mask == EVERY_DAY:
        return "every day"
    if mask == WEEKDAYS:
        return "Mon–Fri"
    if mask == WEEKENDS:
        return "Sat, Sun"
    return ", ".join(name for bit, name in enumerate(DAY_NAMES) if mask & (1 << bit))


def level_label(level: int) -> str:
    return "Off" if level == 0 else f"{level}%"


def status_label(state: dict) -> str:
    if state.get("charging"):
        return "Charging"
    if state.get("plugged"):
        return "Plugged in"
    return "On battery"


class BatteryScreen(ListScreen):
    title = "Battery"

    def __init__(self, os):
        super().__init__(os)
        self.status: dict | None = None
        self.loading = True
        self.problem = ""
        self._refreshing = False

    def on_show(self) -> None:
        self.refresh()

    def on_power_event(self, event: dict) -> None:
        if event.get("event") in (power.STATE, power.CONFIG, "_connected", "_disconnected"):
            self.refresh()

    def refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True

        def done(status):
            self._refreshing = False
            self.status, self.loading, self.problem = status, False, ""
            self.redraw()

        def failed(exc):
            self._refreshing = False
            self.status, self.loading = None, False
            self.problem = ("The power service is not running" if isinstance(exc, OSError)
                            else str(exc)[:80])
            self.redraw()
        self.os.run_task("power-status", lambda: self.os.power.client.status(details=True),
                         done, failed)

    # ------------------------------------------------------------ changes
    def set(self, key: str, value) -> None:
        def failed(exc):
            self.os.toast(str(exc)[:40] or "Not changed", "error")
            self.refresh()
        self.os.run_task("power-set", lambda: self.os.power.client.set(key, value),
                         lambda _config: self.refresh(), failed)

    def _probe(self) -> None:
        self.loading = True
        self.os.run_task("power-probe", self.os.power.client.probe, lambda _s: self.refresh(),
                         lambda exc: self.os.toast(str(exc)[:40], "error"))

    def _save_clock(self) -> None:
        self.os.run_task("power-clock", lambda: self.os.power.client.clock("save"),
                         lambda _t: self.os.toast("Battery clock set"),
                         lambda exc: self.os.toast(str(exc)[:40], "error"))

    def _choice(self, title: str, key: str, options: list) -> None:
        current = (self.status or {}).get("config", {}).get(key)
        self.os.push(ChoiceScreen(self.os, title, options, current,
                                  lambda value: self.set(key, value)))

    # ------------------------------------------------------------ rows
    def items(self) -> list[Item]:
        if self.loading and self.status is None:
            return [Item("Reading the battery…", kind="info", tone="muted"), back_item()]
        if self.status is None:
            return [Item(self.problem or "No answer", kind="info", icon="warning", tone="warning",
                         subtitle="Install it with scripts/install.sh"),
                    Item("Try again", self.refresh, icon="refresh"), back_item()]
        status = self.status
        if not status.get("present"):
            reason = status.get("error") or "No PiSugar found"
            return [Item("No battery board", lambda: self.os.show_message(
                         "No battery board", reason, icon="battery"),
                         kind="nav", icon="battery", subtitle=reason),
                    Item("Look again", self._probe, icon="search"), back_item()]
        config = status.get("config", {})
        board = status.get("board", {})
        features = set(status.get("features", []))
        percent = status.get("level")
        rows = [
            Item("Level", kind="info", icon="battery",
                 value=f"{percent}%" if percent is not None else "—",
                 tone="error" if percent is not None and percent <= 15 else None),
            Item("Status", kind="info", value=status_label(status)),
        ]
        if status.get("voltage") is not None:
            rows.append(Item("Voltage", kind="info", value=f"{status['voltage']:.2f} V"))
        rows.append(Item("Board", kind="info", value=status.get("model", ""),
                         subtitle=f"Firmware {status['firmware']}" if status.get("firmware") else None))
        if status.get("temperature") is not None:
            rows.append(Item("Temperature", kind="info", value=f"{status['temperature']} °C"))
        if status.get("error"):
            rows.append(Item(status["error"], kind="info", icon="warning", tone="warning"))

        level = config.get("safe_shutdown_level", 0)
        rows += [
            section("SAFE SHUTDOWN"),
            Item("Shut down at", lambda: self._choice(
                "Shut down at", "safe_shutdown_level",
                [(v, level_label(v)) for v in SHUTDOWN_LEVELS]),
                kind="nav", value=level_label(level)),
            Item("Countdown", lambda: self._choice(
                "Countdown", "safe_shutdown_delay", [(v, f"{v} sec") for v in SHUTDOWN_DELAYS]),
                kind="nav", value=f"{config.get('safe_shutdown_delay', 30)} sec", enabled=level > 0,
                data={"disabled_reason": "Safe shutdown is off"}),
        ]
        if "taps" in features:
            actions = [(a, ACTION_LABELS[a]) for a in BUTTON_ACTIONS]
            p3 = status.get("key") == "pisugar3"
            rows += [
                section("POWER BUTTON"),
                Item("Double press", lambda: self._choice("Double press", "button_double", actions),
                     kind="nav", value=ACTION_LABELS.get(config.get("button_double"), "Nothing"),
                     enabled=not p3,
                     data={"disabled_reason": "On PiSugar 3 each press returns Home"}),
                Item("Long press", lambda: self._choice("Long press", "button_long", actions),
                     kind="nav", value=ACTION_LABELS.get(config.get("button_long"), "Nothing")),
            ]
        if "soft_poweroff" in features:
            on = bool(board.get("soft_poweroff", config.get("soft_poweroff")))
            rows.append(Item("Hold to shut down safely", lambda on=on: self.set("soft_poweroff", not on),
                             kind="toggle", value=on))
        if "anti_mistouch" in features:
            on = bool(board.get("anti_mistouch", config.get("anti_mistouch")))
            rows.append(Item("Anti-mistouch", lambda on=on: self.set("anti_mistouch", not on),
                             kind="toggle", value=on))
        charging_rows = []
        if "power_restore" in features:
            on = bool(board.get("power_restore", config.get("power_restore")))
            charging_rows.append(Item("Power on when plugged in",
                                      lambda on=on: self.set("power_restore", not on),
                                      kind="toggle", value=on))
        if "battery_protect" in features:
            on = bool(board.get("battery_protect", config.get("battery_protect")))
            charging_rows.append(Item("Battery protection", lambda on=on: self.set("battery_protect", not on),
                                      kind="toggle", value=on,
                                      subtitle="Stops charging early for a longer life"))
        if "charging_control" in features and status.get("key") != "pisugar3":
            span = config.get("charging_range")
            options = [(None, "Off")] + [(list(r), f"{r[0]}–{r[1]}%") for r in CHARGING_RANGES]
            charging_rows.append(Item("Charging range", lambda: self._choice(
                "Charging range", "charging_range", options), kind="nav",
                value=f"{span[0]}–{span[1]}%" if span else "Off"))
        if charging_rows:
            rows += [section("CHARGING")] + charging_rows
        if "rtc" in features:
            wake = config.get("wake_time")
            rows += [
                section("CLOCK"),
                Item("Wake up", lambda: self.os.push(WakeAlarmScreen(self.os, self)), kind="nav",
                     value=f"{wake} {days_label(config.get('wake_days', EVERY_DAY))}" if wake
                     else "Off"),
                Item("Save time to battery clock", self._save_clock, icon="refresh"),
            ]
        rows.append(back_item())
        return rows


class WakeAlarmScreen(ListScreen):
    """Off, or days then hour then minute (local time)."""

    title = "Wake up"

    def __init__(self, os, battery: BatteryScreen):
        super().__init__(os)
        self.battery = battery
        config = (battery.status or {}).get("config", {})
        self.current = config.get("wake_time")
        self.days = config.get("wake_days", EVERY_DAY)

    def items(self) -> list[Item]:
        rows = [Item("Off", self._off, icon="check" if not self.current else "dot")]
        for mask, label in ((EVERY_DAY, "Every day"), (WEEKDAYS, "Weekdays"),
                            (WEEKENDS, "Weekends")):
            chosen = bool(self.current) and self.days == mask
            rows.append(Item(label, lambda m=mask: self._pick_hour(m), kind="nav",
                             icon="check" if chosen else "dot",
                             value=self.current if chosen else None))
        rows.append(back_item())
        return rows

    def _off(self) -> None:
        self.battery.set("wake_time", None)
        self.os.pop()

    def _pick_hour(self, mask: int) -> None:
        hour, minute = (int(x) for x in (self.current or "07:00").split(":"))

        def chose_hour(h):
            self.os.loop.post(lambda: self.os.push(RangeScreen(
                self.os, "Wake minute", minute - minute % 5, 0, 55, 5, "",
                lambda _v: None, lambda m: self._save(mask, h, m))))
        self.os.push(RangeScreen(self.os, "Wake hour", hour, 0, 23, 1, ":00", lambda _v: None,
                                 chose_hour))

    def _save(self, mask: int, hour: int, minute: int) -> None:
        battery = self.battery

        def save():
            battery.os.power.client.set("wake_days", mask)
            return battery.os.power.client.set("wake_time", f"{hour:02d}:{minute:02d}")

        def failed(exc):
            battery.os.toast(str(exc)[:40], "error")
            battery.refresh()
        battery.os.run_task("power-wake", save, lambda _c: battery.refresh(), failed)
        self.os.loop.post(lambda: self.os.pop_to_type(BatteryScreen))


class LowBatteryScreen(MessageScreen):
    """The safe-shutdown countdown, kept current between the service's events."""

    def __init__(self, os, level: int | None, seconds: int):
        self.level = level
        self.deadline = time.monotonic() + seconds
        self._timer = None
        actions = [Item("OK", kind="back", icon="check"),
                   Item("Shut down now", self._now, kind="danger", icon="power")]
        super().__init__(os, "Battery low", self._text(), actions, tone="warning", icon="battery",
                         page="Battery")

    def _text(self) -> str:
        left = max(0, math.ceil(self.deadline - time.monotonic()))
        level = f"{self.level}% left. " if self.level is not None else ""
        return (f"{level}mFruit OS shuts down in {left} s to protect your data. "
                "Connect power to keep going.")

    def update(self, level: int | None, seconds: int) -> None:
        self.level = level
        self.deadline = time.monotonic() + seconds
        self.message = self._text()
        self.redraw()

    def on_show(self) -> None:
        self._tick()

    def on_hide(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _tick(self) -> None:
        self.message = self._text()
        self.redraw()
        self._timer = self.os.loop.call_later(1.0, self._tick)

    def _now(self) -> None:
        self.os.power_shutdown(reboot=False)


class PowerMenuScreen(ListScreen):
    """Lock, restart or shut down through the power service (safe shutdown)."""

    title = "Power"

    def items(self) -> list[Item]:
        os = self.os
        return [
            Item("Lock screen", os.lock_screen, icon="lock"),
            Item("Restart", lambda: os.push(confirm(
                os, "Restart?", "Running apps are closed and the device restarts.", "Restart",
                lambda: os.power_shutdown(reboot=True), danger=False)), icon="refresh"),
            Item("Shut down", lambda: os.push(confirm(
                os, "Shut down?", "Running apps are closed and the device switches off.",
                "Shut down", lambda: os.power_shutdown(reboot=False))), icon="power"),
            back_item(),
        ]
