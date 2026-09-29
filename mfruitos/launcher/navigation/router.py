"""Screen stack. The root (Home) can never be popped."""

from __future__ import annotations

import logging

log = logging.getLogger("mfruitos.router")


class Router:
    def __init__(self, on_change=None):
        self._stack: list = []
        self._on_change = on_change or (lambda: None)

    @property
    def top(self):
        return self._stack[-1] if self._stack else None

    @property
    def depth(self) -> int:
        return len(self._stack)

    def __iter__(self):
        return iter(list(self._stack))

    def set_root(self, screen) -> None:
        for old in reversed(self._stack):
            old.on_hide()
        self._stack = [screen]
        screen.on_show()
        self._on_change()

    def push(self, screen) -> None:
        if self.top is not None:
            self.top.on_hide()
        self._stack.append(screen)
        log.debug("push %s", type(screen).__name__)
        screen.on_show()
        self._on_change()

    def replace(self, screen) -> None:
        if len(self._stack) <= 1:
            self.set_root(screen)
            return
        self._stack.pop().on_hide()
        self._stack.append(screen)
        screen.on_show()
        self._on_change()

    def pop(self) -> bool:
        if len(self._stack) <= 1:
            return False
        self._stack.pop().on_hide()
        self.top.on_show()
        self._on_change()
        return True

    def pop_to(self, screen_type) -> bool:
        """Pop until the top is an instance of ``screen_type``."""
        if not any(isinstance(s, screen_type) for s in self._stack):
            return False
        while len(self._stack) > 1 and not isinstance(self.top, screen_type):
            self._stack.pop().on_hide()
        self.top.on_show()
        self._on_change()
        return True

    def home(self) -> None:
        if len(self._stack) <= 1:
            return
        while len(self._stack) > 1:
            self._stack.pop().on_hide()
        self.top.on_show()
        self._on_change()
