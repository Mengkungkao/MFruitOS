"""Wi-Fi setup from a phone: PiSugar's sugar-wifi-conf, installed and run by mFruit OS.

sugar-wifi-conf (https://github.com/PiSugar/sugar-wifi-conf, GPL v3, by
PiSugar) is a Bluetooth Low Energy service. The PiSugar app, PiSugar's WeChat
mini-program or its Web Bluetooth page (pisugar.com/sugar-wifi-conf, Chrome)
connect to it to read the device's Wi-Fi name, addresses and "custom info",
to set the Wi-Fi network (SSID and password, guarded by a key), and to run
the "custom commands" of its config file. It also tunnels SSH over
Bluetooth to the local sshd (an SSH login is still needed).

Its config (``custom_config.json``) has two lists: ``info`` items, each with a
``label`` (at most 20 bytes, one BLE packet), a shell ``command`` whose
output is sent and an ``interval`` in seconds; and ``commands``, each a
``label`` and a shell ``command`` a phone may run with the key.

What mFruit OS does around it (docs/platform/ADR/0013-phone-wifi-setup.md):

* installs the newest pinned release whose build runs here (PiSugar's
  v2.3.0 build needs glibc 2.39; v2.2.3 runs from 2.30), checked by SHA-256,
  into the OS home (``system/tools/sugar-wifi-conf/<version>/``); offline
  packs carry it;
* runs it only when wanted -- while Settings > Wi-Fi > Phone Setup is open,
  or also while there is no Wi-Fi, or always -- as the user, never as a root
  service;
* writes its config: device information and commands that go through mFruit
  OS (safe shutdown and restart through the power service);
* uses a random key for this device (shown on the screen) instead of the
  well-known default "pisugar";
* puts Bluetooth back as it was: the tool turns Bluetooth on, sets the
  adapter name and turns pairing off every second while it runs;
* turns the tool's log into the status shown on screen, and never stores the
  Wi-Fi password the tool logs for its deprecated input.

    python3 -m mfruitos.system.wifi_setup install [--offline PACK] [--home DIR]
    python3 -m mfruitos.system.wifi_setup url       the download for this machine
    python3 -m mfruitos.system.wifi_setup config    print the generated config
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import logging.handlers
import os
import platform
import queue
import re
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

from mfruitos import __version__

log = logging.getLogger("mfruitos.wifi_setup")

NAME = "sugar-wifi-conf"
SOURCE = "https://github.com/PiSugar/sugar-wifi-conf"
LICENSE = "GNU General Public License v3.0"


@dataclass(frozen=True)
class Pick:
    version: str
    commit: str
    asset: str
    digest: str
    min_glibc: tuple


# Pinned releases, newest first; each asset with its SHA-256 (as GitHub
# publishes it) and the oldest glibc it runs on. PiSugar's v2.3.0 build needs
# glibc 2.39 (Raspberry Pi OS trixie, Ubuntu 24.04); v2.2.3 runs from glibc
# 2.30 (Bookworm, Ubuntu 22.04) and lacks only v2.3.0's advertising and SSH
# tunnel fixes and its once-a-second "pairing off" guard.
RELEASES = (
    ("2.3.0", "13da41595eb5c5acc24581b75d18f6073f29770a", {
        "aarch64": ("sugar-wifi-conf-aarch64",
                    "6188d4cefeae8ba5a4b361c090ca78624a8d386f09ef8f53f72aed4ca0397812", (2, 39)),
        "armv7l": ("sugar-wifi-conf-armv7",
                   "c3323f65f2187657429b18402ddcdc54d278c845db8720c82d19c63b52e747c3", (2, 39)),
        "armv6l": ("sugar-wifi-conf-armv6",
                   "4f44f5299d8f62ca9d07228aea5386e8b4d5ee5cbc9cd523817043edd5369c5b", (2, 34)),
    }),
    ("2.2.3", "2c578f1163f0b6f55ad4d005c5580b8ddcf92bff", {
        "aarch64": ("sugar-wifi-conf-aarch64",
                    "c1b350f28b5abd3744c1ffdd28b1467d35cd1de57fb6bdab2e7a597ad6273748", (2, 30)),
        "armv7l": ("sugar-wifi-conf-armv7",
                   "a58a3d9709f56c288c0f78d57620e371f37dd7fae2dbda6444935fad9e428bf8", (2, 30)),
        "armv6l": ("sugar-wifi-conf-armv6",
                   "6426dcec8b2ef519cab7418d760fecf5f554d28ac11b294abc95c931eeff3c86", (2, 34)),
    }),
)
MACHINE_ALIASES = {"arm64": "aarch64", "armv8l": "armv7l", "armhf": "armv7l"}
MAX_DOWNLOAD = 20 * 1024 * 1024
KEY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i: easy to type
KEY_LENGTH = 8
LABEL_MAX_BYTES = 20
MODES = ("screen", "offline", "always")
RESTART_DELAYS = (5.0, 15.0, 60.0)
STOP_GRACE_SEC = 3.0

# Status shown on screen.
OFF, UNAVAILABLE, STARTING, WAITING, PHONE, DONE, FAILED = (
    "off", "unavailable", "starting", "waiting", "phone", "done", "failed")


# ============================================================ the binary
def userland_bits() -> int:
    """32 or 64: what this Python, and so the system's userland, is built for."""
    return struct.calcsize("P") * 8


