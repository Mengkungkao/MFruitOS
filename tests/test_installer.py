import json
import os
import tarfile
import threading
import unittest
from unittest import mock

from helpers import TempHomeTestCase, make_package
from mfruitos.apps.registry import AppRegistry
from mfruitos.system.settings import Settings
from mfruitos.updater import rollback
from mfruitos.updater.installer import InstallError, Installer, InstallRequest


class FakeGitHub:
    """Serves local archives for https:// URLs."""

    def __init__(self):
        self.files = {}

    def download(self, url, dest, max_bytes, progress=None):
        import hashlib
        import shutil
        shutil.copy(self.files[url], dest)
        with open(dest, "rb") as fp:
            data = fp.read()
        return len(data), hashlib.sha256(data).hexdigest()


class InstallerTestBase(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.settings = Settings(None)
        self.registered = []
        self.github = FakeGitHub()
        self.installer = Installer(self.paths, "1.0.0", self.settings, self.github,
                                   register=self.registered.append)

    def package(self, version="1.0.0", **kw):
        return make_package(os.path.join(self.tmp, f"src-{version}-{len(os.listdir(self.tmp))}"),
                            app_id="weather", version=version, **kw)

    def tarball(self, version="1.0.0", **kw):
        src = self.package(version, **kw)
        path = os.path.join(self.tmp, f"weather-{version}-{len(os.listdir(self.tmp))}.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            tar.add(src, arcname=f"example-whisplay-weather-{version}")
        url = f"https://example.invalid/{os.path.basename(path)}"
        self.github.files[url] = path
        return url

    def install(self, version="1.0.0", mode="install", **kw):
        url = self.tarball(version, **kw)
        return self.installer.run(InstallRequest(
            repository="https://github.com/example/whisplay-weather", version=version,
            url=url, app_id="weather" if mode != "install" else "", mode=mode))

    def current_version(self):
        root = self.paths.app_root("weather")
        with open(os.path.join(rollback.current_target(root), "manifest.json")) as fp:
            return json.load(fp)["version"]


class InstallerTests(InstallerTestBase):
    def test_fresh_install_layout_and_registration(self):
        result = self.install("1.0.0")
        self.assertEqual(result.version, "1.0.0")
        root = self.paths.app_root("weather")
        self.assertTrue(os.path.islink(os.path.join(root, "current")))
        self.assertTrue(os.path.isdir(os.path.join(root, "data")))
        self.assertEqual(self.current_version(), "1.0.0")
        self.assertEqual([m.id for m in self.registered], ["weather"])
        with open(os.path.join(rollback.current_target(root), ".mfruit-entrypoint")) as fp:
            self.assertEqual(fp.read().strip(), "run.sh")
        self.assertIn("No checksum", result.warnings[0])
        # The registry sees it as a healthy OS-managed app.
        registry = AppRegistry(self.paths, self.settings, "1.0.0")
        registry.refresh(None)
        self.assertEqual(registry.get("weather").version, "1.0.0")
        self.assertEqual(registry.get("weather").broken, "")

    def test_update_then_downgrade_keeps_previous(self):
        self.install("1.0.0")
        data_file = os.path.join(self.paths.app_root("weather"), "data", "state.txt")
        with open(data_file, "w") as fp:
            fp.write("user data")
        result = self.install("1.1.0", mode="update")
        self.assertEqual(result.previous_version, "1.0.0")
        self.assertEqual(self.current_version(), "1.1.0")
        with open(data_file) as fp:
            self.assertEqual(fp.read(), "user data")
        self.install("1.0.0", mode="downgrade")
        self.assertEqual(self.current_version(), "1.0.0")

    def test_failed_install_script_rolls_back(self):
        self.install("1.0.0")
        data_file = os.path.join(self.paths.app_root("weather"), "data", "state.txt")
        with open(data_file, "w") as fp:
            fp.write("before")
        breaking = "#!/bin/sh\necho corrupt > \"$WHISPLAY_OS_APP_DATA/state.txt\"\nexit 3\n"
        with self.assertRaises(InstallError) as ctx:
            self.install("2.0.0", mode="update", install_sh=breaking)
        self.assertEqual(ctx.exception.step, "install")
        self.assertTrue(ctx.exception.rolled_back)
        self.assertEqual(self.current_version(), "1.0.0")
        with open(data_file) as fp:
            self.assertEqual(fp.read(), "before")  # data snapshot restored
        versions = os.listdir(os.path.join(self.paths.app_root("weather"), "versions"))
        self.assertEqual(len(versions), 1)

    def test_failed_test_script_rolls_back(self):
        self.install("1.0.0")
        with self.assertRaises(InstallError) as ctx:
            self.install("1.2.0", mode="update", test_sh="#!/bin/sh\nexit 1\n")
        self.assertEqual(ctx.exception.step, "test")
        self.assertEqual(self.current_version(), "1.0.0")

    def test_failed_activation_rolls_back_symlink(self):
        self.install("1.0.0")

        def boom(manifest):
            raise OSError("daemon exploded")
        record = self.installer.read_record(self.paths.app_root("weather"))
        self.installer.register = boom
        with self.assertRaises(InstallError) as ctx:
            self.install("1.3.0", mode="update")
        self.assertEqual(self.installer.read_record(self.paths.app_root("weather")), record)
        self.assertEqual(ctx.exception.step, "activate")
        self.assertTrue(ctx.exception.rolled_back)
        self.assertEqual(self.current_version(), "1.0.0")

    def test_failed_manual_rollback_restores_version_and_record(self):
        self.install("1.0.0")
        self.install("1.1.0")
        record = self.installer.read_record(self.paths.app_root("weather"))
        from unittest.mock import Mock
        self.installer.register = Mock(side_effect=OSError("registration failed"))
        with self.assertRaises(OSError):
            self.installer.rollback_to_previous("weather")
        self.assertEqual(self.current_version(), "1.1.0")
        self.assertEqual(self.installer.read_record(self.paths.app_root("weather")), record)

    def test_failed_fresh_install_leaves_nothing(self):
        with self.assertRaises(InstallError):
            self.install("1.0.0", install_sh="#!/bin/sh\nexit 1\n")
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))

    def test_version_mismatch_rejected(self):
        url = self.tarball("1.0.0")
        with self.assertRaises(InstallError) as ctx:
            self.installer.run(InstallRequest(repository="https://github.com/example/whisplay-weather",
                                              version="9.9.9", url=url))
        self.assertEqual(ctx.exception.step, "verify")

    def test_repository_mismatch_rejected(self):
        url = self.tarball("1.0.0")
        with self.assertRaises(InstallError) as ctx:
            self.installer.run(InstallRequest(repository="https://github.com/attacker/other",
                                              version="1.0.0", url=url))
        self.assertIn("repository", ctx.exception.message)

    def test_wrong_app_id_rejected(self):
        url = self.tarball("1.0.0")
        with self.assertRaises(InstallError):
            self.installer.run(InstallRequest(repository="", version="1.0.0", url=url,
                                              app_id="bitcoin", mode="update"))

    def test_checksum_mismatch_rejected_and_match_marks_verified(self):
        url = self.tarball("1.0.0")
        with self.assertRaises(InstallError) as ctx:
            self.installer.run(InstallRequest(repository="", version="1.0.0", url=url,
                                              expected_sha256="0" * 64))
        self.assertIn("checksum", ctx.exception.message)
        from mfruitos.updater.verifier import sha256_file
        good = sha256_file(self.github.files[url])
        result = self.installer.run(InstallRequest(repository="", version="1.0.0", url=url,
                                                   expected_sha256=good))
        self.assertTrue(result.verified)

    def test_require_checksum_setting(self):
        self.settings.set("updater.require_checksum", True)
        with self.assertRaises(InstallError) as ctx:
            self.install("1.0.0")
        self.assertEqual(ctx.exception.step, "verify")

    def test_min_os_version_enforced(self):
        with self.assertRaises(InstallError):
            self.install("1.0.0", extra_manifest={"min_os_version": "5.0.0"})

    def test_user_rollback_and_prune(self):
        self.install("1.0.0")
        self.install("1.1.0", mode="update")
        self.install("1.2.0", mode="update")
        versions = os.listdir(os.path.join(self.paths.app_root("weather"), "versions"))
        self.assertEqual(len(versions), 2)  # keep_versions = 2
        self.assertEqual(self.installer.rollback_to_previous("weather"), "1.1.0")
        self.assertEqual(self.current_version(), "1.1.0")

    def test_persist_paths_carried_over(self):
        self.install("1.0.0", extra_manifest={"persist": [".venv"]})
        current = rollback.current_target(self.paths.app_root("weather"))
        os.makedirs(os.path.join(current, ".venv", "bin"))
        with open(os.path.join(current, ".venv", "bin", "python"), "w") as fp:
            fp.write("venv")
        self.install("1.1.0", mode="update", extra_manifest={"persist": [".venv", "../bad"]})
        new = rollback.current_target(self.paths.app_root("weather"))
        self.assertTrue(os.path.isfile(os.path.join(new, ".venv", "bin", "python")))

    def test_persisted_config_replaces_packaged_default(self):
        self.install("1.0.0", extra_manifest={"persist": ["config.yaml"]})
        current = rollback.current_target(self.paths.app_root("weather"))
        with open(os.path.join(current, "config.yaml"), "w") as fp:
            fp.write("radio: user-setting\n")
        src = self.package("1.1.0", extra_manifest={"persist": ["config.yaml"]})
        with open(os.path.join(src, "config.yaml"), "w") as fp:
            fp.write("radio: default\n")
        self.installer.run(InstallRequest(repository="", local_path=src, app_id="weather",
                                          mode="update"))
        new = rollback.current_target(self.paths.app_root("weather"))
        with open(os.path.join(new, "config.yaml")) as fp:
            self.assertEqual(fp.read(), "radio: user-setting\n")

    def test_sideload_directory_is_copied_not_moved(self):
        src = self.package("1.0.0")
        self.installer.run(InstallRequest(repository="", local_path=src))
        self.assertTrue(os.path.isfile(os.path.join(src, "manifest.json")))
        self.assertEqual(self.current_version(), "1.0.0")

    # A sideloaded folder gets the same checks as an archive (KI-1).
    def sideload_dir(self, prepare):
        src = self.package("1.0.0")
        prepare(src)
        return src

    def assert_sideload_refused(self, src, message):
        result = {}

        def run():
            try:
                self.installer.run(InstallRequest(repository="", local_path=src))
            except InstallError as exc:
                result["error"] = exc
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(10)
        self.assertFalse(worker.is_alive(), "sideload blocked instead of refusing the package")
        self.assertIn("error", result, "unsafe package folder was installed")
        self.assertEqual(result["error"].step, "verify")
        self.assertIn(message, result["error"].message)
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))

    def test_sideload_directory_with_escaping_symlink_is_refused(self):
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w") as fp:
            fp.write("private\n")
        self.assert_sideload_refused(
            self.sideload_dir(lambda d: os.symlink(outside, os.path.join(d, "data.txt"))),
            "absolute symlink")
        self.assert_sideload_refused(
            self.sideload_dir(lambda d: os.symlink("../../outside.txt", os.path.join(d, "assets", "x"))),
            "symlink escapes the package")

    def test_sideload_directory_with_fifo_is_refused(self):
        self.assert_sideload_refused(self.sideload_dir(lambda d: os.mkfifo(os.path.join(d, "pipe"))),
                                     "special file")

    def test_sideload_directory_limits_apply(self):
        from mfruitos.updater import verifier
        with mock.patch.object(verifier, "MAX_FILES", 3):
            self.assert_sideload_refused(self.package("1.0.0"), "too many files")

    def test_sideload_directory_keeps_internal_links_and_strips_unsafe_modes(self):
        def prepare(d):
            os.symlink("run.sh", os.path.join(d, "start.sh"))
            os.chmod(os.path.join(d, "run.sh"), 0o4777)
        self.installer.run(InstallRequest(repository="", local_path=self.sideload_dir(prepare)))
        current = rollback.current_target(self.paths.app_root("weather"))
        self.assertEqual(os.readlink(os.path.join(current, "start.sh")), "run.sh")
        self.assertEqual(os.stat(os.path.join(current, "run.sh")).st_mode & 0o7777, 0o755)

    def test_uninstall_removes_only_app(self):
        self.install("1.0.0")
        with open(self.paths.app_log("weather"), "w") as fp:
            fp.write("log")
        self.installer.uninstall("weather")
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))
        self.assertFalse(os.path.exists(self.paths.app_log("weather")))
        self.assertTrue(os.path.isdir(self.paths.apps_dir))
        with self.assertRaises(InstallError):
            self.installer.uninstall("../../etc")
        with self.assertRaises(InstallError):
            self.installer.uninstall("mfruit-os")


