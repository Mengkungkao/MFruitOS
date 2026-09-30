"""Whisplay's user interface in the background (scripts/whisplay-daemon-mfruit.py).

Runs the REAL whisplay-daemon code with MFruit OS's daemon wrapper patches and
MFruit OS on top, driven by simulated physical button presses.
"""

import hashlib
import logging
import os
import shutil
import threading
import time
import unittest

import helpers  # noqa: F401
from real_daemon import RealDaemon, find_whisplay_src, new_home
from mfruitos.launcher.runtime import Runtime
from mfruitos.paths import Paths

WHISPLAY_SRC = find_whisplay_src()


@unittest.skipIf(WHISPLAY_SRC is None, "Whisplay source not found (set WHISPLAY_SRC)")
class BackgroundUiTests(unittest.TestCase):
    def setUp(self):
        logging.getLogger("mfruitos").setLevel(logging.CRITICAL)
        self.home = new_home()
        self.daemon = RealDaemon(self.home)
        for app_id, priority, *flags in (("slow", 30, "--startup", "3.0"),
                                         ("beta", 20, "--startup", "1.0"),
                                         ("sticky", 10, "--linger")):
            self.daemon.add_app(app_id, priority, *flags)
        paths = Paths(os.path.join(self.home, "os"), os.path.join(self.home, ".whisplay-daemon"))
        self.paths = paths
        self.daemon.start(WHISPLAY_SRC, mfruit_lock=os.path.join(paths.state_dir, "launcher.lock"))
        # Move the daemon desktop's selection off the top, as on a used device.
        for _ in range(2):
            self.daemon.press()
            time.sleep(0.03)
            self.daemon.release()
            time.sleep(0.03)
        self.rt = Runtime(paths, helpers.ROOT, socket_path=self.daemon.socket_path)
        self.rt.settings.set("button.click_gap_ms", 200)
        self.thread = threading.Thread(target=self.rt.run, daemon=True)
        self.thread.start()
        self.wait(lambda: self.rt.focus.has_focus and not self.rt._booting
                  and self.rt.router.top is self.rt.home_screen, "MFruit OS home", 20)
        time.sleep(0.5)
        self.base = self.daemon.state()

    def tearDown(self):
        self.rt.loop.post(self.rt.shutdown, 0)
        self.thread.join(5)
        self.daemon.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def wait(self, condition, what, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}; daemon={self.daemon.state()} focus={self.rt.focus.describe()}")

    def tap(self):
        self.daemon.press()
        time.sleep(0.06)
        self.daemon.release()
        time.sleep(0.3)

    def hold(self, seconds=0.9):
        self.daemon.press()
        time.sleep(seconds)
        self.daemon.release()

    def open_by_hold(self, key):
        home = self.rt.home_screen
        for _ in range(20):
            if home.entries()[home.selected].key == key:
                break
            self.tap()
        self.hold()

    def quad(self):
        for _ in range(4):
            self.daemon.press()
            time.sleep(0.05)
            self.daemon.release()
            time.sleep(0.1)

    def launches(self):
        return [l["app_id"] for l in self.daemon.state()["launches"]][len(self.base["launches"]):]

    # ------------------------------------------------------------- tests
    def test_daemon_desktop_is_never_drawn_while_mfruit_runs(self):
        self.open_by_hold("slow")
        self.wait(lambda: "acquired" in self.daemon.records("slow"), "slow on screen")
        self.quad()
        self.wait(lambda: self.rt.focus.has_focus and self.daemon.state()["foreground"] == "mfruit-os",
                  "back home")
        self.assertEqual(self.daemon.state()["desktop_renders"], self.base["desktop_renders"])

    def test_loading_screen_stays_until_the_app_draws(self):
        self.open_by_hold("slow")
        time.sleep(1.2)                                   # the app is still starting
        loading = hashlib.sha1(self.rt._last_frame).hexdigest()[:12]
        self.assertEqual(type(self.rt.router.top).__name__, "LoadingScreen")
        self.assertEqual(self.daemon.state()["lcd"], loading, "LCD shows 'Opening…'")
        self.wait(lambda: "acquired" in self.daemon.records("slow"), "slow on screen")
        time.sleep(0.3)
        self.assertNotEqual(self.daemon.state()["lcd"], loading, "the app's own frame replaced it")

    def test_presses_during_start_up_do_nothing(self):
        self.open_by_hold("slow")
        time.sleep(0.2)
        self.hold()                                       # nobody owns the screen now
        self.tap()
        self.wait(lambda: "acquired" in self.daemon.records("slow"), "slow on screen")
        time.sleep(0.5)
        self.assertEqual(self.launches(), ["slow"])
        self.assertEqual(self.daemon.state()["foreground"], "slow")

    def test_app_is_closed_completely_after_exit(self):
        self.open_by_hold("sticky")
        self.wait(lambda: "acquired" in self.daemon.records("sticky"), "sticky on screen")
        self.quad()                                       # sticky releases but does not quit
        self.wait(lambda: "released_but_still_running" in self.daemon.records("sticky"), "released")
        self.wait(lambda: self.rt.focus.has_focus, "back home")
        self.wait(lambda: "sticky" not in self.daemon.state()["running"], "sticky closed", 12)

    def test_keep_running_app_is_left_running(self):
        self.rt.loop.post(self.rt.settings.set_app_flag, "sticky", "background", True)
        time.sleep(0.2)
        self.open_by_hold("sticky")
        self.wait(lambda: "acquired" in self.daemon.records("sticky"), "sticky on screen")
        self.quad()
        self.wait(lambda: self.rt.focus.has_focus, "back home")
        time.sleep(6)                                     # longer than the close grace period
        self.assertIn("sticky", self.daemon.state()["running"])

    def test_daemon_desktop_mode_shows_the_daemon_ui_again(self):
        self.rt.loop.post(self.rt.yield_to_desktop)
        self.wait(lambda: self.daemon.state()["foreground"] is None, "daemon desktop")
        time.sleep(0.5)
        self.assertGreater(self.daemon.state()["desktop_renders"], self.base["desktop_renders"])
        selected = self.daemon.state()["selected"]
        self.daemon.press()
        time.sleep(0.05)
        self.daemon.release()
        time.sleep(0.3)
        self.assertNotEqual(self.daemon.state()["selected"], selected, "the daemon desktop works")

    def test_without_mfruit_the_daemon_behaves_normally(self):
        self.rt.loop.post(self.rt.shutdown, 0)
        self.thread.join(5)
        time.sleep(0.5)                                   # the probe caches for 0.3 s
        selected = self.daemon.state()["selected"]
        self.daemon.press()
        time.sleep(0.05)
        self.daemon.release()
        time.sleep(0.3)
        state = self.daemon.state()
        self.assertNotEqual(state["selected"], selected)
        self.assertGreater(state["desktop_renders"], self.base["desktop_renders"])

    def test_grabbed_keyboard_can_leave_a_daemon_page(self):
        from mfruitos.sdk.keys import DOWN, UP, KeyEvent
        from mfruitos.daemon.client import DaemonRequestError
        self.rt.loop.post(self.rt.open_system_page, "whisplay-volume")
        self.wait(lambda: self.rt.focus.mode == "system", "Volume page")
        # The wrapper rejects keys addressed to a different page.
        with self.assertRaises(DaemonRequestError):
            self.rt.client.request("mfruit.page.key", {"app_id": "whisplay-system",
                                                       "kind": "key", "value": "escape"})
        self.rt.loop.post(self.rt._on_hardware_key, KeyEvent("key", "escape", DOWN, 1))
        self.rt.loop.post(self.rt._on_hardware_key, KeyEvent("key", "escape", UP, 1))
        self.wait(lambda: self.rt.focus.has_focus, "keyboard returns from Volume")


if __name__ == "__main__":
    unittest.main()
