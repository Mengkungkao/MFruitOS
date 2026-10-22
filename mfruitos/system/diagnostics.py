"""Health checks and hardware tests. Checks are blocking and run on a worker thread."""

from __future__ import annotations

import array
import logging
import math
import operator
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
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


# ------------------------------------------------------------- microphone
# The microphone is recorded the way the Whisplay driver's own ALSA setup
# uses the card: 48 kHz, two channels. Asked for one channel, the Whisplay
# card on an Orange Pi Zero 2W gave the microphone 35 dB down (2026-10-22),
# so a one-channel test would blame a working microphone.
MIC_RATE = 48000
MIC_CHANNELS = 2
WHISPLAY_DRIVER_DIR = "/usr/local/share/whisplay"   # where mFruit OS installs the driver
_MIC_CARDS = ("whisplay", "wm8960", "es8389")
_NOT_A_MIC = ("hdmi", "loopback")
_CARD_LINE = re.compile(r"^card (\d+): (\S+) \[")
SILENT_DB = -120.0
# Peak levels while someone speaks at arm's length: a working Whisplay
# microphone at the default level reaches -20 dBFS and more; room noise
# alone was -35 dBFS. Below -80 dBFS there is no signal at all (an unused
# channel measured -90).
MIC_QUIET_DB = -30.0
MIC_DEAD_DB = -80.0


@dataclass
class MicLevels:
    seconds: float
    left_peak: float           # dBFS
    right_peak: float
    left_rms: float
    right_rms: float

    @property
    def peak(self) -> float:
        return max(self.left_peak, self.right_peak)

    @property
    def side(self) -> str:
        """Where the microphone is: "left", "right" or "both"."""
        if self.left_peak - self.right_peak >= 20:
            return "left"
        if self.right_peak - self.left_peak >= 20:
            return "right"
        return "both"


@dataclass
class MicTest:
    result: CheckResult
    levels: MicLevels | None = None
    audio: bytes = b""          # what was recorded: 48 kHz, 16-bit, stereo
    card: str = ""


def _db(value: float) -> float:
    return 20 * math.log10(value / 32768) if value > 0 else SILENT_DB


def capture_cards() -> list[tuple[int, str]]:
    """(index, name) of every capture card `arecord -l` lists."""
    try:
        out = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    cards = []
    for line in out.splitlines():
        match = _CARD_LINE.match(line)
        if match and (int(match.group(1)), match.group(2)) not in cards:
            cards.append((int(match.group(1)), match.group(2)))
    return cards


def find_microphone() -> tuple[str | None, str]:
    """(ALSA device, card name), or (None, why there is none).

    The Whisplay card first. When the Whisplay driver is installed but its
    card is missing, that is the answer -- not some other card: on
    2026-10-22 the codec did not answer at boot, the card never appeared,
    and a check satisfied by any card said audio was fine.
    """
    cards = [(index, name) for index, name in capture_cards()
             if not any(word in name.lower() for word in _NOT_A_MIC)]
    for index, name in cards:
        if any(word in name.lower() for word in _MIC_CARDS):
            return f"plughw:{index}", name
    if os.path.isdir(WHISPLAY_DRIVER_DIR):
        return None, "Whisplay sound card missing"
    if cards:
        return f"plughw:{cards[0][0]}", cards[0][1]
    return None, "no microphone"


def mic_holder(device: str, proc: str = "/proc") -> str:
    """Name and PID of a process that has `device`'s capture open, or "".

    Only processes we may look into are seen (our own user's); that is
    where a leftover recorder from an app would be.
    """
    match = re.search(r"(\d+)", device or "")
    if not match:
        return ""
    target = f"/dev/snd/pcmC{match.group(1)}D0c"
    try:
        pids = [entry for entry in os.listdir(proc) if entry.isdigit()]
    except OSError:
        return ""
    for pid in pids:
        fd_dir = os.path.join(proc, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(os.path.join(fd_dir, fd)) != target:
                    continue
            except OSError:
                continue
            try:
                with open(os.path.join(proc, pid, "comm")) as fp:
                    name = fp.read().strip()
            except OSError:
                name = "a program"
            return f"{name} ({pid})"
    return ""


def analyse_stereo(raw: bytes) -> MicLevels:
    """Peak and RMS of each channel of 16-bit little-endian stereo."""
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) & ~3])
    if sys.byteorder == "big":
        samples.byteswap()
    channels = []
    for channel in (samples[0::2], samples[1::2]):
        if not channel:
            channels.append((SILENT_DB, SILENT_DB))
            continue
        peak = max(max(channel), -min(channel))
        rms = math.sqrt(sum(map(operator.mul, channel, channel)) / len(channel))
        channels.append((_db(peak), _db(rms)))
    (left_peak, left_rms), (right_peak, right_rms) = channels
    return MicLevels(len(samples) / MIC_CHANNELS / MIC_RATE, left_peak, right_peak,
                     left_rms, right_rms)