class UninstallDeleteResetTests(InstallerTestBase):
    """Fruit Store: uninstall keeps data, delete removes it, reset empties it."""

    def write_data(self, name="notes.txt", text="mine"):
        path = os.path.join(self.paths.app_root("weather"), "data", name)
        with open(path, "w") as fp:
            fp.write(text)
        return path

    def registry(self):
        registry = AppRegistry(self.paths, self.settings, "1.0.0")
        registry.refresh([])
        return registry

    def test_uninstall_keeps_data_and_lists_it_as_a_leftover(self):
        self.install("1.0.0")
        self.write_data()
        with open(self.paths.app_log("weather"), "w") as fp:
            fp.write("log")
        self.assertTrue(self.installer.uninstall("weather"))
        root = self.paths.app_root("weather")
        self.assertEqual(sorted(os.listdir(root)), ["data", "uninstalled.json"])
        registry = self.registry()
        self.assertIsNone(registry.get("weather"), "no longer an app")
        self.assertEqual([(i.id, i.kind, i.version) for i in registry.leftovers()],
                         [("weather", "os", "1.0.0")])

    def test_reinstall_finds_the_kept_data(self):
        self.install("1.0.0")
        data = self.write_data()
        self.installer.uninstall("weather")
        self.install("1.0.0")
        with open(data) as fp:
            self.assertEqual(fp.read(), "mine")
        root = self.paths.app_root("weather")
        self.assertFalse(os.path.exists(os.path.join(root, "uninstalled.json")))
        self.assertIsNotNone(self.registry().get("weather"))
        self.assertEqual(self.registry().leftovers(), [])

    def test_failed_reinstall_never_deletes_kept_data(self):
        self.install("1.0.0")
        data = self.write_data()
        self.installer.uninstall("weather")
        with self.assertRaises(InstallError):
            self.install("1.0.0", test_sh="#!/bin/sh\necho changed > \"$WHISPLAY_OS_APP_DATA/notes.txt\"\nexit 1\n")
        with open(data) as fp:
            self.assertEqual(fp.read(), "mine", "kept data restored after the failed install")
        self.assertEqual([i.id for i in self.registry().leftovers()], ["weather"])

    def test_an_app_without_data_is_removed_completely(self):
        self.install("1.0.0")
        self.assertFalse(self.installer.uninstall("weather"))
        self.assertFalse(os.path.exists(self.paths.app_root("weather")))

    def test_delete_is_refused_while_installed_then_removes_everything(self):
        self.install("1.0.0")
        self.write_data()
        with self.assertRaises(InstallError):
            self.installer.delete_data("weather")
        self.installer.uninstall("weather")
        adopted = os.path.join(self.paths.home, "adopted", "weather")
        os.makedirs(adopted)
        with open(self.paths.app_log("weather"), "w") as fp:
            fp.write("log")
        removed = self.installer.delete_data("weather")
        self.assertIn(self.paths.app_root("weather"), removed)
        for path in (self.paths.app_root("weather"), adopted, self.paths.app_log("weather")):
            self.assertFalse(os.path.exists(path), path)
        self.assertEqual(self.registry().leftovers(), [])
        with self.assertRaises(InstallError):
            self.installer.delete_data("../../etc")

    def test_reset_empties_the_data_and_keeps_the_app(self):
        self.install("1.0.0")
        self.write_data()
        os.makedirs(os.path.join(self.paths.app_root("weather"), "data", "cache"))
        self.assertEqual(self.installer.reset_data("weather"), 2)
        root = self.paths.app_root("weather")
        self.assertEqual(os.listdir(os.path.join(root, "data")), [])
        self.assertEqual(self.current_version(), "1.0.0")
        with self.assertRaises(InstallError):
            self.installer.reset_data("mfruit-os")


