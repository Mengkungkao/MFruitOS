"""After an app is closed, the registry is refreshed whatever way it ended.

Found on the Pi (2026-10-03): RadioConnect exited on its own, the refresh at
session end still saw it running, and `mfruitctl rollback` was then refused
("Stop the app before rolling back") although nothing was running.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import helpers  # noqa: F401
from mfruitos.launcher.runtime import Runtime


class AppCloseRefreshTests(unittest.TestCase):
    def close(self, result):
        rt = SimpleNamespace(
            registry=Mock(), lifecycle=Mock(), refresh_registry=Mock(),
            run_task=lambda name, work, done, lane: done(work()))
        rt.registry.get.return_value = SimpleNamespace(background=False)
        rt.lifecycle.ensure_stopped.return_value = result
        Runtime._close_app_after_session(rt, SimpleNamespace(app_id="demo", id="s1", kind="app"))
        return rt.refresh_registry

    def test_every_way_of_closing_refreshes_the_registry(self):
        for result in ("exited", "terminated", "killed", "not running"):
            with self.subTest(result=result):
                self.close(result).assert_called_once_with(query_daemon=True)


if __name__ == "__main__":
    unittest.main()
