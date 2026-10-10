"""Health checks and hardware tests. Checks are blocking and run on a worker thread."""

from __future__ import annotations

import logging
import math
import os
import shutil
import socket
import struct
import subprocess
import time
import wave
from dataclasses import dataclass

from mfruitos.daemon.client import DaemonError, WhisplayDaemonClient
from mfruitos.system import system_info

log = logging.getLogger("mfruitos.diagnostics")

MIN_FREE_GB = 0.3


@dataclass
class CheckResult:
    name: str
    ok: bool | None          # None: not applicable / unknown
    detail: str = ""


def check_daemon(client: WhisplayDaemonClient) -> CheckResult:
    start = time.monotonic()
    try:
        client.ping()
    except DaemonError as exc:
        return CheckResult("Hardware service", False, str(exc)[:80])
    ms = (time.monotonic() - start) * 1000
    return CheckResult("Hardware service", True, f"{ms:.0f} ms")


def daemon_ui_in_background() -> bool:
    """True if whisplay-daemon runs through mFruit OS's background wrapper."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fp:
                if b"whisplay-daemon-mfruit" in fp.read():
                    return True
        except OSError:
            continue
    return False


def check_daemon_ui() -> CheckResult:
    if daemon_ui_in_background():
        return CheckResult("Hardware desktop", True, "background")
    return CheckResult("Hardware desktop", None, "visible (run install.sh)")


def check_keyboard(devices: list) -> CheckResult:
    """USB / Bluetooth keyboards mFruit OS is reading (none is fine)."""
    if devices:
        return CheckResult("Keyboard", True, ", ".join(devices))
    return CheckResult("Keyboard", None, "none plugged in")


def check_display(has_focus: bool) -> CheckResult:
    return CheckResult("Display", has_focus, "OK" if has_focus else "no framebuffer")


def check_button(client: WhisplayDaemonClient) -> CheckResult:
    try:
        pressed = client.button_pressed()
    except DaemonError as exc:
        return CheckResult("Button", False, str(exc)[:80])
    return CheckResult("Button", True, "pressed" if pressed else "released")


def check_led(client: WhisplayDaemonClient, current: tuple | None) -> CheckResult:
    try:
        client.set_led(*(current or (0, 0, 0)))
    except DaemonError as exc:
        return CheckResult("RGB LED", False, str(exc)[:80])
    return CheckResult("RGB LED", True, "OK")


def check_audio() -> CheckResult:
    if shutil.which("aplay") is None:
        return CheckResult("Audio", False, "aplay not installed")
    try:
        out = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("Audio", False, str(exc)[:80])
    cards = [l for l in out.splitlines() if l.startswith("card ")]
    if not cards:
        return CheckResult("Audio", False, "no sound card")
    names = [c.split(":", 1)[1].split("[")[0].strip() for c in cards]
    preferred = next((n for n in names if "whisplay" in n.lower() or "wm8960" in n.lower()), names[0])
    return CheckResult("Audio", True, preferred.split()[0][:14])


def check_network() -> CheckResult:
    ip = system_info.local_ip()
    if not system_info.has_default_route() or not ip:
        return CheckResult("Network", False, "not connected")
    return CheckResult("Network", True, ip)


def check_storage(path: str) -> CheckResult:
    _, total, free = system_info.storage_gb(path)
    if total == 0:
        return CheckResult("Storage", None, "unknown")
    return CheckResult("Storage", free >= MIN_FREE_GB, f"{free:.1f} GB free")


def check_internet(host: str = "api.github.com", port: int = 443, timeout: float = 4.0) -> CheckResult:
    try:
        socket.getaddrinfo(host, port)
    except OSError:
        return CheckResult("Internet", False, "DNS lookup failed")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return CheckResult("Internet", False, str(exc)[:60])
    return CheckResult("Internet", True, "OK")


def check_github(github) -> CheckResult:
    try:
        remaining, reset = github.rate_limit()
    except Exception as exc:  # any GitHub failure is a failed check, never a crash
        return CheckResult("GitHub", False, str(exc)[:60])
    if remaining == 0:
        return CheckResult("GitHub", False, f"rate limited until {time.strftime('%H:%M', time.localtime(reset))}")
    return CheckResult("GitHub", True, f"{remaining} calls left")


def make_tone(path: str, hz: int = 660, seconds: float = 0.6, rate: int = 22050) -> str:
    """Write a short sine beep (with fade in/out to avoid clicks)."""
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames = int(rate * seconds)
    fade = int(rate * 0.03)
    data = bytearray()
    for i in range(frames):
        env = min(1.0, i / fade, (frames - i) / fade)
        sample = int(12000 * env * math.sin(2 * math.pi * hz * i / rate))
        data += struct.pack("<h", sample)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(data))
    return path


def play_tone(cache_dir: str, device: str = "") -> CheckResult:
    if shutil.which("aplay") is None:
        return CheckResult("Speaker", False, "aplay not installed")
    path = make_tone(os.path.join(cache_dir, "test-tone.wav"))
    command = ["aplay", "-q"] + (["-D", device] if device else []) + [path]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("Speaker", False, str(exc)[:60])
    if result.returncode != 0:
        return CheckResult("Speaker", False, (result.stderr.strip() or "aplay failed")[:60])
    return CheckResult("Speaker", True, "tone played")
