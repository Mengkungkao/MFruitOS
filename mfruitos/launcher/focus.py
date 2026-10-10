"""Whisplay host: screen ownership between mFruit OS, apps and daemon pages.

This is the platform side of an application session (see
``mfruitos.core.application_manager``). It owns the whisplay-daemon focus of
the OS itself and carries out launches the ApplicationManager decided on.

Screen modes
------------
``HOME``     mFruit OS owns the screen (daemon foreground app ``mfruit-os``).
``APP``      a session's app is starting (phase ``pending``) or on screen.
``SYSTEM``   a session's daemon page (WiFi, Volume, Power...) is on screen.
``DESKTOP``  the user chose the daemon's own desktop; stay out until summoned.
``LOCKED``   the daemon locked the screen (Power page).
``OFFLINE``  no daemon connection.

Why a launch is done this way: whisplay-daemon refuses ``app.launch`` while
another app is foreground, so the OS releases its focus first. From that
moment until the new app takes the screen, the physical button belongs to
the daemon's *own desktop* — an independent launcher. Therefore:

* the launching gesture is completed before the hand-over (long press fires
  on release, see gestures.py) — RC1;
* the app launch is authorised by a one-shot ticket that ``mfruit-run``
  checks, so the daemon desktop cannot start another app meanwhile — RC2;
* a daemon page or ungated app that takes the screen during a launch is an
  *intruder* and is closed with ``app.exit.request`` — RC2;
* all timers and reports carry the session id — stale ones are ignored.

Decisions are made by ``reconcile()``, which asks the daemon who is
foreground (``health.ping``) instead of trusting event order.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from mfruitos.core.application_manager import (EXITED, FAILED, HEADLESS, REPLACED,
                                               ApplicationManager, Session)
from mfruitos.daemon.client import (DaemonError, DaemonRequestError, DaemonUnavailable,
                                    WhisplayDaemonClient)
from mfruitos.daemon.framebuffer import Framebuffer

log = logging.getLogger("mfruitos.focus")
lifecycle_log = logging.getLogger("mfruitos.lifecycle")

HOME, APP, SYSTEM, DESKTOP, LOCKED, OFFLINE = (
    "home", "app", "system", "desktop", "locked", "offline")

# whisplay-daemon's PENDING_LAUNCH_TIMEOUT_SEC is 8 s; allow a little slack.
PENDING_TIMEOUT_SEC = 9.5
# Poll only while a launch is pending (bounded by PENDING_TIMEOUT_SEC); short so
# a daemon page opened from the daemon desktop in that window is closed quickly.
MONITOR_INTERVAL_SEC = 0.25
RECONCILE_DELAY_SEC = 0.03
RETRY_DELAY_SEC = 1.0
SUMMON_DELAY_SEC = 0.4


class FocusListener(Protocol):
    def on_focus_gained(self) -> None: ...
    def on_focus_lost(self) -> None: ...
    def on_button(self, pressed: bool) -> None: ...
    def on_exit_requested(self) -> None: ...
    def on_daemon_state(self, connected: bool) -> None: ...


class ForegroundManager:
    def __init__(self, client: WhisplayDaemonClient, loop, app_id: str, listener: FocusListener,
                 manager: ApplicationManager | None = None, clock=time.monotonic,
                 prepare_launch: Callable[[Session], None] | None = None,
                 run_state: Callable[[str], dict | None] | None = None,
                 is_page: Callable[[str], bool] | None = None):
        self.client = client
        self.loop = loop
        self.app_id = app_id
        self.listener = listener
        self.manager = manager or ApplicationManager(clock)
        self.manager.host = self
        self.clock = clock
        self.prepare_launch = prepare_launch or (lambda session: None)
        self.run_state = run_state or (lambda app_id: None)
        self.is_page = is_page or (lambda app_id: False)
        self.framebuffer = Framebuffer()
        self.mode = OFFLINE
        self.session: Session | None = None
        self.phase: str | None = None
        self.token: str | None = None
        self.connected = False
        self._launch_started = 0.0
        self._reconcile_timer = None
        self._monitor_timer = None
        self._prefer_desktop = False

    # ------------------------------------------------------------ queries
    @property
    def target(self) -> str | None:
        return self.session.app_id if self.session else None

    @property
    def has_focus(self) -> bool:
        return self.token is not None and self.framebuffer.attached

    def describe(self) -> dict:
        return {"mode": self.mode, "target": self.target, "phase": self.phase,
                "session": self.session.id if self.session else None,
                "has_focus": self.has_focus, "connected": self.connected}

    def _current(self, session_id: str) -> bool:
        return self.session is not None and self.session.id == session_id

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
        if self.mode != DESKTOP:
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

    # ---------------------------------------------------- Host interface
    def start(self, session: Session) -> None:
        """Put a session's app (or daemon page) on screen. Called by the manager."""
        self._cancel_monitor()
        self.session = session
        self.mode = SYSTEM if session.kind == "page" else APP
        self.phase = "pending"
        self._launch_started = self.clock()
        self._release_own()
        if session.kind == "app":
            self.prepare_launch(session)
        try:
            self.client.launch_app(session.app_id)
        except DaemonError as exc:
            self._diagnose_refusal(session, exc)
            self._end(FAILED, _friendly_error(exc))
            return
        lifecycle_log.info("DAEMON_LAUNCH app=%s session=%s", session.app_id, session.id)
        if session.kind == "page":
            # Daemon pages become foreground synchronously inside app.launch.
            self._on_target_foreground(session.id)
        else:
            self._monitor_timer = self.loop.call_later(MONITOR_INTERVAL_SEC, self._monitor, session.id)

    def _diagnose_refusal(self, session: Session, exc: Exception) -> None:
        """Record who held the screen when the daemon refused our launch (we had
        just released it), so an unexpected refusal can be traced afterwards."""
        try:
            foreground = self.client.ping().get("foreground_app_id")
            running = [a["app_id"] for a in self.client.list_apps() if a.get("running")]
        except DaemonError:
            foreground, running = "?", []
        lifecycle_log.error("LAUNCH_REFUSED_BY_DAEMON app=%s session=%s error=%s foreground_now=%s "
                            "running=%s", session.app_id, session.id, exc, foreground, running)
        if foreground not in (None, "?", self.app_id, session.app_id):
            self._evict(foreground, session)

    def stop(self, session: Session) -> None:
        """Ask the app to leave (it gets app_exit_requested; the daemon forces the
        screen back after 1.5 s). Process clean-up is the runtime's job."""
        try:
            self.client.request_exit(session.app_id)
        except DaemonError as exc:
            log.warning("Exit request for %s failed: %s", session.app_id, exc)

    # ------------------------------------------------------- launch window
    def _monitor(self, session_id: str) -> None:
        """Bounded polling while a launch is pending (the daemon has no event for it)."""
        self._monitor_timer = None
        if not self._current(session_id) or self.phase != "pending":
            return
        session = self.session
        state = self.run_state(session.app_id)
        if state and state.get("session") == session_id and state.get("pid"):
            self.manager.process_started(session_id, state["pid"])
        try:
            apps = {a["app_id"]: a for a in self.client.list_apps()}
        except DaemonError as exc:
            log.debug("Launch monitor: %s", exc)
            apps = None
        if apps is not None:
            info = apps.get(session.app_id, {})
            if info.get("foreground"):
                self._on_target_foreground(session_id)
                return
            intruder = next((a for a, i in apps.items()
                             if i.get("foreground") and a not in (session.app_id, self.app_id)), None)
            if intruder:
                self._evict(intruder, session)
            elif not info.get("running"):
                # Let already-received events drain before deciding it failed.
                self.loop.call_later(0.25, self._confirm_launch_failed, session_id)
                return
            elif self.clock() - self._launch_started > PENDING_TIMEOUT_SEC:
                log.warning("%s is running but never took the screen", session.app_id)
                self._end(HEADLESS, "running without a screen")
                return
        self._monitor_timer = self.loop.call_later(MONITOR_INTERVAL_SEC, self._monitor, session_id)

    def _evict(self, intruder: str, session: Session) -> None:
        """Something else took the screen while ``session`` was starting: the
        daemon desktop handled a press (it owns the button during the launch
        window) or an app opened another one. Close it so the right app gets
        the screen."""
        lifecycle_log.warning("INTRUDER app=%s during session=%s (starting %s); closing it. "
                              "Likely cause: button input reached the daemon desktop while "
                              "the app was starting", intruder, session.id, session.app_id)
        try:
            self.client.request_exit(intruder)
        except DaemonError as exc:
            log.warning("Could not close %s: %s", intruder, exc)

    def _confirm_launch_failed(self, session_id: str) -> None:
        if not self._current(session_id) or self.phase != "pending":
            return
        app_id = self.session.app_id
        try:
            foreground = self.client.ping().get("foreground_app_id")
        except DaemonError:
            foreground = None
        state = self.run_state(app_id)
        # Only this session's own run record counts; an older run cannot leak in.
        exit_code = state.get("exit_code") if state and state.get("session") == session_id else None
        detail = "The app exited before it opened a screen."
        if foreground not in (None, self.app_id, app_id):
            self._evict(foreground, self.session)
            detail = f"{foreground} took the screen while it was starting."
        log.warning("%s exited before showing a screen", app_id)
        self._end(FAILED, detail, exit_code)

    def _on_target_foreground(self, session_id: str) -> None:
        if not self._current(session_id) or self.phase == "foreground":
            return
        self.phase = "foreground"
        self._cancel_monitor()
        log.info("%s is in the foreground", self.session.app_id)
        self.manager.on_foreground(session_id)

    def _cancel_monitor(self) -> None:
        if self._monitor_timer is not None:
            self._monitor_timer.cancel()
            self._monitor_timer = None

    def _end(self, outcome: str, detail: str = "", exit_code: int | None = None) -> None:
        """Finish the current session and take the screen back."""
        session = self.session
        self._cancel_monitor()
        self.session = None
        self.phase = None
        if self.mode not in (DESKTOP, LOCKED, OFFLINE):
            self.mode = HOME
        if session is not None:
            log.info("%s left the foreground (%s)", session.app_id, outcome)
            # Listeners update the UI (e.g. remove "Opening…") before the first
            # frame is drawn again.
            self.manager.on_ended(session.id, outcome, detail, exit_code)
        if self.mode == HOME and not self.has_focus:
            self.acquire()

    # ---------------------------------------------------- desktop / summon
    def yield_to_desktop(self) -> None:
        """Show whisplay-daemon's own desktop until the user summons mFruit OS."""
        self._prefer_desktop = True
        self.mode = DESKTOP
        self._release_own()

    def summon(self) -> None:
        self._prefer_desktop = False
        if self.mode in (DESKTOP, HOME, OFFLINE) and not self.has_focus and self.session is None:
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
            self.mode = OFFLINE
            if self.session is not None:
                self._end(EXITED, "daemon connection lost")
            self.listener.on_daemon_state(False)
        elif name in ("button_pressed", "button_released"):
            if app == self.app_id and self.has_focus and self.mode == HOME:
                self.listener.on_button(name == "button_pressed")
        elif name == "app_foreground_acquired":
            if app == self.app_id:
                return
            if self.session is not None and app == self.session.app_id:
                self._on_target_foreground(self.session.id)
            elif self.session is not None and self.phase == "pending":
                self._evict(app, self.session)
            else:
                self._schedule_reconcile()
        elif name in ("app_focus_revoked", "desktop_entered"):
            # Never act on a revoke directly: it may be the echo of our own
            # earlier release arriving after we re-acquired. Reconcile asks the
            # daemon who really is foreground (covers e.g. the exit timeout).
            self._schedule_reconcile()
        elif name == "app_exit_requested":
            if app == self.app_id:
                # Esc key, PiSugar home button or remote request: treat as "Home".
                self.listener.on_exit_requested()
                self.reacquire()
        elif name == "screen_locked":
            self._cancel_monitor()
            self._drop_focus()
            if self.session is not None:
                session, self.session, self.phase = self.session, None, None
                self.manager.on_ended(session.id, EXITED, "screen locked")
            self.mode = LOCKED
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
                # Something we did not launch is on screen (e.g. after a launcher
                # restart). Track it as an external session so we return afterwards.
                self._drop_focus()
                session = self.manager.adopt_external(foreground)
                if session is not None:
                    self.session, self.phase = session, "foreground"
                    self.mode = SYSTEM if self.is_page(foreground) else APP
            return
        if self.session is None:
            self.mode = HOME
            self._schedule_reconcile(0)
            return
        if self.phase == "pending":
            if foreground == self.session.app_id:
                self._on_target_foreground(self.session.id)
            elif foreground not in (None, self.app_id):
                self._evict(foreground, self.session)
            return  # otherwise the launch monitor decides
        if foreground == self.session.app_id:
            return
        if foreground is None or foreground == self.app_id:
            self._end(EXITED)
        else:
            # Another app took the screen from the running one.
            replaced_by = foreground
            self._end(REPLACED, f"replaced by {replaced_by}")
            self._schedule_reconcile(0)


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "another app is foreground" in text or "another app is pending" in text:
        return "Another app is still closing. Try again in a moment."
    if "unknown app" in text:
        return "The daemon does not know this app. Try Reload Apps."
    if "no launch command" in text:
        return "This app has no launch command."
    return text[:120]
