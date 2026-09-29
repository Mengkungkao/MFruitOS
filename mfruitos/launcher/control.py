"""Local control socket (``~/.whisplay-os/state/control.sock``, mode 0600).

Used by ``mfruitctl``: the daemon-desktop "summon" entry, SSH users
installing apps, and remote/automated testing (inject gestures, take
screenshots). Requests are line-delimited JSON ``{"cmd": ..., "args": {...}}``;
handlers run on the UI thread.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from typing import Callable

log = logging.getLogger("mfruitos.control")

HANDLER_TIMEOUT_SEC = 15.0


class ControlServer:
    def __init__(self, path: str, post: Callable[..., None],
                 handler: Callable[[str, dict], dict]):
        self.path = path
        self._post = post
        self._handler = handler
        self._sock: socket.socket | None = None
        self._running = False

    def start(self) -> bool:
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            old_umask = os.umask(0o177)
            try:
                sock.bind(self.path)
            finally:
                os.umask(old_umask)
            os.chmod(self.path, 0o600)
            sock.listen(4)
        except OSError as exc:
            log.error("Control socket unavailable: %s", exc)
            return False
        self._sock = sock
        self._running = True
        threading.Thread(target=self._accept, name="control", daemon=True).start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _accept(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            try:
                conn.settimeout(5.0)
                line = conn.makefile("rb").readline(65536)
                request = json.loads(line.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                cmd = str(request.get("cmd", ""))
                args = request.get("args") or {}
                response = self._dispatch(cmd, args if isinstance(args, dict) else {})
            except (OSError, ValueError, UnicodeDecodeError) as exc:
                response = {"ok": False, "error": f"bad request: {exc}"}
            try:
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            except OSError:
                pass

    def _dispatch(self, cmd: str, args: dict) -> dict:
        done = threading.Event()
        box: dict = {}

        def run():
            try:
                box["result"] = self._handler(cmd, args)
            except Exception as exc:  # report handler bugs to the client, keep serving
                log.exception("Control command %s failed", cmd)
                box["result"] = {"ok": False, "error": str(exc)}
            finally:
                done.set()
        self._post(run)
        if not done.wait(HANDLER_TIMEOUT_SEC):
            return {"ok": False, "error": "timed out waiting for the UI thread"}
        return box["result"]


def send(path: str, cmd: str, args: dict | None = None, timeout: float = 20.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall((json.dumps({"cmd": cmd, "args": args or {}}) + "\n").encode())
        data = sock.makefile("rb").readline()
    return json.loads(data.decode("utf-8")) if data else {"ok": False, "error": "no response"}
