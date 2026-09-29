"""Core ApplicationManager: single flight, sessions, stale events (no hardware, no daemon)."""

import unittest

import helpers  # noqa: F401
from helpers import FakeClock
from mfruitos.core.application_manager import (EXITED, FAILED, IDLE, RUNNING, STARTING, STOPPING,
                                               ApplicationManager)


class ScriptedHost:
    def __init__(self):
        self.started = []
        self.stopped = []

    def start(self, session):
        self.started.append(session)

    def stop(self, session):
        self.stopped.append(session)


class Listener:
    def __init__(self):
        self.running = []
        self.ended = []

    def on_session_running(self, session):
        self.running.append(session)

    def on_session_ended(self, session):
        self.ended.append(session)


class ApplicationManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.manager = ApplicationManager(self.clock)
        self.host = ScriptedHost()
        self.listener = Listener()
        self.manager.host = self.host
        self.manager.listener = self.listener

    def test_launch_lifecycle_states(self):
        ok, sid = self.manager.request_launch("alpha", source="home")
        self.assertTrue(ok)
        self.assertEqual(self.manager.state, STARTING)
        self.assertEqual([s.app_id for s in self.host.started], ["alpha"])
        self.manager.process_started(sid, 1234)
        self.manager.on_foreground(sid)
        self.assertEqual(self.manager.state, RUNNING)
        self.manager.on_ended(sid, EXITED, exit_code=0)
        self.assertEqual(self.manager.state, IDLE)
        session = self.listener.ended[0]
        self.assertEqual((session.pid, session.exit_code, session.outcome), (1234, 0, EXITED))
        self.assertEqual([state for _, state in session.history], [STARTING, RUNNING, IDLE])

    def test_duplicate_launch_is_prevented(self):
        self.assertTrue(self.manager.request_launch("alpha")[0])
        for app, source in (("alpha", "home"), ("beta", "control"), ("gamma", "autostart")):
            ok, reason = self.manager.request_launch(app, source=source)
            self.assertFalse(ok)
            self.assertIn("busy", reason)
        self.assertEqual([s.app_id for s in self.host.started], ["alpha"])

    def test_launch_refused_while_running_and_stopping(self):
        ok, sid = self.manager.request_launch("alpha")
        self.manager.on_foreground(sid)
        self.assertFalse(self.manager.request_launch("beta")[0])
        self.assertTrue(self.manager.request_stop("test"))
        self.assertEqual(self.manager.state, STOPPING)
        self.assertFalse(self.manager.request_launch("beta")[0])
        self.manager.on_ended(sid, EXITED)
        self.assertTrue(self.manager.request_launch("beta")[0])

    def test_stale_event_is_ignored(self):
        ok, old = self.manager.request_launch("alpha")
        self.manager.on_ended(old, FAILED, "crashed")
        ok, new = self.manager.request_launch("beta")
        # Late reports about the finished session arrive now:
        self.manager.on_foreground(old)
        self.manager.process_started(old, 999)
        self.manager.on_ended(old, EXITED, exit_code=1)
        self.assertEqual(self.manager.state, STARTING)
        self.assertEqual(self.manager.session.app_id, "beta")
        self.assertIsNone(self.manager.session.pid)
        self.assertEqual(len(self.listener.ended), 1)

    def test_previous_process_cannot_affect_new_session(self):
        ok, first = self.manager.request_launch("alpha")
        self.manager.on_foreground(first)
        self.manager.on_ended(first, EXITED)
        ok, second = self.manager.request_launch("alpha")   # same app, new session
        self.assertNotEqual(first, second)
        self.manager.on_ended(first, EXITED, exit_code=3)  # the old process finally exits
        self.assertEqual(self.manager.state, STARTING)
        self.manager.on_foreground(second)
        self.manager.on_ended(second, EXITED, exit_code=0)
        self.assertEqual([s.exit_code for s in self.listener.ended], [None, 0])

    def test_rejection_is_logged_with_context(self):
        self.manager.context = lambda: {"screen": "Home", "selected": "beta"}
        self.manager.request_launch("alpha")
        with self.assertLogs("mfruitos.lifecycle", "WARNING") as logs:
            self.manager.request_launch("beta", source="retry")
        self.assertIn("LAUNCH_REJECTED app=beta source=retry", logs.output[0])
        self.assertIn("selected=beta", logs.output[0])

    def test_external_session_only_when_idle(self):
        self.assertIsNotNone(self.manager.adopt_external("walkie"))
        self.assertEqual(self.manager.state, RUNNING)
        self.assertIsNone(self.manager.adopt_external("other"))


if __name__ == "__main__":
    unittest.main()
