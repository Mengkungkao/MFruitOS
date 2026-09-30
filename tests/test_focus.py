import time
import unittest

import helpers  # noqa: F401
from fake_daemon import FakeDaemon
from mfruitos.daemon.client import WhisplayDaemonClient
from mfruitos.daemon.events import EventStream
from mfruitos.launcher import focus as focus_mod
from mfruitos.core.application_manager import ApplicationManager
from mfruitos.launcher.focus import APP, DESKTOP, HOME, LOCKED, OFFLINE, SYSTEM, ForegroundManager
from mfruitos.launcher.loop import EventLoop

OS_ID = "mfruit-os"


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("on_"):
            return lambda *args: self.calls.append((name,) + args)
        raise AttributeError(name)

    def names(self):
        return [c[0] for c in self.calls]

    def ended(self, app_id=None, outcome=None):
        return [c[1] for c in self.calls if c[0] == "on_session_ended"
                and (app_id is None or c[1].app_id == app_id)
                and (outcome is None or c[1].outcome == outcome)]


class FocusIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.daemon = FakeDaemon().start()
        self.daemon.handle({"cmd": "app.register", "payload": {"app_id": OS_ID}}, None)
        for app_id in ("good", "crashy", "ghost", "intruded"):
            self.daemon.handle({"cmd": "app.register", "payload": {"app_id": app_id}}, None)
        self.daemon.behaviour.update({"crashy": "crash", "ghost": "headless",
                                      "intruded": "intruded:whisplay-wifi"})
        self.loop = EventLoop()
        self.client = WhisplayDaemonClient(self.daemon.socket_path, timeout=2)
        self.listener = Recorder()
        self.manager = ApplicationManager()
        self.manager.listener = self.listener
        self.fm = ForegroundManager(self.client, self.loop, OS_ID, self.listener, manager=self.manager,
                                    is_page=lambda a: a.startswith("whisplay-"))
        self.stream = EventStream(self.daemon.socket_path,
                                  lambda n, p: self.loop.post(self.fm.on_event, n, p))
        self.stream.start()
        self.wait_for(lambda: self.fm.has_focus, "initial focus")

    def tearDown(self):
        self.stream.stop()
        self.fm.framebuffer.detach()
        self.daemon.stop()

    def wait_for(self, condition, what, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.loop.run_once(block=True, max_wait=0.02)
            if condition():
                return
        self.fail(f"timed out waiting for {what}; state={self.fm.describe()} "
                  f"daemon_fg={self.daemon.foreground} calls={self.listener.names()}")

    def settle(self, seconds=0.3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.loop.run_once(block=True, max_wait=0.02)

    def test_initial_state_home_with_framebuffer(self):
        self.assertEqual(self.fm.mode, HOME)
        self.assertEqual(self.daemon.foreground, OS_ID)
        self.assertTrue(self.fm.framebuffer.write(b"\xff" * (240 * 280 * 2)))
        self.assertEqual(self.daemon.read_frame(OS_ID)[:2], b"\xff\xff")

    def test_launch_app_and_return_home(self):
        self.manager.request_launch("good")
        self.wait_for(lambda: self.fm.phase == "foreground", "app foreground")
        self.assertEqual(self.daemon.foreground, "good")
        self.assertFalse(self.fm.has_focus)
        self.daemon.app_exits("good")
        self.wait_for(lambda: self.fm.has_focus, "focus back")
        self.assertEqual(self.fm.mode, HOME)
        self.assertEqual(len(self.listener.ended("good", "exited")), 1)
        self.assertEqual(self.daemon.foreground, OS_ID)

    def test_own_release_does_not_steal_back_during_launch(self):
        self.daemon.launch_delay = 0.4
        self.manager.request_launch("good")
        self.settle(0.2)  # desktop_entered from our own release has been processed
        self.assertEqual(self.fm.mode, APP)
        self.assertFalse(self.fm.has_focus)
        self.wait_for(lambda: self.daemon.foreground == "good", "app foreground")

    def test_launch_failure_detected(self):
        self.manager.request_launch("crashy")
        self.wait_for(lambda: self.fm.has_focus, "focus back after crash")
        self.assertEqual(len(self.listener.ended("crashy", "failed")), 1)

    def test_intruder_during_launch_is_evicted(self):
        # RC2 (replaces the wrong "hand-off" theory): a daemon page that takes the
        # screen while the requested app starts is closed; the requested app wins.
        self.manager.request_launch("intruded")
        self.wait_for(lambda: self.daemon.foreground == "intruded", "requested app on screen", 6)
        self.wait_for(lambda: self.manager.state == "RUNNING", "session running")
        self.assertEqual(self.listener.ended(), [])
        self.assertIn(("app.exit.request", {"app_id": "whisplay-wifi"}), self.daemon.commands)

    def test_headless_app_detected(self):
        old = focus_mod.PENDING_TIMEOUT_SEC
        focus_mod.PENDING_TIMEOUT_SEC = 0.8
        self.daemon.pending_timeout = 0.5
        try:
            self.manager.request_launch("ghost")
            self.wait_for(lambda: self.fm.has_focus, "focus back after headless")
        finally:
            focus_mod.PENDING_TIMEOUT_SEC = old
        self.assertEqual(len(self.listener.ended("ghost", "headless")), 1)

    def test_unknown_app_launch_rejected(self):
        self.manager.request_launch("nope")
        self.wait_for(lambda: self.fm.has_focus, "focus back")
        self.settle(0.3)
        self.assertEqual(len(self.listener.ended("nope", "failed")), 1)
        # Regression: the echo of our own release must not drop the fresh focus.
        self.assertEqual(self.listener.names().count("on_focus_gained"), 2)
        self.assertTrue(self.fm.has_focus)

    def test_system_page_round_trip(self):
        self.manager.request_launch("whisplay-wifi", "page")
        self.settle(0.2)
        self.assertEqual(self.fm.mode, SYSTEM)
        self.assertEqual(self.daemon.foreground, "whisplay-wifi")
        self.daemon.internal_back("whisplay-wifi")
        self.wait_for(lambda: self.fm.has_focus, "back from wifi page")
        self.assertEqual(len(self.listener.ended("whisplay-wifi", "exited")), 1)

    def test_app_releasing_focus_but_staying_alive(self):
        self.manager.request_launch("good")
        self.wait_for(lambda: self.fm.phase == "foreground", "app foreground")
        self.daemon.app_releases("good")
        self.wait_for(lambda: self.fm.has_focus, "focus back")
        self.assertIn("good", self.daemon.running)

    def test_button_events_only_for_os_while_home(self):
        self.daemon.press()
        self.daemon.release()
        self.wait_for(lambda: ("on_button", False) in self.listener.calls, "button")
        self.assertIn(("on_button", True), self.listener.calls)
        self.manager.request_launch("good")
        self.wait_for(lambda: self.fm.phase == "foreground", "app foreground")
        count = len([c for c in self.listener.calls if c[0] == "on_button"])
        self.daemon.press()
        self.daemon.release()
        self.settle(0.2)
        self.assertEqual(count, len([c for c in self.listener.calls if c[0] == "on_button"]))

    def test_screen_lock_and_unlock(self):
        self.manager.request_launch("whisplay-volume", "page")
        self.settle(0.1)
        self.daemon.lock_screen()
        self.wait_for(lambda: self.fm.mode == LOCKED, "locked")
        self.daemon.unlock_screen()
        self.wait_for(lambda: self.fm.has_focus, "focus after unlock")
        self.assertEqual(self.fm.mode, HOME)

    def test_daemon_restart_recovers_focus(self):
        path = self.daemon.socket_path
        self.daemon.stop()
        self.wait_for(lambda: self.fm.mode == OFFLINE, "offline")
        self.assertFalse(self.fm.has_focus)
        self.daemon = FakeDaemon(path).start()
        self.daemon.handle({"cmd": "app.register", "payload": {"app_id": OS_ID}}, None)
        self.wait_for(lambda: self.fm.has_focus, "focus after daemon restart", timeout=8)
        self.assertEqual(self.daemon.foreground, OS_ID)

    def test_exit_request_is_home_and_keeps_focus(self):
        token = self.fm.token
        self.client.request_exit(OS_ID)
        self.wait_for(lambda: self.fm.token not in (None, token), "reacquired")
        self.assertIn(("on_exit_requested",), self.listener.calls)
        self.assertEqual(self.daemon.foreground, OS_ID)

    def test_desktop_mode_and_summon(self):
        self.fm.yield_to_desktop()
        self.settle(0.3)
        self.assertEqual(self.fm.mode, DESKTOP)
        self.assertIsNone(self.daemon.foreground)
        self.fm.summon()
        self.wait_for(lambda: self.fm.has_focus, "summoned")
        self.assertEqual(self.fm.mode, HOME)

    def test_revoked_by_daemon_is_recovered(self):
        # e.g. the daemon's exit timeout released the OS
        self.daemon.app_releases(OS_ID)
        self.wait_for(lambda: self.fm.has_focus and self.daemon.foreground == OS_ID,
                      "re-acquired after revoke")



class AdoptionTests(unittest.TestCase):
    def test_adopt_and_restore_round_trip(self):
        import os
        import shutil
        import tempfile
        from mfruitos.launcher.app_manager.lifecycle import AppLifecycle
        from mfruitos.paths import Paths
        tmp = tempfile.mkdtemp()
        daemon = FakeDaemon().start()
        try:
            paths = Paths(os.path.join(tmp, "os"), os.path.join(tmp, "d"))
            paths.ensure()
            life = AppLifecycle(WhisplayDaemonClient(daemon.socket_path), paths)
            original = {"app_id": "walkie", "display_name": "WalkieTalkie", "icon": "WT",
                        "launch_command": "/home/u/WalkieTalkie/run.sh", "cwd": "/home/u/WalkieTalkie",
                        "exit_gesture": "none", "priority": 45, "use_daemon_default_log": True,
                        "disable_esc_exit_key": True}
            self.assertTrue(life.adopt(original))
            adopted = daemon.apps["walkie"]
            self.assertIn("mfruit-run", adopted["launch_command"])
            for key in ("cwd", "exit_gesture", "priority", "disable_esc_exit_key", "icon"):
                self.assertEqual(adopted[key], original[key], key)
            self.assertFalse(life.adopt(dict(original, launch_command=adopted["launch_command"])))
            self.assertEqual(life.restore_adopted(), 1)
            self.assertEqual(daemon.apps["walkie"]["launch_command"], original["launch_command"])
            self.assertFalse(life.is_adopted("walkie"))
        finally:
            daemon.stop()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
