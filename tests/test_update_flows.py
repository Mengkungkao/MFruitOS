"""Exercise release resolution, package switching and the Settings entry points."""
import hashlib
import os
import shutil
import tarfile
from unittest.mock import Mock

from helpers import ROOT, TempHomeTestCase, make_package
from mfruitos.apps.registry import AppRegistry, AppEntry
from mfruitos.launcher.runtime import Runtime
from mfruitos.launcher.ui.screens.apps import ApplicationsScreen
from mfruitos.launcher.ui.screens.updater import (InstallAppScreen, LocalPackagesScreen,
                                                 UpdaterScreen, VersionListScreen)
from mfruitos.system.settings import Settings
from mfruitos.updater.github import Release
from mfruitos.updater.installer import Installer, InstallError
from mfruitos.updater.service import UpdateService, UpdateInfo


class ReleaseFlowTests(TempHomeTestCase):
    def test_install_update_downgrade_reinstall_and_failure_preserve_data(self):
        github = Mock()
        archives = {}
        manifests = {}
        releases = []
        for version, test in [("1.0.0", "exit 0"), ("1.1.0", "exit 0"), ("2.0.0", "exit 1")]:
            src = make_package(os.path.join(self.tmp, version), version=version,
                               test_sh="#!/bin/sh\n" + test + "\n")
            with open(os.path.join(src, "manifest.json"), "rb") as fp:
                manifests["v" + version] = fp.read()
            archive = src + ".tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(src, arcname="package")
            url = "https://github.com/example/whisplay-weather/" + version
            archives[url] = archive
            releases.insert(0, Release(version, "v" + version, tarball_url=url))

        def download(url, destination, max_bytes, progress=None):
            shutil.copyfile(archives[url], destination)
            with open(destination, "rb") as fp:
                data = fp.read()
            return len(data), hashlib.sha256(data).hexdigest()

        github.download.side_effect = download
        github.raw_file.side_effect = lambda owner, repo, ref, path: manifests[ref]
        settings = Settings(None)
        installer = Installer(self.paths, "1.4.0", settings, github)
        service = UpdateService(self.paths, settings, github, installer, "1.4.0")
        registry = AppRegistry(self.paths, settings, "1.4.0")
        github.releases.return_value = [releases[-1]]
        result = service.install_from_repository("github.com/example/whisplay-weather")
        self.assertEqual(result.version, "1.0.0")
        data_path = os.path.join(self.paths.app_root("weather"), "data", "keep.txt")
        with open(data_path, "w") as fp:
            fp.write("user state")
        github.releases.return_value = releases
        for version in ("1.1.0", "1.0.0", "1.0.0"):
            registry.refresh(None)
            result = service.install_version(registry.get("weather"), version)
            self.assertEqual(result.version, version)
            registry.refresh(None)
            self.assertEqual(registry.get("weather").version, version)
            with open(data_path) as fp:
                self.assertEqual(fp.read(), "user state")
        with self.assertRaises(InstallError):
            service.install_version(registry.get("weather"), "2.0.0")
        registry.refresh(None)
        self.assertEqual(registry.get("weather").version, "1.0.0")
        self.assertFalse(registry.get("weather").broken)


class UpdateScreenTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.rt = Runtime(self.paths, ROOT, socket_path=self.tmp + "/none.sock")
        self.rt.router.set_root(self.rt.home_screen)

    def test_apps_exposes_install_and_offline_updater_keeps_management(self):
        screen = ApplicationsScreen(self.rt)
        screen.items()[0].action()
        self.assertIsInstance(self.rt.router.top, InstallAppScreen)
        self.rt.updater.online = False
        self.rt.registry.apps = Mock(return_value=[AppEntry("demo", "Demo", "os")])
        labels = [i.label for i in UpdaterScreen(self.rt).items()]
        for label in ("Internet unavailable", "MFruit OS", "Demo", "Install app"):
            self.assertIn(label, labels)

    def test_empty_versions_explains_missing_releases(self):
        screen = VersionListScreen(self.rt, "mfruit-os")
        screen.releases = []
        self.assertEqual(screen.items()[0].label, "No published versions")
        self.assertIn("Retry", [i.label for i in screen.items()])

    def test_local_package_is_only_installed_after_confirmation(self):
        directory = os.path.join(self.paths.home, "inbox")
        make_package(os.path.join(directory, "weather"))
        screen = LocalPackagesScreen(self.rt)
        self.rt.push(screen)
        for _ in range(4):
            self.rt.loop.run_once()
        self.rt.sideload = Mock()
        screen.items()[0].action()
        self.rt.sideload.assert_not_called()
        confirm = self.rt.router.top
        next(i for i in confirm.items() if i.label == "Install").action()
        self.rt.sideload.assert_called_once_with(os.path.join(directory, "weather"))

    def test_running_app_cannot_update_or_rollback(self):
        self.rt.registry.get = Mock(return_value=AppEntry("demo", "Demo", "os", running=True))
        self.rt.start_job = Mock()
        self.rt.install_app_version("demo", "1.0.0")
        self.rt.rollback_app("demo")
        self.rt.git_rollback("demo")
        self.rt.start_job.assert_not_called()

    def test_update_all_clears_successful_release_badge(self):
        entry = AppEntry("demo", "Demo", "os")
        self.rt.registry.apps = Mock(return_value=[entry])
        info = UpdateInfo("demo", "Demo", "release", latest="1.1.0", update_available=True)
        self.rt.updater.info = lambda app_id: info if app_id == "demo" else None
        self.rt.updater.install_version = Mock(return_value=Mock(app_id="demo", version="1.1.0"))
        self.rt.updater.mark_installed = Mock()
        self.rt.start_job = Mock()
        self.rt.update_all()
        work = self.rt.start_job.call_args.args[1]
        self.assertEqual(work(Mock()), ["Demo"])
        self.rt.updater.mark_installed.assert_called_once_with("demo", "1.1.0")

    def test_missing_releases_do_not_report_everything_up_to_date(self):
        info = UpdateInfo("mfruit-os", "MFruit OS", "system", error="No releases or version tags")
        self.rt.updater._infos = {info.app_id: info}
        self.rt.updater.check = Mock()
        self.rt.updater.online = True
        self.rt.toast = Mock()
        self.rt.check_updates()
        self.rt.loop.run_once()
        self.rt.toast.assert_called_once_with("Check update details", "")

    def test_sideload_completion_updates_cached_version(self):
        info = UpdateInfo("demo", "Demo", "release", installed="1.0.0", latest="1.1.0",
                          update_available=True)
        self.rt.updater._infos = {info.app_id: info}
        self.rt._after_new_install("demo", "1.1.0")
        self.assertFalse(self.rt.updater.info("demo").update_available)
        self.assertEqual(self.rt.updater.info("demo").installed, "1.1.0")
