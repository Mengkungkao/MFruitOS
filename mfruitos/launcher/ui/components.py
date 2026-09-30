"""Shared screen chrome: status bar (page name, WiFi, battery), footer hints, list, toast."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.theme import CORNER_INSET, MARGIN, SCREEN_W

STATUS_Y = 9
LIST_TOP = 40
LIST_BOTTOM = 248
FOOTER_Y = 256
ROW_H = 36
ROW_H_SUB = 46


@dataclass
class StatusInfo:
    time_text: str = ""
    wifi_level: int | None = None     # None: no wifi, 0: disconnected, 1..3
    battery: int | None = None
    charging: bool = False
    busy: bool = False                 # updater working
    daemon_ok: bool = True


def _draw_wifi(p: Painter, x: int, y: int, level: int) -> None:
    """Three arcs, lit according to signal strength (0 = disconnected)."""
    t = p.theme
    cx, cy = x + 8, y + 13
    for index, radius in enumerate((4, 8, 12)):
        lit = level >= index + 1
        color = t.text if lit else t.surface_hi
        p.draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), 225, 315, fill=color,
                   width=2)
    p.draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=t.text if level else t.text_faint)
    if level == 0:
        p.draw.line((x + 1, y + 2, x + 15, y + 14), fill=t.warning, width=2)


def _draw_battery(p: Painter, x: int, y: int, status: StatusInfo) -> int:
    """Battery outline, fill and percentage right-aligned at ``x``; returns the new x."""
    t = p.theme
    label = f"{status.battery}%"
    x -= p.text_width(label, 13, "medium")
    p.text(x, y + 1, label, 13, "medium", t.text)
    x -= 27
    body = (x, y + 4, x + 21, y + 14)
    p.rounded(body, 2, outline=t.text_muted, width=1)
    p.rect((body[2] + 1, y + 7, body[2] + 2, y + 11), t.text_muted)
    fill_w = max(1, int(17 * status.battery / 100))
    color = t.error if status.battery <= 15 else (t.success if status.charging else t.text)
    p.rect((x + 2, y + 6, x + 2 + fill_w, y + 12), color)
    if status.charging:
        p.icon("bolt", x + 5, y + 3, 12, t.bg)
    return x


def draw_status_bar(p: Painter, status: StatusInfo, title: str = "") -> None:
    """Page name on the left; WiFi signal and battery on the right."""
    t = p.theme
    x = SCREEN_W - CORNER_INSET
    if status.battery is not None:
        x = _draw_battery(p, x, STATUS_Y, status) - 8
    if status.wifi_level is not None:
        x -= 17
        _draw_wifi(p, x, STATUS_Y, status.wifi_level)
        x -= 6
    if not status.daemon_ok:
        x -= 15
        p.icon("warning", x, STATUS_Y + 2, 14, t.warning)
        x -= 4
    elif status.busy:
        x -= 15
        p.icon("download", x, STATUS_Y + 2, 14, t.accent)
        x -= 4
    if title:
        left = CORNER_INSET - 4
        p.text(left, STATUS_Y - 1, title, 17, "bold", t.text, max_width=max(20, x - left - 6))


def draw_footer(p: Painter, hints: list[tuple[str, str]]) -> None:
    """``hints`` is [(gesture label, action label)], e.g. [("tap", "next")]."""
    t = p.theme
    if not hints:
        return
    parts = []
    for gesture, action in hints:
        parts.append((gesture, action))
    size = 11
    widths = [p.text_width(g, size, "semibold") + 4 + p.text_width(a, size) for g, a in parts]
    gap = 12
    total = sum(widths) + gap * (len(parts) - 1)
    while total > SCREEN_W - 2 * CORNER_INSET and len(parts) > 1:
        parts.pop()
        widths.pop()
        total = sum(widths) + gap * (len(parts) - 1)
    x = (SCREEN_W - total) // 2
    p.hline(CORNER_INSET, SCREEN_W - CORNER_INSET, FOOTER_Y - 5, t.separator)
    for (gesture, action), width in zip(parts, widths):
        gw = p.text(x, FOOTER_Y, gesture, size, "semibold", t.accent)
        p.text(x + gw + 4, FOOTER_Y, action, size, "regular", t.text_muted)
        x += width + gap


# ------------------------------------------------------------------ lists
@dataclass
class Item:
    """One row in a list screen. Callables are evaluated at draw time."""
    label: Any
    action: Callable[[], Any] | None = None
    # action | nav | toggle | choice | info | back | danger | section.
    # A "section" starts a group, iPhone style: a gap, with an optional small
    # heading ("MY DEVICES"); it is never selected.
    kind: str = "action"
    value: Any = None             # right-hand text, or bool for toggles
    subtitle: Any = None
    icon: str | None = None
    tone: str | None = None       # success | warning | error | accent | muted
    enabled: bool = True
    data: dict = field(default_factory=dict)
    tile: tuple | None = None     # draw the icon white on a rounded tile of this colour

    def resolve(self, attr: str):
        value = getattr(self, attr)
        return value() if callable(value) else value


def back_item(label: str = "Back") -> Item:
    return Item(label, kind="back", icon="back")


def _tone_color(p: Painter, tone: str | None, default):
    t = p.theme
    return {"success": t.success, "warning": t.warning, "error": t.error,
            "accent": t.accent, "muted": t.text_faint}.get(tone or "", default)


SECTION_GAP = 10
SECTION_TITLE_H = 24


def section(title: str = "") -> Item:
    """A group break in a list (with an optional heading); never selected."""
    return Item(title, kind="section")


def selectable(item: Item) -> bool:
    return item.kind != "section"


def row_height(item: Item) -> int:
    if item.kind == "section":
        return SECTION_TITLE_H if item.resolve("label") else SECTION_GAP
    return ROW_H_SUB if item.resolve("subtitle") else ROW_H


def draw_list(p: Painter, items: list[Item], selected: int, top: int = LIST_TOP,
              bottom: int = LIST_BOTTOM) -> None:
    t = p.theme
    if not items:
        p.text(SCREEN_W // 2, (top + bottom) // 2, "Nothing here", 14, "medium", t.text_faint,
               anchor="mm")
        return
    heights = [row_height(item) for item in items]
    # Scroll in whole rows so text is never sliced under the status bar.
    offset = 0
    visible = bottom - top
    first = 0
    selected_bottom = sum(heights[:selected + 1])
    while first < selected and selected_bottom - offset > visible:
        offset += heights[first]
        first += 1

    # Rows are drawn on their own layer so scrolled content is clipped to
    # the list area and can never paint over the header or message text.
    layer = p.layer(SCREEN_W, visible + 1)
    y = -offset
    left, right = MARGIN - 4, SCREEN_W - MARGIN + 4
    for index, (item, height) in enumerate(zip(items, heights)):
        if y < 0:
            y += height
            continue
        if y + height > visible:
            break
        is_sel = index == selected and selectable(item)
        if is_sel:
            layer.rounded((left, y + 1, right, y + height - 1), 12, fill=t.accent_dim)
        elif (index > 0 and index - 1 != selected and selectable(item)
              and selectable(items[index - 1])):
            layer.hline(left + (40 if item.tile else 12), right - 12, y, t.separator)
        _draw_row(layer, item, y, height, left, right, is_sel)
        y += height
    p.image.paste(layer.image, (0, top))
    total = sum(heights)
    if total > visible:
        track_x = SCREEN_W - 5
        bar_h = max(18, int(visible * visible / total))
        bar_y = top + int((visible - bar_h) * (offset / max(1, total - visible)))
        p.rounded((track_x, top, track_x + 2, bottom), 1, fill=t.surface_hi)
        p.rounded((track_x, bar_y, track_x + 2, bar_y + bar_h), 1, fill=t.text_muted)


def _draw_row(p: Painter, item: Item, y: int, height: int, left: int, right: int,
              selected: bool) -> None:
    t = p.theme
    if item.kind == "section":
        title = str(item.resolve("label") or "")
        if title:
            p.text(left + 10, y + height - 7, title.upper(), 11, "semibold", t.text_faint,
                   anchor="ls")
        return
    label = str(item.resolve("label"))
    subtitle = item.resolve("subtitle")
    value = item.resolve("value")
    enabled = item.enabled
    base = t.text if enabled else t.text_faint
    if item.kind == "danger" and enabled:
        base = t.error
    if item.kind == "back":
        base = t.text_muted if not selected else t.text
    x = left + 10
    if item.tile and item.icon:
        size = 24
        tile_y = y + (height - size) // 2
        p.rounded((x, tile_y, x + size, tile_y + size), 7, fill=item.tile)
        p.icon(item.icon, x + 5, tile_y + 5, 14, (255, 255, 255))
        x += size + 10
    elif item.icon:
        icon_color = t.accent if selected and item.kind != "danger" else (
            t.error if item.kind == "danger" else t.text_muted)
        p.icon(item.icon, x, y + (height - 16) // 2, 16, icon_color)
        x += 24
    right_edge = right - 10
    # Right-hand side
    if item.kind == "toggle":
        p.toggle(right_edge - 30, y + (height - 16) // 2, bool(value))
        right_edge -= 38
    elif item.kind == "nav":
        p.icon("chevron", right_edge - 10, y + (height - 12) // 2, 12, t.text_faint)
        right_edge -= 16
        if value not in (None, ""):
            w = p.text(right_edge, y + height // 2, str(value), 13, "medium",
                       _tone_color(p, item.tone, t.text_muted), anchor="rm",
                       max_width=int((right_edge - x) * 0.45))
            right_edge -= w + 8
    elif value not in (None, ""):
        w = p.text(right_edge, y + height // 2, str(value), 13, "medium",
                   _tone_color(p, item.tone, t.text_muted), anchor="rm",
                   max_width=int((right_edge - x) * 0.42))
        right_edge -= w + 8
    max_w = right_edge - x
    if subtitle:
        p.text(x, y + 7, label, 15, "semibold" if selected else "medium", base, max_width=max_w)
        subtitle_tone = item.tone if value in (None, "") and item.kind != "nav" else None
        p.text(x, y + 26, str(subtitle), 12, "regular", _tone_color(p, subtitle_tone, t.text_muted),
               max_width=max_w)
    else:
        p.text(x, y + height // 2, label, 15, "semibold" if selected else "medium", base,
               anchor="lm", max_width=max_w)


def draw_toast(p: Painter, text: str, tone: str = "") -> None:
    t = p.theme
    width = min(SCREEN_W - 40, p.text_width(text, 13, "semibold") + 28)
    x0 = (SCREEN_W - width) // 2
    y0 = FOOTER_Y - 40
    p.rounded((x0, y0, x0 + width, y0 + 30), 15, fill=t.surface_hi,
              outline=_tone_color(p, tone, t.separator))
    p.text(SCREEN_W // 2, y0 + 15, text, 13, "semibold", t.text, anchor="mm",
           max_width=width - 20)
