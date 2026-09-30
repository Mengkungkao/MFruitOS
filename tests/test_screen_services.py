"""App handoff preserves Settings for Wi-Fi and launch guards for every app."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import helpers  # noqa: F401
from mfruitos.apps.registry import AppEntry
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.ui.screens.dialogs import LoadingScreen


class LaunchTransitionTests(unittest.TestCase):
    def setUp(self):
        self.services = ScreenServices()
        self.settings_screen = object()
        self.stack = [self.settings_screen]
        self.frames = []
        self.services.registry = Mock()
        self.services.focus = SimpleNamespace(connected=True)
        self.services.apps = Mock(busy=False)
        self.services.apps.request_launch.return_value = (True, "")
        self.services.lifecycle = Mock()
        self.services.backlight = Mock()
        self.services.led = Mock()
        self.services.flush_settings = Mock()
        self.services.router = SimpleNamespace(top=self.settings_screen)
        self.services.router.push = Mock(side_effect=self.push)
        self.services.router.pop = Mock(side_effect=self.pop)
        self.services._render_now = Mock(side_effect=lambda: self.frames.append(self.stack[-1]))

    def push(self, screen):
        self.stack.append(screen)
        self.services.router.top = screen

    def pop(self):
        self.stack.pop()
        self.services.router.top = self.stack[-1]

    def entry(self, app_id):
        entry = AppEntry(app_id, app_id.title(), "daemon")
        self.services.registry.get.return_value = entry
        return entry

    def test_wifi_keeps_settings_visible_and_uses_launch_authority(self):
        entry = self.entry("connectwifi")
        self.assertTrue(self.services.launch_app("connectwifi", source="settings"))
        self.assertEqual(self.frames, [self.settings_screen])
        self.services.router.push.assert_not_called()
        self.services.lifecycle.prepare_launch.assert_called_once_with(entry)
        self.services.apps.request_launch.assert_called_once_with("connectwifi", "app", "settings")

    def test_other_apps_still_draw_loading_screen(self):
        self.entry("demo")
        self.assertTrue(self.services.launch_app("demo"))
        self.assertIsInstance(self.frames[0], LoadingScreen)
        self.assertIs(self.services.router.top, self.frames[0])
        self.assertEqual(self.frames[0].app_id, "demo")

    def test_rejected_launch_never_pops_settings(self):
        for app_id in ("connectwifi", "demo"):
            with self.subTest(app_id=app_id):
                self.entry(app_id)
                self.services.apps.request_launch.return_value = (False, "refused")
                self.assertFalse(self.services.launch_app(app_id, source="settings"))
                self.assertEqual(self.stack, [self.settings_screen])

    def test_duplicate_wifi_launch_does_not_prepare_or_redraw(self):
        self.entry("connectwifi")
        self.services.apps.busy = True
        self.assertFalse(self.services.launch_app("connectwifi", source="settings"))
        self.services.lifecycle.prepare_launch.assert_not_called()
        self.services._render_now.assert_not_called()
        self.services.apps.request_launch.assert_called_once_with("connectwifi", "app", "settings")


if __name__ == "__main__":
    unittest.main()
