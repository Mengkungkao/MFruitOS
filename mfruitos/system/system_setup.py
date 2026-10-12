"""The system setup: the parts of mFruit OS that ``scripts/install.sh``
installs as root (systemd units, sudoers and polkit rules, the shutdown hook,
the Whisplay driver, packages).

A System update replaces mFruit OS's code in the user's folder only. The
root-owned ``mfruit-system-apply.service`` (installed by ``install.sh``)
applies the system setup of the running version from its official release
(docs/platform/ADR/0015-system-setup-from-releases.md). This module reads that
service's status and asks systemd to start it through the one sudoers rule
``install.sh`` writes for it; it never runs anything as root itself.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from mfruitos.updater.version import parse_version

log = logging.getLogger(__name__)

UNIT = "mfruit-system-apply.service"
APPLIER = "/usr/local/lib/mfruit-os/mfruit-system-apply"
STATUS_FILE = "/var/lib/mfruit-os/system-setup.json"
LOG_FILE = "/var/lib/mfruit-os/system-setup.log"
# The service downloads a few MB; a new sound card build can take long on a Pi Zero.
APPLY_TIMEOUT_SEC = 50 * 60
# For a device set up before the service existed: once, with the owner's password.
SETUP_COMMAND = "bash ~/.whisplay-os/system/current/scripts/install.sh --system-only"


class SetupError(Exception):
    pass


@dataclass
class SetupStatus:
    installed: bool = False       # mfruit-system-apply is on this device
    version: str = ""             # whose system setup was applied (or last tried)
    result: str = ""              # ok, failed, offline, unsupported; "" never ran
    message: str = ""
    reboot_required: bool = False
    finished_at: float = 0.0
    changed: list = field(default_factory=list)

    def applied(self, version: str) -> bool:
        """Is ``version``'s system setup on the device?"""
        mine = parse_version(self.version)
        return self.result == "ok" and mine is not None and mine == parse_version(version)


def read_status(status_file: str = STATUS_FILE, applier: str = APPLIER) -> SetupStatus:
    status = SetupStatus(installed=os.path.isfile(applier))
    try:
        with open(status_file, encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return status
    if not isinstance(data, dict):
        return status
    for name, kind in (("version", str), ("result", str), ("message", str),
                       ("reboot_required", bool), ("finished_at", (int, float)), ("changed", list)):
        value = data.get(name)
        if isinstance(value, kind):
            setattr(status, name, value)
    return status


def apply(timeout: float = APPLY_TIMEOUT_SEC, status_file: str = STATUS_FILE,
          applier: str = APPLIER) -> SetupStatus:
    """Run the system setup service and wait for it. Worker threads only.
    Raises SetupError with what to show the user."""
    systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
    try:
        result = subprocess.run(["sudo", "-n", systemctl, "start", UNIT], capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SetupError("The system setup is still running; look again later") from None
    except OSError as exc:
        raise SetupError(f"Cannot start the system setup: {exc}") from None
    status = read_status(status_file, applier)
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        log.warning("%s failed (exit %s): %s", UNIT, result.returncode, detail[-300:])
        if "password" in detail or "not allowed" in detail:
            raise SetupError("This device does not permit it yet. Once, from a computer, run on "
                             f"the device: {SETUP_COMMAND}")
        raise SetupError(status.message or detail[-160:] or "The system setup failed")
    log.info("System setup of %s applied (changed: %s)", status.version,
             ", ".join(status.changed) or "nothing")
    return status
