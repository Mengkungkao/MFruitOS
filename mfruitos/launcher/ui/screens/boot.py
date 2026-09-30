"""Boot screen: real startup steps, no artificial delay."""

from __future__ import annotations

import logging
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.screens.base import Screen
from mfruitos.launcher.ui.theme import DARK, SCREEN_H, SCREEN_W

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
        logging.getLogger("mfruitos.boot").info("%s: %s", self.steps[index][0], state)
        self.redraw()

    def handle(self, action: str) -> bool:
        return True  # input is ignored while booting

    def footer(self, p: Painter) -> None:
        pass

    def draw(self, p: Painter) -> None:
        p.rect((0, 0, SCREEN_W, SCREEN_H), DARK.bg)
        draw_logo(p, SCREEN_W // 2, SCREEN_H // 2, 64)
