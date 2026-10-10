"""Talk to the power service (launcher, mfruitctl, tests).

``PowerClient`` sends one request per connection. ``PowerEvents`` keeps a
subscription open on its own thread, reconnects with backoff and reports
``_connected`` / ``_disconnected`` like the daemon event stream.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Callable

log = logging.getLogger("mfruitos.power.client")

MIN_BACKOFF_SEC = 1.0
MAX_BACKOFF_SEC = 10.0


class PowerError(Exception):
    """The service answered with an error."""


class PowerClient:
    def __init__(self, path: str, timeout: float = 3.0):
        self.path = path
        self.timeout = timeout

    def request(self, cmd: str, **args) -> dict:
        """Send one request. OSError: the service is not reachable."""
        message = dict(args, cmd=cmd)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            sock.connect(self.path)
            sock.sendall((json.dumps(message) + "\n").encode("utf-8"))
            reader = sock.makefile("rb")
            line = reader.readline(1 << 20)
        if not line:
            raise OSError("power service closed the connection")
        response = json.loads(line.decode("utf-8"))
        if not isinstance(response, dict):
            raise OSError("power service sent a malformed answer")
        return response

    def _ok(self, cmd: str, **args) -> dict:
        response = self.request(cmd, **args)
        if not response.get("ok"):
            raise PowerError(response.get("error") or "power service refused the request")
        return response

    def status(self, details: bool = False) -> dict:
        return self._ok("status", details=details)["status"]

    def set(self, key: str, value) -> dict:
        return self._ok("set", key=key, value=value)["config"]

    def shutdown(self, reboot: bool = False, reason: str = "request") -> None:
        self._ok("shutdown", reboot=reboot, reason=reason)

    def probe(self) -> dict:
        return self._ok("probe")["status"]

    def clock(self, action: str) -> str:
        return self._ok("clock", action=action)["time"]


class PowerEvents:
    def __init__(self, path: str, callback: Callable[[dict], None], name: str = "power-events"):
        self.path = path
        self.callback = callback
        self.name = name
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.connected = False

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _emit(self, event: dict) -> None:
        try:
            self.callback(event)
        except Exception:   # consumer bugs must not kill the stream thread
            log.exception("power event callback failed for %s", event.get("event"))

    def _run(self) -> None:
        backoff = MIN_BACKOFF_SEC
        while not self._stop.is_set():
            try:
                self._subscribe_and_read()
                backoff = MIN_BACKOFF_SEC
            except (OSError, ValueError) as exc:
                log.debug("power event stream: %s", exc)
            if self.connected:
                self.connected = False
                if self._stop.is_set():
                    break
                log.info("Lost the power service event stream")
                self._emit({"event": "_disconnected"})
            if self._stop.wait(backoff):
                break
            backoff = min(MAX_BACKOFF_SEC, backoff * 2)

    def _subscribe_and_read(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            self._sock = sock
            try:
                sock.settimeout(3.0)
                sock.connect(self.path)
                sock.sendall(b'{"cmd": "subscribe"}\n')
                reader = sock.makefile("rb")
                ack = json.loads(reader.readline(1 << 20).decode("utf-8") or "null")
                if not isinstance(ack, dict) or not ack.get("ok"):
                    raise ValueError(f"subscription refused: {ack!r}")
                sock.settimeout(None)
                self.connected = True
                log.info("Subscribed to power events")
                self._emit({"event": "_connected"})
                for raw in reader:
                    if self._stop.is_set():
                        return
                    try:
                        event = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if isinstance(event, dict) and event.get("event"):
                        self._emit(event)
            finally:
                self._sock = None
