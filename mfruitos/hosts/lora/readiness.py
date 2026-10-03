"""Is the LoRa radio ready for apps? Read-only and unprivileged.

Used by the Fruit Store, ``mfruitctl catalog`` and the radio setup's
final check. ``find_library`` may run ``ldconfig``; call this off the UI
thread.
"""

from __future__ import annotations

import ctypes.util
import importlib.util
import os

from mfruitos.sdk.radio.settings import load_radio, radio_dir

SETUP_HINT = ("run 'bash ~/.whisplay-os/system/current/scripts/setup-radio.sh' "
              "once over SSH (sudo password needed)")


def radio_status(home: str | None = None) -> dict:
    problems = []
    settings = load_radio(radio_dir(home))
    if settings is None:
        problems.append(f"The radio is not set up: {SETUP_HINT}")
    port = settings.port if settings else "/dev/ttyS0"
    if not os.path.exists(port):
        problems.append(f"{port} is missing (the UART is not enabled yet; a reboot may be pending)")
    elif not os.access(port, os.R_OK | os.W_OK):
        problems.append(f"No permission for {port}: the user must be in the 'dialout' group "
                        "(restart the services or log in again after the setup)")
    if ctypes.util.find_library("codec2") is None:
        problems.append("libcodec2 is not installed (voice needs it)")
    for module, package in (("serial", "python3-serial"), ("cryptography", "python3-cryptography")):
        if importlib.util.find_spec(module) is None:
            problems.append(f"{package} is not installed")
    return {"ready": not problems, "problems": problems,
            "settings": settings.to_dict() if settings else None}
