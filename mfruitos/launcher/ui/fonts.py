"""Font loading with caching. Inter is bundled (SIL OFL) so every board looks
the same; DejaVu (installed with whisplay-daemon's dependencies) is the fallback."""

from __future__ import annotations

import logging
import os

from PIL import ImageFont

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
