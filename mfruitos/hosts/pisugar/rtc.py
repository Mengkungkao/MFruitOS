"""The battery boards' real-time clocks, as the power service sees them.

All times are UTC (the boards keep UTC). Weekday masks use bit 0 for Sunday
through bit 6 for Saturday; 0x7F is every day.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

EVERY_DAY = 0x7F


@dataclass
class Alarm:
    hour: int
    minute: int
    second: int
    weekdays: int          # bit 0 = Sunday ... bit 6 = Saturday
    enabled: bool


class Rtc:
    name = ""

    def read_time(self) -> _dt.datetime:
        raise NotImplementedError

    def write_time(self, when: _dt.datetime) -> None:
        raise NotImplementedError

    def read_alarm(self) -> Alarm:
        raise NotImplementedError

    def set_alarm(self, hour: int, minute: int, second: int, weekdays: int) -> None:
        raise NotImplementedError

    def disable_alarm(self) -> None:
        raise NotImplementedError

    def housekeeping(self) -> None:
        """Slow periodic work (e.g. charging the clock's backup cell)."""


def weekday_sunday0(when: _dt.datetime) -> int:
    """0 = Sunday ... 6 = Saturday."""
    return (when.weekday() + 1) % 7


def utc(when: _dt.datetime) -> _dt.datetime:
    if when.tzinfo is None:
        raise ValueError("naive datetime; give a timezone")
    return when.astimezone(_dt.timezone.utc)


def validate_alarm(hour: int, minute: int, second: int, weekdays: int) -> None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError("alarm time must be HH:MM:SS within a day")
    if not 1 <= weekdays <= EVERY_DAY:
        raise ValueError("choose at least one day for the alarm")


def shift_weekdays(mask: int, days: int) -> int:
    """Rotate a weekday mask by ``days`` (+1: every day moves one later)."""
    days %= 7
    mask &= EVERY_DAY
    return ((mask << days) | (mask >> (7 - days))) & EVERY_DAY


def local_to_utc_alarm(hour: int, minute: int, weekdays: int,
                       now: _dt.datetime | None = None) -> tuple:
    """A local wall-clock alarm as (hour, minute, weekdays) in UTC.

    The boards compare against UTC. When the UTC time falls on the previous
    or next day, the weekday mask moves with it.
    """
    now = now or _dt.datetime.now().astimezone()
    local = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    in_utc = local.astimezone(_dt.timezone.utc)
    day_shift = (in_utc.date() - local.date()).days
    return in_utc.hour, in_utc.minute, shift_weekdays(weekdays, day_shift)
