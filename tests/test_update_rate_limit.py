"""An update check cut short by GitHub's rate limit is retried once it resets.

GitHub allows 60 unauthenticated API calls an hour per internet address,
shared by every device and computer at home. On 2026-10-12 the limit was used
up while AI Chatbot 1.1.0 was being released; a device whose check was
refused then would have waited a full check interval (12 hours) before seeing
the update. GitHub is faked; no network.
"""
from unittest import mock

from helpers import TempHomeTestCase
from mfruitos.apps.registry import AppEntry
from mfruitos.system.settings import Settings
from mfruitos.updater.github import RateLimitError, Release
from mfruitos.updater import service as service_module
from mfruitos.updater.service import UpdateService

RATE_LIMIT_MARGIN_SEC = getattr(service_module, "RATE_LIMIT_MARGIN_SEC", 60)

NOW = 1_791_760_000.0
RESET = NOW + 600


class RateLimitRetryTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.settings = Settings(None)
        self.settings.set("system.repository", "https://github.com/Mengkungkao/MFruitOS")
        self.github = mock.Mock()
        self.app = AppEntry("demo", "Demo", "os", version="1.0.2",
                            repository="https://github.com/Mengkungkao/demo")

    def service(self):
        return UpdateService(self.paths, self.settings, self.github, mock.Mock(), "1.5.1")

    def check(self, service, at):
        with mock.patch("time.time", return_value=at):
            service.check([self.app])

    def due(self, service, at):
        with mock.patch("time.time", return_value=at):
            return service.check_due()

    def test_a_refused_check_runs_again_after_the_reset(self):
        self.github.releases.side_effect = RateLimitError(RESET)
        service = self.service()
        self.check(service, NOW)
        self.assertIn("rate limit", service.info("demo").error)
        self.assertEqual(getattr(service, "retry_at", None), RESET + RATE_LIMIT_MARGIN_SEC)
        self.assertFalse(self.due(service, RESET))              # not before the limit resets
        self.assertTrue(self.due(service, RESET + RATE_LIMIT_MARGIN_SEC))
        # remembered across a restart (the device may reboot in between)
        self.assertTrue(self.due(self.service(), RESET + RATE_LIMIT_MARGIN_SEC))

    def test_the_retry_finds_the_update_and_normal_checks_resume(self):
        self.github.releases.side_effect = RateLimitError(RESET)
        service = self.service()
        self.check(service, NOW)
        self.github.releases.side_effect = None
        self.github.releases.return_value = [Release("1.1.0", "v1.1.0", tarball_url="https://x")]
        self.check(service, RESET + RATE_LIMIT_MARGIN_SEC)
        self.assertTrue(service.info("demo").update_available)
        self.assertFalse(getattr(service, "retry_at", 0.0))
        self.assertFalse(self.due(service, RESET + 3600))       # back to the 12 h interval

    def test_a_limit_without_a_reset_time_retries_like_offline(self):
        self.github.releases.side_effect = RateLimitError(0)
        service = self.service()
        self.check(service, NOW)
        self.assertTrue(self.due(service, NOW + 600 + RATE_LIMIT_MARGIN_SEC))
