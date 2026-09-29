"""Backlight and RGB LED policy. All hardware access goes through whisplay-daemon
(``backlight.set`` / ``led.set``); nothing here touches GPIO. Values are cached
so repeated requests cost no IPC."""

from __future__ import annotations

import logging
import os
import re
import socket

from mfruitos.daemon.client import DaemonError, WhisplayDaemonClient
from mfruitos.system.settings import Settings

log = logging.getLogger("mfruitos.hardware")

LED_RGB = {
    "off": (0, 0, 0), "white": (255, 255, 255), "blue": (0, 90, 255), "cyan": (0, 220, 255),
    "green": (0, 255, 60), "yellow": (255, 200, 0), "orange": (255, 110, 0),
    "red": (255, 0, 0), "purple": (160, 0, 255), "pink": (255, 40, 150),
}
LED_STATES = ("idle", "running", "update", "error")
PISUGAR_SOCKETS = ("/tmp/pisugar-server.sock", "/run/pisugar-server.sock")


class BacklightController:
    """Screen brightness with auto-dim and timeout (only while the OS owns the screen)."""

    def __init__(self, client: WhisplayDaemonClient, settings: Settings):
        self.client = client
        self.settings = settings
        self.level: int | None = None
        self.state = "on"            # on | dim | off

    def _apply(self, level: int) -> None:
        if level == self.level:
            return
        try:
            self.client.set_backlight(level)
            self.level = level
        except DaemonError as exc:
            log.warning("backlight.set failed: %s", exc)
            self.level = None

    def wake(self) -> None:
        self.state = "on"
        self._apply(self.settings.get("display.brightness"))

    def dim(self) -> None:
        self.state = "dim"
        brightness = self.settings.get("display.brightness")
        self._apply(min(brightness, self.settings.get("display.dim_level")))

    def off(self) -> None:
        self.state = "off"
        self._apply(0)

    def preview(self, level: int) -> None:
        self._apply(level)

    def forget(self) -> None:
        """Another app may have changed the backlight; re-send next time."""
        self.level = None


class LedController:
    def __init__(self, client: WhisplayDaemonClient, settings: Settings):
        self.client = client
        self.settings = settings
        self.state = "idle"
        self.current: tuple[int, int, int] | None = None

    def color_for(self, state: str) -> tuple[int, int, int]:
        if not self.settings.get("led.enabled"):
            return (0, 0, 0)
        name = self.settings.get(f"led.{state}_color") if state in LED_STATES else "off"
        r, g, b = LED_RGB.get(name, (0, 0, 0))
        scale = self.settings.get("led.brightness") / 100.0
        return (int(r * scale), int(g * scale), int(b * scale))

    def show(self, state: str, force: bool = False) -> None:
        self.state = state
        self.set_rgb(self.color_for(state), force=force)

    def set_rgb(self, rgb: tuple[int, int, int], force: bool = False) -> None:
        if rgb == self.current and not force:
            return
        try:
            self.client.set_led(*rgb)
            self.current = rgb
        except DaemonError as exc:
            log.warning("led.set failed: %s", exc)
            self.current = None

    def forget(self) -> None:
        self.current = None


def read_battery() -> tuple[int | None, bool]:
    """Battery percent and charging flag from pisugar-server, if present."""
    path = next((p for p in PISUGAR_SOCKETS if os.path.exists(p)), None)
    if path is None:
        return None, False
    level = _pisugar(path, "get battery", r"battery:\s*(-?[\d.]+)")
    charging = _pisugar(path, "get battery_charging", r"battery_charging:\s*(\w+)")
    try:
        percent = int(float(level)) if level is not None else None
    except ValueError:
        percent = None
    if percent is not None and percent < 0:
        percent = None
    return (min(100, percent) if percent is not None else None,
            str(charging).lower() == "true")


def _pisugar(path: str, command: str, pattern: str) -> str | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(path)
            sock.sendall((command + "\n").encode())
            data = sock.recv(256).decode("utf-8", "replace")
    except OSError:
        return None
    match = re.search(pattern, data, flags=re.IGNORECASE)
    return match.group(1) if match else None
