"""Shared screen chrome: status bar, header, footer hints, list view, toast."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.theme import CORNER_INSET, MARGIN, SCREEN_W

STATUS_Y = 7
TITLE_Y = 31
LIST_TOP = 62
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


def draw_status_bar(p: Painter, status: StatusInfo) -> None:
    t = p.theme
    p.text(CORNER_INSET + 4, STATUS_Y, status.time_text, 14, "semibold", t.text)
    x = SCREEN_W - CORNER_INSET - 4
    if status.battery is not None:
        label = f"{status.battery}%"
        x -= p.text_width(label, 12, "medium")
        p.text(x, STATUS_Y + 1, label, 12, "medium", t.text_muted)
        x -= 25
        body = (x, STATUS_Y + 3, x + 19, STATUS_Y + 12)
        p.rounded(body, 2, outline=t.text_muted, width=1)
        p.rect((body[2] + 1, STATUS_Y + 6, body[2] + 2, STATUS_Y + 9), t.text_muted)
        fill_w = max(1, int(15 * status.battery / 100))
        color = t.error if status.battery <= 15 else (t.success if status.charging else t.text)
        p.rect((x + 2, STATUS_Y + 5, x + 2 + fill_w, STATUS_Y + 10), color)
        if status.charging:
            p.icon("bolt", x + 4, STATUS_Y + 2, 11, t.bg)
        x -= 6
    if status.wifi_level is not None:
        x -= 16
        if status.wifi_level == 0:
            p.icon("wifi", x, STATUS_Y, 15, t.text_faint)
        else:
            p.icon("wifi", x, STATUS_Y, 15, t.text if status.wifi_level >= 2 else t.warning)
        x -= 6
    if not status.daemon_ok:
        x -= 14
        p.icon("warning", x, STATUS_Y + 1, 13, t.warning)
    elif status.busy:
        x -= 14
        p.icon("download", x, STATUS_Y + 1, 13, t.accent)


def draw_header(p: Painter, title: str, subtitle: str = "") -> None:
    p.text(MARGIN + 2, TITLE_Y, title, 20, "bold", p.theme.text, max_width=SCREEN_W - 2 * MARGIN)
    if subtitle:
        width = p.text_width(title, 20, "bold")
        room = SCREEN_W - MARGIN * 2 - width - 10
        if room > 30:
            p.text(SCREEN_W - MARGIN - 2, TITLE_Y + 6, subtitle, 12, "medium",
                   p.theme.text_muted, anchor="ra", max_width=room)


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
    kind: str = "action"          # action | nav | toggle | choice | info | back | danger
    value: Any = None             # right-hand text, or bool for toggles
    subtitle: Any = None
    icon: str | None = None
    tone: str | None = None       # success | warning | error | accent | muted
    enabled: bool = True
    data: dict = field(default_factory=dict)

    def resolve(self, attr: str):
        value = getattr(self, attr)
        return value() if callable(value) else value


def back_item(label: str = "Back") -> Item:
    return Item(label, kind="back", icon="back")


def _tone_color(p: Painter, tone: str | None, default):
    t = p.theme
    return {"success": t.success, "warning": t.warning, "error": t.error,
            "accent": t.accent, "muted": t.text_faint}.get(tone or "", default)


def row_height(item: Item) -> int:
    return ROW_H_SUB if item.resolve("subtitle") else ROW_H


def draw_list(p: Painter, items: list[Item], selected: int, top: int = LIST_TOP,
              bottom: int = LIST_BOTTOM) -> None:
    t = p.theme
    if not items:
        p.text(SCREEN_W // 2, (top + bottom) // 2, "Nothing here", 14, "medium", t.text_faint,
               anchor="mm")
        return
    heights = [row_height(item) for item in items]
    # Scroll so the selected row is visible, keeping one row of context above.
    offset = 0
    y_sel = sum(heights[:selected])
    visible = bottom - top
    if y_sel + heights[selected] > visible - (heights[selected + 1] // 2 if selected + 1 < len(items) else 0):
        offset = y_sel + heights[selected] - visible + (
            heights[selected + 1] // 2 if selected + 1 < len(items) else 0)
    if selected > 0 and y_sel - offset < heights[selected - 1] // 2:
        offset = max(0, y_sel - heights[selected - 1] // 2)
    offset = max(0, min(offset, max(0, sum(heights) - visible)))

    # Rows are drawn on their own layer so scrolled content is clipped to
    # the list area and can never paint over the header or message text.
    layer = p.layer(SCREEN_W, visible + 1)
    y = -offset
    left, right = MARGIN - 4, SCREEN_W - MARGIN + 4
    for index, (item, height) in enumerate(zip(items, heights)):
        if y + height < 0:
            y += height
            continue
        if y > visible:
            break
        is_sel = index == selected
        if is_sel:
            layer.rounded((left, y + 1, right, y + height - 1), 12, fill=t.accent_dim)
        elif index > 0 and index - 1 != selected:
            layer.hline(left + 12, right - 12, y, t.separator)
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
    if item.icon:
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