def judge_microphone(levels: MicLevels) -> CheckResult:
    """What a recording made while someone spoke says about the microphone."""
    if levels.seconds < 0.5:
        return CheckResult("Microphone", False, "recorded nothing")
    if levels.peak <= MIC_DEAD_DB:
        return CheckResult("Microphone", False, "no sound at all")
    if levels.peak < MIC_QUIET_DB:
        return CheckResult("Microphone", False, f"very quiet ({levels.peak:.0f} dB)")
    where = "" if levels.side == "both" else f", {levels.side}"
    return CheckResult("Microphone", True, f"OK ({levels.peak:.0f} dB{where})")


def _record(device: str, frames: int) -> tuple[bytes, str]:
    """(audio, "") or (b"", what went wrong)."""
    if shutil.which("arecord") is None:
        return b"", "arecord not installed"
    command = ["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", str(MIC_RATE),
               "-c", str(MIC_CHANNELS), "-t", "raw", "-s", str(frames)]
    try:
        done = subprocess.run(command, capture_output=True,
                              timeout=frames / MIC_RATE + 10)
    except (OSError, subprocess.SubprocessError) as exc:
        return b"", str(exc)[:60]
    if done.returncode == 0 and done.stdout:
        return done.stdout, ""
    said = done.stderr.decode("utf-8", "replace").strip().splitlines()
    said = said[-1] if said else f"arecord exited with code {done.returncode}"
    if "busy" in said.lower():
        holder = mic_holder(device)
        return b"", f"busy: used by {holder}" if holder else "busy: another program has it"
    return b"", said[:60]


def check_microphone() -> CheckResult:
    """Quick check for Diagnostics: there is a microphone, it opens and it
    delivers a signal. Whether it hears speech needs Test microphone."""
    device, card = find_microphone()
    if device is None:
        missing = card == "no microphone"
        return CheckResult("Microphone", None if missing else False, card)
    audio, error = _record(device, MIC_RATE // 2)
    if error:
        return CheckResult("Microphone", False, error)
    if analyse_stereo(audio).peak <= MIC_DEAD_DB:
        return CheckResult("Microphone", False, "no signal")
    return CheckResult("Microphone", True, card[:14])


def record_microphone(seconds: int = 3) -> MicTest:
    """Record `seconds` while the user speaks, and judge the levels."""
    device, card = find_microphone()
    if device is None:
        return MicTest(CheckResult("Microphone", False, card))
    audio, error = _record(device, MIC_RATE * seconds)
    if error:
        log.warning("microphone test on %s failed: %s", device, error)
        return MicTest(CheckResult("Microphone", False, error), card=card)
    levels = analyse_stereo(audio)
    result = judge_microphone(levels)
    log.info("microphone test on %s (%s): left %.1f dBFS, right %.1f dBFS -> %s",
             device, card, levels.left_peak, levels.right_peak, result.detail)
    return MicTest(result, levels, audio, card)


def play_recording(audio: bytes, cache_dir: str, device: str = "") -> CheckResult:
    """Play a recording made by record_microphone back on the speaker."""
    if shutil.which("aplay") is None:
        return CheckResult("Speaker", False, "aplay not installed")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "mic-test.wav")
    with wave.open(path, "wb") as out:
        out.setnchannels(MIC_CHANNELS)
        out.setsampwidth(2)
        out.setframerate(MIC_RATE)
        out.writeframes(audio)
    command = ["aplay", "-q"] + (["-D", device] if device else []) + [path]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=len(audio) / (MIC_RATE * 4) + 10)
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("Speaker", False, str(exc)[:60])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if result.returncode != 0:
        return CheckResult("Speaker", False, (result.stderr.strip() or "aplay failed")[:60])
    return CheckResult("Speaker", True, "played back")
