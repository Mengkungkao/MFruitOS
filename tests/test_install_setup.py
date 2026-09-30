"""Installer privilege setup with command doubles; never changes host services."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from helpers import ROOT


SCRIPTS = Path(ROOT) / "scripts"
BASH = shutil.which("bash")
if BASH is None and os.name == "nt":
    candidate = Path("C:/Program Files/Git/bin/bash.exe")
    if candidate.is_file():
        BASH = str(candidate)


class WifiPolicyTests(unittest.TestCase):
    def policy(self, username):
        source = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
        generator = source.split("<<'PYRULE'\n", 1)[1].split("\nPYRULE", 1)[0]
        output = io.StringIO()
        with patch("sys.argv", ["-", username]), redirect_stdout(output):
            exec(compile(generator, "install.sh:PYRULE", "exec"), {})
        return output.getvalue()

    def test_only_target_user_and_required_actions_are_authorized(self):
        policy = self.policy("fixture")
        self.assertIn('subject.user === "fixture" && [', policy)
        self.assertEqual(re.findall(r'"org.freedesktop.NetworkManager.([^"]+)"', policy),
                         ["wifi.scan", "network-control", "settings.modify.system", "enable-disable-wifi"])
        self.assertIn("].indexOf(action.id) !== -1) return polkit.Result.YES;", policy)
        self.assertEqual(policy.count("polkit.Result.YES"), 1)

    def test_username_is_escaped_as_a_javascript_string(self):
        username = 'fixture" || true; //\\\n'
        policy = self.policy(username)
        self.assertIn("subject.user === " + json.dumps(username) + " && [", policy)
        self.assertNotIn(username, policy)


@unittest.skipUnless(BASH, "bash is required for installer shell tests")
class InstallerCommandTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mfruit-install-script-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "commands.log"
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        SUDO_USER="fixture", SCRIPT_TEST_HOME=self.tmp.as_posix(),
                        SCRIPT_TEST_BIN=self.bin.as_posix(),
                        SCRIPT_TEST_LOG=self.log.as_posix(),
                        WHISPLAY_OS_HOME=(self.tmp / "installed").as_posix())
        self.command("id", '''case "$1" in
  -un|-gn) echo fixture ;;
  -u) echo 1000 ;;
  *) exit 99 ;;
esac
''')
        self.command("getent", '''if [ "$1" = passwd ]; then
  printf 'fixture:x:1000:1000::%s:/bin/sh\\n' "$SCRIPT_TEST_HOME"
else
  exit 1
fi
''')
        self.command("uname", "echo Linux\n")
        self.command("systemctl", "exit 1\n")
        self.command("sudo", '''printf 'sudo %s\\n' "$*" >> "$SCRIPT_TEST_LOG"
exit "${SCRIPT_TEST_SUDO_EXIT:-0}"
''')
        self.command("rm", '''printf 'rm %s\\n' "$*" >> "$SCRIPT_TEST_LOG"
exit 0
''')

    def command(self, name, body):
        target = self.bin / name
        with target.open("w", encoding="utf-8", newline="\n") as fp:
            fp.write("#!/bin/sh\n" + body)
        target.chmod(0o755)

    def run_script(self, name, *args):
        # Git Bash prepends its own tools to PATH at startup; put doubles first
        # inside the shell so even rm/id cannot resolve to a host command.
        launch = 'export PATH="$(cd "$SCRIPT_TEST_BIN" && pwd):$PATH"; source "$@"'
        return subprocess.run([BASH, "-c", launch, "--", (SCRIPTS / name).as_posix(), *args], env=self.env,
                              text=True, capture_output=True, timeout=20)

    def missing_venv(self):
        self.command("python3", '''if [ "$1" = - ]; then cat >/dev/null; exit 0; fi
if [ "$1" = --version ]; then echo Python-fixture; exit 0; fi
case "$*" in
  *ensurepip*) exit 1 ;;
  *PIL*) echo pillow-fixture; exit 0 ;;
  *) echo "unexpected python call: $*" >&2; exit 99 ;;
esac
''')

    def test_files_only_install_checks_venv_before_changing_active_version(self):
        self.missing_venv()
        self.env["SCRIPT_TEST_SUDO_EXIT"] = "7"
        result = self.run_script("install.sh", "--no-service")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("python3-venv is required", result.stdout)
        self.assertIn("sudo apt-get install -y python3-venv", self.log.read_text())
        self.assertFalse((self.tmp / "installed").exists())

    def test_successful_package_command_does_not_hide_missing_venv(self):
        self.missing_venv()
        result = self.run_script("install.sh", "--no-service")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("venv support is still unavailable", result.stdout)
        self.assertFalse((self.tmp / "installed").exists())

    def test_uninstall_removes_the_persistent_wifi_permission(self):
        self.command("python3", "cat >/dev/null\nexit 0\n")
        result = self.run_script("uninstall.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        removal = next(line for line in self.log.read_text().splitlines()
                       if line.startswith("sudo rm -f /etc/sudoers.d/whisplay-os "))
        self.assertIn("/etc/polkit-1/rules.d/49-mfruit-wifi.rules", removal.split())


if __name__ == "__main__":
    unittest.main()
