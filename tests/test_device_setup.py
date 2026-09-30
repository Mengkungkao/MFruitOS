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
        env = dict(self.env, WHISPLAY_OS_HOME=str(os_home))
        result = subprocess.run(["bash", str(Path(ROOT) / "scripts/install.sh"), "--no-service"],
                                env=env, text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        current = os_home / "system/current"
        for relative in ("docs/APP_RULES.md", "docs/DEVICE_SETUP.md"):
            self.assertEqual((current / relative).read_bytes(), (Path(ROOT) / relative).read_bytes())
        self.assertTrue((os_home / "bin/mfruitctl").is_file())


if __name__ == "__main__":
    unittest.main()
