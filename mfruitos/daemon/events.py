"""Long-lived ``events.subscribe`` stream with automatic reconnect.

MFruit OS subscribes *globally* (no app_id). whisplay-daemon only sends
``desktop_entered``, ``screen_locked`` and ``screen_unlocked`` to global
subscribers, and those are exactly the signals the OS needs to take the
screen back after an app exits. Global subscribers also receive app-scoped
events (button, focus) for every app, so consumers must filter by
``payload.app_id``.

Synthetic events emitted by this module:
  ``_connected``     subscription (re)established
  ``_disconnected``  stream lost (daemon stopped/restarted)
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Callable

from mfruitos.daemon.client import encode_request

log = logging.getLogger("mfruitos.daemon.events")

EventCallback = Callable[[str, dict], None]

MIN_BACKOFF_SEC = 0.5
MAX_BACKOFF_SEC = 5.0


class EventStream:
    def __init__(self, socket_path: str, callback: EventCallback):
        self.socket_path = socket_path
        self.callback = callback
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.connected = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="daemon-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already closed by the peer
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _emit(self, name: str, payload: dict) -> None:
        try:
            self.callback(name, payload)
        except Exception:  # consumer bugs must not kill the stream thread
            log.exception("event callback failed for %s", name)

    def _run(self) -> None:
        backoff = MIN_BACKOFF_SEC
        while not self._stop.is_set():
            try:
                self._subscribe_and_read()
                backoff = MIN_BACKOFF_SEC
            except OSError as exc:
                log.debug("event stream error: %s", exc)
            except ValueError as exc:
                log.warning("event stream protocol error: %s", exc)
            if self.connected:
                self.connected = False
                log.warning("Lost daemon event stream")
                self._emit("_disconnected", {})
            if self._stop.wait(backoff):
                break
            backoff = min(MAX_BACKOFF_SEC, backoff * 2)

    def _subscribe_and_read(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            self._sock = sock
            try:
                sock.settimeout(3.0)
                sock.connect(self.socket_path)
                sock.sendall(encode_request("events.subscribe", {}))
                reader = sock.makefile("rb")
                ack = reader.readline()
                if not ack:
                    raise OSError("subscription closed before ack")
                response = json.loads(ack.decode("utf-8"))
                if not isinstance(response, dict) or not response.get("ok"):
                    raise ValueError(f"subscription rejected: {response!r}")
                # Events can be minutes apart; block without a timeout.
                sock.settimeout(None)
                self.connected = True
                log.info("Subscribed to daemon events")
                self._emit("_connected", {})
                for raw in reader:
                    if self._stop.is_set():
                        return
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        message = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        log.warning("Ignoring malformed event line: %r", raw[:120])
                        continue
                    if not isinstance(message, dict) or not message.get("event"):
                        log.debug("Ignoring unexpected event message: %r", message)
                        continue
                    payload = message.get("payload") or {}
                    self._emit(str(message["event"]), payload if isinstance(payload, dict) else {})
            finally:
                self._sock = None
