"""The power service's sockets and event loop (one thread, ``selectors``).

API socket (``state/power.sock``, mode 0600), one JSON object per line::

    {"cmd": "ping"}                          -> {"ok": true, "version": ...}
    {"cmd": "status", "details": false}      -> {"ok": true, "status": {...}}
    {"cmd": "subscribe"}                     -> {"ok": true}, then events
    {"cmd": "set", "key": K, "value": V}     -> {"ok": true, "config": {...}}
    {"cmd": "probe"}                         -> {"ok": true, "status": {...}}
    {"cmd": "shutdown", "reboot": false}     -> {"ok": true}
    {"cmd": "clock", "action": "save"|"load"} -> {"ok": true, "time": ...}

Errors answer ``{"ok": false, "error": "..."}``. Events are JSON objects with
an ``event`` key (``mfruitos.power`` lists them). The PiSugar socket
(``compat.py``) is served by the same loop.
"""

from __future__ import annotations

import json
import logging
import os
import selectors
import socket
import subprocess
import threading
import time
from collections import deque
from typing import Callable

from mfruitos import __version__, power
from mfruitos.hosts.pisugar.base import Unsupported
from mfruitos.power.compat import Compat
from mfruitos.power.service import drop_ambient_caps
from mfruitos.system.settings import Invalid

log = logging.getLogger("mfruitos.power.server")

MAX_CLIENTS = 32
MAX_LINE = 8192
HOOK_TIMEOUT_SEC = 60.0
MAX_WAIT_SEC = 30.0


class _Conn:
    def __init__(self, sock: socket.socket, kind: str):
        self.sock = sock
        self.kind = kind              # "api" or "compat"
        self.inbuf = bytearray()
        self.outbuf = bytearray()
        self.subscribed = False
        self.closing = False


