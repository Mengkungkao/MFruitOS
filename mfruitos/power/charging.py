"""Charging, judged from the battery voltage alone.

Some boards cannot tell whether external power is connected: the PiSugar 2
with four LEDs, and a PiSugar 2 whose LED count is not configured. For them
the power service has only the battery voltage to go on.

The first rule tried (PiSugar's own: "the oldest of the last 30 one-second
samples is below their mean, and the newest is above it") reacts to noise.
On battery the voltage moves by a few millivolts from sample to sample, and
it dips while the system works harder (a radio transmitting, the CPU busy)
and comes back up when the work ends. Each recovery looks like a rising
voltage, so a discharging board was reported as charging every now and then.
A false "charging" also cancels the low-battery countdown, which then starts
again from the beginning, so the safe shutdown could be put off until the
battery died.

This judge is built from what charging actually does to the voltage:

* **Plugging in is a step up.** The battery stops supplying the load and
  starts taking the charge current, so its voltage jumps by the change in
  current times its internal resistance: about a tenth of a volt or more.
  Load changes on a small board move it by a few tens of millivolts. A step
  of STEP_VOLTS between the last whole minute's mean and the mean of the
  newest RECENT_SAMPLES samples therefore means "charging"; the same step
  down means "unplugged".
* **Charging keeps the voltage rising for minutes.** If the board starts
  already plugged in there is no step to see, so charging is also judged
  from whole-minute means: RISE_MINUTES successive minutes each higher than
  the one before, by RISE_VOLTS in all. Discharging only ever falls over
  that time; one recovery after heavy work is one rise, not three.
* **It ends when the voltage falls.** Once charging, the judgement stands
  until a minute's mean is FALL_VOLTS below the highest of the recent
  minutes, or a step down. Near full the charger holds the voltage level,
  which keeps the judgement (the charger is still connected).

The thresholds are set from the physics above, not from measurements on a
board; the record lists them as not verified.
"""

from __future__ import annotations

from collections import deque

MINUTE_SEC = 60.0
RECENT_SAMPLES = 10
STEP_VOLTS = 0.10
RISE_MINUTES = 3
RISE_VOLTS = 0.015
FALL_VOLTS = 0.008


class ChargeJudge:
    """Feed it plausible voltage samples; ``charging`` holds the judgement."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.minutes: deque = deque(maxlen=RISE_MINUTES + 1)
        self.recent: deque = deque(maxlen=RECENT_SAMPLES)
        self._sum = 0.0
        self._count = 0
        self._started: float | None = None
        self.charging = False
        self.reason = ""

    def add(self, now: float, volts: float) -> bool:
        """Take one sample at monotonic time ``now``; returns ``charging``."""
        if self._started is None:
            self._started = now
        self.recent.append(volts)
        self._sum += volts
        self._count += 1
        if now - self._started >= MINUTE_SEC:
            self.minutes.append(self._sum / self._count)
            self._sum, self._count, self._started = 0.0, 0, now
            self._judge_minutes()
        self._judge_step()
        return self.charging

    def _set(self, charging: bool, reason: str) -> None:
        self.charging = charging
        self.reason = reason

    def _judge_step(self) -> None:
        if len(self.recent) < RECENT_SAMPLES or not self.minutes:
            return
        change = sum(self.recent) / len(self.recent) - self.minutes[-1]
        if not self.charging and change >= STEP_VOLTS:
            self._set(True, f"voltage stepped up {change * 1000:.0f} mV")
        elif self.charging and change <= -STEP_VOLTS:
            self._set(False, f"voltage stepped down {-change * 1000:.0f} mV")

    def _judge_minutes(self) -> None:
        means = list(self.minutes)
        if self.charging:
            drop = max(means) - means[-1]
            if drop >= FALL_VOLTS:
                self._set(False, f"voltage fell {drop * 1000:.0f} mV")
            return
        if len(means) < RISE_MINUTES + 1:
            return
        rising = all(later > earlier for earlier, later in zip(means, means[1:]))
        rise = means[-1] - means[0]
        if rising and rise >= RISE_VOLTS:
            self._set(True, f"voltage rose {rise * 1000:.0f} mV over {RISE_MINUTES} minutes")
