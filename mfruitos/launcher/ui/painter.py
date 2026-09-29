"""Drawing helpers on a 240x280 frame. Screens draw only through this class."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from PIL import Image, ImageDraw

from mfruitos.launcher.ui.fonts import Fonts
from mfruitos.launcher.ui.icons import icon_mask
from mfruitos.launcher.ui.theme import SCREEN_H, SCREEN_W, Color, Theme, tile_color

log = logging.getLogger("mfruitos.ui")
_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


@lru_cache(maxsize=64)
def _rounded_mask(size: int, radius: int) -> Image.Image:
    scale = 4
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * scale - 1, size * scale - 1],
                                           radius=radius * scale, fill=255)
    return mask.resize((size, size), _LANCZOS)


@lru_cache(maxsize=48)
def _load_png_icon(path: str, mtime: float, size: int) -> Image.Image | None:
    try:
        with Image.open(path) as source:
            icon = source.convert("RGBA")
            icon.thumbnail((size, size), _LANCZOS)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            canvas.paste(icon, ((size - icon.width) // 2, (size - icon.height) // 2), icon)
            return canvas
    except (OSError, ValueError) as exc:
        log.warning("Cannot load icon %s: %s", path, exc)
        return None


class Painter:
    def __init__(self, theme: Theme, fonts: Fonts):
        self.theme = theme
        self.fonts = fonts
        self.image = Image.new("RGB", (SCREEN_W, SCREEN_H), theme.bg)
        self.draw = ImageDraw.Draw(self.image)

    def layer(self, width: int, height: int) -> "Painter":
        """A painter over a separate image, used to clip scrolling content."""
        sub = Painter.__new__(Painter)
        sub.theme, sub.fonts = self.theme, self.fonts
        sub.image = Image.new("RGB", (width, height), self.theme.bg)
        sub.draw = ImageDraw.Draw(sub.image)
        return sub

    # --------------------------------------------------------------- text
    def font(self, size: int, weight: str = "regular"):
        return self.fonts.get(size, weight)

    def text_width(self, text: str, size: int, weight: str = "regular") -> int:
        return self.fonts.text.length(text, size, weight)

    def fit(self, text: str, size: int, weight: str, max_width: int) -> str:
        """Ellipsize ``text`` to ``max_width`` pixels."""
        return self.fonts.text.fit(text, size, weight, max_width)

    def wrap(self, text: str, size: int, weight: str, max_width: int,
             max_lines: int = 99) -> list[str]:
        lines: list[str] = []
        for paragraph in str(text).split("\n"):
            words = paragraph.split(" ")
            line = ""
            for word in words:
                candidate = f"{line} {word}".strip()
                if self.text_width(candidate, size, weight) <= max_width or not line:
                    line = candidate
                else:
                    lines.append(line)
                    line = word
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self.fit(lines[-1] + " …", size, weight, max_width)
        return [self.fit(line, size, weight, max_width) for line in lines]

    def text(self, x: float, y: float, text: str, size: int = 15, weight: str = "regular",
             color: Color | None = None, anchor: str = "la", max_width: int | None = None) -> int:
        if max_width is not None:
            text = self.fit(text, size, weight, max_width)
        if not text:
            return 0
        mask, dx, dy = self.fonts.text.mask(text, size, weight, anchor)
        self.image.paste(color or self.theme.text, (int(round(x)) + dx, int(round(y)) + dy), mask)
        return self.text_width(text, size, weight)

    # ------------------------------------------------------------- shapes
    def rect(self, box, fill: Color):
        self.draw.rectangle(box, fill=fill)

    def rounded(self, box, radius: int, fill: Color | None = None,
                outline: Color | None = None, width: int = 1):
        self.draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def hline(self, x0: int, x1: int, y: int, color: Color | None = None):
        self.draw.line([(x0, y), (x1, y)], fill=color or self.theme.separator, width=1)

    def icon(self, name: str, x: int, y: int, size: int, color: Color | None = None):
        self.image.paste(color or self.theme.text, (x, y), icon_mask(name, size))

    def progress(self, box, fraction: float, fg: Color | None = None, bg: Color | None = None):
        x0, y0, x1, y1 = box
        radius = (y1 - y0) // 2
        self.rounded(box, radius, fill=bg or self.theme.surface_hi)
        fraction = max(0.0, min(1.0, fraction))
        if fraction > 0:
            self.rounded((x0, y0, x0 + max(y1 - y0, int((x1 - x0) * fraction)), y1), radius,
                         fill=fg or self.theme.accent)

    def toggle(self, x: int, y: int, on: bool):
        """A 30x16 switch whose left edge is ``x``."""
        t = self.theme
        self.rounded((x, y, x + 30, y + 16), 8, fill=t.accent if on else t.surface_hi)
        knob = x + 16 if on else x + 2
        self.draw.ellipse((knob, y + 2, knob + 12, y + 14), fill=(255, 255, 255))

    def pill(self, x: int, y: int, text: str, fg: Color, bg: Color, size: int = 11,
             align_right: bool = False) -> int:
        width = self.text_width(text, size, "semibold") + 12
        if align_right:
            x -= width
        self.rounded((x, y, x + width, y + size + 7), (size + 7) // 2, fill=bg)
        self.text(x + 6, y + 3, text, size, "semibold", fg)
        return width

    def spinner(self, cx: int, cy: int, radius: int, phase: int, color: Color | None = None):
        start = (phase * 45) % 360
        self.draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start, start + 270,
                      fill=color or self.theme.accent, width=3)

    # ------------------------------------------------------------ app tile
    def app_icon(self, app_id: str, label: str, icon_path: str, x: int, y: int, size: int,
                 muted: bool = False):
        radius = max(4, size // 4)
        png = None
        if icon_path:
            try:
                png = _load_png_icon(icon_path, os.path.getmtime(icon_path), size)
            except OSError:
                png = None
        if png is not None:
            tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            tile.paste(png, (0, 0), png)
            mask = Image.composite(tile.getchannel("A"), Image.new("L", (size, size), 0),
                                   _rounded_mask(size, radius))
            self.image.paste(tile.convert("RGB"), (x, y), mask)
            return
        color = tile_color(app_id)
        if muted:
            color = tuple((c + self.theme.surface_hi[i]) // 2 for i, c in enumerate(color))
        self.image.paste(color, (x, y), _rounded_mask(size, radius))
        text = (label or app_id[:2]).strip()[:3].upper() or "?"
        font_size = int(size * (0.46 if len(text) <= 2 else 0.36))
        self.text(x + size / 2, y + size / 2 + 1, text, font_size, "bold", (255, 255, 255),
                  anchor="mm")

    def system_tile(self, icon: str, x: int, y: int, size: int, color: Color):
        self.image.paste(color, (x, y), _rounded_mask(size, max(4, size // 4)))
        inner = int(size * 0.6)
        self.icon(icon, x + (size - inner) // 2, y + (size - inner) // 2, inner, (255, 255, 255))
