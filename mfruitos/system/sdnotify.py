"""Minimal systemd notify protocol (READY / WATCHDOG) without dependencies."""

from __future__ import annotations

import logging
import os
import socket

log = logging.getLogger("mfruitos.sdnotify")


def notify(message: str) -> bool:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
        return True
    except OSError as exc:
        log.debug("sd_notify failed: %s", exc)
        return False


def watchdog_interval() -> float | None:
    """Half of WatchdogSec, if systemd enabled the watchdog for this process."""
    usec = os.environ.get("WATCHDOG_USEC")
    pid = os.environ.get("WATCHDOG_PID")
    if not usec or (pid and pid != str(os.getpid())):
        return None
    try:
        return int(usec) / 1_000_000 / 2
    except ValueError:
        return None
