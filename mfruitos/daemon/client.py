"""The single abstraction for talking to whisplay-daemon.

Protocol (see Whisplay APP_INTEGRATION.md): Unix socket, line-delimited JSON,
``{"version": 1, "cmd": ..., "payload": {...}}`` -> ``{"ok": bool, ...}``.
Every request uses a fresh connection with a timeout so a restarted or wedged
daemon can never hang the launcher.

Only commands that exist in whisplay_daemon.py are used:
health.ping, app.register, app.list, app.launch, app.focus.acquire,
app.focus.release, app.exit.request, framebuffer.acquire, backlight.set,
led.set, led.fade, button.get_state, events.subscribe.
"""

from __future__ import annotations

import json
import logging
import socket
from typing import Any

log = logging.getLogger("mfruitos.daemon")

DEFAULT_SOCKET_PATH = "/tmp/whisplay-daemon.sock"
PROTOCOL_VERSION = 1
MAX_RESPONSE_BYTES = 1024 * 1024


class DaemonError(Exception):
    """Base class for daemon communication failures."""


class DaemonUnavailable(DaemonError):
    """The daemon socket is missing, refused the connection or timed out."""


class DaemonProtocolError(DaemonError):
    """The daemon answered with something that is not a valid response."""


class DaemonRequestError(DaemonError):
    """The daemon understood the request and rejected it (``ok: false``)."""


def encode_request(cmd: str, payload: dict | None = None) -> bytes:
    body = {"version": PROTOCOL_VERSION, "cmd": cmd, "payload": payload or {}}
    return (json.dumps(body) + "\n").encode("utf-8")


def read_line(sock: socket.socket, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        data = sock.recv(4096)
        if not data:
            break
        newline = data.find(b"\n")
        if newline >= 0:
            chunks.append(data[:newline])
            break
        chunks.append(data)
        total += len(data)
        if total > limit:
            raise DaemonProtocolError("response too large")
    return b"".join(chunks)


class WhisplayDaemonClient:
    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH, timeout: float = 3.0):
        self.socket_path = socket_path
        self.timeout = timeout

    # ------------------------------------------------------------ transport
    def request(self, cmd: str, payload: dict | None = None,
                timeout: float | None = None) -> dict:
        """Send one command; return the response payload (``{}`` if none)."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout or self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(encode_request(cmd, payload))
                line = read_line(sock)
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise DaemonUnavailable(f"daemon socket unavailable: {exc}") from exc
        except socket.timeout as exc:
            raise DaemonUnavailable(f"daemon timed out on {cmd}") from exc
        except OSError as exc:
            raise DaemonUnavailable(f"daemon connection failed on {cmd}: {exc}") from exc
        if not line.strip():
            raise DaemonProtocolError(f"empty response to {cmd}")
        try:
            response = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DaemonProtocolError(f"malformed response to {cmd}: {line[:120]!r}") from exc
        if not isinstance(response, dict):
            raise DaemonProtocolError(f"unexpected response to {cmd}: {response!r}")
        if not response.get("ok"):
            raise DaemonRequestError(str(response.get("error") or f"{cmd} failed"))
        payload_out = response.get("payload") or {}
        return payload_out if isinstance(payload_out, dict) else {}

    # -------------------------------------------------------------- health
    def ping(self) -> dict:
        return self.request("health.ping", timeout=2.0)

    def is_available(self) -> bool:
        try:
            self.ping()
            return True
        except DaemonError:
            return False

    # ----------------------------------------------------------------- apps
    def register_app(self, app_id: str, display_name: str, **fields: Any) -> dict:
        payload = {"app_id": app_id, "display_name": display_name}
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.request("app.register", payload)

    def unregister_app(self, app_id: str) -> dict:
        """Remove a registration. Needs mFruit OS's daemon wrapper
        (``mfruit.app.unregister``); a plain daemon answers "unknown command"."""
        return self.request("mfruit.app.unregister", {"app_id": app_id})

    def list_apps(self) -> list[dict]:
        apps = self.request("app.list").get("apps", [])
        if not isinstance(apps, list):
            raise DaemonProtocolError("app.list returned a non-list")
        return [a for a in apps if isinstance(a, dict) and a.get("app_id")]

    def launch_app(self, app_id: str) -> dict:
        return self.request("app.launch", {"app_id": app_id})

    def request_exit(self, app_id: str) -> None:
        self.request("app.exit.request", {"app_id": app_id})

    # ---------------------------------------------------------------- focus
    def acquire_focus(self, app_id: str) -> str:
        token = self.request("app.focus.acquire", {"app_id": app_id}).get("session_token")
        if not token:
            raise DaemonProtocolError("app.focus.acquire returned no session_token")
        return str(token)

    def acquire_framebuffer(self, app_id: str, session_token: str) -> dict:
        info = self.request("framebuffer.acquire",
                            {"app_id": app_id, "session_token": session_token})
        for key in ("buffer_handle", "width", "height", "stride"):
            if key not in info:
                raise DaemonProtocolError(f"framebuffer.acquire missing {key}")
        return info

    def release_focus(self, app_id: str, session_token: str) -> None:
        self.request("app.focus.release", {"app_id": app_id, "session_token": session_token})

    # ------------------------------------------------------------- hardware
    def set_backlight(self, brightness: int) -> None:
        self.request("backlight.set", {"brightness": max(0, min(100, int(brightness)))})

    def set_led(self, r: int, g: int, b: int) -> None:
        self.request("led.set", {"r": _byte(r), "g": _byte(g), "b": _byte(b)})

    def fade_led(self, r: int, g: int, b: int, duration_ms: int = 300) -> None:
        self.request("led.fade", {"r": _byte(r), "g": _byte(g), "b": _byte(b),
                                  "duration_ms": max(0, int(duration_ms))})

    def button_pressed(self) -> bool:
        return bool(self.request("button.get_state").get("pressed"))


def _byte(value: int) -> int:
    return max(0, min(255, int(value)))