def compat_socket_in_use(path: str) -> bool:
    """True when another server answers on ``path`` (e.g. PiSugar's own)."""
    if not os.path.exists(path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(path)
        return True
    except OSError:
        return False


class PowerServer:
    def __init__(self, service, api_path: str, compat_path: str | None = None,
                 monotonic: Callable[[], float] = time.monotonic, run_hook=None):
        self.service = service
        self.compat = Compat(service)
        self.api_path = api_path
        self.compat_path = compat_path
        self.monotonic = monotonic
        self.run_hook = run_hook or self._run_hook
        self.selector = selectors.DefaultSelector()
        self._listeners: dict = {}
        self._conns: dict = {}
        self._posted: deque = deque()
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        self.selector.register(self._wake_r, selectors.EVENT_READ, ("wake", None))
        self._periodic: list = []
        self._stop = threading.Event()
        service.post = self.post
        if hasattr(service.runner, "post"):
            service.runner.post = self.post
        service.on_event = self.broadcast
        self._update_tap_listeners()

    # ------------------------------------------------------------ setup
    def _listen(self, path: str, kind: str) -> None:
        if os.path.exists(path):
            os.unlink(path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old_umask = os.umask(0o177)
        try:
            sock.bind(path)
        finally:
            os.umask(old_umask)
        os.chmod(path, 0o600)
        sock.listen(8)
        sock.setblocking(False)
        self._listeners[sock] = (path, kind)
        self.selector.register(sock, selectors.EVENT_READ, ("listen", kind))

    def bind(self) -> list:
        """Open the sockets. The API socket is required; returns warnings."""
        warnings = []
        os.makedirs(os.path.dirname(self.api_path), mode=0o700, exist_ok=True)
        self._listen(self.api_path, "api")
        if self.compat_path:
            if compat_socket_in_use(self.compat_path):
                warnings.append(f"{self.compat_path} is served by another program "
                                "(PiSugar's pisugar-server?); PiSugar protocol not offered")
            else:
                try:
                    self._listen(self.compat_path, "compat")
                except OSError as exc:
                    warnings.append(f"PiSugar protocol socket {self.compat_path} unavailable: "
                                    f"{exc.strerror or exc}")
        for warning in warnings:
            log.warning(warning)
        return warnings

    def every(self, interval: float, fn: Callable[[], None]) -> None:
        self._periodic.append([interval, self.monotonic() + interval, fn])

    def post(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` on the loop thread (safe from any thread)."""
        self._posted.append(fn)
        try:
            os.write(self._wake_w, b"x")
        except (BlockingIOError, OSError):
            pass

    def stop(self) -> None:
        self._stop.set()
        self.post(lambda: None)

    # ------------------------------------------------------------ loop
    def run(self) -> None:
        while not self._stop.is_set():
            self.run_once()

    def run_once(self, max_wait: float = MAX_WAIT_SEC) -> None:
        now = self.monotonic()
        deadlines = [due for due in (self.service.due(),) if due is not None]
        deadlines += [item[1] for item in self._periodic]
        wait = max_wait if not deadlines else max(0.0, min(min(deadlines) - now, max_wait))
        if self._posted:
            wait = 0.0
        for key, mask in self.selector.select(wait):
            kind, extra = key.data
            try:
                if kind == "wake":
                    try:
                        os.read(self._wake_r, 4096)
                    except BlockingIOError:
                        pass
                elif kind == "listen":
                    self._accept(key.fileobj, extra)
                elif kind == "conn":
                    self._io(extra, mask)
            except Exception:   # isolation boundary: one client must not stop the loop
                log.exception("power server: error handling %s", kind)
        while self._posted:
            fn = self._posted.popleft()
            try:
                fn()
            except Exception:
                log.exception("power server: posted call failed")
        now = self.monotonic()
        due = self.service.due()
        if due is not None and now >= due:
            try:
                self.service.tick(now)
            except Exception:   # a driver bug must not kill the service
                log.exception("power service tick failed")
        for item in self._periodic:
            if now >= item[1]:
                item[1] = now + item[0]
                try:
                    item[2]()
                except Exception:
                    log.exception("power server: periodic call failed")

    def _accept(self, listener: socket.socket, kind: str) -> None:
        try:
            sock, _ = listener.accept()
        except (BlockingIOError, OSError):
            return
        if len(self._conns) >= MAX_CLIENTS:
            sock.close()
            return
        sock.setblocking(False)
        conn = _Conn(sock, kind)
        self._conns[sock] = conn
        self.selector.register(sock, selectors.EVENT_READ, ("conn", conn))

    def _io(self, conn: _Conn, mask: int) -> None:
        if mask & selectors.EVENT_READ:
            try:
                data = conn.sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                data = None
            except OSError:
                data = b""
            if data == b"":
                self._close(conn)
                return
            if data:
                conn.inbuf += data
                while b"\n" in conn.inbuf:
                    raw, _, rest = bytes(conn.inbuf).partition(b"\n")
                    conn.inbuf = bytearray(rest)
                    self._request(conn, raw.decode("utf-8", "replace").strip())
                if len(conn.inbuf) > MAX_LINE:
                    self._close(conn)
                    return
        if mask & selectors.EVENT_WRITE:
            self._flush(conn)

    def _send(self, conn: _Conn, text: str) -> None:
        if conn.sock.fileno() < 0:
            return
        conn.outbuf += (text + "\n").encode("utf-8")
        if len(conn.outbuf) > 256 * 1024:   # a client that never reads
            self._close(conn)
            return
        self._flush(conn)

    def _flush(self, conn: _Conn) -> None:
        try:
            while conn.outbuf:
                sent = conn.sock.send(conn.outbuf)
                del conn.outbuf[:sent]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self._close(conn)
            return
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if conn.outbuf else 0)
        try:
            self.selector.modify(conn.sock, events, ("conn", conn))
        except (KeyError, ValueError):
            pass

    def _close(self, conn: _Conn) -> None:
        self._conns.pop(conn.sock, None)
        try:
            self.selector.unregister(conn.sock)
        except (KeyError, ValueError):
            pass
        try:
            conn.sock.close()
        except OSError:
            pass

    # ------------------------------------------------------------ requests
    def _request(self, conn: _Conn, line: str) -> None:
        if not line:
            return
        if conn.kind == "compat":
            answer = self.compat.handle(line)
            if answer:
                self._send(conn, answer)
            self._update_tap_listeners()
            return
        request: dict = {}
        try:
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise ValueError("request must be a JSON object")
            request = parsed
            response = self._api(conn, request)
        except ValueError as exc:
            response = {"ok": False, "error": f"bad request: {exc}"}
        except (Invalid, Unsupported) as exc:
            response = {"ok": False, "error": str(exc)}
        except KeyError as exc:
            response = {"ok": False, "error": f"unknown setting {exc}"}
        except OSError as exc:
            response = {"ok": False, "error": f"battery board error: {exc}"}
        self._send(conn, json.dumps(response))
        if response.get("ok") and request.get("cmd") == "subscribe":
            self._send(conn, json.dumps({"event": power.STATE, "state": self.service.view()}))
            self._send(conn, json.dumps({"event": power.CONFIG,
                                         "config": self.service.public_config()}))

    def _api(self, conn: _Conn, request: dict) -> dict:
        cmd = request.get("cmd")
        service = self.service
        if cmd == "ping":
            return {"ok": True, "version": __version__}
        if cmd == "status":
            return {"ok": True, "status": service.status(details=bool(request.get("details")))}
        if cmd == "subscribe":
            conn.subscribed = True
            return {"ok": True}
        if cmd == "set":
            key = request.get("key")
            if not isinstance(key, str) or key == "tap_hooks":
                raise ValueError("set needs a setting name")
            service.set_option(key, request.get("value"))
            self._update_tap_listeners()
            return {"ok": True, "config": service.public_config()}
        if cmd == "probe":
            service.probe()
            return {"ok": True, "status": service.status()}
        if cmd == "shutdown":
            service.request_shutdown(reboot=bool(request.get("reboot")),
                                     reason=str(request.get("reason") or "request")[:40])
            return {"ok": True}
        if cmd == "clock":
            action = request.get("action")
            if action == "save":
                return {"ok": True, "time": service.save_clock()}
            if action == "load":
                return {"ok": True, "time": service.load_clock()}
            raise ValueError("clock action must be save or load")
        raise ValueError(f"unknown command {cmd!r}")

    # ------------------------------------------------------------ events
    def _update_tap_listeners(self) -> None:
        self.service.extra_tap_listeners = self.compat.hooks_wanting_taps()

    def broadcast(self, event: dict) -> None:
        line = json.dumps(event)
        for conn in list(self._conns.values()):
            if conn.kind == "api" and conn.subscribed:
                self._send(conn, line)
            elif conn.kind == "compat" and event.get("event") == power.BUTTON:
                self._send(conn, event["tap"])
        if event.get("event") == power.BUTTON:
            hook = self.service.config.get("tap_hooks").get(event["tap"], {})
            if hook.get("enabled") and hook.get("shell"):
                self.run_hook(hook["shell"], event["tap"])
        elif event.get("event") == power.CONFIG:
            self._update_tap_listeners()

    def _run_hook(self, shell: str, tap: str) -> None:
        def work():
            try:
                result = subprocess.run(["/bin/sh", "-c", shell], capture_output=True, text=True,
                                        timeout=HOOK_TIMEOUT_SEC, stdin=subprocess.DEVNULL,
                                        preexec_fn=drop_ambient_caps)
                if result.returncode:
                    log.warning("%s press hook exited %s: %s", tap, result.returncode,
                                (result.stderr or "").strip()[:200])
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("%s press hook failed: %s", tap, exc)
        threading.Thread(target=work, name="power-hook", daemon=True).start()

    # ------------------------------------------------------------ teardown
    def close(self) -> None:
        for conn in list(self._conns.values()):
            self._close(conn)
        for sock, (path, _kind) in list(self._listeners.items()):
            try:
                self.selector.unregister(sock)
            except (KeyError, ValueError):
                pass
            sock.close()
            try:
                os.unlink(path)
            except OSError:
                pass
        self._listeners.clear()
        try:
            self.selector.unregister(self._wake_r)
        except (KeyError, ValueError):
            pass
        self.selector.close()
        for fd in (self._wake_r, self._wake_w):
            try:
                os.close(fd)
            except OSError:
                pass
