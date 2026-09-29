"""A minimal Whisplay app that behaves like the official runtime/whisplay_client.py:
subscribe to its events, acquire the foreground with retries (5 s, every 0.2 s),
draw once, and exit when the daemon sends app_exit_requested.

Usage: fakeapp.py <app_id> <socket> <record_file> [--crash] [--exit-after SEC]
Every lifecycle step is appended to <record_file> as "<event> <pid>".
"""

import json
import mmap
import os
import socket
import sys
import threading
import time

app_id, socket_path, record_file = sys.argv[1:4]
crash = "--crash" in sys.argv
# --linger: on exit, release the screen but keep running (an app that forgets to quit)
linger = "--linger" in sys.argv
exit_after = float(sys.argv[sys.argv.index("--exit-after") + 1]) if "--exit-after" in sys.argv else None
# Real Python apps need 1.5-7 s on a Pi Zero 2 W / Orange Pi before they ask for the screen.
startup = float(sys.argv[sys.argv.index("--startup") + 1]) if "--startup" in sys.argv else 0.0


def record(event):
    with open(record_file, "a") as fp:
        fp.write(f"{event} {os.getpid()}\n")


def request(cmd, payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(socket_path)
        sock.sendall((json.dumps({"version": 1, "cmd": cmd, "payload": payload}) + "\n").encode())
        response = json.loads(sock.makefile().readline())
    if not response.get("ok"):
        raise RuntimeError(response.get("error"))
    return response.get("payload") or {}


record("start")
time.sleep(startup)
if crash:
    record("crash")
    sys.exit(3)

done = threading.Event()


def events():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(socket_path)
        sock.sendall((json.dumps({"version": 1, "cmd": "events.subscribe",
                                  "payload": {"app_id": app_id}}) + "\n").encode())
        reader = sock.makefile()
        reader.readline()
        for line in reader:
            event = json.loads(line).get("event")
            if event == "app_exit_requested":
                record("exit_requested")
                done.set()
            elif event in ("button_pressed", "button_released"):
                record(event)


threading.Thread(target=events, daemon=True).start()
time.sleep(0.1)
deadline = time.time() + 5.0
token = None
while time.time() < deadline:
    try:
        token = request("app.focus.acquire", {"app_id": app_id})["session_token"]
        info = request("framebuffer.acquire", {"app_id": app_id, "session_token": token})
        with open(info["buffer_handle"], "r+b") as fp, mmap.mmap(fp.fileno(), 0) as fb:
            fb[:] = b"\x07\xe0" * (240 * 280)
        break
    except (OSError, RuntimeError) as exc:
        token = None
        record(f"acquire_failed:{str(exc).replace(' ', '_')}")
        time.sleep(0.2)
if token is None:
    record("gave_up")
    sys.exit(1)
record("acquired")
done.wait(exit_after)
try:
    request("app.focus.release", {"app_id": app_id, "session_token": token})
except (OSError, RuntimeError):
    pass
if linger:
    record("released_but_still_running")
    while True:
        time.sleep(1)
record("exit")
