"""Launch-lifecycle regression tests against the REAL whisplay-daemon code.

The daemon runs from a Whisplay checkout (WHISPLAY_SRC, ~/Whisplay or
~/ai-chatbot/Whisplay) with a simulated board; fake apps take the screen the
way Whisplay clients do (subscribe, then acquire with retries) after a
realistic start-up delay. MFruit OS runs in-process and is driven only by
simulated physical button presses, exactly like on the device.

Root causes covered (docs/platform/LIFECYCLE.md):
RC1  acting while the button was still held leaked the release to the next
     screen owner (daemon desktop launched its own selection, daemon pages
     took it as "select", apps got a stray release)
RC2  presses during an app's start-up reached the daemon's own desktop
RC3  the daemon's single pending-launch slot
RC4  no single-flight launch rule in MFruit OS
"""

import contextlib
import logging
import os
import random
import shutil
import threading
import time
import unittest

import helpers  # noqa: F401
from real_daemon import RealDaemon, find_whisplay_src, new_home
from mfruitos.daemon.client import WhisplayDaemonClient
from mfruitos.launcher.runtime import Runtime
from mfruitos.paths import Paths

WHISPLAY_SRC = find_whisplay_src()
STARTUP = "1.5"   # seconds a real Python app needs before asking for the screen
# whisplay-daemon's internal pages in its desktop order (priority 200..170);
# a daemon build may lack some of them.
DAEMON_PAGES = ("whisplay-bluetooth", "whisplay-wifi", "whisplay-volume", "whisplay-system")


