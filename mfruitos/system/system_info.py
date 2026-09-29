"""Cheap system metrics from /proc and /sys. Nothing here spawns processes
except the optional SSID lookup, which is cached."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

_ssid_cache: tuple[float, str | None] = (0.0, None)


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return ""


def device_model() -> str:
    model = _read("/proc/device-tree/model").strip("\x00\n ")
    return model or os.uname().machine


def cpu_name() -> str:
    text = _read("/proc/cpuinfo")
    parts = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            parts.setdefault(key.strip(), value.strip())
    if "model name" in parts:
        return parts["model name"]
    implementer, part = parts.get("CPU implementer"), parts.get("CPU part")
    arm = {"0xd03": "Cortex-A53", "0xd04": "Cortex-A35", "0xd05": "Cortex-A55",
           "0xd07": "Cortex-A57", "0xd08": "Cortex-A72", "0xd0b": "Cortex-A76"}
    if implementer == "0x41" and part in arm:
        return f"ARM {arm[part]}"
    return os.uname().machine


def cpu_count() -> int:
    return os.cpu_count() or 1


def memory_mb() -> tuple[int, int]:
    """(used, total) in MB, where used excludes cache (MemTotal - MemAvailable)."""
    info = {}
    for line in _read("/proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            info[parts[0].rstrip(":")] = int(parts[1])
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    return (max(0, total - available) // 1024, total // 1024)


def storage_gb(path: str = "/") -> tuple[float, float, float]:
    """(used, total, free) in GB."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return (0.0, 0.0, 0.0)
    gb = 1024 ** 3
    return (usage.used / gb, usage.total / gb, usage.free / gb)


def temperature_c() -> float | None:
    raw = _read("/sys/class/thermal/thermal_zone0/temp").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value / 1000.0 if value > 1000 else value


def uptime_seconds() -> float:
    try:
        return float(_read("/proc/uptime").split()[0])
    except (IndexError, ValueError):
        return 0.0


def load_average() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return 0.0


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def local_ip() -> str | None:
    """IP of the interface holding the default route (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("0.") else ip


def has_default_route() -> bool:
    for line in _read("/proc/net/route").splitlines()[1:]:
        fields = line.split()
        if len(fields) > 2 and fields[1] == "00000000":
            return True
    return False


def wifi_level() -> int | None:
    """0..3 like the daemon's status icon; None if there is no wireless interface."""
    lines = _read("/proc/net/wireless").splitlines()[2:]
    if not lines:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            quality = float(parts[2].rstrip("."))
        except ValueError:
            continue
        if quality <= 0:
            continue
        return 3 if quality >= 55 else 2 if quality >= 35 else 1
    return 0


def wifi_ssid(max_age: float = 30.0) -> str | None:
    global _ssid_cache
    now = time.monotonic()
    if now - _ssid_cache[0] < max_age:
        return _ssid_cache[1]
    ssid = None
    for command in (["iwgetid", "-r"], ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]):
        if shutil.which(command[0]) is None:
            continue
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if command[0] == "nmcli":
            out = next((l.split(":", 1)[1] for l in out.splitlines() if l.startswith("yes:")), "")
        if out.strip():
            ssid = out.strip()
            break
    _ssid_cache = (now, ssid)
    return ssid


def gather() -> dict:
    used_mb, total_mb = memory_mb()
    used_gb, total_gb, free_gb = storage_gb()
    return {
        "model": device_model(),
        "cpu": cpu_name(),
        "cores": cpu_count(),
        "load": load_average(),
        "ram_used_mb": used_mb,
        "ram_total_mb": total_mb,
        "disk_used_gb": used_gb,
        "disk_total_gb": total_gb,
        "disk_free_gb": free_gb,
        "temperature_c": temperature_c(),
        "uptime": uptime_seconds(),
        "ip": local_ip(),
        "online": has_default_route(),
        "wifi_level": wifi_level(),
        "ssid": wifi_ssid(),
        "hostname": socket.gethostname(),
        "kernel": os.uname().release,
    }
