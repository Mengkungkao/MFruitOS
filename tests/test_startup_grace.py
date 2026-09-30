"""The daemon startup grace is bounded and ends when the launcher takes over."""

import importlib.util
import os
import unittest
from unittest.mock import patch

from helpers import ROOT, FakeClock


spec = importlib.util.spec_from_file_location(
    "mfruit_daemon_startup", os.path.join(ROOT, "scripts", "whisplay-daemon-mfruit.py"))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class StartupGraceTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(100)
        self.addCleanup(patch.stopall)
        patch.object(wrapper.time, "monotonic", self.clock).start()
        self.held = patch.object(wrapper.MfruitProbe, "_held", return_value=False).start()
        self.desktop = patch.object(wrapper.MfruitProbe, "_desktop_mode", return_value=False).start()

    def test_hides_desktop_before_launcher_lock_exists(self):
        probe = wrapper.MfruitProbe("launcher.lock", startup_grace=30)
        self.assertTrue(probe())
        self.clock.advance(20)
        self.assertTrue(probe())

    def test_first_probe_runs_even_at_monotonic_zero(self):
        self.clock.now = 0
        probe = wrapper.MfruitProbe("launcher.lock", startup_grace=30)
        self.assertTrue(probe())
        self.held.assert_called_once()

    def test_grace_expires_at_deadline_even_inside_cache_window(self):
        probe = wrapper.MfruitProbe("launcher.lock", startup_grace=30)
        self.clock.advance(29.9)
        self.assertTrue(probe())
        self.clock.advance(0.1)
        self.assertFalse(probe())

    def test_lock_handoff_ends_grace_so_crash_restores_desktop(self):
        probe = wrapper.MfruitProbe("launcher.lock", startup_grace=30)
        self.assertTrue(probe())
        self.held.return_value = True
        self.clock.advance(1)
        self.assertTrue(probe())
        self.held.return_value = False
        self.clock.advance(1)
        self.assertFalse(probe())

    def test_held_lock_keeps_desktop_hidden_after_grace(self):
        probe = wrapper.MfruitProbe("launcher.lock", startup_grace=30)
        self.held.return_value = True
        self.clock.advance(40)
        self.assertTrue(probe())

    def test_explicit_desktop_mode_overrides_startup_grace(self):
        probe = wrapper.MfruitProbe("launcher.lock", startup_grace=30)
        self.desktop.return_value = True
        self.assertFalse(probe())

    def test_default_has_no_grace_and_preserves_probe_cache(self):
        probe = wrapper.MfruitProbe("launcher.lock")
        self.assertFalse(probe())
        self.held.return_value = True
        self.clock.advance(0.1)
        self.assertFalse(probe())
        self.clock.advance(wrapper.CACHE_SEC)
        self.assertTrue(probe())


if __name__ == "__main__":
    unittest.main()
