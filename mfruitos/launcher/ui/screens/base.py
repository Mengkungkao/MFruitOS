"""Screen base classes.

Every screen answers the four UI questions from CLAUDE.md §9:
where am I (page name in the status bar), what is selected (highlight), what
happens when I press (footer hints) and how do I go back (footer + a Back row).
"""

from __future__ import annotations

from mfruitos.launcher.ui.components import Item, draw_footer, draw_list
from mfruitos.launcher.ui.painter import Painter


class Screen:
    title = ""
    subtitle = ""
    show_status = True
    modal = False          # True: back/home gestures are refused (e.g. during an update)
    select_label = "select"

    def __init__(self, os):
        self.os = os

    def on_show(self) -> None:
        """Became the top screen (pushed, or uncovered by a pop)."""

    def on_hide(self) -> None:
        """Covered by another screen or popped."""

    def handle(self, action: str) -> bool:
        """Handle a navigation action; return True if consumed."""
        return False

    def draw(self, p: Painter) -> None:
        """Draw the content area; the page name is shown in the status bar."""

    def footer(self, p: Painter) -> None:
        draw_footer(p, self.os.hints(select=self.select_label, back=not self.modal))

    def redraw(self) -> None:
        self.os.request_render()


class ListScreen(Screen):
    def __init__(self, os):
        super().__init__(os)
        self.selected = 0

    def items(self) -> list[Item]:
        return []

    def current_items(self) -> list[Item]:
        items = self.items()
        if items:
            self.selected = max(0, min(self.selected, len(items) - 1))
        return items

    def handle(self, action: str) -> bool:
        items = self.current_items()
        if action in ("next", "previous"):
            if items:
                step = 1 if action == "next" else -1
                self.selected = (self.selected + step) % len(items)
                self.redraw()
            return True
        if action == "select" and items:
            item = items[self.selected]
            if item.kind == "back":
                self.os.pop()
                return True
            if not item.enabled:
                reason = item.data.get("disabled_reason")
                if reason:
                    self.os.toast(reason)
                return True
            if item.action is not None:
                item.action()
                self.redraw()
            return True
        return False

    def select_id(self, key: str) -> None:
        for index, item in enumerate(self.current_items()):
            if item.data.get("id") == key:
                self.selected = index
                return

    def draw(self, p: Painter) -> None:
        draw_list(p, self.current_items(), self.selected)
