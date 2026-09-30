"""Keyboard presence detection for Wi-Fi setup.

InputController owns input decoding and device reading; this module only
detects whether a keyboard is available for entering network details.

The presence filter below requires the full letter row, excluding HDMI-CEC
remotes and other devices that also claim a keyboard handler.
"""

from __future__ import annotations

import os
import struct

LETTER_KEYCODES = tuple(range(16, 26)) + tuple(range(30, 39)) + tuple(range(44, 51))


def has_letter_keys(key_bits: str) -> bool:
    """The kernel prints capability bitmaps as unsigned longs, most
    significant word first, so word width follows the userspace long."""
    words = key_bits.split()
    if not words:
        return False
    word_bits = struct.calcsize("l") * 8
    bitmap = 0
    for index, word in enumerate(reversed(words)):
        try:
            bitmap |= int(word, 16) << (word_bits * index)
        except ValueError:
            return False
    return all((bitmap >> code) & 1 for code in LETTER_KEYCODES)


def keyboard_event_names(devices_text: str) -> list[str]:
    """eventN names of real keyboards in /proc/bus/input/devices. HDMI-CEC
    receivers also claim a kbd handler but only carry remote keys, and
    udev gives them no *-kbd link, so filter on capabilities instead."""
    names: list[str] = []
    for block in devices_text.split("\n\n"):
        handlers: list[str] = []
        key_bits = ""
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
            elif line.startswith("B: KEY="):
                key_bits = line.split("=", 1)[1]
        if "kbd" not in handlers or not has_letter_keys(key_bits):
            continue
        names += [token for token in handlers if token.startswith("event") and token not in names]
    return names


def keyboard_device_paths() -> list[str]:
    try:
        with open("/proc/bus/input/devices", "r", encoding="utf-8") as fp:
            text = fp.read()
    except OSError:
        return []
    paths = [os.path.join("/dev/input", name) for name in keyboard_event_names(text)]
    return [path for path in paths if os.access(path, os.R_OK)]
