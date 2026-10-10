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
        # Packages go through the helper that uses an offline pack when there is one.
        self.assertRegex(self.log.read_text(), r"sudo bash \S+/scripts/offline\.sh install python3-venv\n")
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

    def test_uninstall_removes_the_power_service_and_enables_pisugar_again(self):
        self.command("python3", "cat >/dev/null\nexit 0\n")
        self.command("systemctl", '''printf 'systemctl %s\\n' "$*" >> "$SCRIPT_TEST_LOG"
case "$1" in cat|list-unit-files) exit 0 ;; *) exit 0 ;; esac
''')
        state = self.tmp / "installed" / "state"
        state.mkdir(parents=True)
        (state / "pisugar-services-disabled").write_text(
            "pisugar-server.service\nsugar-wifi-config.service\nevil.service\n")
        result = self.run_script("uninstall.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.log.read_text()
        self.assertIn("sudo rm -f /usr/lib/systemd/system-shutdown/mfruit-power-off", log)
        self.assertIn("sudo rm -f /etc/modules-load.d/mfruit-power.conf", log)
        self.assertIn("sudo systemctl enable pisugar-server.service", log)
        self.assertIn("sudo systemctl start pisugar-server.service", log)
        self.assertIn("sudo systemctl enable sugar-wifi-config.service", log)
        self.assertNotIn("evil.service", log)


class PowerServiceInstallTests(unittest.TestCase):
    """The power unit and shutdown hook the installer writes (static checks
    of security-relevant properties, plus systemd-analyze when available)."""

    def setUp(self):
        self.source = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
        self.unit = self.source.split('cat > "$POWER_TMP" <<EOF\n', 1)[1].split("\nEOF\n", 1)[0]

    def test_unit_runs_as_the_user_with_only_the_clock_capability(self):
        self.assertIn("User=$TARGET_USER", self.unit)
        self.assertIn("SupplementaryGroups=$POWER_GROUPS", self.unit)
        self.assertIn("AmbientCapabilities=CAP_SYS_TIME", self.unit)
        # A capability bounding set or NoNewPrivileges would break the
        # "sudo -n systemctl poweroff" the safe shutdown relies on.
        self.assertNotIn("CapabilityBoundingSet", self.unit)
        self.assertNotIn("NoNewPrivileges", self.unit)
        self.assertIn("Before=$DAEMON_SERVICE $SERVICE", self.unit)
        self.assertIn("ExecStart=$PYTHON -m mfruitos.power serve", self.unit)
        self.assertIn('POWER_GROUPS="i2c"', self.source)

    def test_shutdown_hook_is_a_root_owned_copy(self):
        self.assertIn('sed "s|@POWER_CONFIG@|$OS_HOME/config/power.json|" "$SRC/scripts/mfruit-power-off"',
                      self.source)
        self.assertIn('sudo install -D -o root -g root -m 0755 "$HOOK_TMP" '
                      '"$POWER_HOOK_DIR/mfruit-power-off"', self.source)
        self.assertNotRegex(self.source, r"ln -s\S* [^\n]*system-shutdown")
        hook = (SCRIPTS / "mfruit-power-off").read_text(encoding="utf-8")
        self.assertIn('CONFIG = "@POWER_CONFIG@"', hook)
        self.assertTrue(hook.startswith("#!/usr/bin/python3 -I"))

    def test_sudoers_allows_only_restart_poweroff_and_reboot(self):
        line = next(l for l in self.source.splitlines()
                    if l.startswith("printf '%s ALL=(root) NOPASSWD:"))
        self.assertIn("%s poweroff, %s reboot", line)
        self.assertNotIn("ALL\\n", line.split("NOPASSWD:", 1)[1])

    def run_i2c_dev_block(self, modprobe_exit, etc_modules=""):
        """Run the installer's i2c-dev lines with sudo/modprobe doubles."""
        block = self.source.split("  # >>> i2c-dev\n", 1)[1].split("  # <<< i2c-dev\n", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            (tmp / "modules-load.d").mkdir()
            (tmp / "modules").write_text(etc_modules, encoding="utf-8")
            (tmp / "bin" / "modprobe").write_text(
                f"#!/bin/sh\necho \"modprobe $*\" >> {tmp}/log\nexit {modprobe_exit}\n")
            (tmp / "bin" / "sudo").write_text('#!/bin/sh\n"$@"\n')
            for name in ("modprobe", "sudo"):
                (tmp / "bin" / name).chmod(0o755)
            script = (f'PATH="{tmp}/bin:$PATH"\nok() {{ echo "ok $*"; }}\nwarn() {{ echo "warn $*"; }}\n'
                      f'I2C_DEV_CONF="{tmp}/modules-load.d/mfruit-power.conf"\n'
                      f'I2C_MODULE_LISTS="{tmp}/modules {tmp}/modules-load.d/*.conf"\n' + block)
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", script], capture_output=True,
                                    text=True, timeout=20)
            conf = tmp / "modules-load.d" / "mfruit-power.conf"
            return (result, conf.read_text(encoding="utf-8") if conf.exists() else None,
                    (tmp / "log").read_text(encoding="utf-8") if (tmp / "log").exists() else "")

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_i2c_dev_is_loaded_now_and_at_boot(self):
        # Without it there is no /dev/i2c-N even with the bus on (Pi Zero 2 W, 2026-10-10).
        result, conf, log = self.run_i2c_dev_block(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("modprobe i2c-dev", log)
        self.assertEqual(conf, "i2c-dev\n")
        self.assertIn("at every boot", result.stdout)

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_i2c_dev_already_listed_is_not_listed_twice(self):
        result, conf, _ = self.run_i2c_dev_block(0, etc_modules="# comment\ni2c-dev\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(conf)
        self.assertIn("already loaded at boot", result.stdout)

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_a_missing_i2c_dev_module_warns_and_does_not_stop_the_install(self):
        result, conf, _ = self.run_i2c_dev_block(1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(conf)
        self.assertIn("warn could not load the i2c-dev kernel module", result.stdout)

    def test_no_power_option_skips_it(self):
        self.assertIn("--no-power) INSTALL_POWER=0 ;;", self.source)
        self.assertIn('if [ "$INSTALL_POWER" = 1 ]; then', self.source)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not available")
    def test_rendered_unit_passes_systemd_analyze(self):
        import getpass
        import sys
        user = getpass.getuser()
        values = {"$DAEMON_SERVICE": "whisplay-daemon.service", "$SERVICE": "whisplay-os.service",
                  "$TARGET_USER": user, "$TARGET_GROUP": user, "$POWER_GROUPS": "",
                  "$TARGET_HOME": os.path.expanduser("~"), "$OS_HOME": "/tmp",
                  "$PYTHON": sys.executable}
        unit = self.unit
        for name in sorted(values, key=len, reverse=True):
            unit = unit.replace(name, values[name])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mfruit-power.service"
            path.write_text(unit, encoding="utf-8")
            result = subprocess.run(["systemd-analyze", "verify", str(path)], capture_output=True,
                                    text=True, timeout=60)
        problems = [l for l in (result.stdout + result.stderr).splitlines()
                    if "mfruit-power.service" in l and "Unknown" in l]
        self.assertEqual(problems, [], result.stdout + result.stderr)


class WifiSetupInstallTests(unittest.TestCase):
    def setUp(self):
        self.source = (SCRIPTS / "install.sh").read_text(encoding="utf-8")

    def test_the_tool_is_installed_as_the_user_never_with_sudo(self):
        line = next(l for l in self.source.splitlines() if "-m mfruitos.system.wifi_setup" in l)
        self.assertIn("as_user env", line)
        self.assertNotIn("sudo", line)
        self.assertIn('WS_ARGS=(--home "$OS_HOME" install)', self.source)
        self.assertIn('WS_ARGS+=(--offline "$OFFLINE_PACK")', self.source)

    def test_option_and_pisugar_service_hand_over(self):
        self.assertIn("--no-wifi-setup) WIFI_SETUP=0 ;;", self.source)
        block = self.source.split("for unit in sugar-wifi-config.service; do", 1)[1].split("done", 1)[0]
        self.assertIn('sudo systemctl disable --now "$unit"', block)
        self.assertIn("pisugar-services-disabled", block)

    def test_offline_packs_carry_the_tool(self):
        pack = (SCRIPTS / "make-offline-pack.sh").read_text(encoding="utf-8")
        self.assertIn("python3 -m mfruitos.system.wifi_setup url", pack)
        self.assertIn('offline_file_key "$url"', pack)


if __name__ == "__main__":
    unittest.main()
