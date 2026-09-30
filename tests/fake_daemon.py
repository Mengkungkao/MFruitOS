"""In-process fake of whisplay-daemon for integration tests.

It mirrors the semantics of the real daemon (whisplay_daemon.py, upstream
1066486) that MFruit OS depends on:

* app.launch is refused while another app is foreground;
* app.focus.acquire is refused while another app is foreground or pending;
* releasing focus broadcasts ``app_focus_revoked`` (app-scoped) and then
  ``desktop_entered`` (global subscribers only);
* internal pages become foreground on launch without any focus event;
* a launched process that exits before taking focus clears the pending state
  silently (no event), exactly like the real monitor loop;
* app-scoped events also go to global subscribers.

Launched apps are simulated by per-app behaviours:
``"acquire"`` (takes focus shortly after launch), ``"crash"`` (exits before
focus), ``"headless"`` (runs but never takes focus).
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import uuid

INTERNAL = {"whisplay-wifi", "whisplay-volume"}
FB_W, FB_H = 240, 280


class FakeDaemon:
    def __init__(self, socket_path: str | None = None):
        self.dir = tempfile.mkdtemp(prefix="fake-daemon-")
        self.socket_path = socket_path or os.path.join(self.dir, "d.sock")
        self.lock = threading.RLock()
        self.apps: dict[str, dict] = {}
        self.behaviour: dict[str, str] = {}
        self.foreground: str | None = None
        self.pending: str | None = None
        self.running: set[str] = set()
        self.tokens: dict[str, str] = {}
        self.fb_paths: dict[str, str] = {}
        self.global_subs: list[socket.socket] = []
        self.app_subs: dict[str, list[socket.socket]] = {}
        self.commands: list[tuple[str, dict]] = []
        self.backlight = 100
        self.led = (0, 0, 0)
        self._server: socket.socket | None = None
        self._running = False
        self.launch_delay = 0.05
        self.pending_timeout = 8.0  # PENDING_LAUNCH_TIMEOUT_SEC in the real daemon
        for app_id in INTERNAL:
            self.apps[app_id] = {"app_id": app_id, "display_name": app_id, "priority": 100}

    # --------------------------------------------------------------- server
    def start(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(16)
        self._running = True
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        self._running = False
        with self.lock:
            subs = list(self.global_subs) + [s for v in self.app_subs.values() for s in v]
            self.global_subs.clear()
            self.app_subs.clear()
            for app_id in list(self.fb_paths):
                self._teardown(app_id)
            self.foreground = None
            self.pending = None
        for conn in subs:
            try:
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
            except OSError:
                pass
        if self._server:
            self._server.close()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    def _accept(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        keep = False
        try:
            with conn.makefile("r") as reader:
                line = reader.readline()
            if not line:
                return
            request = json.loads(line)
            try:
                response, keep = self.handle(request, conn)
            except RuntimeError as exc:
                response, keep = {"ok": False, "error": str(exc)}, False
            conn.sendall((json.dumps(response) + "\n").encode())
            if keep:
                while self._running:
                    time.sleep(0.05)
        except OSError:
            pass
        finally:
            if not keep:
                conn.close()

    # ------------------------------------------------------------- events
    def broadcast(self, event, payload=None, app_id=None):
        msg = {"event": event}
        if payload:
            msg["payload"] = payload
        wire = (json.dumps(msg) + "\n").encode()
        with self.lock:
            targets = list(self.global_subs)
            if app_id:
                targets += self.app_subs.get(app_id, [])
        for conn in targets:
            try:
                conn.sendall(wire)
            except OSError:
                pass

    # ------------------------------------------------------------ commands
    def handle(self, request, conn):
        cmd = request.get("cmd")
        payload = request.get("payload") or {}
        with self.lock:
            self.commands.append((cmd, payload))
            app_id = str(payload.get("app_id", ""))
            if cmd == "health.ping":
                return {"ok": True, "payload": {"service": "whisplay-daemon",
                                                "foreground_app_id": self.foreground}}, False
            if cmd == "app.register":
                record = self.apps.setdefault(app_id, {"app_id": app_id})
                record.update({k: v for k, v in payload.items()})
                return {"ok": True, "payload": {"app_id": app_id}}, False
            if cmd == "app.list":
                apps = [{"app_id": a, "display_name": r.get("display_name", a),
                         "icon": r.get("icon", ""), "priority": r.get("priority", 0),
                         "exit_gesture": r.get("exit_gesture", "quad_click"),
                         "running": a in self.running, "selected": False,
                         "foreground": a == self.foreground}
                        for a, r in self.apps.items()]
                return {"ok": True, "payload": {"apps": apps}}, False
            if cmd == "app.launch":
                if app_id not in self.apps:
                    raise RuntimeError(f"unknown app: {app_id}")
                if self.foreground and self.foreground != app_id:
                    raise RuntimeError("cannot launch while another app is foreground")
                self._launch(app_id)
                return {"ok": True, "payload": {"app_id": app_id, "pending": True}}, False
            if cmd == "app.focus.acquire":
                if app_id not in self.apps:
                    raise RuntimeError(f"unknown app: {app_id}")
                if self.pending and self.pending != app_id and self.foreground != app_id:
                    raise RuntimeError("another app is pending foreground")
                token = self._grant(app_id)
                return {"ok": True, "payload": {"app_id": app_id, "session_token": token}}, False
            if cmd == "framebuffer.acquire":
                if self.tokens.get(app_id) != payload.get("session_token") or self.foreground != app_id:
                    raise RuntimeError("invalid foreground session")
                return {"ok": True, "payload": {
                    "app_id": app_id, "session_token": self.tokens[app_id], "width": FB_W,
                    "height": FB_H, "stride": FB_W * 2, "pixel_format": "RGB565",
                    "buffer_handle": self.fb_paths[app_id]}}, False
            if cmd == "app.focus.release":
                if self.tokens.get(app_id) != payload.get("session_token"):
                    raise RuntimeError("invalid session")
                if self.foreground == app_id:
                    self._release(app_id, "app_release")
                return {"ok": True}, False
            if cmd == "app.exit.request":
                if app_id not in self.apps:
                    raise RuntimeError(f"unknown app: {app_id}")
                self.broadcast("app_exit_requested", {"app_id": app_id, "reason": "remote_request"},
                               app_id=app_id)
                if app_id in INTERNAL and self.foreground == app_id:
                    self._release(app_id, "remote_request")
                return {"ok": True}, False
            if cmd == "backlight.set":
                self.backlight = int(payload.get("brightness", 0))
                return {"ok": True}, False
            if cmd in ("led.set", "led.fade"):
                self.led = (payload.get("r"), payload.get("g"), payload.get("b"))
                return {"ok": True}, False
            if cmd == "button.get_state":
                return {"ok": True, "payload": {"pressed": False}}, False
            if cmd == "events.subscribe":
                if app_id:
                    self.app_subs.setdefault(app_id, []).append(conn)
                else:
                    self.global_subs.append(conn)
                return {"ok": True, "payload": {"subscribed": True, "app_id": app_id or None}}, True
        return {"ok": False, "error": f"unknown command: {cmd}"}, False

    # -------------------------------------------------------------- state
    def _grant(self, app_id):
        if self.foreground and self.foreground != app_id:
            raise RuntimeError("another app is already foreground")
        self._teardown(app_id)
        token = uuid.uuid4().hex
        path = os.path.join(self.dir, f"fb-{app_id}-{token}.bin")
        with open(path, "wb") as fp:
            fp.write(b"\x00" * FB_W * FB_H * 2)
        self.tokens[app_id] = token
        self.fb_paths[app_id] = path
        self.foreground = app_id
        self.pending = None
        self.broadcast("app_foreground_acquired", {"app_id": app_id, "session_token": token},
                       app_id=app_id)
        return token

    def _teardown(self, app_id):
        path = self.fb_paths.pop(app_id, None)
        if path and os.path.exists(path):
            os.unlink(path)

    def _release(self, app_id, reason):
        self.broadcast("app_focus_revoked", {"app_id": app_id, "reason": reason}, app_id=app_id)
        self.tokens.pop(app_id, None)
        self._teardown(app_id)
        self.foreground = None
        self.pending = None
        self.broadcast("desktop_entered", {"reason": reason})

    def _launch(self, app_id):
        if app_id in INTERNAL:
            self.foreground = app_id
            self.pending = None
            return
        behaviour = self.behaviour.get(app_id, "acquire")
        self.running.add(app_id)
        self.pending = app_id

        def run():
            time.sleep(self.launch_delay)
            with self.lock:
                if behaviour == "acquire":
                    try:
                        self._grant(app_id)
                    except RuntimeError:
                        pass
                elif behaviour.startswith("intruded:"):
                    # While the app starts, the daemon desktop handles a press and
                    # opens one of its pages (it owns the button in that window).
                    # Like whisplay_client, the app keeps retrying app.focus.acquire.
                    self.foreground = behaviour.split(":", 1)[1]
                    self.pending = None
                elif behaviour == "crash":
                    self.running.discard(app_id)
                    if self.pending == app_id:
                        self.pending = None  # silent, like the real monitor loop
            if behaviour.startswith("intruded:"):
                for _ in range(40):
                    time.sleep(0.1)
                    with self.lock:
                        if self.foreground is None:
                            self._grant(app_id)
                            break
            if behaviour == "headless":
                time.sleep(self.pending_timeout)
                with self.lock:
                    if self.pending == app_id:
                        self.pending = None  # real daemon: "Pending launch timeout"
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------- test controls
    def app_exits(self, app_id, reason="process_exit"):
        """Simulate the foreground app's process ending."""
        with self.lock:
            self.running.discard(app_id)
            if self.foreground == app_id:
                self._release(app_id, reason)

    def app_releases(self, app_id):
        """Simulate an app releasing focus but staying alive."""
        with self.lock:
            if self.foreground == app_id:
                self._release(app_id, "app_release")

    def internal_back(self, app_id):
        with self.lock:
            if self.foreground == app_id:
                self._release(app_id, "list_back")

    def press(self):
        with self.lock:
            fg = self.foreground
        if fg and fg not in INTERNAL:
            self.broadcast("button_pressed", {"app_id": fg}, app_id=fg)

    def release(self):
        with self.lock:
            fg = self.foreground
        if fg and fg not in INTERNAL:
            self.broadcast("button_released", {"app_id": fg}, app_id=fg)

    def lock_screen(self):
        with self.lock:
            if self.foreground:
                self.tokens.pop(self.foreground, None)
                self._teardown(self.foreground)
            self.foreground = None
            self.pending = None
        self.broadcast("screen_locked")

    def unlock_screen(self):
        self.broadcast("screen_unlocked")

    def read_frame(self, app_id):
        path = self.fb_paths.get(app_id)
        if not path:
            return None
        with open(path, "rb") as fp:
            return fp.read()