class SafeDeleteTests(TempHomeTestCase):
    def test_refuses_outside_and_protected(self):
        with self.assertRaises(rollback.UnsafePathError):
            rollback.safe_rmtree(self.tmp, self.paths.apps_dir)
        with self.assertRaises(rollback.UnsafePathError):
            rollback.safe_rmtree("/etc", "/")
        with self.assertRaises(rollback.UnsafePathError):
            rollback.safe_rmtree(self.paths.apps_dir, self.paths.apps_dir)
        with self.assertRaises(rollback.UnsafePathError):
            rollback.safe_rmtree(os.path.join(self.paths.apps_dir, "..", ".."), self.paths.apps_dir)

    def test_symlink_is_unlinked_not_followed(self):
        outside = os.path.join(self.tmp, "precious")
        os.makedirs(outside)
        with open(os.path.join(outside, "keep"), "w") as fp:
            fp.write("x")
        link = os.path.join(self.paths.apps_dir, "evil")
        os.symlink(outside, link)
        rollback.safe_rmtree(link, self.paths.apps_dir)
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.isfile(os.path.join(outside, "keep")))



class UpdateServiceTests(TempHomeTestCase):
    def test_offline_check_retries_soon(self):
        import time
        from mfruitos.updater.service import OFFLINE_RETRY_SEC, UpdateService
        service = UpdateService(self.paths, Settings(None), None, None, "1.0.0")
        service.last_check = time.time() - OFFLINE_RETRY_SEC - 1
        service.online = True
        self.assertFalse(service.check_due())      # online: wait the full interval
        service.online = False
        self.assertTrue(service.check_due())       # offline: retry after 10 minutes



