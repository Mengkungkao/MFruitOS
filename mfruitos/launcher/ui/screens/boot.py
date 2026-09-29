"""Boot screen: real startup steps, no artificial delay."""

from __future__ import annotations

from mfruitos import OS_NAME
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.screens.base import Screen
from mfruitos.launcher.ui.theme import SCREEN_W

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"


def draw_logo(p: Painter, cx: int, cy: int, size: int) -> None:
    """The MFruit mark: an accent tile with a leaf and an 'M'."""
    t = p.theme
    half = size // 2
    p.rounded((cx - half, cy - half, cx + half, cy + half), size // 4, fill=t.accent)
    leaf = size // 5
    p.draw.ellipse((cx + half // 5, cy - half - leaf // 2, cx + half // 5 + leaf, cy - half + leaf // 2),
                   fill=t.success)
    p.text(cx, cy + 2, "M", int(size * 0.55), "bold", (255, 255, 255), anchor="mm")


class BootScreen(Screen):
    show_status = False

    def __init__(self, os, version: str):
        super().__init__(os)
        self.version = version
        self.steps: list[list[str]] = [
            ["Starting system", PENDING],
            ["Checking daemon", PENDING],
            ["Loading configuration", PENDING],
            ["Loading applications", PENDING],
        ]
        self.ready = False

    def set_step(self, index: int, state: str) -> None:
        self.steps[index][1] = state
        self.redraw()

    def handle(self, action: str) -> bool:
        return True  # input is ignored while booting

    def footer(self, p: Painter) -> None:
        pass

    def draw(self, p: Painter) -> None:
        t = p.theme
        draw_logo(p, SCREEN_W // 2, 62, 52)
        p.text(SCREEN_W // 2, 104, OS_NAME, 22, "bold", t.text, anchor="ma")
        p.text(SCREEN_W // 2, 132, f"Version {self.version}", 12, "medium", t.text_muted, anchor="ma")
        y = 162
        for label, state in self.steps:
            color = {DONE: t.success, FAILED: t.error, RUNNING: t.accent}.get(state, t.text_faint)
            if state == DONE:
                p.icon("check", 44, y - 1, 14, color)
            elif state == FAILED:
                p.icon("cross", 44, y - 1, 14, color)
            else:
                p.draw.ellipse((48, y + 3, 55, y + 10), fill=color)
            p.text(66, y, label, 13, "medium", t.text if state != PENDING else t.text_faint)
            y += 21
        if self.ready:
            p.text(SCREEN_W // 2, 256, "Ready", 13, "semibold", t.success, anchor="ma")
