"""Visual tokens. One source for every colour the UI draws."""

from __future__ import annotations

from dataclasses import dataclass

Color = tuple[int, int, int]

SCREEN_W = 240
SCREEN_H = 280
# The Whisplay LCD has rounded corners; keep text clear of them.
CORNER_INSET = 20
MARGIN = 14


@dataclass(frozen=True)
class Theme:
    name: str
    bg: Color
    surface: Color
    surface_hi: Color
    separator: Color
    text: Color
    text_muted: Color
    text_faint: Color
    accent: Color
    accent_dim: Color
    accent_text: Color
    success: Color
    warning: Color
    error: Color


DARK = Theme(
    name="dark",
    bg=(10, 12, 16),
    surface=(24, 27, 33),
    surface_hi=(34, 38, 46),
    separator=(40, 45, 54),
    text=(244, 246, 250),
    text_muted=(150, 158, 170),
    text_faint=(96, 104, 116),
    accent=(46, 140, 255),
    accent_dim=(16, 42, 82),
    accent_text=(255, 255, 255),
    success=(52, 199, 110),
    warning=(255, 176, 32),
    error=(255, 77, 79),
)

LIGHT = Theme(
    name="light",
    bg=(242, 244, 247),
    surface=(255, 255, 255),
    surface_hi=(232, 236, 242),
    separator=(218, 223, 230),
    text=(17, 20, 24),
    text_muted=(94, 103, 115),
    text_faint=(150, 158, 170),
    accent=(10, 108, 255),
    accent_dim=(214, 230, 255),
    accent_text=(255, 255, 255),
    success=(26, 158, 80),
    warning=(204, 126, 0),
    error=(214, 40, 40),
)

THEMES = {"dark": DARK, "light": LIGHT}

# Muted, distinguishable tile colours for apps without a PNG icon.
APP_TILE_COLORS: tuple[Color, ...] = (
    (46, 140, 255), (52, 199, 110), (255, 149, 0), (175, 82, 222),
    (255, 69, 108), (0, 184, 204), (255, 196, 0), (94, 92, 230),
    (48, 176, 136), (232, 96, 64),
)


def get_theme(name: str) -> Theme:
    return THEMES.get(name, DARK)


def tile_color(app_id: str) -> Color:
    # Stable across runs (unlike hash()), so an app keeps its colour.
    total = sum((i + 1) * ord(ch) for i, ch in enumerate(app_id))
    return APP_TILE_COLORS[total % len(APP_TILE_COLORS)]


def blend(a: Color, b: Color, t: float) -> Color:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]