class SystemUpdateTests(TempHomeTestCase):
    """MFruit OS updating itself: self-test gate, activation, rollback."""

    def os_package(self, version, break_code=False):
        import shutil
        from helpers import ROOT
        pkg = os.path.join(self.tmp, f"os-{version}")
        for item in ("mfruitos", "assets", "config", "scripts", "manifest.json"):
            src = os.path.join(ROOT, item)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(pkg, item),
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, os.path.join(pkg, item))
        manifest_path = os.path.join(pkg, "manifest.json")
        with open(manifest_path) as fp:
            manifest = json.load(fp)
        manifest["version"] = version
        with open(manifest_path, "w") as fp:
            json.dump(manifest, fp)
        if break_code:
            with open(os.path.join(pkg, "mfruitos", "launcher", "runtime.py"), "a") as fp:
                fp.write("\nthis is not python\n")
        return pkg

    def setUp(self):
        super().setUp()
        self.installer = Installer(self.paths, "1.0.0", Settings(None), None)
        # an existing, working system version
        old = os.path.join(self.paths.system_dir, "versions", "1.0.0-local")
        os.makedirs(old)
        with open(os.path.join(old, "manifest.json"), "w") as fp:
            json.dump({"id": "mfruit-os", "type": "system", "name": "MFruit OS",
                       "version": "1.0.0", "entrypoint": "manifest.json"}, fp)
        os.symlink("versions/1.0.0-local", os.path.join(self.paths.system_dir, "current"))
        self.old = old

    def test_good_system_update_activates_and_arms_boot_guard(self):
        result = self.installer.run(InstallRequest(repository="", local_path=self.os_package("1.1.0"),
                                                   mode="system"))
        self.assertTrue(result.restart_required)
        current = rollback.current_target(self.paths.system_dir)
        self.assertIn("1.1.0-", current)
        with open(os.path.join(self.paths.state_dir, "pending_system_update.env")) as fp:
            self.assertIn(f"PREVIOUS_DIR={self.old}", fp.read())

    def test_system_rollback_arms_guard_for_the_version_being_left(self):
        self.installer.run(InstallRequest(repository="", local_path=self.os_package("1.1.0"),
                                         mode="system"))
        before = rollback.current_target(self.paths.system_dir)
        self.assertEqual(self.installer.rollback_to_previous("mfruit-os", system=True), "1.0.0")
        with open(os.path.join(self.paths.state_dir, "pending_system_update.env")) as fp:
            self.assertIn(f"PREVIOUS_DIR={before}", fp.read())
        with open(os.path.join(self.paths.state_dir, "pending_system_update.json")) as fp:
            pending = json.load(fp)
        self.assertEqual(pending["previous_dir"], before)
        self.assertEqual(pending["new_dir"], self.old)

    def test_broken_system_update_fails_self_test_and_keeps_current(self):
        with self.assertRaises(InstallError) as ctx:
            self.installer.run(InstallRequest(repository="", local_path=self.os_package("1.2.0", True),
                                              mode="system"))
        self.assertEqual(ctx.exception.step, "test")
        self.assertEqual(os.path.realpath(rollback.current_target(self.paths.system_dir)),
                         os.path.realpath(self.old))
        self.assertFalse(os.path.exists(os.path.join(self.paths.state_dir,
                                                     "pending_system_update.env")))

    def test_app_package_rejected_as_system_update(self):
        with self.assertRaises(InstallError):
            self.installer.run(InstallRequest(repository="", mode="system",
                                              local_path=make_package(os.path.join(self.tmp, "app"))))


if __name__ == "__main__":
    unittest.main()


class InUseTests(InstallerTestBase):
    """Installing over an app that is open is refused (found with RadioConnect)."""

    def test_an_open_app_is_not_installed_over_and_a_closed_one_is(self):
        self.install("1.0.0")
        self.installer.in_use = lambda app_id: app_id == "weather"
        with self.assertRaises(InstallError) as ctx:
            self.install("1.1.0", mode="update")
        self.assertEqual(ctx.exception.step, "check")
        self.assertIn("is open", ctx.exception.message)
        self.assertEqual(self.current_version(), "1.0.0")
        self.installer.in_use = lambda app_id: False
        self.install("1.1.0", mode="update")
        self.assertEqual(self.current_version(), "1.1.0")

    def test_a_fresh_install_does_not_ask(self):
        asked = []
        self.installer.in_use = lambda app_id: asked.append(app_id) or True
        self.install("1.0.0")
        self.assertEqual(asked, [])
