"""After an app is closed, the registry is refreshed whatever way it ended.

Found on the Pi (2026-10-03): RadioConnect exited on its own, the refresh at
session end still saw it running, and `mfruitctl rollback` was then refused
("Stop the app before rolling back") although nothing was running.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import helpers  # noqa: F401
from mfruitos.launcher.app_manager.lifecycle import AppLifecycle
from mfruitos.launcher.runtime import Runtime


class AppCloseRefreshTests(unittest.TestCase):
    def close(self, result, background=False, kind="app"):
        rt = SimpleNamespace(
            registry=Mock(), lifecycle=Mock(), refresh_registry=Mock(),
            run_task=lambda name, work, done, lane: done(work()))
        rt.registry.get.return_value = SimpleNamespace(background=background)
        rt.lifecycle.ensure_stopped.return_value = result
        rt.lifecycle.wait_exited.return_value = result
        Runtime._close_app_after_session(rt, SimpleNamespace(app_id="demo", id="s1", kind=kind))
        return rt

    def test_every_way_of_closing_refreshes_the_registry(self):
        for result in ("exited", "terminated", "killed", "not running"):
            with self.subTest(result=result):
                self.close(result).refresh_registry.assert_called_once_with(query_daemon=True)

    def test_an_app_adopted_after_a_restart_is_watched_not_stopped(self):
        """KI-16 on the Pi Zero, 2026-10-10: RadioConnect, adopted when the
        launcher restarted, exited and stayed listed as running."""
        for background in (False, True):
            with self.subTest(background=background):
                rt = self.close("exited", background=background, kind="external")
                rt.lifecycle.ensure_stopped.assert_not_called()
                rt.lifecycle.wait_exited.assert_called_once_with("demo", None)
                rt.refresh_registry.assert_called_once_with(query_daemon=True)

    def test_a_daemon_page_is_left_alone(self):
        rt = self.close("exited", kind="page")
        rt.lifecycle.wait_exited.assert_not_called()
        rt.lifecycle.ensure_stopped.assert_not_called()

    def test_an_app_that_may_keep_running_is_watched_not_stopped(self):
        """KI-16 (Pi Zero and Orange Pi, 2026-10-10): RadioConnect with Keep
        running was asked to exit; the session-end refresh still saw it
        running and nothing refreshed again, so its update was refused."""
        for result in ("exited", "running", "unknown"):
            with self.subTest(result=result):
                rt = self.close(result, background=True)
                rt.lifecycle.ensure_stopped.assert_not_called()
                rt.lifecycle.wait_exited.assert_called_once_with("demo", "s1")
                rt.refresh_registry.assert_called_once_with(query_daemon=True)



class WaitExitedTests(unittest.TestCase):
    """wait_exited only watches: it never signals the app."""

    def lifecycle(self, state, alive):
        return SimpleNamespace(run_state=lambda app_id: state,
                               _is_wrapper=lambda pid, app_id: alive())

    def test_an_ending_process_is_seen_to_end(self):
        calls = iter([True, True, False])
        fake = self.lifecycle({"session": "s1", "pid": 4242, "state": "running"}, lambda: next(calls))
        self.assertEqual(AppLifecycle.wait_exited(fake, "demo", "s1", grace=5.0), "exited")

    def test_a_process_that_keeps_running_is_left_running(self):
        fake = self.lifecycle({"session": "s1", "pid": 4242, "state": "running"}, lambda: True)
        self.assertEqual(AppLifecycle.wait_exited(fake, "demo", "s1", grace=0.3), "running")

    def test_any_session_when_none_is_given(self):
        calls = iter([True, False])
        fake = self.lifecycle({"session": "from-before-the-restart", "pid": 4242, "state": "running"},
                              lambda: next(calls))
        self.assertEqual(AppLifecycle.wait_exited(fake, "demo", None, grace=5.0), "exited")

    def test_no_record_for_this_session(self):
        fake = self.lifecycle({"session": "other", "pid": 4242}, lambda: True)
        self.assertEqual(AppLifecycle.wait_exited(fake, "demo", "s1", grace=0.3), "unknown")
        fake = self.lifecycle({"session": "s1", "state": "exited"}, lambda: True)
        self.assertEqual(AppLifecycle.wait_exited(fake, "demo", "s1", grace=0.3), "exited")

if __name__ == "__main__":
    unittest.main()
