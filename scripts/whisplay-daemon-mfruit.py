#!/usr/bin/env python3
"""Run whisplay-daemon with its own user interface in the background.

Installed by MFruit OS's install.sh as a systemd drop-in for
whisplay-daemon.service:

    python3 whisplay-daemon-mfruit.py --whisplay /home/pi/Whisplay \\
        --lock /home/pi/.whisplay-os/state/launcher.lock

It starts the unmodified daemon from the Whisplay checkout and changes four
behaviours *only while MFruit OS is running* (MFruit OS holds an flock on
``--lock``; the check reads /proc/locks and never takes the lock itself):

* the daemon does not draw its desktop or its "Opening app…" modal — the
  screen keeps MFruit OS's last frame (its loading screen) until the app draws;
* the button and keyboard are ignored while no app owns the screen, so the
  daemon's desktop can no longer act as a second launcher;
* when an app (or MFruit OS) gives up the screen, its final frame is drawn
  first, so what the user saw last stays up until the next owner draws.

Hardware, app registration, focus, events and the daemon's own pages
(WiFi, Bluetooth, Volume, Power) are untouched. When MFruit OS is not
running — or the daemon code does not look as expected — the daemon behaves
exactly as usual, so the device is never left without a user interface.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

OS_APP_ID = "mfruit-os"
CACHE_SEC = 0.3


class MfruitProbe:
    """Does MFruit OS own the user interface?

    True while some process holds an flock on ``lock_path`` (MFruit OS running)
    and MFruit OS has not handed the screen to the daemon's desktop on purpose
    (``launch-policy`` = ``open``, its "Daemon desktop" developer option).
    A bounded startup grace covers the first handoff and ends as soon as the
    launcher lock is observed, so an early launcher exit restores the desktop.
    """

    def __init__(self, lock_path: str, startup_grace: float = 0):
        self.lock_path = lock_path
        self._checked_at = float("-inf")
        self._value = False
        self._startup_until = time.monotonic() + startup_grace

    def __call__(self) -> bool:
        now = time.monotonic()
        if (now - self._checked_at < CACHE_SEC
                and not self._checked_at < self._startup_until <= now):
            return self._value
        self._checked_at = now
        held = self._held()
        if held:
            self._startup_until = 0.0
        self._value = (held or now < self._startup_until) and not self._desktop_mode()
        return self._value

    def _desktop_mode(self) -> bool:
        policy = os.path.join(os.path.dirname(self.lock_path), "launch-policy")
        try:
            with open(policy, "r", encoding="ascii", errors="replace") as fp:
                return fp.read().strip() == "open"
        except OSError:
            return False

    def _held(self) -> bool:
        try:
            st = os.stat(self.lock_path)
        except OSError:
            return False
        key = "%02x:%02x:%d" % (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
        try:
            with open("/proc/locks", "r", encoding="ascii", errors="replace") as fp:
                for line in fp:
                    fields = line.split()
                    if len(fields) > 5 and fields[1] == "FLOCK" and fields[5] == key:
                        return True
        except OSError:
            return False
        return False


def apply(module, lock_path: str, log=print, startup_grace: float = 0) -> list[str]:
    """Patch ``module.WhisplayDaemon``; returns the names of patched methods."""
    cls = getattr(module, "WhisplayDaemon", None)
    if cls is None:
        return []
    mfruit_running = MfruitProbe(lock_path, startup_grace)
    size = getattr(module, "FRAMEBUFFER_SIZE", 240 * 280 * 2)
    width = getattr(module, "SCREEN_WIDTH", 240)
    height = getattr(module, "SCREEN_HEIGHT", 280)
    patched: list[str] = []

    def unowned(self) -> bool:
        return (not self.foreground_app_id and not getattr(self, "_screen_locked", False)
                and mfruit_running())

    if hasattr(cls, "_render_desktop"):
        original_render = cls._render_desktop

        def _render_desktop(self):
            if mfruit_running():
                self.last_frame = None  # the next app frame is always drawn
                return None
            return original_render(self)
        cls._render_desktop = _render_desktop
        patched.append("_render_desktop")

    if hasattr(cls, "_on_button_pressed"):
        original_pressed = cls._on_button_pressed

        def _on_button_pressed(self):
            if unowned(self):
                return None  # MFruit OS is handing the screen over or taking it back
            return original_pressed(self)
        cls._on_button_pressed = _on_button_pressed
        patched.append("_on_button_pressed")

    if hasattr(cls, "_on_button_released"):
        original_released = cls._on_button_released

        def _on_button_released(self):
            if unowned(self):
                with self.state_lock:
                    self._button_press_started_at = 0.0
                return None
            return original_released(self)
        cls._on_button_released = _on_button_released
        patched.append("_on_button_released")

    if hasattr(cls, "_handle_keyboard_action"):
        original_keyboard = cls._handle_keyboard_action

        def _handle_keyboard_action(self, action):
            if unowned(self):
                return None
            return original_keyboard(self, action)
        cls._handle_keyboard_action = _handle_keyboard_action
        patched.append("_handle_keyboard_action")

    if hasattr(cls, "_release_focus"):
        original_release = cls._release_focus

        def _release_focus(self, app, reason):
            if mfruit_running():
                framebuffer = getattr(app, "framebuffer_mmap", None)
                if framebuffer is not None:
                    try:
                        framebuffer.seek(0)
                        frame = framebuffer.read(size)
                        if frame != self.last_frame:
                            self.board.draw_image(0, 0, width, height, frame)
                            self.last_frame = frame
                    except (ValueError, OSError) as exc:
                        log(f"[mfruit] could not show the final frame of {app.app_id}: {exc}")
            return original_release(self, app, reason)
        cls._release_focus = _release_focus
        patched.append("_release_focus")

    if hasattr(cls, "handle_command"):
        original_command = cls.handle_command

        def handle_command(self, request, conn):
            if request.get("cmd") != "mfruit.page.key":
                return original_command(self, request, conn)
            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                return {"ok": False, "error": "invalid key payload"}, False
            with self.state_lock:
                app_id = payload.get("app_id")
                if (request.get("version", 1) != 1 or not mfruit_running()
                        or self._screen_locked or self.foreground_app_id != app_id
                        or not self.internal_apps.is_internal_app(app_id)):
                    return {"ok": False, "error": "page does not own input"}, False
                kind, value = payload.get("kind"), payload.get("value")
                action = {"up": "up", "left": "up", "down": "down", "right": "down",
                          "tab": "down", "enter": "submit", "escape": "cancel",
                          "backspace": "backspace", "space": ("char", " ")}.get(value)
                if kind == "char" and isinstance(value, str) and len(value) == 1:
                    action = ("char", value)
                if action is None:
                    return {"ok": False, "error": "unsupported key"}, False
                self._handle_keyboard_action(action)
                return {"ok": True, "payload": {}}, False
        cls.handle_command = handle_command
        patched.append("handle_command")
    return patched


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--whisplay", required=True, help="Whisplay checkout (contains daemon/)")
    parser.add_argument("--lock", required=True, help="MFruit OS launcher.lock")
    args, rest = parser.parse_known_args(argv)
    daemon_dir = os.path.join(os.path.abspath(args.whisplay), "daemon")
    sys.path.insert(0, daemon_dir)
    sys.argv = [os.path.join(daemon_dir, "whisplay_daemon.py")] + rest

    import whisplay_daemon as daemon  # noqa: E402  (path set above)

    needed = ("parse_args", "resolve_runtime_config", "cleanup_and_exit", "WhisplayDaemon")
    if not all(hasattr(daemon, name) for name in needed):
        print("[mfruit] unfamiliar whisplay-daemon version; running it unmodified", flush=True)
        import runpy
        runpy.run_path(sys.argv[0], run_name="__main__")
        return 0
    patched = apply(daemon, args.lock, startup_grace=30)
    print(f"[mfruit] daemon user interface in the background while MFruit OS runs "
          f"(patched: {', '.join(patched)})", flush=True)

    # The same start-up as whisplay_daemon.py's own __main__ block.
    runtime_config = daemon.resolve_runtime_config(daemon.parse_args())
    daemon.daemon_instance = daemon.WhisplayDaemon(runtime_config["socket_path"],
                                                   runtime_config["apps_dir"],
                                                   runtime_config["settings_path"])
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, daemon.cleanup_and_exit)
    try:
        daemon.daemon_instance.start()
    except KeyboardInterrupt:
        daemon.cleanup_and_exit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
