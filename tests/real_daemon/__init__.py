"""Harness that runs the real whisplay-daemon code with a simulated board."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# The daemon mFruit OS ships (drivers/whisplay). WHISPLAY_SRC replaces it, e.g.
# with a newer PiSugar/Whisplay checkout; a WHISPLAY_SRC without a daemon skips
# the real-daemon tests (the Python 3.9 CI job sets /nonexistent).
BUNDLED = os.path.join(os.path.dirname(os.path.dirname(HERE)), "drivers", "whisplay")


def find_whisplay_src() -> str | None:
    path = os.environ.get("WHISPLAY_SRC") or BUNDLED
    if os.path.isfile(os.path.join(path, "daemon", "whisplay_daemon.py")):
        return path
    return None


class RealDaemon:
    def __init__(self, home: str):
        self.home = home
        self.socket_path = os.path.join(home, "daemon.sock")
        self.apps_dir = os.path.join(home, ".whisplay-daemon", "app")
        self.record_dir = os.path.join(home, "records")
        os.makedirs(self.apps_dir, exist_ok=True)
        os.makedirs(self.record_dir, exist_ok=True)
        self.proc = None
        self.log_path = os.path.join(home, "daemon.log")

    def add_app(self, app_id: str, priority: int = 0, *flags: str) -> None:
        """Persist an app entry, as an install script would, before the daemon starts."""
        record = os.path.join(self.record_dir, f"{app_id}.txt")
        command = " ".join([sys.executable, os.path.join(HERE, "fakeapp.py"), app_id,
                            self.socket_path, record, *flags])
        with open(os.path.join(self.apps_dir, f"{app_id}.json"), "w") as fp:
            json.dump({"app_id": app_id, "display_name": app_id.title(), "icon": app_id[:2].upper(),
                       "launch_command": command, "cwd": self.home, "priority": priority,
                       "persist": True, "exit_gesture": "quad_click"}, fp)

    def start(self, whisplay_src: str, mfruit_lock: str = "") -> "RealDaemon":
        extra = [mfruit_lock] if mfruit_lock else []
        with open(self.log_path, "w") as log:
            self.proc = subprocess.Popen([sys.executable, os.path.join(HERE, "runner.py"), whisplay_src,
                                          self.socket_path, self.home, *extra],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                         text=True, bufsize=1)
        deadline = time.time() + 15
        while not os.path.exists(self.socket_path):
            if self.proc.poll() is not None or time.time() > deadline:
                self.stop()
                raise RuntimeError(f"real daemon failed to start; see {self.log_path}")
            time.sleep(0.05)
        return self

    def _cmd(self, command: str) -> dict:
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def press(self):
        return self._cmd("press")

    def release(self):
        return self._cmd("release")

    def state(self) -> dict:
        return self._cmd("state")

    def launched(self) -> list[str]:
        return [item["app_id"] for item in self.state()["launches"]]

    def records(self, app_id: str) -> list[str]:
        try:
            with open(os.path.join(self.record_dir, f"{app_id}.txt")) as fp:
                return [line.split()[0] for line in fp if line.strip()]
        except FileNotFoundError:
            return []

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("quit\n")
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        if self.proc:
            self.proc.stdin.close()
            self.proc.stdout.close()
        subprocess.run(["pkill", "-f", os.path.join(HERE, "fakeapp.py") + " "], check=False)


def new_home() -> str:
    return tempfile.mkdtemp(prefix="mfruit-realdaemon-")