def machine() -> str:
    """The build to download. A 64-bit kernel can run a 32-bit system (the
    32-bit Raspberry Pi OS on a Pi Zero 2 W, 3 or 4 may report aarch64), and
    the program has to match the system's libraries, not the kernel."""
    raw = platform.machine()
    arch = MACHINE_ALIASES.get(raw, raw)
    if arch == "aarch64" and userland_bits() == 32:
        return "armv7l"
    return arch


def glibc() -> tuple | None:
    """This system's glibc version, e.g. (2, 35); None when not glibc."""
    try:
        name, _, version = (os.confstr("CS_GNU_LIBC_VERSION") or "").partition(" ")
    except (ValueError, OSError):
        return None
    if name != "glibc":
        return None
    try:
        return tuple(int(part) for part in version.split(".")[:2])
    except ValueError:
        return None


def choose(arch: str | None = None, libc: tuple | None = None):
    """The newest pinned build that runs here (``Pick``), or None.

    ``arch`` and ``libc`` default to this machine. Offline packs are made on
    a board of the same image, so they pick the same build.
    """
    arch = MACHINE_ALIASES.get(arch, arch) if arch else machine()
    libc = libc if libc is not None else glibc()
    for version, commit, assets in RELEASES:
        entry = assets.get(arch)
        if entry is None:
            continue
        asset, digest, minimum = entry
        if libc is not None and libc >= minimum:
            return Pick(version, commit, asset, digest, minimum)
    return None


def unavailable_reason() -> str:
    arch, libc = machine(), glibc()
    if not any(arch in assets for _version, _commit, assets in RELEASES):
        return f"No build for {platform.machine()}"
    if libc is None:
        return "Needs glibc (PiSugar's builds)"
    return f"Needs glibc 2.30 or newer (this system: {libc[0]}.{libc[1]})"


def download_url(pick: Pick) -> str:
    return f"{SOURCE}/releases/download/v{pick.version}/{pick.asset}"


def tool_dir(paths, pick: Pick | None = None) -> str:
    pick = pick or choose()
    version = pick.version if pick else "none"
    return os.path.join(paths.system_dir, "tools", NAME, version)


def tool_path(paths, pick: Pick | None = None) -> str:
    return os.path.join(tool_dir(paths, pick), NAME)


def installed(paths) -> bool:
    return choose() is not None and os.access(tool_path(paths), os.X_OK)


def offline_file_key(url: str) -> str:
    """The name an offline pack stores a download under (scripts/offline.sh)."""
    return f"{hashlib.sha256(url.encode()).hexdigest()[:16]}-{os.path.basename(url)}"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: str, opener=urllib.request.urlopen) -> None:
    if not url.startswith("https://"):
        raise ValueError("downloads must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": f"mFruitOS/{__version__}"})
    with opener(request, timeout=60) as response, open(target, "wb") as out:
        total = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                raise ValueError("download larger than expected")
            out.write(chunk)


