"""On a board: does mFruit OS stop listing an app as running once it has exited?

KI-16 (docs/quality/KNOWN_ISSUES.md). Run on the board as the mFruit OS user:

    python3 tests/device/keep_running_exit.py [APP_ID]   (default radioconnect)

It closes APP_ID if it runs (an app adopted after a launcher restart is timed
too), launches it through mFruit OS, asks it to exit through the daemon, and
reports how long `mfruitctl apps` keeps calling it running, without
`mfruitctl reload`. Exit status 0 when the listing clears within 30 s. It
leaves the app closed: open it again afterwards if it was in use.
"""
import json
import os
import socket
import subprocess
import sys
import time

APP = sys.argv[1] if len(sys.argv) > 1 else "radioconnect"


def ctl(*args):
    return json.loads(subprocess.run(["mfruitctl", *args], capture_output=True, text=True).stdout)


def listed_running():
    apps = ctl("apps")
    apps = apps.get("apps", apps) if isinstance(apps, dict) else apps
    return next((bool(a.get("running")) for a in apps if a.get("id") == APP), None)


def session_state():
    session = ctl("status").get("session") or {}
    return session.get("app"), session.get("state"), session.get("source")


def process_alive():
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fp:
                    if fp.read().startswith(b"python3\0-m\0app.main"):
                        return True
            except OSError:
                pass
    return False


def exit_request():
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    s.connect("/tmp/whisplay-daemon.sock")
    s.sendall((json.dumps({"version": 1, "cmd": "app.exit.request",
                           "payload": {"app_id": APP}}) + "\n").encode())
    s.recv(4096)
    s.close()


def wait(predicate, limit):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return predicate()


# 1. A clean start: not running, launched by mFruit OS (kind "app", not adopted).
if process_alive():
    print("already running (after a launcher restart: adopted) | session", session_state())
    exit_request()
    t0 = time.monotonic()
    wait(lambda: not process_alive(), 20)
    cleared = wait(lambda: listed_running() is False, 30)
    print(f"adopted app: mFruit OS lists it not running: {cleared} after "
          f"{time.monotonic() - t0:.1f} s (without reload)")
print("before launch: listed running =", listed_running(), "| session", session_state())
subprocess.run(["mfruitctl", "launch", APP], capture_output=True)
ok = wait(lambda: session_state()[1] == "RUNNING" and process_alive(), 60)
print("launched:", ok, "| session", session_state(), "| listed running =", listed_running())
if not ok:
    sys.exit(2)
time.sleep(5)   # let it settle on its first screen (not a synchronisation fix: the test is about after exit)

# 2. Ask it to exit, then watch mFruit OS's own listing.
exit_request()
t0 = time.monotonic()
wait(lambda: not process_alive(), 20)
gone = time.monotonic() - t0
cleared = wait(lambda: listed_running() is False, 30)
print(f"process gone after {gone:.1f} s; mFruit OS lists it not running: {cleared} "
      f"after {time.monotonic() - t0:.1f} s (without reload)")
sys.exit(0 if cleared else 1)
