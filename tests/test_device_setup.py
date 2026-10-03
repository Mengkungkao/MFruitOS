"""Device setup defaults to inspection and delegates explicit installation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from helpers import ROOT


class DeviceSetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mfruit-device-setup-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.source = self.tmp / "source"
        self.source.mkdir()
        shutil.copytree(Path(ROOT) / "mfruitos", self.source / "mfruitos",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(Path(ROOT) / "manifest.json", self.source / "manifest.json")
        (self.source / "scripts").mkdir()
        shutil.copyfile(Path(ROOT) / "scripts/setup-device.sh",
                        self.source / "scripts/setup-device.sh")
        (self.source / "scripts/install.sh").write_text(
            '#!/bin/bash\nprintf "%s\\n" "$@" > "$SETUP_TEST_ARGS"\n'
            'exit "${SETUP_TEST_INSTALL_EXIT:-0}"\n')
        (self.source / "mfruitos/daemon/client.py").write_text(
            'import os\nclass DaemonError(Exception): pass\n'
            'class WhisplayDaemonClient:\n'
            '    def ping(self):\n'
            '        if os.environ.get("SETUP_TEST_PING_FAIL"):\n'
            '            raise DaemonError("test socket unavailable")\n'
            '        return {}\n')
        self.driver = self.tmp / "driver"
        (self.driver / "daemon").mkdir(parents=True)
        (self.driver / "daemon/whisplay_daemon.py").write_text("# fixture\n")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.command("id", '''case "$1" in
  -u) echo 1000 ;;
  -un) echo fixture ;;
  -gn) echo fixture ;;
  *) exit 1 ;;
esac
''')
        self.command("getent", '''if [ "$1" = passwd ]; then
  printf 'fixture:x:1000:1000::%s:/bin/bash\\n' "$SETUP_TEST_HOME"
else
  exit 1
fi
''')
        self.command("systemctl", '''case "$1 $2" in
  "cat whisplay-daemon.service") echo '[Service]' ;;
  "show --property=User") echo "${SETUP_TEST_DAEMON_USER:-fixture}" ;;
  "show --property=WorkingDirectory") echo "$SETUP_TEST_DRIVER" ;;
  "show -p") printf 'WorkingDirectory=%s\\n' "$SETUP_TEST_DRIVER" ;;
  "is-active --quiet") test -z "${SETUP_TEST_INACTIVE:-}" ;;
  "is-active whisplay-daemon.service") echo active ;;
  *) echo "unexpected systemctl mutation: $*" >&2; exit 99 ;;
esac
''')
        self.command("sudo", 'echo "unexpected sudo call" >&2\nexit 99\n')
        self.args_file = self.tmp / "installer-args"
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        PYTHONDONTWRITEBYTECODE="1", SUDO_USER="fixture",
                        SETUP_TEST_HOME=str(self.tmp), SETUP_TEST_DRIVER=str(self.driver),
                        SETUP_TEST_ARGS=str(self.args_file))

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def run_setup(self, *args):
        return subprocess.run(["bash", str(self.source / "scripts/setup-device.sh"), *args],
                              env=self.env, text=True, capture_output=True, timeout=20)

    def test_default_and_check_leave_checkout_unchanged_and_never_install(self):
        before = {str(path.relative_to(self.source)) for path in self.source.rglob("*")}
        for args in ((), ("--check",)):
            result = self.run_setup(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Preflight passed", result.stdout)
            self.assertFalse(self.args_file.exists())
        after = {str(path.relative_to(self.source)) for path in self.source.rglob("*")}
        self.assertEqual(before, after)

    def test_install_forwards_options_and_preserves_installer_exit_status(self):
        self.env["SETUP_TEST_INSTALL_EXIT"] = "23"
        result = self.run_setup("--install", "--dev", "--no-background-daemon", "--yes")
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.args_file.read_text().splitlines(),
                         ["--dev", "--no-background-daemon", "--yes"])

    def test_failed_daemon_ping_blocks_install(self):
        self.env["SETUP_TEST_PING_FAIL"] = "1"
        result = self.run_setup("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("health.ping failed", result.stderr)
        self.assertFalse(self.args_file.exists())

    def test_missing_pillow_blocks_install(self):
        shadow = self.tmp / "missing-pillow"
        shadow.mkdir()
        (shadow / "PIL.py").write_text('raise ImportError("fixture: Pillow not installed")\n')
        self.env["PYTHONPATH"] = str(shadow)
        result = self.run_setup("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Pillow is missing", result.stderr)
        self.assertFalse(self.args_file.exists())

    def test_wrong_daemon_user_blocks_install(self):
        self.env["SETUP_TEST_DAEMON_USER"] = "another-user"
        result = self.run_setup("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log in as its configured non-root user", result.stderr)
        self.assertFalse(self.args_file.exists())

    def test_source_manifest_version_mismatch_blocks_install(self):
        path = self.source / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = "99.0.0"
        path.write_text(json.dumps(manifest))
        result = self.run_setup("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source version and system manifest disagree", result.stderr)
        self.assertFalse(self.args_file.exists())

    def test_install_flags_require_explicit_install_mode(self):
        for args in (("--dev",), ("--check", "--yes"), ("--check", "--install")):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_setup(*args).returncode, 0)
                self.assertFalse(self.args_file.exists())

    def test_files_only_installer_preserves_app_rules_and_device_guide(self):
        os_home = self.tmp / "installed"
        from helpers import make_package
        previous = os_home / "system/versions/1.0.0-local-old"
        make_package(str(previous), app_id="mfruit-os", version="1.0.0",
                     extra_manifest={"type": "system"})
        (os_home / "system/current").symlink_to(previous)
        env = dict(self.env, WHISPLAY_OS_HOME=str(os_home))
        result = subprocess.run(["bash", str(Path(ROOT) / "scripts/install.sh"), "--no-service"],
                                env=env, text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        current = os_home / "system/current"
        for relative in ("docs/apps/APP_CONTRACT.md", "docs/platform/INSTALLATION.md"):
            self.assertEqual((current / relative).read_bytes(), (Path(ROOT) / relative).read_bytes())
        self.assertTrue((os_home / "bin/mfruitctl").is_file())
        record = json.loads((os_home / "system/app.json").read_text())
        self.assertEqual(record["previous_dir"], str(previous))
        self.assertEqual(record["previous_version"], "1.0.0")
        self.assertEqual(record["installed_dir"], str(current.resolve()))

    def test_files_only_first_install_and_rerun_preserve_provisioned_apps(self):
        from mfruitos.paths import Paths
        from mfruitos.system.settings import Settings

        os_home = self.tmp / "installed"
        paths = Paths(str(os_home), str(self.tmp / ".whisplay-daemon"))
        starter = "whisplay-jump"
        templates = self.driver / "daemon/default_apps"
        templates.mkdir()
        example = self.driver / "example"
        example.mkdir()
        (example / "game.py").write_text(
            'raise AssertionError("installer must not launch starter apps")\n', encoding="utf-8")
        (templates / (starter + ".json")).write_text(json.dumps({
            "app_id": starter, "display_name": "Jump",
            "cwd": "__EXAMPLE_DIR__",
            "launch_command": 'python3 "__EXAMPLE_DIR__/game.py"',
        }), encoding="utf-8")
        env = dict(self.env, WHISPLAY_OS_HOME=str(os_home))

        def install(stamp):
            # Distinct release directories without waiting for the wall clock.
            self.command("date", "printf '%s\\n' '" + stamp + "'\n")
            result = subprocess.run(
                ["bash", str(Path(ROOT) / "scripts/install.sh"), "--no-service"],
                cwd=self.tmp, env=env, text=True, capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result

        first = install("20261001010000")
        self.assertIn("Initial Apps menu configured; available starter games: 1", first.stdout)
        settings_file = Path(paths.settings_file)
        settings = Settings(str(settings_file))
        settings.load()
        self.assertEqual(settings.load_errors, [])
        self.assertTrue(settings.get("apps.clean_menu"))
        self.assertEqual(settings.get("apps.installed_ids"), [starter, "connectwifi"])
        self.assertEqual(settings.get("apps.order"), [starter])
        self.assertEqual(settings.get("apps.default_app"), "")
        for app_id in (starter, "connectwifi"):
            self.assertTrue(settings.app_flags(app_id)["enabled"])
            self.assertFalse(settings.app_flags(app_id)["autostart"])
        self.assertTrue(settings.app_flags("connectwifi")["hidden"])
        daemon_apps = Path(paths.daemon_apps_dir)
        registration = daemon_apps / (starter + ".json")
        raw = json.loads(registration.read_text(encoding="utf-8"))
        self.assertEqual(raw["cwd"], str(self.driver / "example"))
        self.assertEqual(raw["launch_command"],
                         'python3 "' + str(self.driver / "example/game.py") + '"')
        self.assertFalse((daemon_apps / "whisplay-flappy-bird.json").exists())

        wifi_root = Path(paths.app_root("connectwifi"))
        wifi_current = wifi_root / "current"
        self.assertTrue(wifi_current.is_symlink())
        wifi_directory = wifi_current.resolve()
        for source, installed in ((Path(ROOT) / "bundled/connectwifi", wifi_current),
                                  (Path(ROOT) / "mfruitos/sdk", wifi_current / "mfruit_sdk")):
            for path in source.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    self.assertEqual((installed / path.relative_to(source)).read_bytes(),
                                     path.read_bytes())
        marker = os_home / "state/provisioned.json"
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), {"schema": 1})
        marker_before = (marker.read_bytes(), marker.stat().st_mtime_ns)
        policy = os_home / "state/launch-policy"
        self.assertEqual(policy.read_text(encoding="utf-8"), "gate\n")
        backups = list((os_home / "backups").glob("first-install-*/settings.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), (Path(ROOT) / "config/default.json").read_bytes())

        settings.set("display.brightness", 47)
        settings.set("apps.installed_ids", ["weather", starter, "connectwifi"])
        settings.set("apps.order", ["weather", starter])
        settings.set("apps.default_app", "weather")
        settings.set("system.show_system_pages_on_home", True)
        settings.set_app_flag("weather", "autostart", True)
        settings.set_app_flag("connectwifi", "enabled", False)
        settings.set_app_flag("connectwifi", "hidden", False)
        self.assertTrue(settings.save())
        settings_before = settings_file.read_bytes()
        wifi_data = wifi_root / "data/networks.json"
        wifi_data.write_text('{"fixture": "keep user data"}\n', encoding="utf-8")
        wifi_local = wifi_current / "local-preferences.json"
        wifi_local.write_text('{"fixture": "keep installed directory"}\n', encoding="utf-8")
        wifi_record_before = (wifi_root / "app.json").read_bytes()
        raw["launch_command"] = "custom-game-command"
        registration.write_text(json.dumps(raw), encoding="utf-8")
        registration_before = registration.read_bytes()
        policy.write_text("open\n", encoding="utf-8")

        second = install("20261001010001")
        self.assertNotIn("Initial Apps menu configured", second.stdout)
        self.assertEqual(settings_file.read_bytes(), settings_before)
        self.assertEqual(wifi_current.resolve(), wifi_directory)
        self.assertEqual(list((wifi_root / "versions").iterdir()), [wifi_directory])
        self.assertEqual((wifi_root / "app.json").read_bytes(), wifi_record_before)
        self.assertEqual(wifi_data.read_text(encoding="utf-8"), '{"fixture": "keep user data"}\n')
        self.assertEqual(wifi_local.read_text(encoding="utf-8"),
                         '{"fixture": "keep installed directory"}\n')
        self.assertEqual(registration.read_bytes(), registration_before)
        self.assertEqual((marker.read_bytes(), marker.stat().st_mtime_ns), marker_before)
        self.assertEqual(policy.read_text(encoding="utf-8"), "open\n")
        self.assertEqual(list((os_home / "backups").glob("first-install-*/settings.json")), backups)


if __name__ == "__main__":
    unittest.main()
