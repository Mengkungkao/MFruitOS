"""Fallback display when whisplay-daemon is not running.

Why this bypasses the daemon (docs/platform/DEVELOPMENT_RULES.md requires a
documented reason for any direct hardware access):
without the daemon there is no framebuffer, so MFruit OS could not show the
"Daemon unavailable" screen the user needs to recover. This module is only
used when the daemon's systemd unit is *inactive or failed* (never while it
is starting), and the hardware is released as soon as the unit is active
again, so it can never compete with a running daemon for GPIO/SPI.

It uses ``WhisplayBoard`` from the MFruit OS Whisplay driver's runtime
(drivers/whisplay, installed to /usr/local/share/whisplay; docs/WHISPLAY_DRIVER.md);
no hardware logic is duplicated here.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import subprocess
import sys
from typing import Callable

from mfruitos.paths import package_root

log = logging.getLogger("mfruitos.direct")

DAEMON_UNIT = "whisplay-daemon.service"
DRIVER_DIR = "/usr/local/share/whisplay"
SAFE_STATES = {"inactive", "failed"}


def daemon_unit_state() -> str:
    """``systemctl is-active`` for the daemon; "unknown" without systemd."""
    if shutil.which("systemctl") is None:
        return "unknown"
    try:
        result = subprocess.run(["systemctl", "is-active", DAEMON_UNIT], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def find_whisplay_root(configured: str = "") -> str | None:
    candidates = [configured] if configured else []
    try:
        out = subprocess.run(["systemctl", "show", "-p", "WorkingDirectory", DAEMON_UNIT],
                             capture_output=True, text=True, timeout=5).stdout
        if "=" in out:
            candidates.append(out.split("=", 1)[1].strip())
    except (OSError, subprocess.SubprocessError):
        pass
    # The installed driver, then a Whisplay checkout of an older installation,
    # then the copy shipped with this MFruit OS version.
    candidates += [DRIVER_DIR, os.path.expanduser("~/Whisplay"),
                   os.path.join(package_root(), "drivers", "whisplay")]
    for path in candidates:
        if path and os.path.isfile(os.path.join(path, "runtime", "whisplay.py")):
            return path
    return None


def restart_daemon() -> bool:
    """Ask systemd to restart the daemon (needs the sudoers rule from install.sh)."""
    try:
        result = subprocess.run(["sudo", "-n", "systemctl", "restart", DAEMON_UNIT],
                                capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Cannot restart daemon: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("Daemon restart refused: %s", result.stderr.strip()[:120])
    return result.returncode == 0


class DirectDisplay:
    def __init__(self, whisplay_root: str, on_button: Callable[[bool], None]):
        self.whisplay_root = whisplay_root
        self.on_button = on_button
        self.board = None

    @property
    def attached(self) -> bool:
        return self.board is not None

    def open(self) -> bool:
        runtime = os.path.join(self.whisplay_root, "runtime")
        if runtime not in sys.path:
            sys.path.append(runtime)
        try:
            module = importlib.import_module("whisplay")
            board = module.WhisplayBoard()
        except Exception as exc:  # hardware/library failures vary widely by platform
            log.error("Direct display unavailable: %s", exc)
            return False
        board.on_button_press(lambda: self.on_button(True))
        board.on_button_release(lambda: self.on_button(False))
        board.set_backlight(80)
        self.board = board
        log.warning("Using direct display: whisplay-daemon is not running")
        return True

    def write(self, frame: bytes) -> bool:
        if self.board is None:
            return False
        try:
            self.board.draw_image(0, 0, 240, 280, frame)
            return True
        except Exception as exc:  # SPI errors must not crash the launcher
            log.error("Direct draw failed: %s", exc)
            return False

    def close(self) -> None:
        board, self.board = self.board, None
        if board is None:
            return
        try:
            board.cleanup()
        except Exception as exc:  # best effort: we are handing hardware back to the daemon
            log.warning("Board cleanup: %s", exc)
        log.info("Released direct display hardware")
