"""Fruit Store apps that need system packages (2026-10-05: AI Chatbot needs
sox, mpg123, cairosvg, … which only sudo can install, so the Store cannot)."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from helpers import ROOT, TempHomeTestCase
from mfruitos.updater import autoinstall, catalog

BASH = shutil.which("bash")


def entry(app_id="chat", **changes):
    item = dict(id=app_id, name="Chat", description="", repository=f"https://github.com/example/{app_id}",
                ref="b" * 40, url=f"https://api.github.com/repos/example/{app_id}/tarball/" + "b" * 40,
                sha256="c" * 64, native=True, version="1.0.0", system_packages=["sox", "mpg123"])
    item.update(changes)
    return item


class CatalogueFieldTests(TempHomeTestCase):
    def test_package_names_are_validated(self):
        self.assertEqual(catalog.check_entry(entry())["system_packages"], ["sox", "mpg123"])
        for bad in (["sox; rm -rf /"], ["-y"], "sox", ["Sox"], ["a" * 70], ["x"] * 41):
            with self.subTest(bad=bad), self.assertRaises(catalog.CatalogError):
                catalog.check_entry(entry(system_packages=bad))

    def test_missing_packages_come_from_dpkg(self):
        out = "sox install ok installed\nmpg123 deinstall ok config-files\n"
        with patch("subprocess.run", return_value=Mock(stdout=out)) as run:
            self.assertEqual(catalog.missing_packages(["sox", "mpg123", "gone"]), ["mpg123", "gone"])
        self.assertEqual(run.call_args.args[0][:2], ["dpkg-query", "-W"])
        with patch("subprocess.run", side_effect=OSError("no dpkg")):
            self.assertEqual(catalog.missing_packages(["sox"]), ["sox"])
        self.assertEqual(catalog.missing_packages([]), [])

    def test_missing_packages_are_a_requirement_with_the_setup_command(self):
        with patch.object(catalog, "missing_packages", return_value=["mpg123"]):
            problems = catalog.missing_requirements(entry())
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith(catalog.PACKAGES_MISSING))
        self.assertIn("setup-app.sh chat", problems[0])
        with patch.object(catalog, "missing_packages", return_value=[]):
            self.assertEqual(catalog.missing_requirements(entry()), [])

    def test_a_queued_app_waits_for_its_packages(self):
        autoinstall.add(self.paths.home, ["chat"])
        with patch.object(catalog, "entries", return_value=[entry()]), \
                patch.object(catalog, "missing_packages", return_value=["mpg123"]):
            with self.assertLogs("mfruitos.updater.autoinstall", "INFO"):
                self.assertEqual(autoinstall.next_app(self.paths.home, set()), (None, []))
        with patch.object(catalog, "entries", return_value=[entry()]), \
                patch.object(catalog, "missing_packages", return_value=[]):
            self.assertEqual(autoinstall.next_app(self.paths.home, set())[0], "chat")


class StoreTextTests(TempHomeTestCase):
    def test_store_says_setup_first_and_how(self):
        from mfruitos.apps.registry import AppRegistry
        from mfruitos.launcher.services import ScreenServices
        from mfruitos.launcher.ui.screens.updater import InstallAppScreen
        from mfruitos.system.settings import Settings
        os_ = ScreenServices()
        os_.settings = Settings(None)
        os_.registry = AppRegistry(self.paths, os_.settings, "1.4.0")
        os_.push, os_.updater, os_.start_job = Mock(), Mock(), Mock()
        os_.run_task = lambda name, fn, done, error=None, lane="quick": done(fn()) \
            if name == "app-requirements" else None
        with patch.object(catalog, "entries", return_value=[entry()]), \
                patch.object(catalog, "missing_packages", return_value=["mpg123"]):
            screen = InstallAppScreen(os_)
            screen.redraw = Mock()
            screen.on_show()
            row = screen.items()[0]
            self.assertEqual((row.value, row.subtitle), ("Download", "Needs setup first"))
            row.action()
        dialog = os_.push.call_args.args[0]
        self.assertIn("setup-app.sh chat", dialog.message)


@unittest.skipUnless(BASH and os.name == "posix", "bash is required")
class SetupAppScriptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mfruit-setup-app-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.home = self.tmp / "home"
        (self.home / "cache").mkdir(parents=True)
        # The downloaded Fruit Store list, as the Store keeps it.
        (self.home / "cache" / "catalog.json").write_text(json.dumps(
            {"fetched_at": time.time(), "entries": [entry()]}), encoding="utf-8")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "commands.log"
        self.fake("sudo", 'printf "sudo %s\\n" "$*" >> "$LOG"\nexit "${SUDO_EXIT:-0}"\n')
        self.fake("dpkg-query", 'echo "sox install ok installed"\n')
        self.fake("systemctl", "exit 3\n")
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", LOG=str(self.log),
                        WHISPLAY_OS_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")

    def fake(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_script(self, *args):
        return subprocess.run([BASH, str(Path(ROOT) / "scripts" / "setup-app.sh"), *args],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def commands(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_installs_only_the_missing_packages_then_queues_the_app(self):
        result = self.run_script("--yes", "chat")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.commands()), 1)
        self.assertRegex(self.commands()[0], r"^sudo bash \S+/scripts/offline\.sh install mpg123$")
        self.assertEqual(autoinstall.load(str(self.home)), {"chat": 0})

    def test_check_changes_nothing(self):
        result = self.run_script("--check", "chat")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing: mpg123", result.stdout)
        self.assertEqual(self.commands(), [])
        self.assertEqual(autoinstall.load(str(self.home)), {})

    def test_failed_package_install_does_not_queue(self):
        self.env["SUDO_EXIT"] = "100"
        result = self.run_script("--yes", "chat")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(autoinstall.load(str(self.home)), {})

    def test_unknown_app_fails(self):
        result = self.run_script("--yes", "nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not in the Fruit Store list", result.stdout)


if __name__ == "__main__":
    unittest.main()
