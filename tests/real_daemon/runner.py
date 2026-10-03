"""Runs the *real* whisplay-daemon (drivers/whisplay or WHISPLAY_SRC) with a stub board.

Usage: python3 runner.py <whisplay_src> <socket_path> <home> [<mfruit_lock>]

With <mfruit_lock>, MFruit OS's whisplay-daemon-mfruit.py patches are applied
(daemon user interface in the background while MFruit OS runs).

Protocol on stdin/stdout, one line each:
  press | release        -> {"ok": true}
  state                  -> {"foreground": ..., "pending": ..., "selected": ..., "launches": [...],
                             "running": [...]}
Daemon output goes to stderr (the harness captures it).

Only side effects that need real hardware or services are neutralised:
PiSugar detection, the Bluetooth agent and the keyboard reader.
"""

import json
import os
import sys
import threading
import time

whisplay_src, socket_path, home = sys.argv[1:4]
mfruit_lock = sys.argv[4] if len(sys.argv) > 4 else ""
os.environ["HOME"] = home  # daemon_shared resolves ~/.whisplay-daemon at import time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"))
sys.path.insert(1, os.path.join(whisplay_src, "daemon"))

proto = os.fdopen(os.dup(1), "w", buffering=1)
sys.stdout = sys.stderr

import whisplay  # noqa: E402  (the stub)
import whisplay_daemon  # noqa: E402
from daemon_pisugar import PiSugarManager  # noqa: E402
from internal_apps import ExternalKeyboardReader, InternalAppManager  # noqa: E402

PiSugarManager.socket_path = lambda self: None
if hasattr(PiSugarManager, "detect_pisugar3"):  # upstream c73051e probes I2C for a PiSugar 3
    PiSugarManager.detect_pisugar3 = lambda self: False
PiSugarManager.probe_battery_level = lambda self: None
InternalAppManager.start = lambda self: None
InternalAppManager.stop = lambda self: None
InternalAppManager.refresh_async = lambda self, app_id, force=False: None
ExternalKeyboardReader.start = lambda self, callback: None

if mfruit_lock:
    import importlib.util
    shim_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "scripts", "whisplay-daemon-mfruit.py")
    spec = importlib.util.spec_from_file_location("mfruit_shim", shim_path)
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    print("[harness] shim patched:", shim.apply(whisplay_daemon, mfruit_lock), flush=True)

apps_dir = os.path.join(home, ".whisplay-daemon", "app")
os.makedirs(apps_dir, exist_ok=True)
daemon = whisplay_daemon.WhisplayDaemon(socket_path, apps_dir,
                                        os.path.join(home, ".whisplay-daemon", "settings.json"))

launches = []
_original_launch = daemon._launch_app


def recording_launch(app):
    launches.append({"app_id": app.app_id, "t": time.time()})
    print(f"[harness] _launch_app({app.app_id})", flush=True)
    return _original_launch(app)


daemon._launch_app = recording_launch

desktop_renders = [0]
_original_desktop_render = daemon.desktop.render


def counting_desktop_render(*args, **kwargs):
    desktop_renders[0] += 1
    return _original_desktop_render(*args, **kwargs)


daemon.desktop.render = counting_desktop_render

# Trace every foreground change and command, for diagnosing launch races.
T0 = time.time()


def trace(message):
    print(f"[trace {time.time() - T0:8.3f} {threading.current_thread().name}] {message} "
          f"(fg={daemon.foreground_app_id} pending={daemon.pending_launch_app_id})", flush=True)


def wrap(name):
    original = getattr(daemon, name)

    def traced(*args, **kwargs):
        first = args[0] if args else None
        label = getattr(first, "app_id", first if isinstance(first, str) else "")
        trace(f"{name}({label}) begin")
        try:
            return original(*args, **kwargs)
        finally:
            trace(f"{name}({label}) end")
    setattr(daemon, name, traced)


for _name in ("_grant_focus", "_release_focus", "_request_exit"):
    wrap(_name)
_original_handle = daemon.handle_command


def traced_handle(request, conn):
    cmd = request.get("cmd")
    if cmd not in ("health.ping", "app.list", "button.get_state", "led.set", "backlight.set"):
        trace(f"CMD {cmd} {(request.get('payload') or {}).get('app_id', '')}")
    return _original_handle(request, conn)


daemon.handle_command = traced_handle
threading.Thread(target=daemon.start, daemon=True).start()
while not os.path.exists(socket_path):
    time.sleep(0.02)

for line in sys.stdin:
    command = line.strip()
    if command == "press":
        trace("BUTTON press")
        whisplay.BOARD.press()
        reply = {"ok": True}
    elif command == "release":
        trace("BUTTON release")
        whisplay.BOARD.release()
        reply = {"ok": True}
    elif command == "state":
        with daemon.state_lock:
            selected = daemon._current_selected_app()
            reply = {"foreground": daemon.foreground_app_id,
                     "pending": daemon.pending_launch_app_id,
                     "selected": selected.app_id if selected else None,
                     "launches": list(launches),
                     "running": sorted(a.app_id for a in daemon.apps.values() if a.is_running()),
                     "desktop_renders": desktop_renders[0],
                     "lcd": __import__("hashlib").sha1(whisplay.BOARD.last_frame).hexdigest()[:12]}
    elif command == "quit":
        break
    else:
        reply = {"ok": False, "error": f"unknown {command}"}
    proto.write(json.dumps(reply) + "\n")
daemon.stop()