def install(paths, offline_packs=(), opener=urllib.request.urlopen, pick: Pick | None = None) -> str:
    """Install the pinned binary that runs here (offline pack first, else
    GitHub); returns its path.

    The file is checked against its SHA-256 before it is made executable.
    Raises ValueError (no build for this machine, checksum mismatch) or OSError.
    """
    pick = pick or choose()
    if pick is None:
        raise ValueError(f"no {NAME} build runs here: {unavailable_reason()}")
    asset, digest = pick.asset, pick.digest
    target = tool_path(paths, pick)
    if os.path.isfile(target) and _sha256(target) == digest:
        return target
    os.makedirs(tool_dir(paths, pick), exist_ok=True)
    url = download_url(pick)
    temp = f"{target}.part-{os.getpid()}"
    try:
        source = next((os.path.join(pack, "files", offline_file_key(url)) for pack in offline_packs
                       if pack and os.path.isfile(os.path.join(pack, "files",
                                                               offline_file_key(url)))), None)
        if source:
            shutil.copyfile(source, temp)
            origin = f"offline pack {os.path.dirname(os.path.dirname(source))}"
        else:
            _download(url, temp, opener)
            origin = url
        actual = _sha256(temp)
        if actual != digest:
            raise ValueError(f"{asset}: checksum mismatch (got {actual[:12]}…, expected "
                             f"{digest[:12]}…); not installed")
        os.chmod(temp, 0o755)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    with open(os.path.join(tool_dir(paths, pick), "NOTICE"), "w", encoding="utf-8") as fp:
        fp.write(f"{NAME} {pick.version} by PiSugar, {LICENSE}.\n"
                 f"Source: {SOURCE} (tag v{pick.version}, commit {pick.commit}).\n"
                 f"Binary: {asset}, SHA-256 {digest}, from {origin}.\n"
                 "mFruit OS runs it unmodified (docs/platform/ADR/0013-phone-wifi-setup.md).\n")
    _prune(paths, pick.version)
    log.info("%s %s installed from %s", NAME, pick.version, origin)
    return target


def _prune(paths, keep: str) -> None:
    """Remove other versions of the tool (they live only in the OS home)."""
    root = os.path.join(paths.system_dir, "tools", NAME)
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if name != keep and os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)


# ============================================================ its config
def new_key() -> str:
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))


def valid_key(key: object) -> bool:
    return isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9]{6,32}", key) is not None


def default_config(paths) -> dict:
    """mFruit OS's custom_config.json: information about the device, and
    commands that go through mFruit OS (safe shutdown and restart)."""
    ctl = os.path.join(paths.bin_dir, "mfruitctl")
    return {
        "info": [
            {"label": "mFruit OS", "command": f"echo {__version__}", "interval": 3600},
            {"label": "Battery", "command": f"{ctl} power level 2>/dev/null || echo none",
             "interval": 30},
            {"label": "CPU Temp", "command": "awk '{printf \"%.1f C\", $1/1000}' "
             "/sys/class/thermal/thermal_zone0/temp", "interval": 10},
            {"label": "Memory", "command": "free -m | awk 'NR==2{printf \"%s/%sMB\", $3,$2}'",
             "interval": 10},
            {"label": "Up time", "command": "uptime -p | cut -d' ' -f2-", "interval": 60},
        ],
        "commands": [
            {"label": "Restart mFruit OS",
             "command": "sudo -n systemctl restart whisplay-os.service"},
            {"label": "Reboot", "command": f"{ctl} power reboot || sudo -n systemctl reboot"},
            {"label": "Shut down",
             "command": f"{ctl} power shutdown || sudo -n systemctl poweroff"},
        ],
    }


def validate_config(data) -> dict:
    """The tool's config, or ValueError (labels must fit one BLE packet)."""
    if not isinstance(data, dict):
        raise ValueError("expected an object with info and commands")
    clean = {"info": [], "commands": []}
    for kind, fields in (("info", ("label", "command", "interval")), ("commands", ("label", "command"))):
        items = data.get(kind, [])
        if not isinstance(items, list) or len(items) > 32:
            raise ValueError(f"{kind} must be a list of at most 32 items")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"each {kind} entry must be an object")
            label, command = item.get("label"), item.get("command")
            if not isinstance(label, str) or not label or len(label.encode()) > LABEL_MAX_BYTES:
                raise ValueError(f"{kind} label {label!r} must be 1-{LABEL_MAX_BYTES} bytes")
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"{kind} {label!r} needs a command")
            entry = {"label": label, "command": command}
            if kind == "info":
                interval = item.get("interval", 10)
                if isinstance(interval, bool) or not isinstance(interval, int) \
                        or not 1 <= interval <= 86400:
                    raise ValueError(f"info {label!r}: interval must be 1-86400 seconds")
                entry["interval"] = interval
            clean[kind].append(entry)
    return clean


