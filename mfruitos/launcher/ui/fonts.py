"""Font loading with caching. Inter is bundled (SIL OFL) so every board looks
the same; DejaVu (installed with whisplay-daemon's dependencies) is the fallback."""

from __future__ import annotations

import logging
import os
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("mfruitos.fonts")

WEIGHTS = {
    "regular": ("Inter-Regular.ttf", "DejaVuSans.ttf"),
    "medium": ("Inter-Medium.ttf", "DejaVuSans.ttf"),
    "semibold": ("Inter-SemiBold.ttf", "DejaVuSans-Bold.ttf"),
    "bold": ("Inter-Bold.ttf", "DejaVuSans-Bold.ttf"),
}
SYSTEM_FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu")


def _basic_layout():
    layout = getattr(ImageFont, "Layout", None)  # Pillow >= 9.1
    if layout is not None:
        return layout.BASIC
    return getattr(ImageFont, "LAYOUT_BASIC", 0)


class Fonts:
    def __init__(self, font_dir: str):
        self.font_dir = font_dir
        self._cache: dict[tuple[str, int], ImageFont.ImageFont] = {}
        self._paths: dict[str, str | None] = {}
        self._layout = _basic_layout()
        self.text = TextCache(self)

    def _path(self, weight: str) -> str | None:
        if weight not in self._paths:
            bundled, system = WEIGHTS.get(weight, WEIGHTS["regular"])
            candidates = [os.path.join(self.font_dir, bundled)]
            candidates += [os.path.join(d, system) for d in SYSTEM_FONT_DIRS]
            self._paths[weight] = next((p for p in candidates if os.path.isfile(p)), None)
            if self._paths[weight] is None:
                log.warning("No TrueType font found for weight %s; using PIL default", weight)
        return self._paths[weight]

    def get(self, size: int, weight: str = "regular"):
        key = (weight, size)
        font = self._cache.get(key)
        if font is None:
            path = self._path(weight)
            try:
                font = (ImageFont.truetype(path, size=size, layout_engine=self._layout)
                        if path else ImageFont.load_default())
            except OSError as exc:
                log.error("Cannot load font %s: %s", path, exc)
                font = ImageFont.load_default()
            self._cache[key] = font
        return font


class TextCache:
    """Rasterised text, cached.

    FreeType rasterisation was ~85 % of a frame on a Pi Zero 2 W (~3 ms per
    string); the same strings (app names, hints, status text) are drawn on
    every frame. A string is rasterised once into an 8-bit alpha mask and then
    pasted in any colour, which gives the same pixels as ``ImageDraw.text``.
    """

    MAX_ENTRIES = 1200

    def __init__(self, fonts: Fonts):
        self.fonts = fonts
        self._masks: OrderedDict = OrderedDict()
        self._lengths: dict = {}
        self._fits: dict = {}

    def _remember(self, store, key, value):
        store[key] = value
        if isinstance(store, OrderedDict):
            store.move_to_end(key)
            if len(store) > self.MAX_ENTRIES:
                store.popitem(last=False)
        elif len(store) > self.MAX_ENTRIES * 4:
            store.clear()
        return value

    def length(self, text: str, size: int, weight: str) -> int:
        key = (text, size, weight)
        value = self._lengths.get(key)
        if value is None:
            value = self._remember(self._lengths, key,
                                   int(self.fonts.get(size, weight).getlength(text)))
        return value

    def fit(self, text: str, size: int, weight: str, max_width: int) -> str:
        """``text`` shortened with an ellipsis to fit ``max_width`` pixels."""
        key = (text, size, weight, max_width)
        value = self._fits.get(key)
        if value is not None:
            return value
        if self.length(text, size, weight) <= max_width:
            return self._remember(self._fits, key, text)
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.length(text[:mid].rstrip() + "…", size, weight) <= max_width:
                low = mid
            else:
                high = mid - 1
        return self._remember(self._fits, key, text[:low].rstrip() + "…")

    def mask(self, text: str, size: int, weight: str, anchor: str):
        """(alpha mask, dx, dy) to paste at the anchor point."""
        key = (text, size, weight, anchor)
        value = self._masks.get(key)
        if value is not None:
            self._masks.move_to_end(key)
            return value
        font = self.fonts.get(size, weight)
        try:
            x0, y0, x1, y1 = font.getbbox(text, anchor=anchor)
        except (TypeError, ValueError):  # bitmap fallback fonts do not take anchors
            x0, y0, x1, y1 = font.getbbox(text)
        mask = Image.new("L", (max(1, x1 - x0), max(1, y1 - y0)), 0)
        draw = ImageDraw.Draw(mask)
        try:
            draw.text((-x0, -y0), text, font=font, fill=255, anchor=anchor)
        except (TypeError, ValueError):
            draw.text((-x0, -y0), text, font=font, fill=255)
        return self._remember(self._masks, key, (mask, x0, y0))
