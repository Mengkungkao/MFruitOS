"""The launcher's link to the power service (``mfruitos/power``).

Live battery state for the status bar and Settings > Battery comes from the
service's event stream (``PowerEvents``, its own thread), posted to the UI
loop: the UI thread never waits on the power socket. Requests that change
something run as tasks (``ScreenServices.run_task``).
"""

from __future__ import annotations

import logging
from typing import Callable

from mfruitos import power
from mfruitos.power.client import PowerClient, PowerEvents

log = logging.getLogger("mfruitos.power.link")


class PowerLink:
    def __init__(self, path: str, post: Callable[..., None]):
        self.client = PowerClient(path)
        self._post = post
        self.events = PowerEvents(path, lambda event: post(self._event, event))
        self.connected = False
        self.state: dict = {}
        self.config: dict = {}
        self.listener: Callable[[dict], None] = lambda event: None

    def start(self) -> None:
        self.events.start()

    def stop(self) -> None:
        self.events.stop()

    # loop thread
    def _event(self, event: dict) -> None:
        name = event.get("event")
        if name == "_connected":
            self.connected = True
        elif name == "_disconnected":
            self.connected = False
            self.state = {}
        elif name == power.STATE:
            self.state = dict(event.get("state") or {})
        elif name == power.CONFIG:
            self.config = dict(event.get("config") or {})
        self.listener(event)

    def battery(self) -> tuple | None:
        """(percent or None, charging) while the service runs; None when it
        does not (the caller may fall back to PiSugar's own server)."""
        if not self.connected:
            return None
        level = self.state.get("level") if self.state.get("present") else None
        return level, bool(self.state.get("charging")) if level is not None else False

    def button_action(self, tap: str) -> str:
        if tap not in ("double", "long"):
            return "none"      # a single press belongs to whisplay-daemon (Home)
        return str(self.config.get(f"button_{tap}", "none"))
