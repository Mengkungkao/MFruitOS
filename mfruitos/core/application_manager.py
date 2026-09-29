"""ApplicationManager — the single authority for application launches.

Guarantees (see docs/LAUNCH_LIFECYCLE.md):

* **Single flight** — at most one application session exists. A launch
  request while a session is starting, running or stopping is refused and
  logged with its source; it is never queued for later.
* **Sessions** — every launch gets a new session id. Everything the platform
  host reports back carries that id; reports for any other session are stale
  and are dropped (logged as STALE_EVENT), so an old process or timer can
  never affect a new launch.
* **Explicit states** — IDLE -> STARTING -> RUNNING -> STOPPING -> IDLE. Every
  transition is logged on ``mfruitos.lifecycle``.

The UI never starts processes. It asks for a launch; the platform *host*
(e.g. the Whisplay daemon host) performs it and reports back.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

lifecycle_log = logging.getLogger("mfruitos.lifecycle")

IDLE, STARTING, RUNNING, STOPPING = "IDLE", "STARTING", "RUNNING", "STOPPING"

# Session outcomes reported to listeners.
EXITED = "exited"          # the app left the screen normally
FAILED = "failed"          # it never showed a screen (crash, refused, blocked)
HEADLESS = "headless"      # it runs but never took the screen
REPLACED = "replaced"      # another app took the screen from it


@dataclass
class Session:
    id: str
    app_id: str
    kind: str                     # "app" | "page" (daemon page) | "external"
    source: str                   # what asked for it: home, retry, autostart, control, external
    state: str = IDLE
    started_at: float = 0.0
    pid: int | None = None
    exit_code: int | None = None
    outcome: str = ""
    detail: str = ""
    history: list = field(default_factory=list)


class Host(Protocol):
    """Platform side of a session (put the app on screen, take it off)."""

    def start(self, session: Session) -> None: ...
    def stop(self, session: Session) -> None: ...


class Listener(Protocol):
    def on_session_running(self, session: Session) -> None: ...
    def on_session_ended(self, session: Session) -> None: ...


class ApplicationManager:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.host: Host | None = None
        self.listener: Listener | None = None
        self.session: Session | None = None
        self.last_session: Session | None = None
        self.context: Callable[[], dict] = lambda: {}

    # ------------------------------------------------------------ queries
    @property
    def busy(self) -> bool:
        return self.session is not None

    @property
    def state(self) -> str:
        return self.session.state if self.session else IDLE

    def is_current(self, session_id: str | None) -> bool:
        return self.session is not None and session_id == self.session.id

    def describe(self) -> dict:
        s = self.session
        return {"state": self.state, "app": s.app_id if s else None,
                "session": s.id if s else None, "source": s.source if s else None,
                "pid": s.pid if s else None}

    # ------------------------------------------------------------ requests
    def request_launch(self, app_id: str, kind: str = "app", source: str = "home") -> tuple[bool, str]:
        """Start ``app_id`` unless a session already exists. Never queues."""
        ctx = self._ctx()
        if self.session is not None:
            reason = f"busy ({self.session.app_id} {self.session.state} session={self.session.id})"
            lifecycle_log.warning("LAUNCH_REJECTED app=%s source=%s reason=%s%s", app_id, source,
                                  reason, ctx)
            return False, reason
        if self.host is None:
            return False, "no host"
        session = Session(id=secrets.token_hex(4), app_id=app_id, kind=kind, source=source,
                          started_at=self.clock())
        self.session = session
        lifecycle_log.info("LAUNCH_REQUEST app=%s kind=%s source=%s session=%s%s", app_id, kind,
                           source, session.id, ctx)
        self._transition(session, STARTING)
        self.host.start(session)
        return True, session.id

    def request_stop(self, reason: str = "user") -> bool:
        session = self.session
        if session is None or session.state not in (STARTING, RUNNING):
            return False
        lifecycle_log.info("STOP_REQUEST app=%s session=%s reason=%s", session.app_id, session.id,
                           reason)
        self._transition(session, STOPPING)
        self.host.stop(session)
        return True

    def adopt_external(self, app_id: str, kind: str = "external") -> Session | None:
        """An app we did not launch is on screen (e.g. after a launcher restart)."""
        if self.session is not None:
            return None
        session = Session(id=secrets.token_hex(4), app_id=app_id, kind=kind, source="external",
                          started_at=self.clock())
        self.session = session
        lifecycle_log.info("EXTERNAL_SESSION app=%s session=%s", app_id, session.id)
        self._transition(session, RUNNING)
        return session

    # ------------------------------------------------------ host reports
    def _current(self, session_id: str, event: str) -> Session | None:
        if self.is_current(session_id):
            return self.session
        lifecycle_log.info("STALE_EVENT event=%s session=%s current=%s", event, session_id,
                           self.session.id if self.session else None)
        return None

    def process_started(self, session_id: str, pid: int) -> None:
        session = self._current(session_id, "process_started")
        if session is not None and session.pid != pid:
            session.pid = pid
            lifecycle_log.info("PROCESS_STARTED app=%s pid=%s session=%s", session.app_id, pid,
                               session.id)

    def on_foreground(self, session_id: str) -> None:
        session = self._current(session_id, "foreground")
        if session is not None and session.state == STARTING:
            self._transition(session, RUNNING)
            if self.listener:
                self.listener.on_session_running(session)

    def on_ended(self, session_id: str, outcome: str, detail: str = "",
                 exit_code: int | None = None) -> None:
        session = self._current(session_id, f"ended:{outcome}")
        if session is None:
            return
        if exit_code is not None:
            session.exit_code = exit_code
        session.outcome, session.detail = outcome, detail
        lifecycle_log.info("SESSION_END app=%s session=%s outcome=%s exit_code=%s detail=%s",
                           session.app_id, session.id, outcome, session.exit_code, detail or "-")
        self._transition(session, IDLE)
        self.session = None
        self.last_session = session
        if self.listener:
            self.listener.on_session_ended(session)

    # ------------------------------------------------------------ helpers
    def _transition(self, session: Session, state: str) -> None:
        old, session.state = session.state, state
        session.history.append((round(self.clock() - session.started_at, 3), state))
        lifecycle_log.info("STATE %s %s -> %s session=%s", session.app_id, old, state, session.id)

    def _ctx(self) -> str:
        try:
            context = self.context()
        except Exception:  # diagnostics must never break a launch decision
            return ""
        return "".join(f" {k}={v}" for k, v in context.items())
