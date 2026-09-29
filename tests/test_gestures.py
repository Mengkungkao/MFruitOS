import unittest

from helpers import FakeClock
from mfruitos.launcher.loop import EventLoop
from mfruitos.launcher.navigation.gestures import GestureRecognizer

DEFAULT_MAP = {"single_click": "next", "double_click": "previous", "triple_click": "none",
               "long_press": "select", "quad_click": "back"}


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.loop = EventLoop(clock=self.clock)
        self.events = []
        self.rec = GestureRecognizer(self.events.append, self.loop.call_later, self.clock)
        self.rec.configure(DEFAULT_MAP, 300, 700)

    def step(self, seconds):
        self.clock.advance(seconds)
        self.loop.run_once()

    def click(self, hold=0.08, gap=0.1):
        self.rec.press()
        self.step(hold)
        self.rec.release()
        self.step(gap)

    def test_single_click_resolves_after_gap(self):
        self.click()
        self.assertEqual(self.events, [])
        self.step(0.3)
        self.assertEqual(self.events, ["single_click"])

    def test_double_and_triple(self):
        self.click(); self.click()
        self.step(0.4)
        self.click(); self.click(); self.click()
        self.step(0.4)
        self.assertEqual(self.events, ["double_click", "triple_click"])

    def test_quad_click_fires_immediately_once(self):
        for _ in range(4):
            self.click()
        self.assertEqual(self.events, ["quad_click"])
        self.step(1.0)
        self.assertEqual(self.events, ["quad_click"])

    def test_long_press_arms_while_held_and_fires_on_release(self):
        # Regression RC1: acting while the button was still down leaked the
        # release to the next screen owner.
        armed = []
        self.rec._on_armed = armed.append
        self.rec.press()
        self.step(0.69)
        self.assertEqual((self.events, armed), ([], []))
        self.step(0.02)
        self.assertEqual(self.events, [])            # nothing happens while held
        self.assertEqual(armed, [True])              # only visual feedback
        self.step(2.0)
        self.assertEqual(self.events, [])
        self.rec.release()
        self.assertEqual(self.events, ["long_press"])
        self.assertEqual(armed, [True, False])
        self.step(1.0)
        self.assertEqual(self.events, ["long_press"])

    def test_reset_while_armed_cancels_the_long_press(self):
        self.rec.press()
        self.step(0.8)
        self.rec.reset()                             # e.g. the screen changed owner
        self.rec.release()
        self.step(1.0)
        self.assertEqual(self.events, [])

    def test_click_then_long_press_flushes_click_first(self):
        self.click()
        self.rec.press()
        self.step(0.8)
        self.assertEqual(self.events, ["single_click"])
        self.rec.release()
        self.assertEqual(self.events, ["single_click", "long_press"])

    def test_release_without_press_ignored(self):
        self.rec.release()
        self.step(1.0)
        self.assertEqual(self.events, [])

    def test_slow_clicks_are_separate_singles(self):
        self.click(gap=0.5)
        self.click(gap=0.5)
        self.assertEqual(self.events, ["single_click", "single_click"])

    def test_eager_mode_when_multi_clicks_unmapped(self):
        mapping = dict(DEFAULT_MAP, double_click="none")
        self.rec.configure(mapping, 300, 700)
        self.rec.press(); self.step(0.05); self.rec.release()
        self.assertEqual(self.events, ["single_click"])  # no wait for the gap
        for _ in range(3):
            self.click()
        self.assertEqual(self.events, ["single_click"] * 4 + ["quad_click"])

    def test_reset_cancels_pending(self):
        self.click()
        self.rec.reset()
        self.step(1.0)
        self.assertEqual(self.events, [])


class EventLoopTests(unittest.TestCase):
    def test_timers_and_cancel(self):
        clock = FakeClock()
        loop = EventLoop(clock=clock)
        calls = []
        loop.call_later(1.0, calls.append, "a")
        timer = loop.call_later(2.0, calls.append, "b")
        loop.post(calls.append, "posted")
        loop.run_once()
        self.assertEqual(calls, ["posted"])
        clock.advance(1.5)
        timer.cancel()
        loop.run_once()
        clock.advance(1.0)
        loop.run_once()
        self.assertEqual(calls, ["posted", "a"])

    def test_handler_exception_does_not_stop_loop(self):
        loop = EventLoop()
        calls = []
        loop.post(lambda: 1 / 0)
        loop.post(calls.append, "after")
        loop.run_once()
        self.assertEqual(calls, ["after"])


if __name__ == "__main__":
    unittest.main()
