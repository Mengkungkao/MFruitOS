"""Apps queued by the device installer install themselves (2026-10-05: the user
wants ``install.sh --radio`` to end with RadioConnect on the device, and the
radio settings written after the reboot without a second command)."""

import json
import os
import subprocess
import sys
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from helpers import ROOT, TempHomeTestCase
from mfruitos.apps.registry import AppEntry, AppRegistry
from mfruitos.hosts.lora.__main__ import BOOT_UNIT, boot_unit
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.tasks import TaskRunner
from mfruitos.system.settings import Settings
from mfruitos.updater import autoinstall, catalog
from mfruitos.updater.github import OfflineError


def entry(app_id, requires=()):
    return dict(id=app_id, name=app_id.title(), description="", requires=list(requires),
                native=True, version="1.0.0")


class QueueTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.home = self.paths.home
        self.items = [entry("radioapp", ["radio"]), entry("plain")]
        lookup = patch.object(catalog, "entries", return_value=self.items)
        lookup.start()
        self.addCleanup(lookup.stop)
        self.missing = {}
        need = patch.object(catalog, "missing_requirements",
                            side_effect=lambda item, home=None: self.missing.get(item["id"], []))
        need.start()
        self.addCleanup(need.stop)

    def test_apps_needing_a_requirement_are_found_by_requirement_not_by_id(self):
        self.assertEqual(autoinstall.needing("radio"), ["radioapp"])

    def test_queue_add_attempts_and_remove(self):
        self.assertEqual(autoinstall.load(self.home), {})
        self.assertEqual(autoinstall.add(self.home, ["radioapp", "radioapp", "../bad"]), ["radioapp"])
        self.assertEqual(autoinstall.note_attempt(self.home, "radioapp"), 1)
        self.assertEqual(autoinstall.load(self.home), {"radioapp": 1})
        autoinstall.remove(self.home, "radioapp")
        self.assertEqual(autoinstall.load(self.home), {})
        self.assertFalse(os.path.exists(autoinstall.queue_file(self.home)))

    def test_a_corrupt_queue_is_ignored(self):
        os.makedirs(os.path.dirname(autoinstall.queue_file(self.home)), exist_ok=True)
        with open(autoinstall.queue_file(self.home), "w") as fp:
            fp.write("{oops")
        with self.assertLogs("mfruitos.updater.autoinstall", "WARNING"):
            self.assertEqual(autoinstall.load(self.home), {})

    def test_next_app_waits_for_requirements_and_drops_installed_or_unknown(self):
        autoinstall.add(self.home, ["gone", "plain", "radioapp"])
        self.missing["radioapp"] = ["The radio is not set up"]
        with self.assertLogs("mfruitos.updater.autoinstall", "INFO"):
            self.assertEqual(autoinstall.next_app(self.home, {"plain"}), (None, ["gone", "plain"]))
        self.missing.clear()
        self.assertEqual(autoinstall.next_app(self.home, set())[0], "plain")
        for _ in range(autoinstall.MAX_ATTEMPTS):
            autoinstall.note_attempt(self.home, "plain")
        self.assertEqual(autoinstall.next_app(self.home, set())[0], "radioapp", "plain gave up")

    def test_command_line_queues_by_requirement(self):
        result = autoinstall.main(["add", "--requires", "radio", "--home", self.home])
        self.assertEqual(result, 0)
        self.assertEqual(autoinstall.load(self.home), {"radioapp": 0})
        self.assertEqual(autoinstall.main(["add", "nope", "--home", self.home]), 2)


class BundledCatalogueTests(TempHomeTestCase):
    def test_the_shipped_list_queues_radioconnect_for_the_radio(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-m", "mfruitos.updater.autoinstall", "add",
                              "--requires", "radio", "--home", self.paths.home],
                             env=env, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "RadioConnect")
        self.assertEqual(autoinstall.load(self.paths.home), {"radioconnect": 0})


class PendingInstallServiceTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        os_ = self.os = ScreenServices()
        os_.paths = self.paths
        os_.settings = Settings(None)
        os_.registry = AppRegistry(self.paths, os_.settings, "1.4.0")
        os_.tasks = TaskRunner(lambda fn, *a: fn(*a))      # not started: runs inline
        os_.updater = Mock()
        os_.updater.install_catalog.side_effect = lambda app_id, progress: SimpleNamespace(
            app_id=app_id, name=app_id.title(), version="1.0.0")
        os_.loop = Mock()
        os_.led = Mock()
        os_.backlight = Mock()
        os_.push = Mock()
        os_.toast = Mock()
        os_.flush_settings = Mock()
        os_.refresh_registry = Mock()
        os_.home_screen = Mock()
        os_.request_render = Mock()
        self.next = patch.object(autoinstall, "next_app",
                                 side_effect=lambda home, installed: (
                                     next(iter(autoinstall.load(home)), None), []))
        self.next.start()
        self.addCleanup(self.next.stop)

    def test_a_queued_app_installs_through_the_store_job_and_leaves_the_queue(self):
        autoinstall.add(self.paths.home, ["radioapp"])
        self.os.install_pending_apps()
        self.os.updater.refresh_catalog.assert_called_once()
        self.os.updater.install_catalog.assert_called_once()
        self.assertEqual(self.os.updater.install_catalog.call_args.args[0], "radioapp")
        self.assertEqual(autoinstall.load(self.paths.home), {})
        self.assertIn("radioapp", self.os.settings.get("apps.installed_ids"))
        self.os.toast.assert_not_called()

    def test_a_failed_install_counts_an_attempt_and_stays_queued(self):
        autoinstall.add(self.paths.home, ["radioapp"])
        self.os.updater.install_catalog.side_effect = RuntimeError("download failed")
        self.os.install_pending_apps()
        self.assertEqual(autoinstall.load(self.paths.home), {"radioapp": 1})

    def test_offline_waits_without_using_an_attempt(self):
        autoinstall.add(self.paths.home, ["radioapp"])
        self.os.updater.refresh_catalog.side_effect = OfflineError("cannot reach GitHub")
        self.os.install_pending_apps()
        self.os.updater.install_catalog.assert_not_called()
        self.assertEqual(autoinstall.load(self.paths.home), {"radioapp": 0})

    def test_nothing_queued_or_a_busy_job_lane_does_nothing(self):
        self.os.install_pending_apps()
        self.os.updater.refresh_catalog.assert_not_called()
        autoinstall.add(self.paths.home, ["radioapp"])
        self.os.tasks.active["jobs"] = "Install app"
        self.os.install_pending_apps()
        self.os.updater.install_catalog.assert_not_called()

    def test_installed_apps_are_reported_to_the_queue(self):
        autoinstall.add(self.paths.home, ["radioapp"])
        self.os.registry._entries["radioapp"] = AppEntry("radioapp", "Radioapp", "os")
        seen = []
        self.next.stop()
        with patch.object(autoinstall, "next_app",
                          side_effect=lambda home, installed: seen.append(set(installed))
                          or (None, ["radioapp"])):
            self.os.install_pending_apps()
        self.next.start()
        self.assertIn("radioapp", seen[0])
        self.assertEqual(autoinstall.load(self.paths.home), {})


class TaskLaneTests(TempHomeTestCase):
    def test_a_callback_sees_its_own_lane_free(self):
        runner = TaskRunner(lambda fn, *a: fn(*a))
        runner._queues["jobs"] = None      # force the worker path below
        seen = []
        runner._run("jobs", "check", lambda: 1, lambda _: seen.append(runner.busy("jobs")), None)
        runner._run("jobs", "fail", Mock(side_effect=RuntimeError("x")), None,
                    lambda _: seen.append(runner.busy("jobs")))
        self.assertEqual(seen, [False, False])


class BootUnitTests(TempHomeTestCase):
    def args(self, **changes):
        values = dict(band="au915", frequency=None, air_speed=2400, port="/dev/ttyS0",
                      code="/home/pi/.whisplay-os/system/current", home="/home/pi/.whisplay-os",
                      owner="pi")
        values.update(changes)
        return Namespace(**values)

    def test_unit_provisions_once_before_the_daemon_and_disables_itself(self):
        text = boot_unit(self.args())
        self.assertIn("Before=whisplay-daemon.service whisplay-os.service", text)
        self.assertIn("ConditionPathExists=/dev/ttyS0", text)
        self.assertIn("Environment=PYTHONPATH=/home/pi/.whisplay-os/system/current", text)
        self.assertIn("ExecStart=/usr/bin/python3 -m mfruitos.hosts.lora provision --band au915 "
                      "--frequency 920 --air-speed 2400 --port /dev/ttyS0 "
                      "--home /home/pi/.whisplay-os --owner pi", text)
        self.assertIn(f"ExecStartPost=/usr/bin/systemctl disable {BOOT_UNIT}", text)
        self.assertIn("WantedBy=multi-user.target", text)
        self.assertIn("--frequency 868", boot_unit(self.args(band="eu868", frequency=868)))

    def test_unsafe_paths_are_refused(self):
        for changes in ({"home": "/home/a b"}, {"owner": "pi;rm"}, {"code": "$HOME"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                boot_unit(self.args(**changes))
