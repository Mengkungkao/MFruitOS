"""Home / app launcher."""

from __future__ import annotations

from dataclasses import dataclass

from mfruitos.apps.registry import SYSTEM_PAGES, AppEntry
from mfruitos.launcher.ui.components import LIST_BOTTOM, LIST_TOP, draw_footer
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.screens.base import Screen
from mfruitos.launcher.ui.theme import MARGIN, SCREEN_W

CARD_H = 58
ROW_H = 40
GAP = 4


@dataclass
class HomeEntry:
    key: str
    name: str
    kind: str                 # app | system | builtin
    icon: str = ""
    app: AppEntry | None = None
    badge: int = 0


class HomeScreen(Screen):
    select_label = "open"

    def __init__(self, os):
        super().__init__(os)
        self.selected = 0
        self._initial_selection_done = False

    # -------------------------------------------------------------- data
    def entries(self) -> list[HomeEntry]:
        entries = [HomeEntry(a.id, a.name, "app", app=a) for a in self.os.registry.launcher_entries()]
        if self.os.settings.get("system.show_system_pages_on_home"):
            for page in self.os.registry.system_pages():
                label, icon, _ = SYSTEM_PAGES[page.id]
                entries.append(HomeEntry(page.id, label, "system", icon=icon, app=page))
        updates = self.os.updates_available_count()
        entries.append(HomeEntry("os.settings", "Settings", "builtin", icon="settings"))
        entries.append(HomeEntry("os.updater", "Updater", "builtin", icon="updater", badge=updates))
        return entries

    def on_show(self) -> None:
        entries = self.entries()
        if not self._initial_selection_done:
            self._initial_selection_done = True
            default = self.os.settings.get("apps.default_app")
            for index, entry in enumerate(entries):
                if entry.key == default:
                    self.selected = index
        self.selected = min(self.selected, len(entries) - 1)

    def focus_key(self, key: str) -> None:
        for index, entry in enumerate(self.entries()):
            if entry.key == key:
                self.selected = index
                return

    # ------------------------------------------------------------- input
    def handle(self, action: str) -> bool:
        entries = self.entries()
        if not entries:
            return False
        self.selected = min(self.selected, len(entries) - 1)
        if action in ("next", "previous"):
            self.selected = (self.selected + (1 if action == "next" else -1)) % len(entries)
            self.redraw()
            return True
        if action == "select":
            self.os.open_home_entry(entries[self.selected])
            return True
        if action in ("back", "home"):
            if self.selected != 0:
                self.selected = 0
                self.redraw()
            return True
        return False

    # -------------------------------------------------------------- draw
    def footer(self, p: Painter) -> None:
        # Home is the root: offer "previous" instead of "back".
        draw_footer(p, self.os.hints(select=self.select_label, back=False))

    def draw(self, p: Painter) -> None:
        t = p.theme
        entries = self.entries()
        title = self.os.settings.get("system.home_title") or "MFruit OS"
        p.text(MARGIN + 2, 31, title, 20, "bold", t.text, max_width=150)
        if entries:
            p.text(SCREEN_W - MARGIN - 2, 37, f"{self.selected + 1} / {len(entries)}", 12,
                   "medium", t.text_faint, anchor="ra")
        if not entries:
            return
        self.selected = min(self.selected, len(entries) - 1)
        heights = [CARD_H if i == self.selected else ROW_H for i in range(len(entries))]
        tops, y = [], 0
        for h in heights:
            tops.append(y)
            y += h + GAP
        total = y - GAP
        visible = LIST_BOTTOM - LIST_TOP
        context = ROW_H + GAP if self.selected > 0 else 0
        offset = max(0, min(tops[self.selected] - context, max(0, total - visible)))
        for index, entry in enumerate(entries):
            top = LIST_TOP + tops[index] - offset
            if top + heights[index] < LIST_TOP or top > LIST_BOTTOM:
                continue
            if index == self.selected:
                self._draw_card(p, entry, top)
            else:
                self._draw_row(p, entry, top)
        p.rect((0, LIST_BOTTOM + 1, SCREEN_W, 280), t.bg)
        p.rect((0, 0, SCREEN_W, LIST_TOP - 3), t.bg)
        # redraw the header over any row that scrolled beneath it
        p.text(MARGIN + 2, 31, title, 20, "bold", t.text, max_width=150)
        p.text(SCREEN_W - MARGIN - 2, 37, f"{self.selected + 1} / {len(entries)}", 12,
               "medium", t.text_faint, anchor="ra")

    def _tile(self, p: Painter, entry: HomeEntry, x: int, y: int, size: int) -> None:
        t = p.theme
        if entry.kind == "app":
            app = entry.app
            p.app_icon(app.id, app.icon_text or app.name[:2], app.icon_path, x, y, size,
                       muted=not app.launchable)
        else:
            color = (72, 80, 96) if entry.kind == "builtin" else (58, 110, 180)
            if entry.key == "os.updater":
                color = (32, 120, 220)
            p.system_tile(entry.icon, x, y, size, color)
        if entry.badge:
            r = 8
            cx, cy = x + size - 3, y + 3
            p.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=t.error)
            p.text(cx, cy, str(min(entry.badge, 9)), 10, "bold", (255, 255, 255), anchor="mm")

    def _subtitle(self, entry: HomeEntry) -> tuple[str, str]:
        if entry.kind == "builtin":
            if entry.key == "os.updater":
                count = entry.badge
                if count:
                    return (f"{count} update{'s' if count != 1 else ''} available", "accent")
                return (self.os.updater_summary(), "muted")
            return ("Apps, display, button, LED…", "muted")
        if entry.kind == "system":
            return ("Daemon page", "muted")
        app = entry.app
        if app.broken:
            return (app.broken, "error")
        if app.running:
            return ("Running" + (f" · {app.version}" if app.version else ""), "success")
        if app.update_available:
            return (f"Update available · {app.latest_version}", "accent")
        return (app.description or (f"Version {app.version}" if app.version else "Whisplay app"),
                "muted")

    def _draw_card(self, p: Painter, entry: HomeEntry, top: int) -> None:
        t = p.theme
        left, right = MARGIN - 4, SCREEN_W - MARGIN + 4
        p.rounded((left, top, right, top + CARD_H), 16, fill=t.accent_dim)
        p.rounded((left, top, right, top + CARD_H), 16, outline=t.accent, width=1)
        self._tile(p, entry, left + 10, top + 10, 38)
        x = left + 58
        p.text(x, top + 10, entry.name, 17, "semibold", t.text, max_width=right - x - 10)
        text, tone = self._subtitle(entry)
        color = {"error": t.error, "success": t.success, "accent": t.accent}.get(tone, t.text_muted)
        p.text(x, top + 33, text, 12, "medium", color, max_width=right - x - 10)

    def _draw_row(self, p: Painter, entry: HomeEntry, top: int) -> None:
        t = p.theme
        left, right = MARGIN - 4, SCREEN_W - MARGIN + 4
        self._tile(p, entry, left + 16, top + 7, 26)
        x = left + 52
        name_color = t.text
        if entry.kind == "app" and not entry.app.launchable:
            name_color = t.text_faint
        p.text(x, top + ROW_H // 2, entry.name, 15, "medium", name_color, anchor="lm",
               max_width=right - x - 26)
        if entry.kind == "app":
            app = entry.app
            dot = None
            if app.broken:
                p.icon("warning", right - 22, top + 13, 14, t.warning)
            elif app.running:
                dot = t.success
            elif app.update_available:
                dot = t.accent
            if dot:
                cx, cy = right - 15, top + ROW_H // 2
                p.draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=dot)