@unittest.skipIf(WHISPLAY_SRC is None, "Whisplay source not found (set WHISPLAY_SRC)")
class RealDaemonLaunchTests(unittest.TestCase):
    def setUp(self):
        logging.getLogger("mfruitos").setLevel(logging.CRITICAL)
        self.home = new_home()
        self.daemon = RealDaemon(self.home)
        for app_id, priority, *flags in (("alpha", 30, "--startup", STARTUP),
                                         ("beta", 20, "--startup", STARTUP),
                                         ("gamma", 15, "--startup", STARTUP),
                                         ("slow", 14, "--startup", "3.0"),
                                         ("slower", 13, "--startup", "6.0"),
                                         ("fast", 12),
                                         ("crashy", 10, "--crash")):
            self.daemon.add_app(app_id, priority, *flags)
        self.daemon.start(WHISPLAY_SRC)
        # As on a real device: the daemon's own desktop selection has been moved
        # before (it is not on the MFruit OS entry).
        for _ in range(3):
            self.daemon.press()
            time.sleep(0.03)
            self.daemon.release()
            time.sleep(0.03)
        paths = Paths(os.path.join(self.home, "os"), os.path.join(self.home, ".whisplay-daemon"))
        self.rt = Runtime(paths, helpers.ROOT, socket_path=self.daemon.socket_path,
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.settings.set("button.click_gap_ms", 200)
        self.rt.settings.set("system.show_system_pages_on_home", True)
        self.thread = threading.Thread(target=self.rt.run, daemon=True)
        self.thread.start()
        self.wait(lambda: self.rt.focus.has_focus and not self.rt._booting
                  and self.rt.router.top is self.rt.home_screen, "MFruit OS home", 20)
        self.baseline = len(self.daemon.launched())

    def tearDown(self):
        self.rt.loop.post(self.rt.shutdown, 0)
        self.thread.join(5)
        self.daemon.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    # ----------------------------------------------------------- helpers
    def wait(self, condition, what, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}; daemon={self.daemon.state()} "
                  f"focus={self.rt.focus.describe()}")

    def launches(self):
        return self.daemon.launched()[self.baseline:]

    def tap(self):
        self.daemon.press()
        time.sleep(0.06)
        self.daemon.release()
        time.sleep(0.3)  # longer than the click gap: a single click

    def hold(self, seconds=0.9):
        self.daemon.press()
        time.sleep(seconds)
        self.daemon.release()

    def selected_key(self):
        home = self.rt.home_screen
        return home.entries()[home.selected].key

    def go_to(self, key):
        for _ in range(20):
            if self.selected_key() == key:
                return
            self.tap()
        self.fail(f"could not select {key}")

    def launch_by_hold(self, key):
        self.go_to(key)
        self.assertNotEqual(self.daemon.state()["selected"], key,
                            "precondition: the daemon desktop selection is elsewhere")
        self.hold()

    # ------------------------------------------------------------- tests
    def test_selection_does_not_launch(self):
        start = self.selected_key()
        for _ in range(3):
            self.tap()
        self.assertNotEqual(self.selected_key(), start)
        time.sleep(0.5)
        self.assertEqual(self.launches(), [])
        self.assertEqual(self.daemon.state()["foreground"], "mfruit-os")

    def test_correct_app_launches(self):
        self.launch_by_hold("alpha")
        self.wait(lambda: "acquired" in self.daemon.records("alpha"), "alpha on screen")
        self.assertEqual(self.daemon.state()["foreground"], "alpha")
        self.assertEqual(self.launches(), ["alpha"])

    def test_wrong_app_is_not_launched(self):
        # RC1(a): the release used to make the daemon desktop launch its own selection.
        self.launch_by_hold("beta")
        self.wait(lambda: "acquired" in self.daemon.records("beta"), "beta on screen")
        time.sleep(1.0)
        self.assertEqual(self.launches(), ["beta"])
        for other in ("alpha", "gamma", "fast"):
            self.assertEqual(self.daemon.records(other), [], other)

    def test_stale_event_is_ignored(self):
        # RC1(c): a fast app used to receive the release of the launching hold.
        self.launch_by_hold("fast")
        self.wait(lambda: "acquired" in self.daemon.records("fast"), "fast on screen")
        time.sleep(0.5)
        records = self.daemon.records("fast")
        self.assertNotIn("button_released", records)
        self.assertNotIn("button_pressed", records)

    def test_daemon_page_is_not_closed_by_the_launch_gesture(self):
        # RC1(b): the release was taken as "select" on the page's first item (Back).
        page = next(p for p in ("whisplay-volume", "whisplay-system", "whisplay-wifi")
                    if p != self.daemon.state()["selected"])
        self.launch_by_hold(page)
        self.wait(lambda: self.daemon.state()["foreground"] == page, page)
        time.sleep(1.0)
        self.assertEqual(self.daemon.state()["foreground"], page)

    def test_app_exit_returns_to_launcher(self):
        self.launch_by_hold("alpha")
        self.wait(lambda: "acquired" in self.daemon.records("alpha"), "alpha on screen")
        for _ in range(4):  # the daemon's exit gesture for quad_click apps
            self.daemon.press()
            time.sleep(0.05)
            self.daemon.release()
            time.sleep(0.1)
        self.wait(lambda: "exit" in self.daemon.records("alpha"), "alpha exits")
        self.wait(lambda: self.rt.focus.has_focus and self.daemon.state()["foreground"] == "mfruit-os",
                  "back home")
        self.assertIs(self.rt.router.top, self.rt.home_screen)
        self.assertEqual(self.launches(), ["alpha"])

    def test_crashed_app_does_not_crash_launcher(self):
        self.launch_by_hold("crashy")
        self.wait(lambda: self.rt.focus.has_focus and type(self.rt.router.top).__name__ == "MessageScreen",
                  "error screen", 12)
        self.assertTrue(self.thread.is_alive())
        self.assertEqual(self.daemon.state()["foreground"], "mfruit-os")
        self.assertEqual(self.launches(), ["crashy"])

    def test_rapid_input_is_safe(self):
        rng = random.Random(1)
        for _ in range(25):
            self.daemon.press()
            time.sleep(rng.uniform(0.02, 0.15))
            self.daemon.release()
            time.sleep(rng.uniform(0.02, 0.15))
        time.sleep(1.0)
        self.assertEqual(self.launches(), [])
        self.assertTrue(self.rt.focus.has_focus)

    def test_duplicate_launch_is_prevented(self):
        # RC4: a second request while a launch is in progress must be refused,
        # whatever its source (autostart, control socket, a stale Retry).
        self.rt.loop.post(self.rt.launch_app, "alpha")
        self.rt.loop.post(self.rt.launch_app, "beta")
        self.rt.loop.post(self.rt.launch_app, "alpha")
        self.wait(lambda: "acquired" in self.daemon.records("alpha"), "alpha on screen")
        time.sleep(2.5)
        self.assertEqual(self.launches(), ["alpha"])
        self.assertEqual(self.daemon.records("beta"), [])
        self.assertEqual(self.daemon.records("alpha").count("start"), 1)

    def put_daemon_selection_on(self, key):
        """Move whisplay-daemon's own desktop selection (as a user of that desktop would)."""
        self.rt.loop.post(self.rt.yield_to_desktop)
        self.wait(lambda: self.daemon.state()["foreground"] is None, "daemon desktop")
        for _ in range(20):
            if self.daemon.state()["selected"] == key:
                break
            self.daemon.press()
            time.sleep(0.05)
            self.daemon.release()
            time.sleep(0.05)
        self.assertEqual(self.daemon.state()["selected"], key)
        self.rt.loop.post(self.rt.lifecycle.set_gate, "gate")
        self.rt.loop.post(self.rt.focus.summon)
        self.wait(lambda: self.rt.focus.has_focus, "MFruit OS back")
        self.baseline = len(self.daemon.launched())

    def select_on_daemon_desktop(self, key):
        """Tap the daemon desktop (which owns the button) until ``key`` is selected."""
        for _ in range(20):
            if self.daemon.state()["selected"] == key:
                return
            self.daemon.press()
            time.sleep(0.05)
            self.daemon.release()
            time.sleep(0.05)
        self.assertEqual(self.daemon.state()["selected"], key)

    def test_press_during_launch_window_cannot_start_a_second_app(self):
        # RC2: while an app starts up the daemon desktop owns the button. A hold
        # there launches its selected entry; the launch gate must refuse it.
        self.put_daemon_selection_on("beta")
        self.launch_by_hold("slower")             # 6 s start-up: the window stays open
        # The daemon itself sometimes turns a hold into a tap (its monitor loop
        # can reset the press start before the release callback runs), so hold
        # until it really attempts a launch.
        # A hold the daemon turned into a tap also moved its selection on, so
        # put it back on beta before holding again.
        for _ in range(4):
            time.sleep(0.2)
            self.select_on_daemon_desktop("beta")
            self.hold()
            if "beta" in self.launches():
                break
        self.assertIn("beta", self.launches(), "the daemon desktop never tried to launch beta")
        self.wait(lambda: "acquired" in self.daemon.records("slower"), "slower app on screen", 15)
        time.sleep(1.0)
        self.assertEqual(self.daemon.records("beta"), [], "beta must never run")
        self.assertEqual(self.daemon.state()["foreground"], "slower")
        self.assertEqual(self.daemon.state()["running"], ["slower"])
        with open(os.path.join(self.rt.paths.logs_dir, "launch-gate.log")) as fp:
            self.assertIn("DENIED beta", fp.read())

    def wait_for_launch_window(self, app_id):
        """Wait until the daemon desktop owns the button: MFruit OS has released
        the screen and ``app_id`` is the daemon's pending launch. Synchronize on
        this observed state, never on a fixed delay after the launching hold."""
        def window_open():
            state = self.daemon.state()
            return state["foreground"] is None and state["pending"] == app_id
        self.wait(window_open, f"launch window of {app_id}")

    @contextlib.contextmanager
    def lifecycle_messages(self):
        messages = []
        capture = logging.Handler()
        capture.emit = lambda record: messages.append(record.getMessage())
        lifecycle = logging.getLogger("mfruitos.lifecycle")
        lifecycle.addHandler(capture)
        logging.getLogger("mfruitos").setLevel(logging.INFO)
        try:
            yield messages
        finally:
            lifecycle.removeHandler(capture)

    def test_press_during_launch_window_page_is_closed(self):
        # RC2 for daemon pages: the daemon opens them without any launch command,
        # so they cannot be gated; MFruit OS closes the intruder and the app wins.
        # While a launch is pending, whisplay-daemon can turn a hold into a tap
        # (docs/platform/HOST_API.md, daemon fact 8): its monitor loop resets the
        # press start before the release callback runs, and the tap only moves the
        # desktop selection. Daemon pages are consecutive in the desktop order, so
        # start on the first one and hold again while the selection is a page.
        available = {app["app_id"] for app in self.rt.client.list_apps()}
        pages = [page for page in DAEMON_PAGES if page in available]
        self.put_daemon_selection_on(pages[0])
        with self.lifecycle_messages() as messages:
            self.launch_by_hold("slower")         # 6 s start-up: room for another hold
            opened = []
            for _ in pages:
                self.wait_for_launch_window("slower")
                if self.daemon.state()["selected"] not in pages:
                    break
                self.hold()                        # the daemon desktop opens its page
                opened = [app for app in self.launches() if app in pages]
                if opened:
                    break
            if not opened:
                self.skipTest("whisplay-daemon turned every hold into a tap; eviction is covered by "
                              "test_page_opened_by_another_client_during_launch_window_is_closed")
            self.wait(lambda: "acquired" in self.daemon.records("slower"), "slower app on screen", 15)
            time.sleep(1.0)
        self.assertEqual(self.daemon.state()["foreground"], "slower")
        self.assertTrue(any(f"INTRUDER app={opened[0]}" in m for m in messages), messages)

    def test_page_opened_by_another_client_during_launch_window_is_closed(self):
        # The same guarantee without the daemon desktop's button timing: a page
        # that takes the screen while a launch is pending is an intruder. The
        # daemon's app.launch runs the same _launch_app as a desktop hold.
        page = "whisplay-volume"
        with self.lifecycle_messages() as messages:
            self.launch_by_hold("slow")
            self.wait_for_launch_window("slow")
            WhisplayDaemonClient(self.daemon.socket_path).launch_app(page)
            self.wait(lambda: "acquired" in self.daemon.records("slow"), "slow app on screen", 12)
            time.sleep(1.0)
        self.assertEqual(self.daemon.state()["foreground"], "slow")
        self.assertTrue(any(f"INTRUDER app={page}" in m for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
