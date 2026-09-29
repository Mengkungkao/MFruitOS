import time
import unittest

import helpers  # noqa: F401
from fake_daemon import FakeDaemon
from mfruitos.daemon.client import WhisplayDaemonClient
from mfruitos.daemon.events import EventStream
from mfruitos.launcher import focus as focus_mod
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


class FocusIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.daemon = FakeDaemon().start()
        self.daemon.handle({"cmd": "app.register", "payload": {"app_id": OS_ID}}, None)
        for app_id in ("good", "crashy", "ghost", "handoff"):
            self.daemon.handle({"cmd": "app.register", "payload": {"app_id": app_id}}, None)
        self.daemon.behaviour.update({"crashy": "crash", "ghost": "headless",
                                      "handoff": "handoff:whisplay-wifi"})
        self.loop = EventLoop()
        self.client = WhisplayDaemonClient(self.daemon.socket_path, timeout=2)
        self.listener = Recorder()
        self.fm = ForegroundManager(self.client, self.loop, OS_ID, self.listener)
        self.stream = EventStream(self.daemon.socket_path,
                                  lambda n, p: self.loop.post(self.fm.on_event, n, p))
        self.stream.start()
        self.wait_for(lambda: self.fm.has_focus, "initial focus")

    def tearDown(self):
        self.stream.stop()
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
        self.fm.launch("good")
        self.wait_for(lambda: self.fm.phase == "foreground", "app foreground")
        self.assertEqual(self.daemon.foreground, "good")
        self.assertFalse(self.fm.has_focus)
        self.daemon.app_exits("good")
        self.wait_for(lambda: self.fm.has_focus, "focus back")
        self.assertEqual(self.fm.mode, HOME)
        self.assertIn(("on_app_returned", "good", APP), self.listener.calls)
        self.assertEqual(self.daemon.foreground, OS_ID)

    def test_own_release_does_not_steal_back_during_launch(self):
        self.daemon.launch_delay = 0.4
        self.fm.launch("good")
        self.settle(0.2)  # desktop_entered from our own release has been processed
        self.assertEqual(self.fm.mode, APP)
        self.assertFalse(self.fm.has_focus)
        self.wait_for(lambda: self.daemon.foreground == "good", "app foreground")

    def test_launch_failure_detected(self):
        self.fm.launch("crashy")
        self.wait_for(lambda: self.fm.has_focus, "focus back after crash")
        failed = [c for c in self.listener.calls if c[0] == "on_launch_failed"]
        self.assertEqual(failed[0][1], "crashy")

    def test_handoff_to_daemon_page_is_not_a_failure(self):
        # Regression (seen on hardware with ConnectWifi): the launched app opens a
        # daemon page and exits. That must not be reported as a failed launch.
        self.fm.launch("handoff")
        self.wait_for(lambda: self.fm.target == "whisplay-wifi", "follow the hand-off")
        self.settle(0.5)
        self.assertNotIn("on_launch_failed", self.listener.names())
        self.assertFalse(self.fm.has_focus)
        self.daemon.internal_back("whisplay-wifi")
        self.wait_for(lambda: self.fm.has_focus, "back home after the page")
        self.assertNotIn("on_launch_failed", self.listener.names())

    def test_headless_app_detected(self):
        old = focus_mod.PENDING_TIMEOUT_SEC
        focus_mod.PENDING_TIMEOUT_SEC = 0.8
        self.daemon.pending_timeout = 0.5
        try:
            self.fm.launch("ghost")
            self.wait_for(lambda: self.fm.has_focus, "focus back after headless")
        finally:
            focus_mod.PENDING_TIMEOUT_SEC = old
        self.assertIn(("on_app_headless", "ghost"), self.listener.calls)

    def test_unknown_app_launch_rejected(self):
        self.fm.launch("nope")
        self.wait_for(lambda: self.fm.has_focus, "focus back")
        self.settle(0.3)
        self.assertIn("on_launch_failed", self.listener.names())
        # Regression: the echo of our own release must not drop the fresh focus.
        self.assertEqual(self.listener.names().count("on_focus_gained"), 2)
        self.assertTrue(self.fm.has_focus)

    def test_system_page_round_trip(self):
        self.fm.launch("whisplay-wifi", system_page=True)
        self.settle(0.2)
        self.assertEqual(self.fm.mode, SYSTEM)
        self.assertEqual(self.daemon.foreground, "whisplay-wifi")
        self.daemon.internal_back("whisplay-wifi")
        self.wait_for(lambda: self.fm.has_focus, "back from wifi page")
        self.assertIn(("on_app_returned", "whisplay-wifi", SYSTEM), self.listener.calls)

    def test_app_releasing_focus_but_staying_alive(self):
        self.fm.launch("good")
        self.wait_for(lambda: self.fm.phase == "foreground", "app foreground")
        self.daemon.app_releases("good")
        self.wait_for(lambda: self.fm.has_focus, "focus back")
        self.assertIn("good", self.daemon.running)

    def test_button_events_only_for_os_while_home(self):
        self.daemon.press()
        self.daemon.release()
        self.wait_for(lambda: ("on_button", False) in self.listener.calls, "button")
        self.assertIn(("on_button", True), self.listener.calls)
        self.fm.launch("good")
        self.wait_for(lambda: self.fm.phase == "foreground", "app foreground")
        count = len([c for c in self.listener.calls if c[0] == "on_button"])
        self.daemon.press()
        self.daemon.release()
        self.settle(0.2)
        self.assertEqual(count, len([c for c in self.listener.calls if c[0] == "on_button"]))

    def test_screen_lock_and_unlock(self):
        self.fm.launch("whisplay-volume", system_page=True)
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


if __name__ == "__main__":
    unittest.main()
