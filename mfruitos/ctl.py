"""``mfruitctl`` — control MFruit OS from a shell.

    mfruitctl status                  show launcher state
    mfruitctl apps                    list installed apps
    mfruitctl launch <app_id>         open an app
    mfruitctl install <github repo>   install an app from GitHub (progress on the device)
    mfruitctl sideload <path>         install a local package (.tar.gz/.zip/folder)
    mfruitctl catalog                 list the curated catalogue (available/installed/broken)
    mfruitctl catalog <app_id>        install or repair a catalogue app
    mfruitctl jobs                    show the running install/update job
    mfruitctl check                   check for updates
    mfruitctl reload                  rescan apps
    mfruitctl tap|double|hold|quad    simulate a gesture
    mfruitctl next|prev|select|back   simulate a navigation action
    mfruitctl key up|down|enter|...   simulate a key on a keyboard (up down left right
                                      tab enter escape home space)
    mfruitctl screenshot <file.png>   save the current screen
    mfruitctl restart                 restart the launcher
    mfruitctl summon                  bring MFruit OS to the front (daemon desktop entry)
    mfruitctl release                 hand the screen back to the daemon (systemd ExecStopPost)
"""

from __future__ import annotations

import json
import sys

from mfruitos import OS_APP_ID
from mfruitos.paths import resolve_paths

GESTURE_ALIASES = {"tap": "single_click", "double": "double_click", "triple": "triple_click",
                   "hold": "long_press", "quad": "quad_click"}
ACTION_ALIASES = {"next": "next", "prev": "previous", "previous": "previous", "select": "select",
                  "back": "back", "home": "home"}


def _release() -> int:
    """Used by systemd after the launcher stops: if MFruit OS still owns the
    screen (crash), ask the daemon to reclaim it so the device never freezes."""
    from mfruitos.daemon.client import DaemonError, WhisplayDaemonClient
    from mfruitos.system.settings import Settings
    paths = resolve_paths()
    settings = Settings(paths.settings_file)
    settings.load()
    client = WhisplayDaemonClient(settings.get("daemon.socket_path"), timeout=2.0)
    try:
        if client.ping().get("foreground_app_id") == OS_APP_ID:
            client.request_exit(OS_APP_ID)
            print("asked whisplay-daemon to reclaim the screen")
    except DaemonError as exc:
        print(f"daemon not reachable: {exc}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    command, rest = argv[0], argv[1:]
    if command == "release":
        return _release()

    from mfruitos.launcher.control import send
    if command in GESTURE_ALIASES:
        cmd, args = "gesture", {"name": GESTURE_ALIASES[command]}
    elif command in ACTION_ALIASES:
        cmd, args = "action", {"name": ACTION_ALIASES[command]}
    elif command == "key" and rest:
        cmd, args = "key", {"name": rest[0]}
    elif command == "press":
        cmd, args = "button", {"pressed": True}
    elif command == "unpress":
        cmd, args = "button", {"pressed": False}
    elif command == "launch" and rest:
        cmd, args = "launch", {"app_id": rest[0]}
    elif command == "install" and rest:
        cmd, args = "install", {"repository": rest[0]}
    elif command == "sideload" and rest:
        cmd, args = "sideload", {"path": rest[0]}
    elif command == "catalog":
        cmd, args = "catalog", {"app_id": rest[0] if rest else ""}
    elif command == "screenshot":
        cmd, args = "screenshot", {"path": rest[0] if rest else "/tmp/mfruit-screen.png"}
    elif command == "check":
        cmd, args = "check-updates", {}
    elif command in ("status", "apps", "reload", "restart", "summon", "jobs"):
        cmd, args = command, {}
    else:
        print(f"unknown command: {' '.join(argv)}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2
    try:
        response = send(resolve_paths().control_socket, cmd, args)
    except OSError as exc:
        print(f"MFruit OS is not running ({exc})", file=sys.stderr)
        return 1
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
