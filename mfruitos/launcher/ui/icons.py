"""Simple vector icons drawn with Pillow primitives.

Each icon is drawn once at 4x into an 8-bit mask, downsampled for
anti-aliasing and cached; painting an icon is then a single paste.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw

SUPERSAMPLE = 4
_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


class _Pen:
    """Normalised (0..1) drawing helpers on a square supersampled canvas."""

    def __init__(self, size: int, weight: float = 0.09):
        self.s = size
        self.img = Image.new("L", (size, size), 0)
        self.d = ImageDraw.Draw(self.img)
        self.w = max(1, int(size * weight))

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.s, y * self.s)

    def box(self, x0, y0, x1, y1):
        return [x0 * self.s, y0 * self.s, x1 * self.s, y1 * self.s]

    def line(self, *points, width=None):
        pts = [self.p(x, y) for x, y in points]
        w = width or self.w
        self.d.line(pts, fill=255, width=w, joint="curve")
        for x, y in (pts[0], pts[-1]):  # round caps
            r = w / 2
            self.d.ellipse([x - r, y - r, x + r, y + r], fill=255)

    def circle(self, cx, cy, r, fill=False, width=None):
        box = self.box(cx - r, cy - r, cx + r, cy + r)
        if fill:
            self.d.ellipse(box, fill=255)
        else:
            self.d.ellipse(box, outline=255, width=width or self.w)

    def arc(self, cx, cy, r, start, end, width=None):
        self.d.arc(self.box(cx - r, cy - r, cx + r, cy + r), start, end, fill=255,
                   width=width or self.w)

    def rrect(self, x0, y0, x1, y1, radius, fill=False, width=None):
        box = self.box(x0, y0, x1, y1)
        if fill:
            self.d.rounded_rectangle(box, radius=radius * self.s, fill=255)
        else:
            self.d.rounded_rectangle(box, radius=radius * self.s, outline=255,
                                     width=width or self.w)

    def poly(self, *points, erase=False):
        self.d.polygon([self.p(x, y) for x, y in points], fill=0 if erase else 255)


def _gear(p: _Pen):
    teeth = 8
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        c, s = math.cos(a), math.sin(a)
        p.line((0.5 + 0.30 * c, 0.5 + 0.30 * s), (0.5 + 0.42 * c, 0.5 + 0.42 * s), width=int(p.s * 0.13))
    p.circle(0.5, 0.5, 0.29, width=int(p.s * 0.1))
    p.circle(0.5, 0.5, 0.11)


def _download(p: _Pen):
    p.line((0.5, 0.14), (0.5, 0.62))
    p.line((0.3, 0.44), (0.5, 0.64), (0.7, 0.44))
    p.line((0.16, 0.66), (0.16, 0.84), (0.84, 0.84), (0.84, 0.66))


def _refresh(p: _Pen):
    p.arc(0.5, 0.5, 0.32, 200, 520 - 30)
    p.poly((0.62, 0.08), (0.86, 0.2), (0.64, 0.34))


def _wifi(p: _Pen):
    for r in (0.42, 0.28, 0.14):
        p.arc(0.5, 0.78, r, 225, 315)
    p.circle(0.5, 0.78, 0.06, fill=True)


def _bluetooth(p: _Pen):
    p.line((0.3, 0.3), (0.68, 0.64), (0.5, 0.82), (0.5, 0.18), (0.68, 0.36), (0.3, 0.7))


def _speaker(p: _Pen):
    p.poly((0.14, 0.38), (0.3, 0.38), (0.5, 0.2), (0.5, 0.8), (0.3, 0.62), (0.14, 0.62))
    p.arc(0.52, 0.5, 0.16, -50, 50)
    p.arc(0.52, 0.5, 0.3, -50, 50)


def _power(p: _Pen):
    p.arc(0.5, 0.54, 0.32, -60, 240)
    p.line((0.5, 0.14), (0.5, 0.48))


def _chip(p: _Pen):
    p.rrect(0.26, 0.26, 0.74, 0.74, 0.06)
    p.rrect(0.4, 0.4, 0.6, 0.6, 0.02, fill=True)
    for t in (0.36, 0.5, 0.64):
        p.line((t, 0.1), (t, 0.24), width=int(p.s * 0.06))
        p.line((t, 0.76), (t, 0.9), width=int(p.s * 0.06))
        p.line((0.1, t), (0.24, t), width=int(p.s * 0.06))
        p.line((0.76, t), (0.9, t), width=int(p.s * 0.06))


def _pulse(p: _Pen):
    p.line((0.08, 0.54), (0.3, 0.54), (0.4, 0.3), (0.56, 0.76), (0.66, 0.48), (0.92, 0.48))


def _code(p: _Pen):
    p.line((0.34, 0.26), (0.12, 0.5), (0.34, 0.74))
    p.line((0.66, 0.26), (0.88, 0.5), (0.66, 0.74))
    p.line((0.56, 0.2), (0.44, 0.8), width=int(p.s * 0.07))


def _info(p: _Pen):
    p.circle(0.5, 0.5, 0.38)
    p.line((0.5, 0.46), (0.5, 0.7))
    p.circle(0.5, 0.31, 0.055, fill=True)


def _grid(p: _Pen):
    for x in (0.16, 0.56):
        for y in (0.16, 0.56):
            p.rrect(x, y, x + 0.28, y + 0.28, 0.07, fill=True)


def _sun(p: _Pen):
    p.circle(0.5, 0.5, 0.16, fill=True)
    for i in range(8):
        a = 2 * math.pi * i / 8
        p.line((0.5 + 0.28 * math.cos(a), 0.5 + 0.28 * math.sin(a)),
               (0.5 + 0.4 * math.cos(a), 0.5 + 0.4 * math.sin(a)), width=int(p.s * 0.07))


def _button(p: _Pen):
    p.circle(0.5, 0.5, 0.38)
    p.circle(0.5, 0.5, 0.18, fill=True)


def _bulb(p: _Pen):
    p.circle(0.5, 0.4, 0.26)
    p.line((0.4, 0.74), (0.6, 0.74))
    p.line((0.43, 0.86), (0.57, 0.86))


def _globe(p: _Pen):
    p.circle(0.5, 0.5, 0.38)
    p.d.ellipse(p.box(0.34, 0.12, 0.66, 0.88), outline=255, width=int(p.s * 0.06))
    p.line((0.14, 0.5), (0.86, 0.5), width=int(p.s * 0.06))


def _check(p: _Pen):
    p.line((0.2, 0.52), (0.42, 0.72), (0.8, 0.3), width=int(p.s * 0.12))


def _cross(p: _Pen):
    p.line((0.26, 0.26), (0.74, 0.74), width=int(p.s * 0.12))
    p.line((0.74, 0.26), (0.26, 0.74), width=int(p.s * 0.12))


def _arrow_up(p: _Pen):
    p.line((0.5, 0.82), (0.5, 0.2), width=int(p.s * 0.11))
    p.line((0.24, 0.44), (0.5, 0.18), (0.76, 0.44), width=int(p.s * 0.11))


def _arrow_down(p: _Pen):
    p.line((0.5, 0.18), (0.5, 0.8), width=int(p.s * 0.11))
    p.line((0.24, 0.56), (0.5, 0.82), (0.76, 0.56), width=int(p.s * 0.11))


def _chevron(p: _Pen):
    p.line((0.36, 0.2), (0.66, 0.5), (0.36, 0.8), width=int(p.s * 0.11))


def _back(p: _Pen):
    p.line((0.62, 0.2), (0.32, 0.5), (0.62, 0.8), width=int(p.s * 0.11))


def _trash(p: _Pen):
    p.line((0.16, 0.26), (0.84, 0.26))
    p.line((0.4, 0.26), (0.42, 0.14), (0.58, 0.14), (0.6, 0.26))
    p.line((0.26, 0.3), (0.32, 0.86), (0.68, 0.86), (0.74, 0.3))


def _play(p: _Pen):
    p.poly((0.3, 0.18), (0.82, 0.5), (0.3, 0.82))


def _stop(p: _Pen):
    p.rrect(0.24, 0.24, 0.76, 0.76, 0.08, fill=True)


def _bolt(p: _Pen):
    p.poly((0.58, 0.06), (0.22, 0.56), (0.48, 0.56), (0.4, 0.94), (0.78, 0.42), (0.52, 0.42))


def _warning(p: _Pen):
    p.poly((0.5, 0.1), (0.94, 0.86), (0.06, 0.86))
    p.poly((0.46, 0.36), (0.54, 0.36), (0.53, 0.62), (0.47, 0.62), erase=True)
    p.d.ellipse(p.box(0.455, 0.68, 0.545, 0.77), fill=0)


def _box(p: _Pen):
    p.poly((0.5, 0.12), (0.88, 0.3), (0.5, 0.48), (0.12, 0.3))
    p.line((0.12, 0.36), (0.12, 0.72), (0.5, 0.9), (0.88, 0.72), (0.88, 0.36))
    p.line((0.5, 0.52), (0.5, 0.88))


def _search(p: _Pen):
    p.circle(0.43, 0.43, 0.25)
    p.line((0.62, 0.62), (0.86, 0.86), width=int(p.s * 0.12))


def _rollback(p: _Pen):
    p.arc(0.5, 0.5, 0.32, 20, 300)
    p.poly((0.1, 0.2), (0.36, 0.14), (0.26, 0.4))


def _list(p: _Pen):
    for y in (0.26, 0.5, 0.74):
        p.circle(0.18, y, 0.06, fill=True)
        p.line((0.34, y), (0.86, y), width=int(p.s * 0.08))


def _lock(p: _Pen):
    p.rrect(0.2, 0.44, 0.8, 0.88, 0.08, fill=True)
    p.arc(0.5, 0.44, 0.2, 180, 360)
    p.line((0.3, 0.44), (0.3, 0.5))
    p.line((0.7, 0.44), (0.7, 0.5))


def _battery(p: _Pen):
    p.rrect(0.08, 0.3, 0.8, 0.7, 0.07)
    p.rrect(0.82, 0.42, 0.92, 0.58, 0.02, fill=True)
    p.rrect(0.16, 0.38, 0.56, 0.62, 0.03, fill=True)


def _dot(p: _Pen):
    p.circle(0.5, 0.5, 0.3, fill=True)


ICONS = {
    "settings": _gear, "updater": _download, "download": _download, "refresh": _refresh,
    "wifi": _wifi, "bluetooth": _bluetooth, "volume": _speaker, "audio": _speaker,
    "power": _power, "system": _chip, "diagnostics": _pulse, "developer": _code,
    "info": _info, "apps": _grid, "display": _sun, "button": _button, "led": _bulb,
    "network": _globe, "check": _check, "cross": _cross, "up": _arrow_up,
    "down": _arrow_down, "chevron": _chevron, "back": _back, "trash": _trash,
    "play": _play, "stop": _stop, "bolt": _bolt, "warning": _warning, "package": _box,
    "search": _search, "rollback": _rollback, "list": _list, "lock": _lock, "dot": _dot,
    "battery": _battery,
}


@lru_cache(maxsize=256)
def icon_mask(name: str, size: int) -> Image.Image:
    """8-bit alpha mask of ``name`` at ``size`` px (unknown names draw a dot)."""
    pen = _Pen(size * SUPERSAMPLE)
    ICONS.get(name, _dot)(pen)
    return pen.img.resize((size, size), _LANCZOS)


def has_icon(name: str) -> bool:
    return name in ICONS
