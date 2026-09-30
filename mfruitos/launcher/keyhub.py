"""The key hub: MFruit OS hands keyboard keys to the app that owns the screen.

While MFruit OS runs it holds every keyboard exclusively (``KeyReader``
with ``grab=True``), so no key reaches the Linux console, whisplay-daemon or
any other reader. Apps built on the MFruit App SDK connect here
(``state/keys.sock``), say which app they are, and receive the keys meant
for them -- only while they own the screen. The runtime decides where each
key goes (``Runtime._on_hardware_key``); this module only carries them.

Protocol, one JSON object per line:

    app -> hub   {"app_id": "whisplay-lora-messenger"}
    hub -> app   {"type": "keyboards", "devices": ["event3"]}
                 {"type": "key", "kind": "key", "value": "enter", "action": 1, "code": 28}
"""

from __future__ import annotations

import json
import logging
import os
import select
import socket
import threading

log = logging.getLogger("mfruitos.keyhub")

HELLO_TIMEOUT_SEC = 3.0
SEND_TIMEOUT_SEC = 0.5


class KeyHub:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self._server: socket.socket | None = None
        self._clients: dict[str, list[socket.socket]] = {}
        self._lock = threading.Lock()
        self._devices: list[str] = []
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        try:
            os.unlink(self.socket_path)          # left behind by a crash
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        server.listen(8)
        self._server = server
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, name="key-hub", daemon=True)
        self._thread.start()
        log.info("Key hub on %s", self.socket_path)

    def stop(self) -> None:
        self._running = False
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            server.close()
        with self._lock:
            clients = [c for conns in self._clients.values() for c in conns]
            self._clients.clear()
        for conn in clients:
            _close(conn)
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ------------------------------------------------------------- sending
    def connected(self, app_id: str) -> bool:
        with self._lock:
            return bool(self._clients.get(app_id))

    def apps(self) -> list[str]:
        with self._lock:
            return sorted(app for app, conns in self._clients.items() if conns)

    def send(self, app_id: str, event) -> bool:
        """Deliver one key to ``app_id``. False if the app is not listening."""
        line = _line({"type": "key", "kind": event.kind, "value": event.value,
                      "action": int(event.action), "code": int(event.code)})
        with self._lock:
            conns = list(self._clients.get(app_id, ()))
        delivered = False
        for conn in conns:
            delivered = self._send(app_id, conn, line) or delivered
        return delivered

    def set_devices(self, devices: list[str]) -> None:
        """Tell every app which keyboards there are (their hints depend on it)."""
        self._devices = list(devices)
        line = _line({"type": "keyboards", "devices": self._devices})
        with self._lock:
            pairs = [(app, c) for app, conns in self._clients.items() for c in conns]
        for app_id, conn in pairs:
            self._send(app_id, conn, line)

    def _send(self, app_id: str, conn: socket.socket, line: bytes) -> bool:
        try:
            conn.sendall(line)
            return True
        except OSError as exc:
            log.info("Key hub: %s went away (%s)", app_id, exc)
            self._drop(app_id, conn)
            return False

    # ------------------------------------------------------------ clients
    def _accept_loop(self) -> None:
        while self._running:
            server = self._server
            if server is None:
                return
            try:
                conn, _ = server.accept()
            except OSError:
                return                       # stopped
            threading.Thread(target=self._client, args=(conn,), name="key-hub-client",
                             daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        """Read the hello, then watch for the app to go away."""
        app_id = None
        try:
            conn.settimeout(HELLO_TIMEOUT_SEC)
            reader = conn.makefile("rb")
            try:
                hello = json.loads(reader.readline().decode("utf-8") or "{}")
            finally:
                reader.close()               # or it keeps the socket open after close()
            app_id = str(hello.get("app_id") or "").strip()
            if not app_id:
                raise ValueError("no app_id")
            conn.settimeout(SEND_TIMEOUT_SEC)
            with self._lock:
                self._clients.setdefault(app_id, []).append(conn)
            log.info("Key hub: %s connected", app_id)
            self._send(app_id, conn, _line({"type": "keyboards", "devices": self._devices}))
            # The socket keeps its short timeout so a hung app can never
            # block a send on the UI thread for long; this thread waits for
            # the app to go away with select, which costs no wakeups.
            while self._running:
                readable, _, _ = select.select([conn], [], [])
                if readable and not conn.recv(256):   # the app closed its end (exited)
                    break
        except (OSError, ValueError) as exc:
            log.debug("Key hub client ended: %s", exc)
        finally:
            if app_id:
                self._drop(app_id, conn)
            _close(conn)

    def _drop(self, app_id: str, conn: socket.socket) -> None:
        with self._lock:
            conns = self._clients.get(app_id, [])
            if conn in conns:
                conns.remove(conn)
                log.info("Key hub: %s disconnected", app_id)
            if not conns:
                self._clients.pop(app_id, None)


def _line(message: dict) -> bytes:
    return (json.dumps(message) + "\n").encode("utf-8")


def _close(conn: socket.socket) -> None:
    """End the connection for both sides, whatever else still refers to it."""
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        conn.close()
    except OSError:
        pass