def user_config_path(paths) -> str:
    return os.path.join(paths.config_dir, "sugar-wifi-conf.json")


def write_config(paths) -> str:
    """The config the tool runs with: the user's own file when valid, else mFruit OS's."""
    data = None
    custom = user_config_path(paths)
    if os.path.exists(custom):
        try:
            with open(custom, encoding="utf-8") as fp:
                data = validate_config(json.load(fp))
        except (OSError, ValueError) as exc:
            log.warning("Ignoring %s (%s); using mFruit OS's config", custom, exc)
    data = data or default_config(paths)
    target = os.path.join(paths.state_dir, "sugar-wifi-conf.json")
    temp = f"{target}.tmp"
    with open(temp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    return target


# ============================================================ its log
_HIDE = ("Input write request", "InputSep write", "CustomCommand input write")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LEVEL = re.compile(r"^\[[^\]]*\]\s*|^\S+Z\s+\w+\s+\S+\]\s*")


def redact(line: str) -> str:
    """The line without anything a phone typed (the key, an SSID, a password)."""
    line = _ANSI.sub("", line).rstrip()
    for marker in _HIDE:
        index = line.find(marker)
        if index >= 0:
            return line[:index + len(marker)] + ": [hidden]"
    return line


def parse(line: str):
    """(status, detail) for a line of the tool's log, or None."""
    text = redact(line)
    if "Waiting 10 seconds for Bluetooth" in text or "sugar-wifi-conf starting" in text:
        return STARTING, "Getting Bluetooth ready"
    if "Advertising as" in text or "Advertising via" in text:
        return WAITING, "Waiting for a phone"
    if "subscriber connected" in text and ("WifiName" in text or "NotifyMessage" in text):
        return PHONE, "Phone connected"
    if "NotifyMessage subscriber disconnected" in text or "WifiName subscriber disconnected" in text:
        return WAITING, "Phone left; waiting for a phone"
    match = re.search(r"NotifyMessage sending: (.*)$", text)
    if match:
        message = match.group(1).strip()
        if message.startswith("Successfully connected"):
            return DONE, "Wi-Fi set"
        if message.rstrip(".").lower() in ("invalid key", "wrong input key"):
            return PHONE, "The phone used a wrong key"
        if message.rstrip(".").lower() in ("invalid syntax", "wrong input syntax"):
            return PHONE, "The phone sent an unreadable request"
        return PHONE, f"Wi-Fi not set: {message[:80]}"
    if "SSH_CTRL command: CONNECT" in text:
        return PHONE, "SSH over Bluetooth"
    if re.search(r"\bERROR\b|\bError:", text):
        return FAILED, text.split("]")[-1].strip()[:100]
    return None


# ============================================================ running it
class WifiSetupService:
    """Starts and stops the tool for whoever wants it (screen, offline, always).

    Calls arrive on the UI loop thread; starting and stopping (Bluetooth
    changes, the process) run on one worker thread; the tool's output is read
    on another. ``on_change`` is called on the loop thread (through ``post``).
    ``bluetooth`` must be safe to call from the worker thread: ``settings()``,
    ``set_powered(on)``, ``set_pairable(on)``.
    """

    def __init__(self, paths, settings, post: Callable, call_later: Callable, bluetooth,
                 spawn=subprocess.Popen):
        self.paths = paths
        self.settings = settings
        self.post = post
        self.call_later = call_later
        self.bluetooth = bluetooth
        self.spawn = spawn
        self.on_change: Callable[[], None] = lambda: None
        self.state = OFF
        self.detail = ""
        self.advertised = ""           # the Bluetooth name the tool uses
        self.wanted: set = set()
        self.paused: set = set()
        self._running = False          # loop thread's view: a process is (being) started
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._proc = None
        self._saved_bt: dict | None = None
        self._restarts = 0
        self._restart_timer = None
        self._generation = 0
        self._logger = None

    # ------------------------------------------------------------ queries
    def available(self) -> tuple:
        if choose() is None:
            return False, unavailable_reason()
        if not installed(self.paths):
            return False, "Not installed: run scripts/install.sh (with internet or an offline pack)"
        return True, ""

    def name(self) -> str:
        return self.settings.get("wifi_setup.name") or ""

    def key(self) -> str:
        key = self.settings.get("wifi_setup.key")
        if not valid_key(key):
            key = new_key()
            self.settings.set("wifi_setup.key", key)
        return key

    def renew_key(self) -> str:
        key = new_key()
        self.settings.set("wifi_setup.key", key)
        if self._running:
            self._restart_now()
        return key

    # ------------------------------------------------------------ wanting
    def want(self, reason: str) -> None:
        self.wanted.add(reason)
        self._reconcile()

    def unwant(self, reason: str) -> None:
        self.wanted.discard(reason)
        self._reconcile()

    def pause(self, reason: str) -> None:
        self.paused.add(reason)
        self._reconcile()

    def resume(self, reason: str) -> None:
        self.paused.discard(reason)
        self._reconcile()

    def should_run(self) -> bool:
        return bool(self.wanted) and not self.paused and self.available()[0]

    def _reconcile(self) -> None:
        if self.should_run() and not self._running:
            self._running = True
            self._restarts = 0
            self._set(STARTING, "Getting Bluetooth ready")
            self._submit(self._start)
        elif not self.should_run() and self._running:
            self._running = False
            self._cancel_restart()
            self._submit(self._stop)
        elif not self._running and (self.state != FAILED or not self.wanted):
            self._set(*self._idle_state())   # a failure stays shown while still wanted

    def _idle_state(self) -> tuple:
        """(state, detail) while nothing runs."""
        ok, reason = self.available()
        if self.wanted and not ok:
            return UNAVAILABLE, reason
        if self.wanted and self.paused:
            return OFF, "Paused while Bluetooth settings are open"
        return OFF, ""

    def _restart_now(self) -> None:
        self._submit(self._stop)
        self._submit(self._start)

    def _set(self, state: str, detail: str) -> None:
        if (state, detail) != (self.state, self.detail):
            self.state, self.detail = state, detail
            self.on_change()

    def _post_set(self, generation: int, state: str, detail: str) -> None:
        def apply():
            if generation == self._generation and self._running:
                self._set(state, detail)
        self.post(apply)

    # ------------------------------------------------------------ worker
    def _submit(self, job: Callable[[], None]) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, name="wifi-setup", daemon=True)
            self._worker.start()
        self._jobs.put(job)

    def _work(self) -> None:
        while True:
            job = self._jobs.get()      # one long-lived thread: no idle exit to race with
            try:
                job()
            except Exception as exc:   # isolation boundary: report, keep the worker alive
                log.exception("Phone Wi-Fi setup: %s", exc)
                message = str(exc)[:100] or exc.__class__.__name__
                self.post(lambda m=message: self._failed(m))

    def _start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._generation += 1
        generation = self._generation
        settings = self.bluetooth.settings()
        if self._saved_bt is None:
            self._saved_bt = settings
        if not settings.get("powered"):
            self.bluetooth.set_powered(True)
        name = (self.name() or settings.get("alias") or platform.node() or "mfruit")[:29]
        self.post(lambda: setattr(self, "advertised", name))
        config = write_config(self.paths)
        argv = [tool_path(self.paths), "--name", name, "--key", self.key(), "--config", config]
        env = dict(os.environ, RUST_LOG="info")
        log.info("Phone Wi-Fi setup: starting %s %s as %r", NAME,
                 os.path.basename(os.path.dirname(argv[0])), name)
        self._proc = self.spawn(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, cwd=self.paths.state_dir,
                                text=True, errors="replace", close_fds=True)
        threading.Thread(target=self._read, args=(self._proc, generation), name="wifi-setup-log",
                         daemon=True).start()

    def _read(self, proc, generation: int) -> None:
        logger = self._tool_logger()
        for line in proc.stdout:
            clean = redact(line)
            if clean:
                logger.info(clean)
            parsed = parse(line)
            if parsed is not None:
                self._post_set(generation, *parsed)
        code = proc.wait()
        self.post(lambda: self._exited(generation, code))

    def _stop(self) -> None:
        self._generation += 1           # the old process's exit is not a crash
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=STOP_GRACE_SEC)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=STOP_GRACE_SEC)
        saved, self._saved_bt = self._saved_bt, None
        if saved is not None:
            # Put Bluetooth back as it was: the tool turned pairing off (and on).
            try:
                self.bluetooth.set_pairable(bool(saved.get("pairable")))
                if not saved.get("powered"):
                    self.bluetooth.set_powered(False)
            except Exception as exc:
                log.warning("Phone Wi-Fi setup: could not restore Bluetooth: %s", exc)
        log.info("Phone Wi-Fi setup stopped")
        self.post(lambda: self._set(*self._idle_state())
                  if not self._running and (self.state != FAILED or not self.wanted) else None)

    # ------------------------------------------------------------ loop thread
    def _exited(self, generation: int, code: int) -> None:
        if generation != self._generation or not self._running:
            return
        if self._restarts >= len(RESTART_DELAYS):
            self._failed(f"{NAME} stopped (exit {code}); see logs/wifi-setup.log")
            return
        delay = RESTART_DELAYS[self._restarts]
        self._restarts += 1
        log.warning("Phone Wi-Fi setup: %s exited with %s; starting it again in %.0f s",
                    NAME, code, delay)
        self._set(STARTING, f"Restarting (it stopped with exit {code})")
        self._restart_timer = self.call_later(delay, self._restart_if_wanted)

    def _restart_if_wanted(self) -> None:
        self._restart_timer = None
        if self._running and self.should_run():
            self._submit(self._start)

    def _cancel_restart(self) -> None:
        if self._restart_timer is not None:
            self._restart_timer.cancel()
            self._restart_timer = None

    def _failed(self, message: str) -> None:
        self._set(FAILED, message)
        if self._running:
            self._running = False
            self._cancel_restart()
            self._submit(self._stop)

    def close(self) -> None:
        """Launcher shutdown: stop the tool and put Bluetooth back (bounded)."""
        self.wanted.clear()
        self._running = False
        self._cancel_restart()
        done = threading.Event()
        self._submit(self._stop)
        self._submit(done.set)
        done.wait(timeout=STOP_GRACE_SEC * 3)

    def _tool_logger(self):
        if self._logger is None:
            logger = logging.getLogger("mfruitos.wifi_setup.tool")
            logger.propagate = False
            logger.setLevel(logging.INFO)
            try:
                handler = logging.handlers.RotatingFileHandler(
                    os.path.join(self.paths.logs_dir, "wifi-setup.log"), maxBytes=128 * 1024,
                    backupCount=1, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
                logger.addHandler(handler)
            except OSError as exc:
                log.warning("No wifi-setup.log: %s", exc)
                logger.addHandler(logging.NullHandler())
            self._logger = logger
        return self._logger


# ============================================================ command line
def main(argv=None) -> int:
    from mfruitos.paths import resolve_paths
    parser = argparse.ArgumentParser(prog="python3 -m mfruitos.system.wifi_setup",
                                     description="Phone Wi-Fi setup (PiSugar sugar-wifi-conf)")
    parser.add_argument("--home", help="mFruit OS data directory (default ~/.whisplay-os)")
    sub = parser.add_subparsers(dest="command", required=True)
    install_p = sub.add_parser("install", help="install the pinned binary")
    install_p.add_argument("--offline", action="append", default=[], help="offline pack directory")
    sub.add_parser("url", help="print the download for this machine")
    sub.add_parser("config", help="print the config the tool would run with")
    args = parser.parse_args(argv)
    paths = resolve_paths(args.home)
    if args.command == "url":
        pick = choose()
        if pick is None:
            print(f"no {NAME} build runs here: {unavailable_reason()}", file=sys.stderr)
            return 1
        print(download_url(pick))
        return 0
    if args.command == "config":
        print(json.dumps(default_config(paths), indent=2))
        return 0
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        path = install(paths, args.offline)
    except (OSError, ValueError) as exc:
        print(f"{NAME} not installed: {exc}", file=sys.stderr)
        return 1
    print(f"{NAME} {os.path.basename(os.path.dirname(path))}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
