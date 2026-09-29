"""Turns raw button press/release events into gestures.

whisplay-daemon forwards ``button_pressed`` / ``button_released`` to the
foreground app and leaves interpretation to it (daemon desktop gestures only
apply when no app is foreground). MFruit OS registers with
``exit_gesture: "none"`` so the daemon does not also count quad-clicks on the
OS itself; this recognizer is therefore the only interpreter — no competing
gesture system.

Gestures: single_click, double_click, triple_click, quad_click, long_press.

* long_press fires while the button is still held (at ``long_press_ms``), so
  the user gets immediate feedback; the matching release is swallowed.
* Multi-clicks are resolved after ``click_gap_ms`` of quiet. When double and
  triple clicks are unmapped, single clicks fire immediately on release
  ("eager" mode) and quad_click still fires on the fourth rapid click.
"""

from __future__ import annotations

import time
from typing import Callable

CLICK_GESTURES = {1: "single_click", 2: "double_click", 3: "triple_click", 4: "quad_click"}


class GestureRecognizer:
    def __init__(self, emit: Callable[[str], None],
                 schedule: Callable[[float, Callable], object],
                 clock: Callable[[], float] = time.monotonic):
        self._emit = emit
        self._schedule = schedule
        self._clock = clock
        self.click_gap = 0.3
        self.long_press = 0.7
        self.eager = False
        self._pressed = False
        self._press_id = 0
        self._long_fired = False
        self._clicks = 0
        self._burst_timer = None
        self._long_timer = None

    def configure(self, mapping: dict, click_gap_ms: int, long_press_ms: int) -> None:
        self.click_gap = click_gap_ms / 1000.0
        self.long_press = long_press_ms / 1000.0
        self.eager = (mapping.get("double_click", "none") == "none"
                      and mapping.get("triple_click", "none") == "none")

    @property
    def pressed(self) -> bool:
        return self._pressed

    def reset(self) -> None:
        self._cancel(self._burst_timer)
        self._cancel(self._long_timer)
        self._burst_timer = self._long_timer = None
        self._pressed = False
        self._long_fired = False
        self._clicks = 0

    # -------------------------------------------------------------- input
    def press(self) -> None:
        self._pressed = True
        self._long_fired = False
        self._press_id += 1
        # Wait for this press to finish before resolving the burst.
        self._cancel(self._burst_timer)
        self._burst_timer = None
        self._cancel(self._long_timer)
        press_id = self._press_id
        self._long_timer = self._schedule(self.long_press, lambda: self._on_long(press_id))

    def release(self) -> None:
        if not self._pressed:
            return  # release without press (e.g. after reconnect): ignore
        self._pressed = False
        self._cancel(self._long_timer)
        self._long_timer = None
        if self._long_fired:
            self._long_fired = False
            return
        self._clicks += 1
        if self.eager:
            self._emit("single_click")
        if self._clicks >= 4:
            self._clicks = 0
            self._emit("quad_click")
            return
        self._burst_timer = self._schedule(self.click_gap, self._resolve_burst)

    # ------------------------------------------------------------ timers
    def _on_long(self, press_id: int) -> None:
        if not self._pressed or press_id != self._press_id:
            return
        self._long_fired = True
        self._long_timer = None
        self._flush_burst()
        self._emit("long_press")

    def _resolve_burst(self) -> None:
        self._burst_timer = None
        if self._pressed:
            return
        self._flush_burst()

    def _flush_burst(self) -> None:
        count, self._clicks = self._clicks, 0
        if count == 0 or self.eager:
            return
        self._emit(CLICK_GESTURES[min(count, 4)])

    @staticmethod
    def _cancel(timer) -> None:
        if timer is not None:
            timer.cancel()


def gesture_label(gesture: str) -> str:
    return {"single_click": "tap", "double_click": "2×", "triple_click": "3×",
            "quad_click": "4×", "long_press": "hold"}.get(gesture, gesture)
