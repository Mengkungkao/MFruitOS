"""mFruit OS power management (platform service, layer C).

One process, ``mfruit-power.service`` (``python3 -m mfruitos.power serve``),
owns the battery board: it samples it, decides when to shut down safely
(low battery, the power button's soft shutdown), applies the board settings,
keeps the clock in step and announces events. The board drivers are in
``mfruitos/hosts/pisugar`` (layer E).

Sockets:
  ~/.whisplay-os/state/power.sock   JSON lines for mFruit OS (launcher,
                                    mfruitctl): status, settings, events
  /tmp/pisugar-server.sock          the PiSugar text protocol, so the
                                    unmodified whisplay-daemon, apps' status
                                    bars and existing scripts keep working

Design and rules: docs/platform/ADR/0012-own-power-management.md.
"""

from __future__ import annotations

import os

SERVICE = "mfruit-power.service"
COMPAT_SOCKET = "/tmp/pisugar-server.sock"

# Events the service sends to subscribers (JSON objects with "event").
STATE = "state"                       # battery state changed
BUTTON = "button"                     # {"tap": single|double|long}
LOW_BATTERY = "low_battery"           # {"level", "seconds_left"}: shutting down soon
LOW_BATTERY_CANCELLED = "low_battery_cancelled"   # {"reason"}
SHUTTING_DOWN = "shutting_down"       # {"reason", "reboot"}
SHUTDOWN_FAILED = "shutdown_failed"   # {"error"}
CONFIG = "config"                     # settings changed


def api_socket(paths) -> str:
    return os.path.join(paths.state_dir, "power.sock")


def config_file(paths) -> str:
    return os.path.join(paths.config_dir, "power.json")
