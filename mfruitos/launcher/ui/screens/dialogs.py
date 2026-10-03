"""Reusable dialog screens."""

from __future__ import annotations

import re
from typing import Callable

from mfruitos.launcher.ui.components import (LIST_BOTTOM, LIST_TOP, ROW_H, Item, back_item,
                                             draw_list)
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.screens.base import ListScreen, Screen
from mfruitos.launcher.ui.theme import MARGIN, SCREEN_W
from mfruitos.logs import tail


class MessageScreen(ListScreen):
    """Title, wrapped message text, then a short list of actions."""

    def __init__(self, os, title: str, message: str, actions: list[Item] | None = None,
                 tone: str = "", icon: str = "", page: str = ""):
        super().__init__(os)
        # A short page label goes in the status bar; the full title becomes a heading.
        self.title = page or title
        self.heading = title if page else ""
        self.message = message
        self.actions = actions if actions is not None else [Item("OK", kind="back", icon="check")]
        self.tone = tone
        self.icon = icon

    def items(self) -> list[Item]:
        return self.actions

    def draw(self, p: Painter) -> None:
        t = p.theme
        items = self.current_items()
        list_top = max(LIST_TOP + 20, LIST_BOTTOM - ROW_H * len(items))
        x = MARGIN + 2
        y = LIST_TOP + 2
        color = {"error": t.error, "warning": t.warning, "success": t.success}.get(self.tone, t.text)
        if self.heading:
            for line in p.wrap(self.heading, 16, "bold", SCREEN_W - 2 * MARGIN - 4, 2):
                p.text(x, y, line, 16, "bold", t.text)
                y += 21
            y += 4
        if self.icon:
            p.icon(self.icon, x, y + 1, 18, color)
            x += 26
        room = max(1, (list_top - y - 6) // 18)
        for line in p.wrap(self.message, 14, "regular", SCREEN_W - MARGIN - 2 - x, room):
            p.text(x, y, line, 14, "regular", t.text if not line.startswith("  ") else t.text_muted)
            y += 18
        draw_list(p, items, self.selected, top=list_top)


def confirm(os, title: str, message: str, confirm_label: str, on_confirm: Callable[[], None],
            danger: bool = True, cancel_label: str = "Cancel") -> MessageScreen:
    """Ask before acting. The safe choice is first, so a stray select cancels."""
    def accept():
        os.pop()
        on_confirm()
    actions = [Item(cancel_label, kind="back", icon="back"),
               Item(confirm_label, accept, kind="danger" if danger else "action",
                    icon="trash" if danger else "check")]
    return MessageScreen(os, title, message, actions, tone="warning" if danger else "",
                         page="Confirm")


class ChoiceScreen(ListScreen):
    def __init__(self, os, title: str, options: list[tuple[object, str]], current,
                 on_choose: Callable[[object], None]):
        super().__init__(os)
        self.title = title
        self.options = options
        self.current = current
        self.on_choose = on_choose
        for index, (value, _) in enumerate(options):
            if value == current:
                self.selected = index

    def items(self) -> list[Item]:
        rows = []
        for value, label in self.options:
            rows.append(Item(label, lambda v=value: self._choose(v),
                             icon="check" if value == self.current else "dot",
                             tone="accent" if value == self.current else None))
        rows.append(back_item())
        return rows

    def _choose(self, value) -> None:
        try:
            self.on_choose(value)
        except ValueError as exc:  # settings validation (e.g. gesture lock-out)
            self.os.toast(str(exc)[:40], "error")
            return
        self.os.pop()


class RangeScreen(Screen):
    """Adjust a number: next = +step, previous = -step, select = save, back = cancel."""

    select_label = "save"

    def __init__(self, os, title: str, value: int, low: int, high: int, step: int, unit: str,
                 on_change: Callable[[int], None], on_save: Callable[[int], None]):
        super().__init__(os)
        self.title = title
        self.value = self.original = value
        self.low, self.high, self.step, self.unit = low, high, step, unit
        self.on_change = on_change
        self.on_save = on_save

    def handle(self, action: str) -> bool:
        if action in ("next", "previous"):
            delta = self.step if action == "next" else -self.step
            new = max(self.low, min(self.high, self.value + delta))
            if new == self.value and action == "next" and self.value == self.high:
                new = self.low  # wrap around so one direction is enough
            self.value = new
            self.on_change(new)
            self.redraw()
            return True
        if action == "select":
            self.on_save(self.value)
            self.os.pop()
            return True
        if action in ("back", "home"):
            self.on_change(self.original)
            return False
        return False

    def draw(self, p: Painter) -> None:
        t = p.theme
        p.text(SCREEN_W // 2, 96, f"{self.value}{self.unit}", 44, "bold", t.text, anchor="mm")
        fraction = (self.value - self.low) / max(1, self.high - self.low)
        p.progress((MARGIN + 6, 142, SCREEN_W - MARGIN - 6, 154), fraction)
        p.text(SCREEN_W // 2, 180, "tap +  ·  2× −", 13, "medium", t.text_muted, anchor="mm")
        p.text(SCREEN_W // 2, 200, "hold to save  ·  4× cancel", 12, "regular", t.text_faint,
               anchor="mm")


class ProgressScreen(ListScreen):
    """Shows a long-running job (install, update, check) step by step."""

    def __init__(self, os, title: str, steps: list[tuple[str, str]], page: str = "Update"):
        super().__init__(os)
        self.title = page
        self.heading = title
        self.steps = steps                  # [(key, label)]
        self.state: dict[str, str] = {}     # key -> running | done | failed
        self.detail = ""
        self.fraction: float | None = None
        self.running = True
        self.result_text = ""
        self.result_tone = ""
        self.log_path = ""
        self.on_done: Callable[[], None] | None = None
        self.phase = 0
        self._timer = None

    @property
    def modal(self) -> bool:
        return self.running

    def on_show(self) -> None:
        self._tick()

    def on_hide(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _tick(self) -> None:
        self._timer = None
        if self.running and self.os.settings.get("display.animation") == "minimal":
            self.phase += 1
            self.redraw()
            self._timer = self.os.loop.call_later(0.25, self._tick)

    def update(self, step: str, detail: str, fraction: float | None) -> None:
        keys = [k for k, _ in self.steps]
        if step in keys:
            index = keys.index(step)
            for key in keys[:index]:
                self.state[key] = "done"
            self.state[step] = "running"
        self.detail = detail
        self.fraction = fraction
        self.redraw()

    def finish(self, ok: bool, text: str, log_path: str = "") -> None:
        self.running = False
        self.result_text = text
        self.result_tone = "success" if ok else "error"
        self.log_path = log_path
        for key, _ in self.steps:
            if ok:
                self.state[key] = "done"
            elif self.state.get(key) == "running":
                self.state[key] = "failed"
        self.selected = 0
        self.redraw()

    def items(self) -> list[Item]:
        if self.running:
            return []
        rows = [Item("Done", self._close, icon="check")]
        if self.log_path:
            rows.append(Item("View log", lambda: self.os.push(
                LogScreen(self.os, "Log", self.log_path)), kind="nav", icon="list"))
        return rows

    def _close(self) -> None:
        self.os.pop()
        if self.on_done:
            self.on_done()

    def handle(self, action: str) -> bool:
        if self.running:
            if action in ("back", "home"):
                self.os.toast("Please wait…")
            return True
        if action in ("back", "home"):
            self._close()
            return True
        return super().handle(action)

    def draw(self, p: Painter) -> None:
        t = p.theme
        p.text(MARGIN + 2, LIST_TOP, self.heading, 16, "bold", t.text,
               max_width=SCREEN_W - 2 * MARGIN - 4)
        if not self.running:
            self._draw_result(p)
            return
        y = LIST_TOP + 26
        compact = len(self.steps) > 5
        step_h = 17 if compact else 21
        for key, label in self.steps:
            state = self.state.get(key, "pending")
            color = {"done": t.success, "failed": t.error, "running": t.accent}.get(state, t.text_faint)
            if state == "done":
                p.icon("check", MARGIN + 4, y, 13, color)
            elif state == "failed":
                p.icon("cross", MARGIN + 4, y, 13, color)
            elif state == "running" and self.running:
                p.spinner(MARGIN + 10, y + 7, 5, self.phase, color)
            else:
                p.draw.ellipse((MARGIN + 7, y + 4, MARGIN + 13, y + 10), fill=color)
            p.text(MARGIN + 24, y - 1, label, 13, "semibold" if state == "running" else "medium",
                   t.text if state != "pending" else t.text_faint)
            y += step_h
        y += 4
        if self.fraction is not None:
            p.progress((MARGIN + 4, y + 2, SCREEN_W - MARGIN - 4, y + 8), self.fraction)
            y += 14
        p.text(MARGIN + 4, y, self.detail, 12, "regular", t.text_muted,
               max_width=SCREEN_W - 2 * MARGIN - 8)

    def _draw_result(self, p: Painter) -> None:
        t = p.theme
        ok = self.result_tone == "success"
        color = t.success if ok else t.error
        top = LIST_TOP + 28
        p.icon("check" if ok else "cross", MARGIN + 2, top + 2, 20, color)
        failed = next((label for key, label in self.steps if self.state.get(key) == "failed"), "")
        p.text(MARGIN + 30, top + 3, "Done" if ok else f"Failed at {failed or 'start'}",
               15, "bold", color)
        items = self.current_items()
        list_top = LIST_BOTTOM - ROW_H * len(items)
        y = top + 30
        room = max(1, (list_top - y - 4) // 17)
        for line in p.wrap(self.result_text, 13, "medium", SCREEN_W - 2 * MARGIN - 8, room):
            p.text(MARGIN + 4, y, line, 13, "medium", t.text)
            y += 17
        draw_list(p, items, self.selected, top=list_top)

    def footer(self, p: Painter) -> None:
        if self.running:
            from mfruitos.launcher.ui.components import FOOTER_Y
            p.text(SCREEN_W // 2, FOOTER_Y, "Working — please keep the device on", 11, "regular",
                   p.theme.text_faint, anchor="ma")
            return
        super().footer(p)


_LOG_PREFIX = re.compile(r"^\d{4}-\d\d-\d\d[ T](\d\d:\d\d)(?::\d\d(?:[,.]\d+)?)?\s+")


class LogScreen(Screen):
    """Read-only tail of a log file. tap = page down, 2× = page up, hold = close."""

    select_label = "close"
    LINE_H = 14

    def __init__(self, os, title: str, path: str):
        super().__init__(os)
        self.title = title
        self.path = path
        self.lines: list[str] = []
        self.top = 0
        self._wrapped_for = None

    def on_show(self) -> None:
        self.raw = tail(self.path, max_lines=120) or ["(log is empty)"]
        self._wrapped_for = None

    def _wrap(self, p: Painter) -> list[str]:
        if self._wrapped_for is None:
            wrapped = []
            for line in self.raw:
                # "2026-09-29 17:42:10,123 INFO mfruitos.x: msg" -> "17:42 INFO x: msg"
                line = _LOG_PREFIX.sub(r"\1 ", line.replace("\t", "  "))
                line = line.replace("mfruitos.", "")
                wrapped.extend(p.wrap(line, 11, "regular", SCREEN_W - 2 * MARGIN) or [""])
            self.lines = wrapped
            self._wrapped_for = True
            self.top = max(0, len(wrapped) - self.page)
        return self.lines

    @property
    def page(self) -> int:
        return (LIST_BOTTOM - LIST_TOP) // self.LINE_H

    def handle(self, action: str) -> bool:
        if action == "next":
            self.top = min(max(0, len(self.lines) - self.page), self.top + self.page - 1)
        elif action == "previous":
            self.top = max(0, self.top - self.page + 1)
        elif action == "select":
            self.os.pop()
            return True
        else:
            return False
        self.redraw()
        return True

    def draw(self, p: Painter) -> None:
        t = p.theme
        lines = self._wrap(p)
        y = LIST_TOP
        for line in lines[self.top:self.top + self.page]:
            color = t.error if "ERROR" in line or "Traceback" in line else (
                t.warning if "WARN" in line else t.text_muted)
            p.text(MARGIN, y, line, 11, "regular", color)
            y += self.LINE_H


class LoadingScreen(Screen):
    """"Opening <app>" — the last frame MFruit OS draws before an app starts.

    With Whisplay's user interface in the background (whisplay-daemon-mfruit.py)
    the daemon keeps this frame on the LCD until the app draws its own, so the
    user never sees the daemon's desktop while an app starts up. It is static:
    MFruit OS no longer owns the screen once the app is starting.
    """

    show_status = True

    def __init__(self, os, app_id: str, name: str, icon_text: str = "", icon_path: str = ""):
        super().__init__(os)
        self.title = ""
        self.app_id = app_id
        self.name = name
        self.icon_text = icon_text
        self.icon_path = icon_path

    def handle(self, action: str) -> bool:
        return True

    def footer(self, p: Painter) -> None:
        pass

    def draw(self, p: Painter) -> None:
        t = p.theme
        size = 76
        p.app_icon(self.app_id, self.icon_text or self.name[:2], self.icon_path,
                   (SCREEN_W - size) // 2, 70, size)
        p.text(SCREEN_W // 2, 168, self.name, 20, "bold", t.text, anchor="ma",
               max_width=SCREEN_W - 2 * MARGIN)
        p.text(SCREEN_W // 2, 198, "Opening…", 14, "medium", t.text_muted, anchor="ma")
