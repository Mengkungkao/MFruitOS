"""Foreground ownership between MFruit OS, launched apps and daemon pages.

Model
-----
``HOME``     MFruit OS should own the screen (daemon foreground app).
``APP``      the OS yielded to a launched app (phase ``pending`` -> ``foreground``).
``SYSTEM``   the OS yielded to a daemon internal page (WiFi, Volume, Power…).
``DESKTOP``  the user chose the daemon's classic desktop; stay out until summoned.
``LOCKED``   the daemon locked the screen (Power page); wait for unlock.
``OFFLINE``  no daemon connection.

Why the dance: whisplay-daemon refuses ``app.launch`` while another app is
foreground, so the OS releases focus first, launches, and takes the screen
back when the daemon reports the desktop again (``desktop_entered`` is only
sent to global subscribers). Decisions are made by :meth:`reconcile`, which
asks the daemon who is foreground (``health.ping``) instead of trusting event
ordering, so a lost or reordered event cannot leave the screen stuck.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from mfruitos.daemon.client import (DaemonError, DaemonRequestError, DaemonUnavailable,
                                    WhisplayDaemonClient)
from mfruitos.daemon.framebuffer import Framebuffer

log = logging.getLogger("mfruitos.focus")

HOME, APP, SYSTEM, DESKTOP, LOCKED, OFFLINE = (
    "home", "app", "system", "desktop", "locked", "offline")

# whisplay-daemon's PENDING_LAUNCH_TIMEOUT_SEC is 8 s; allow a little slack.
PENDING_TIMEOUT_SEC = 9.5
MONITOR_INTERVAL_SEC = 0.5
RECONCILE_DELAY_SEC = 0.03
RETRY_DELAY_SEC = 1.0
SUMMON_DELAY_SEC = 0.4


class FocusListener(Protocol):
    def on_focus_gained(self) -> None: ...
    def on_focus_lost(self) -> None: ...
    def on_button(self, pressed: bool) -> None: ...
    def on_exit_requested(self) -> None: ...
    def on_app_foreground(self, app_id: str) -> None: ...
    def on_app_returned(self, app_id: str, kind: str) -> None: ...
    def on_launch_failed(self, app_id: str, reason: str) -> None: ...
    def on_app_headless(self, app_id: str) -> None: ...
    def on_daemon_state(self, connected: bool) -> None: ...


class ForegroundManager:
    def __init__(self, client: WhisplayDaemonClient, loop, app_id: str, listener: FocusListener,
                 clock=time.monotonic):
        self.client = client
        self.loop = loop
        self.app_id = app_id
        self.listener = listener
        self.clock = clock
        self.framebuffer = Framebuffer()
        self.mode = OFFLINE
        self.target: str | None = None
        self.phase: str | None = None
        self.token: str | None = None
        self.connected = False
        self._launch_started = 0.0
        self._reconcile_timer = None
        self._monitor_timer = None
        self._prefer_desktop = False

    # ------------------------------------------------------------ queries
    @property
    def has_focus(self) -> bool:
        return self.token is not None and self.framebuffer.attached

    def describe(self) -> dict:
        return {"mode": self.mode, "target": self.target, "phase": self.phase,
                "has_focus": self.has_focus, "connected": self.connected}

    # ------------------------------------------------------------- focus
    def acquire(self) -> bool:
        try:
            token = self.client.acquire_focus(self.app_id)
            info = self.client.acquire_framebuffer(self.app_id, token)
            self.framebuffer.attach(info)
        except DaemonRequestError as exc:
            log.info("Focus not available yet (%s); retrying", exc)
            self._schedule_reconcile(RETRY_DELAY_SEC)
            return False
        except DaemonError as exc:
            log.warning("Could not acquire focus: %s", exc)
            self._schedule_reconcile(RETRY_DELAY_SEC)
            return False
        except (OSError, ValueError) as exc:
            log.error("Could not map framebuffer: %s", exc)
            self._schedule_reconcile(RETRY_DELAY_SEC)
            return False
        self.token = token
        if self.mode not in (DESKTOP,):
            self.mode = HOME
        log.info("Foreground acquired")
        self.listener.on_focus_gained()
        return True

    def _drop_focus(self, notify: bool = True) -> None:
        had = self.token is not None
        self.token = None
        self.framebuffer.detach()
        if had and notify:
            self.listener.on_focus_lost()

    def _release_own(self) -> None:
        token = self.token
        self._drop_focus()
        if token is None:
            return
        try:
            self.client.release_focus(self.app_id, token)
        except DaemonError as exc:
            log.warning("Focus release failed: %s", exc)

    # ------------------------------------------------------------ launch
    def launch(self, app_id: str, system_page: bool = False) -> None:
        """Hand the screen to ``app_id`` (an app or a daemon internal page)."""
        log.info("Launching %s%s", app_id, " (daemon page)" if system_page else "")
        self._cancel_monitor()
        self.mode = SYSTEM if system_page else APP
        self.target = app_id
        self.phase = "pending"
        self._launch_started = self.clock()
        self._release_own()
        try:
            self.client.launch_app(app_id)
        except DaemonError as exc:
            log.error("Daemon refused to launch %s: %s", app_id, exc)
            self._go_home()
            self.listener.on_launch_failed(app_id, _friendly_error(exc))
            return
        if system_page:
            self.phase = "foreground"
        else:
            self._monitor_timer = self.loop.call_later(MONITOR_INTERVAL_SEC, self._monitor, app_id)

    def _monitor(self, app_id: str) -> None:
        """Bounded polling only while a launch is pending (the daemon has no event for it)."""
        self._monitor_timer = None
        if self.mode != APP or self.target != app_id or self.phase != "pending":
            return
        try:
            apps = {a["app_id"]: a for a in self.client.list_apps()}
        except DaemonError as exc:
            log.debug("Launch monitor: %s", exc)
            apps = None
        if apps is not None:
            info = apps.get(app_id, {})
            if info.get("foreground"):
                self._on_target_foreground(app_id)
                return
            if not info.get("running"):
                # Let already-received events drain before deciding it failed.
                self.loop.call_later(0.25, self._confirm_launch_failed, app_id)
                return
            if self.clock() - self._launch_started > PENDING_TIMEOUT_SEC:
                log.warning("%s is running but never took the screen", app_id)
                self._go_home()
                self.listener.on_app_headless(app_id)
                return
        self._monitor_timer = self.loop.call_later(MONITOR_INTERVAL_SEC, self._monitor, app_id)

    def _confirm_launch_failed(self, app_id: str) -> None:
        if self.mode != APP or self.target != app_id or self.phase != "pending":
            return
        try:
            foreground = self.client.ping().get("foreground_app_id")
        except DaemonError:
            foreground = None
        if foreground not in (None, self.app_id, app_id):
            # The app handed over to another app or daemon page (e.g. a WiFi
            # setup app that opens the Bluetooth page, then exits). Follow it.
            log.info("%s handed the screen to %s", app_id, foreground)
            self.target, self.phase = foreground, "foreground"
            self.listener.on_app_foreground(foreground)
            return
        log.warning("%s exited before showing a screen", app_id)
        self._go_home()
        self.listener.on_launch_failed(app_id, "The app exited before it opened a screen.")

    def _on_target_foreground(self, app_id: str) -> None:
        if self.phase != "foreground":
            self.phase = "foreground"
            self._cancel_monitor()
            log.info("%s is in the foreground", app_id)
            self.listener.on_app_foreground(app_id)

    def _cancel_monitor(self) -> None:
        if self._monitor_timer is not None:
            self._monitor_timer.cancel()
            self._monitor_timer = None

    def _go_home(self) -> None:
        self._cancel_monitor()
        self.mode = HOME
        self.target = None
        self.phase = None
        if not self.has_focus:
            self.acquire()

    def _returned(self, reason: str = "") -> None:
        app_id, kind = self.target, self.mode
        log.info("%s left the foreground%s", app_id, f" ({reason})" if reason else "")
        self._go_home()
        if app_id:
            self.listener.on_app_returned(app_id, kind)

    # ---------------------------------------------------- desktop / summon
    def yield_to_desktop(self) -> None:
        """Show whisplay-daemon's own desktop until the user summons MFruit OS."""
        self._prefer_desktop = True
        self.mode = DESKTOP
        self._release_own()

    def summon(self) -> None:
        self._prefer_desktop = False
        if self.mode in (DESKTOP, HOME, OFFLINE) and not self.has_focus:
            self.mode = HOME if self.connected else OFFLINE
            # Give the daemon a moment to notice the summon helper exited.
            self._schedule_reconcile(SUMMON_DELAY_SEC)

    def reacquire(self) -> None:
        """Re-take focus; also cancels a pending daemon exit deadline for the OS."""
        if self.mode == HOME:
            self.token = None
            self.framebuffer.detach()
            self.acquire()

    # -------------------------------------------------------------- events
    def on_event(self, name: str, payload: dict) -> None:
        app = payload.get("app_id")
        if name == "_connected":
            self.connected = True
            if self.mode == OFFLINE:
                self.mode = DESKTOP if self._prefer_desktop else HOME
            self.listener.on_daemon_state(True)
            self._schedule_reconcile(0)
        elif name in ("_disconnected", "daemon_stopping"):
            log.warning("Daemon connection lost (%s)", name)
            if name == "_disconnected":
                self.connected = False
            self._cancel_monitor()
            self._drop_focus()
            self.mode, self.target, self.phase = OFFLINE, None, None
            self.listener.on_daemon_state(False)
        elif name in ("button_pressed", "button_released"):
            if app == self.app_id and self.has_focus and self.mode == HOME:
                self.listener.on_button(name == "button_pressed")
        elif name == "app_foreground_acquired":
            if app == self.app_id:
                return
            if self.mode == APP and app == self.target:
                self._on_target_foreground(app)
            else:
                self._schedule_reconcile()
        elif name == "app_focus_revoked":
            # Never act on a revoke directly: it may be the echo of our own
            # earlier release arriving after we re-acquired. Reconcile asks the
            # daemon who really is foreground (covers e.g. the exit timeout).
            self._schedule_reconcile()
        elif name == "desktop_entered":
            self._schedule_reconcile()
        elif name == "app_exit_requested":
            if app == self.app_id:
                # Esc key, PiSugar home button or remote request: treat as "Home".
                self.listener.on_exit_requested()
                self.reacquire()
        elif name == "screen_locked":
            self._cancel_monitor()
            self._drop_focus()
            self.mode, self.target, self.phase = LOCKED, None, None
        elif name == "screen_unlocked":
            if self.mode == LOCKED:
                self.mode = HOME
            self._schedule_reconcile()

    # ----------------------------------------------------------- reconcile
    def _schedule_reconcile(self, delay: float = RECONCILE_DELAY_SEC) -> None:
        if self._reconcile_timer is not None:
            self._reconcile_timer.cancel()
        self._reconcile_timer = self.loop.call_later(delay, self.reconcile)

    def reconcile(self) -> None:
        self._reconcile_timer = None
        if self.mode in (OFFLINE, LOCKED) or not self.connected:
            return
        try:
            foreground = self.client.ping().get("foreground_app_id")
        except DaemonUnavailable:
            return  # the event stream will report the disconnect
        except DaemonError as exc:
            log.warning("Reconcile failed: %s", exc)
            self._schedule_reconcile(RETRY_DELAY_SEC)
            return

        if self.mode == DESKTOP:
            return
        if self.mode == HOME:
            if foreground == self.app_id:
                if not self.has_focus:
                    self.acquire()
            elif foreground is None:
                # The daemon shows its desktop: any focus we think we hold is stale.
                self._drop_focus(notify=False)
                self.acquire()
            else:
                # Something else was brought forward (e.g. from the daemon desktop).
                self._drop_focus()
                self.mode, self.target, self.phase = APP, foreground, "foreground"
                self.listener.on_app_foreground(foreground)
            return
        if self.mode == APP and self.phase == "pending":
            if foreground == self.target:
                self._on_target_foreground(self.target)
            return  # otherwise the launch monitor decides
        if foreground == self.target:
            return
        if foreground is None or foreground == self.app_id:
            self._returned()
        else:
            # A different app replaced the one we launched; follow it.
            self.mode, self.target, self.phase = APP, foreground, "foreground"


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "another app is foreground" in text or "another app is pending" in text:
        return "Another app is still closing. Try again in a moment."
    if "unknown app" in text:
        return "The daemon does not know this app. Try Reload Apps."
    if "no launch command" in text:
        return "This app has no launch command."
    return text[:120]
