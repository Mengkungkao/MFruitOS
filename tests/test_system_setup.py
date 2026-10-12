"""The system setup follows System updates
(docs/platform/ADR/0015-system-setup-from-releases.md).

scripts/install.sh owns what mFruit OS installs as root (the system setup).
--check-system compares it with the device, --system-only applies only it,
and scripts/mfruit-system-apply (root, mfruit-system-apply.service) runs
that from the official release of the version the user runs. Found on
2026-10-12: a System update from the Fruit Store replaced the code only, so
both boards kept system setups from earlier installs.

Nothing here needs root or changes the machine: commands are doubles, files
root would install land in a temporary folder, GitHub is faked.
"""

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helpers import ROOT, TempHomeTestCase
from mfruitos import __version__
from mfruitos.launcher.runtime import Runtime
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.ui.screens.updater import SystemUpdateScreen
from mfruitos.system import system_setup
from mfruitos.system.settings import Settings
from test_install_setup import fake_install, installer_block

SCRIPTS = Path(ROOT) / "scripts"
BASH = shutil.which("bash")
ME = pwd.getpwuid(os.getuid()).pw_name


def load_applier():
    loader = SourceFileLoader("mfruit_system_apply", str(SCRIPTS / "mfruit-system-apply"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_command(bin_dir, name, body, shell="/bin/sh"):
    target = Path(bin_dir) / name
    target.write_text(f"#!{shell}\n" + body, encoding="utf-8")
    target.chmod(0o755)


# --------------------------------------------------------------------- install.sh
@unittest.skipUnless(BASH, "bash is required")
class RootHelperTests(unittest.TestCase):
    """install.sh's root helpers: a file is installed only where it differs;
    --check-system compares and never asks for root."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mfruit-root-helpers-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "sudo.log"
        write_command(self.bin, "sudo", f'echo "sudo $*" >> "{self.log}"\n"$@"\n')
        fake_install(self.bin)
        self.dest = self.tmp / "etc" / "unit.service"

    def run_helpers(self, mode, snippet):
        script = ('ok() { echo "ok $*"; }; warn() { echo "warn $*"; }; TMP_FILES=(); '
                  f'MODE={mode}\n' + installer_block("root helpers") + snippet +
                  '\necho "CHANGED=${CHANGED[*]-}"; echo "DRIFT=$DRIFT"\n')
        result = subprocess.run([BASH, "-c", "set -euo pipefail\n" + script], text=True,
                                capture_output=True, timeout=30,
                                env=dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def put(self, mode, content):
        return self.run_helpers(mode, f"put_file 644 '{self.dest}' < <(printf '%s' '{content}')")

    def test_install_writes_only_what_differs_and_says_what_changed(self):
        self.assertIn(f"CHANGED={self.dest}", self.put("install", "one"))
        self.assertEqual(self.dest.read_text(), "one")
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o644)
        self.assertIn("CHANGED=\n", self.put("install", "one"))           # the same: untouched
        self.assertIn(f"CHANGED={self.dest}", self.put("install", "two"))
        self.dest.chmod(0o666)                                             # same text, wrong mode
        self.assertIn(f"CHANGED={self.dest}", self.put("install", "two"))
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o644)

    def test_check_compares_and_never_uses_sudo(self):
        out = self.put("check", "one")
        self.assertIn(f"{self.dest} is missing", out)
        self.assertIn("DRIFT=1", out)
        self.assertFalse(self.dest.exists())
        self.put("install", "one")
        self.log.unlink()
        self.assertIn("DRIFT=0", self.put("check", "one"))
        out = self.put("check", "two")
        self.assertIn(f"{self.dest} differs from this version", out)
        self.assertIn("-one", out)
        self.assertIn("+two", out)
        self.assertEqual(self.dest.read_text(), "one")
        self.assertFalse(self.log.exists(), "check mode ran sudo")

    def test_remove_link_and_module_follow_the_mode(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_text("old")
        link = self.tmp / "mfruitctl"
        out = self.run_helpers("check", f"remove_file '{self.dest}'; put_link /target '{link}'")
        self.assertIn("DRIFT=2", out)
        self.assertTrue(self.dest.exists())
        self.assertFalse(link.is_symlink())
        out = self.run_helpers("install", f"remove_file '{self.dest}'; put_link /target '{link}'")
        self.assertFalse(self.dest.exists())
        self.assertEqual(os.readlink(link), "/target")
        self.assertIn(f"CHANGED={self.dest} {link}", out)
        self.assertIn("DRIFT=0", self.run_helpers("check", f"put_link /target '{link}'"))


@unittest.skipUnless(BASH and sys.platform.startswith("linux"), "bash on Linux is required")
class InstallerModeTests(unittest.TestCase):
    """The whole installer with command doubles."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mfruit-install-modes-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "commands.log"
        self.pylog = self.tmp / "python.log"
        self.fake_root = self.tmp / "root"
        self.home = self.tmp / "home"
        self.os_home = self.home / ".whisplay-os"
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", LOG=str(self.log),
                        FAKE_ROOT=str(self.fake_root), WHISPLAY_OS_HOME=str(self.os_home))
        self.env.pop("SUDO_USER", None)
        write_command(self.bin, "getent", f'''case "$1" in
  passwd) [ "$2" = fixture ] && echo "fixture:x:1000:1000::{self.home}:/bin/sh" ;;
  *) exit 2 ;;
esac
''')
        write_command(self.bin, "systemctl", 'echo "systemctl $*" >> "$LOG"; exit 1\n')
        write_command(self.bin, "systemd-run", "exit 1\n")
        write_command(self.bin, "nmcli", "exit 0\n")
        write_command(self.bin, "uname", 'if [ "$1" = -s ]; then echo Linux; else echo "Linux aarch64"; fi\n')

    def run_installer(self, *args):
        return subprocess.run([BASH, str(SCRIPTS / "install.sh"), *args], env=self.env, text=True,
                              capture_output=True, timeout=120, stdin=subprocess.DEVNULL)

    def test_check_system_only_reads(self):
        write_command(self.bin, "id", '''case "$*" in
  -u|"-u fixture") echo 1000 ;;
  -un|"-gn fixture") echo fixture ;;
  *) exit 99 ;;
esac
''')
        write_command(self.bin, "sudo", 'echo "sudo $*" >> "$LOG"; exit 1\n')
        self.env["SUDO_USER"] = "fixture"
        result = self.run_installer("--check-system")
        out = result.stdout + result.stderr
        self.assertIn(result.returncode, (0, 1), out)
        self.assertIn("system setup compared with this device (read-only)", out)
        for path in ("/etc/systemd/system/whisplay-os.service", "/etc/sudoers.d/whisplay-os",
                     "/etc/polkit-1/rules.d/49-mfruit-wifi.rules", "/etc/mfruit-os/system.conf",
                     "/usr/local/lib/mfruit-os/mfruit-system-apply",
                     "/etc/systemd/system/mfruit-system-apply.service",
                     "/etc/systemd/system/mfruit-power.service"):
            self.assertIn(path, out)
        commands = self.log.read_text() if self.log.exists() else ""
        self.assertNotIn("sudo", commands)
        self.assertFalse(self.os_home.exists(), "check mode created the mFruit OS folder")

    def test_system_only_as_root_installs_the_system_setup_and_never_runs_the_users_python(self):
        # The process is root; files root installs land in FAKE_ROOT.
        write_command(self.bin, "id", '''case "$*" in
  -u) echo 0 ;;
  -un) echo root ;;
  "-u fixture") echo 1000 ;;
  "-gn fixture") echo fixture ;;
  *) exit 99 ;;
esac
''')
        write_command(self.bin, "sudo", '''echo "sudo $*" >> "$LOG"
if [ "$1" = -u ]; then shift 2; AS_USER=1 exec "$@"; fi
case "$1" in
  install)
    args=("$@"); src="${args[-2]}"; dest="${args[-1]}"
    mkdir -p "$FAKE_ROOT$(dirname "$dest")" && cp "$src" "$FAKE_ROOT$dest" ;;
  test|cmp|stat) exit 1 ;;
esac
exit 0
''', shell="/bin/bash")
        write_command(self.bin, "python3", f'echo "${{AS_USER:-root}} $*" >> "{self.pylog}"\n'
                                           f'exec {sys.executable} "$@"\n')
        (self.os_home / "system" / "current" / "mfruitos").mkdir(parents=True)
        (self.os_home / "system" / "current" / "mfruitos" / "__init__.py").write_text("")
        result = self.run_installer("--system-only", "--user", "fixture")
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)

        def installed(path):
            return (self.fake_root / path.lstrip("/")).read_text(encoding="utf-8")
        unit = installed("/etc/systemd/system/whisplay-os.service")
        self.assertIn("User=fixture", unit)
        self.assertIn(f"PYTHONPATH={self.os_home}/system/current", unit)
        self.assertIn("start mfruit-system-apply.service", installed("/etc/sudoers.d/whisplay-os"))
        conf = installed("/etc/mfruit-os/system.conf")
        for line in ("TARGET_USER=fixture", f"OS_HOME={self.os_home}",
                     "REPOSITORY=https://github.com/Mengkungkao/MFruitOS", "INSTALL_POWER=1"):
            self.assertIn(line + "\n", conf)
        self.assertEqual(installed("/usr/local/lib/mfruit-os/mfruit-system-apply"),
                         (SCRIPTS / "mfruit-system-apply").read_text(encoding="utf-8"))
        self.assertIn("ExecStart=/usr/bin/python3 -I /usr/local/lib/mfruit-os/mfruit-system-apply",
                      installed("/etc/systemd/system/mfruit-system-apply.service"))
        status = json.loads(installed("/var/lib/mfruit-os/system-setup.json"))
        self.assertEqual((status["version"], status["result"], status["by"]),
                         (__version__, "ok", "install.sh --system-only"))
        self.assertIn("/etc/systemd/system/whisplay-os.service", status["changed"])

        commands = self.log.read_text()
        self.assertIn("drivers/whisplay/install.sh --user fixture --restart-later", commands)
        # Status first, then the launcher (it may be what started this).
        self.assertLess(commands.index("/var/lib/mfruit-os/system-setup.json"),
                        commands.index("sudo systemctl restart whisplay-os.service"))
        self.assertFalse((self.os_home / "system" / "versions").exists(), "code was copied")
        # Root never ran the user's interpreter: every call went through sudo -u.
        calls = self.pylog.read_text().splitlines()
        self.assertTrue(calls)
        self.assertEqual([c for c in calls if not c.startswith("1 ")], [])

    def test_user_option_is_for_root_only(self):
        write_command(self.bin, "id", 'case "$*" in -u) echo 1000 ;; *) echo fixture ;; esac\n')
        result = self.run_installer("--system-only", "--user", "fixture")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--user is for root", result.stderr)


# --------------------------------------------------------------------- the applier
def tar_bytes(entries):
    """entries: (TarInfo-like dict, data)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, data in entries:
            member = tarfile.TarInfo(info["name"])
            member.type = info.get("type", tarfile.REGTYPE)
            member.mode = info.get("mode", 0o644)
            member.linkname = info.get("linkname", "")
            member.size = len(data) if member.type == tarfile.REGTYPE else 0
            tar.addfile(member, io.BytesIO(data) if member.type == tarfile.REGTYPE else None)
    return buffer.getvalue()


def release_package(version, installer_body):
    manifest = json.dumps({"id": "mfruit-os", "type": "system", "version": version}).encode()
    script = ("#!/bin/bash\n# handles --system-only)\n" + installer_body).encode()
    return tar_bytes([({"name": "mfruit-os", "type": tarfile.DIRTYPE, "mode": 0o755}, b""),
                      ({"name": "mfruit-os/manifest.json"}, manifest),
                      ({"name": "mfruit-os/scripts", "type": tarfile.DIRTYPE, "mode": 0o755}, b""),
                      ({"name": "mfruit-os/scripts/install.sh", "mode": 0o755}, script)])


class ApplierTestCase(unittest.TestCase):
    def setUp(self):
        self.applier = load_applier()
        temp = tempfile.TemporaryDirectory(prefix="mfruit-applier-")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.state = self.tmp / "var-lib-mfruit-os"
        self.state.mkdir()
        self.applier.STATE_DIR = str(self.state)
        self.applier.STATUS_FILE = str(self.state / "system-setup.json")
        self.applier.LOG_FILE = str(self.state / "system-setup.log")
        self.applier.CONF = str(self.tmp / "system.conf")
        self.applier.ROOT_UID = os.getuid()
        self.os_home = self.tmp / "home" / ".whisplay-os"
        (self.os_home / "system" / "current").mkdir(parents=True)

    def write_conf(self, **values):
        conf = dict(dict(TARGET_USER=ME, OS_HOME=str(self.os_home),
                         REPOSITORY="https://github.com/Mengkungkao/MFruitOS"), **values)
        path = Path(self.applier.CONF)
        path.write_text("# test\n" + "".join(f"{k}={v}\n" for k, v in conf.items()))
        path.chmod(0o644)

    def write_manifest(self, version, app_id="mfruit-os"):
        (self.os_home / "system" / "current" / "manifest.json").write_text(
            json.dumps({"id": app_id, "type": "system", "version": version}))


@unittest.skipIf(os.getuid() == 0, "the record must belong to a user other than root here")
class ApplierInputTests(ApplierTestCase):
    def test_the_record_must_be_root_owned_and_valid(self):
        self.write_conf()
        self.assertEqual(self.applier.read_conf()["TARGET_USER"], ME)
        os.chmod(self.applier.CONF, 0o664)
        with self.assertRaisesRegex(self.applier.SetupError, "only root can change"):
            self.applier.read_conf()
        self.applier.ROOT_UID = 0                 # owned by a user: refused
        os.chmod(self.applier.CONF, 0o644)
        with self.assertRaisesRegex(self.applier.SetupError, "only root can change"):
            self.applier.read_conf()
        self.applier.ROOT_UID = os.getuid()
        for values, problem in (({"TARGET_USER": "root"}, "does not run as root"),
                                ({"REPOSITORY": "https://evil.example/MFruitOS"}, "REPOSITORY"),
                                ({"OS_HOME": "relative/path"}, "absolute"),
                                ({"TARGET_USER": "no such user!"}, "TARGET_USER")):
            self.write_conf(**values)
            with self.assertRaisesRegex(self.applier.SetupError, problem):
                self.applier.read_conf()

    def test_only_the_version_is_taken_from_the_users_files(self):
        self.write_conf()
        conf = self.applier.read_conf()
        self.write_manifest("1.6.0")
        self.assertEqual(self.applier.running_version(conf), "1.6.0")
        manifest = self.os_home / "system" / "current" / "manifest.json"
        for bad in ('{"id": "mfruit-os", "version": "1.6.0; rm -rf /"}',
                    '{"id": "other", "version": "1.6.0"}', "not json", " " * 70000):
            manifest.write_text(bad)
            with self.assertRaises(self.applier.SetupError):
                self.applier.running_version(conf)
        manifest.unlink()
        os.symlink(self.tmp / "elsewhere.json", manifest)           # a link: not followed
        (self.tmp / "elsewhere.json").write_text('{"id": "mfruit-os", "version": "1.6.0"}')
        with self.assertRaises(self.applier.SetupError):
            self.applier.running_version(conf)
        manifest.unlink()
        os.mkfifo(manifest)                                          # a FIFO: does not hang
        with self.assertRaises(self.applier.SetupError):
            self.applier.running_version(conf)

    def test_checksum(self):
        archive = self.tmp / "mfruit-os-1.6.0.tar.gz"
        archive.write_bytes(b"package")
        good = hashlib.sha256(b"package").hexdigest()
        sums = self.tmp / "sums"
        sums.write_text(f"{good}  mfruit-os-1.6.0.tar.gz\n")
        self.applier.verify(str(archive), str(sums), archive.name)
        for text in (f"{'0' * 64}  mfruit-os-1.6.0.tar.gz\n", f"{good}  other.tar.gz\n", "nonsense"):
            sums.write_text(text)
            with self.assertRaises(self.applier.SetupError):
                self.applier.verify(str(archive), str(sums), archive.name)

    def extract(self, entries):
        archive = self.tmp / "package.tar.gz"
        archive.write_bytes(tar_bytes(entries))
        target = self.tmp / "out"
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir()
        return self.applier.safe_extract(str(archive), str(target))

    def test_extraction_takes_only_plain_files_inside_the_package(self):
        package = self.extract([({"name": "mfruit-os", "type": tarfile.DIRTYPE, "mode": 0o777}, b""),
                                ({"name": "mfruit-os/run.sh", "mode": 0o4777}, b"#!/bin/sh\n")])
        mode = stat.S_IMODE(os.stat(os.path.join(package, "run.sh")).st_mode)
        self.assertFalse(mode & (stat.S_ISUID | 0o022), oct(mode))
        self.assertFalse(stat.S_IMODE(os.stat(package).st_mode) & 0o022)
        for entry in ({"name": "mfruit-os/link", "type": tarfile.SYMTYPE, "linkname": "/etc/shadow"},
                      {"name": "mfruit-os/hard", "type": tarfile.LNKTYPE, "linkname": "mfruit-os/x"},
                      {"name": "mfruit-os/dev", "type": tarfile.CHRTYPE},
                      {"name": "mfruit-os/../escape"}, {"name": "/etc/cron.d/x"},
                      {"name": "elsewhere/file"}):
            with self.subTest(entry=entry["name"]):
                with self.assertRaises(self.applier.SetupError):
                    self.extract([(entry, b"x")])


class FakeGitHub:
    """Release assets from memory; records the URLs asked for."""

    def __init__(self, applier, version, package):
        self.urls = []
        name = f"mfruit-os-{version}.tar.gz"
        base = f"https://github.com/Mengkungkao/MFruitOS/releases/download/v{version}/{name}"
        self.assets = {base: package,
                       base + ".sha256": f"{hashlib.sha256(package).hexdigest()}  {name}\n".encode()}
        self.error = None
        applier.download = self.download

    def download(self, url, target, limit):
        self.urls.append(url)
        if self.error:
            raise self.error
        with open(target, "wb") as fp:
            fp.write(self.assets[url])


@unittest.skipIf(os.getuid() == 0, "runs the fake install.sh as the test user")
class ApplierRunTests(ApplierTestCase):
    def setUp(self):
        super().setUp()
        self.write_conf()
        self.write_manifest("1.6.0")
        self.ran = self.tmp / "install-args"
        status = self.applier.STATUS_FILE
        self.github = FakeGitHub(self.applier, "1.6.0", release_package("1.6.0", f'''
echo "$* | $WHISPLAY_OS_HOME | $(pwd)" > "{self.ran}"
printf '{{"version": "1.6.0", "result": "ok", "changed": []}}' > "{status}"
'''))

    def apply(self, force=False):
        conf = self.applier.read_conf()
        return self.applier.apply(conf, self.applier.running_version(conf), force=force)

    def test_downloads_the_release_of_the_running_version_and_runs_its_system_setup(self):
        self.assertEqual(self.apply(), "1.6.0")
        self.assertEqual(self.github.urls, [
            "https://github.com/Mengkungkao/MFruitOS/releases/download/v1.6.0/mfruit-os-1.6.0.tar.gz.sha256",
            "https://github.com/Mengkungkao/MFruitOS/releases/download/v1.6.0/mfruit-os-1.6.0.tar.gz"])
        args, home, cwd = self.ran.read_text().strip().split(" | ")
        self.assertEqual(args, f"--system-only --user {ME} --yes")
        self.assertEqual((home, cwd), (str(self.os_home), "/"))
        self.assertEqual(os.listdir(self.state), ["system-setup.json"])     # work folder gone
        # Done for this version: nothing is downloaded again, unless forced.
        self.github.urls.clear()
        self.apply()
        self.assertEqual(self.github.urls, [])
        self.apply(force=True)
        self.assertEqual(len(self.github.urls), 2)

    def test_a_package_that_does_not_match_its_checksum_never_runs(self):
        url = next(u for u in self.github.assets if u.endswith(".tar.gz"))
        self.github.assets[url] = release_package("1.6.0", "touch /tmp/should-not-run\n")
        with self.assertRaisesRegex(self.applier.SetupError, "does not match its published SHA-256"):
            self.apply()
        self.assertFalse(self.ran.exists())

    def test_a_package_of_another_version_never_runs(self):
        url = next(u for u in self.github.assets if u.endswith(".tar.gz"))
        package = release_package("1.6.1", "true\n")
        self.github.assets[url] = package
        self.github.assets[url + ".sha256"] = \
            f"{hashlib.sha256(package).hexdigest()}  mfruit-os-1.6.0.tar.gz\n".encode()
        with self.assertRaisesRegex(self.applier.SetupError, "is not mFruit OS 1.6.0"):
            self.apply()
        self.assertFalse(self.ran.exists())

    def test_versions_before_the_service_are_not_applied(self):
        self.write_manifest("1.5.3")
        with self.assertRaises(self.applier.SetupError) as caught:
            self.apply()
        self.assertEqual(caught.exception.result, "unsupported")
        self.assertEqual(self.github.urls, [])

    def test_failures_are_recorded_for_the_launcher(self):
        self.github.error = self.applier.SetupError("offline", "cannot download: no route")
        with contextlib.redirect_stderr(io.StringIO()) as journal:
            self.assertEqual(self.applier.main([]), 1)
        self.assertIn("no route", journal.getvalue())
        status = json.loads(Path(self.applier.STATUS_FILE).read_text())
        self.assertEqual((status["version"], status["result"]), ("1.6.0", "offline"))
        self.assertIn("no route", status["message"])
        self.assertIn("no route", Path(self.applier.LOG_FILE).read_text())

    def test_a_failed_setup_is_reported_with_its_log(self):
        url = next(u for u in self.github.assets if u.endswith(".tar.gz"))
        package = release_package("1.6.0", "echo broken; exit 3\n")
        self.github.assets[url] = package
        self.github.assets[url + ".sha256"] = \
            f"{hashlib.sha256(package).hexdigest()}  mfruit-os-1.6.0.tar.gz\n".encode()
        with self.assertRaisesRegex(self.applier.SetupError, "exit 3"):
            self.apply()


class ApplierDownloadTests(unittest.TestCase):
    def setUp(self):
        self.applier = load_applier()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/missing":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"data")

            def log_message(self, *args):
                pass
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.target = os.path.join(temp.name, "file")

    def test_plain_http_is_refused(self):
        with self.assertRaisesRegex(self.applier.SetupError, "away from HTTPS"):
            self.applier.download(self.url + "/file", self.target, 100)

    def test_a_missing_release_and_no_network(self):
        with self.assertRaises(self.applier.SetupError) as caught:
            self.applier.download(self.url + "/missing", self.target, 100)
        self.assertEqual(caught.exception.result, "failed")
        self.server.shutdown()
        self.server.server_close()
        with self.assertRaises(self.applier.SetupError) as caught:
            self.applier.download(self.url + "/file", self.target, 100)
        self.assertEqual(caught.exception.result, "offline")


# --------------------------------------------------------------------- the launcher
class StatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.status_file = self.dir / "system-setup.json"
        self.applier = self.dir / "mfruit-system-apply"

    def read(self):
        return system_setup.read_status(str(self.status_file), str(self.applier))

    def test_status_is_read_defensively(self):
        self.assertEqual((self.read().installed, self.read().result), (False, ""))
        self.applier.write_text("")
        self.status_file.write_text("[1, 2]")
        self.assertTrue(self.read().installed)
        self.status_file.write_text(json.dumps({"version": "1.6.0", "result": "ok",
                                                "reboot_required": "yes", "changed": ["a"]}))
        status = self.read()
        self.assertEqual((status.version, status.reboot_required, status.changed),
                         ("1.6.0", False, ["a"]))
        self.assertTrue(status.applied("1.6.0"))
        self.assertFalse(status.applied("1.6.1"))
        status.result = "failed"
        self.assertFalse(status.applied("1.6.0"))

    def fake_sudo(self, exit_code, stderr=""):
        bin_dir = self.dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        write_command(bin_dir, "sudo", f'echo "$*" > "{self.dir}/args"\n'
                                       f'[ -z "{stderr}" ] || echo "{stderr}" >&2\nexit {exit_code}\n')
        return mock.patch.dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")

    def apply(self):
        return system_setup.apply(status_file=str(self.status_file), applier=str(self.applier))

    def test_apply_starts_the_service_through_its_sudoers_rule(self):
        self.status_file.write_text(json.dumps({"version": "1.6.0", "result": "ok"}))
        with self.fake_sudo(0):
            self.assertTrue(self.apply().applied("1.6.0"))
        args = (self.dir / "args").read_text().split()
        self.assertEqual(args[0], "-n")
        self.assertTrue(args[1].endswith("systemctl"))
        self.assertEqual(args[2:], ["start", "mfruit-system-apply.service"])

    def test_apply_explains_failures(self):
        with self.fake_sudo(1, "sudo: a password is required"):
            with self.assertRaisesRegex(system_setup.SetupError, "install.sh --system-only"):
                self.apply()
        self.status_file.write_text(json.dumps({"version": "1.6.0", "result": "offline",
                                                "message": "cannot download: no route"}))
        with self.fake_sudo(1, "Job failed"):
            with self.assertRaisesRegex(system_setup.SetupError, "no route"):
                self.apply()


class AutomaticSetupTests(TempHomeTestCase):
    """Once per version, after a System update or roll back; never over an
    open app or another job."""

    def runtime(self, status):
        rt = SimpleNamespace(paths=self.paths, apps=SimpleNamespace(session=None),
                             tasks=SimpleNamespace(busy=lambda lane: False),
                             apply_system_setup=mock.Mock(return_value=True))
        patcher = mock.patch.object(system_setup, "read_status", return_value=status)
        patcher.start()
        self.addCleanup(patcher.stop)
        return rt

    def due(self, rt):
        Runtime._maybe_apply_system_setup(rt)
        return rt.apply_system_setup.call_count

    def test_runs_once_for_a_new_version(self):
        rt = self.runtime(system_setup.SetupStatus(installed=True, version="1.5.9", result="ok"))
        rt.apps.session = object()                     # an app is open: later
        self.assertEqual(self.due(rt), 0)
        rt.apps.session = None
        self.assertEqual(self.due(rt), 1)
        self.assertEqual(self.due(rt), 1)              # not again for this version

    def test_not_when_done_or_not_installed_or_busy(self):
        for status in (system_setup.SetupStatus(installed=True, version=__version__, result="ok"),
                       system_setup.SetupStatus(installed=False)):
            with self.subTest(status=status):
                self.assertEqual(self.due(self.runtime(status)), 0)
        rt = self.runtime(system_setup.SetupStatus(installed=True))
        rt.tasks.busy = lambda lane: lane == "jobs"
        self.assertEqual(self.due(rt), 0)


class SystemUpdateScreenTests(TempHomeTestCase):
    def labels(self, status):
        os_ = ScreenServices()
        os_.settings = Settings(None)
        os_.paths = self.paths
        os_.updater = mock.Mock()
        os_.updater.info.return_value = SimpleNamespace(latest=__version__, update_available=False,
                                                        error="", notes="")
        os_.installer = mock.Mock()
        os_.installer.read_record.return_value = {}
        os_.run_task = lambda name, fn, done, failed=None, lane="quick": done(fn())
        os_.request_render = mock.Mock()
        screen = SystemUpdateScreen(os_, read_setup=lambda: status)
        screen.on_show()
        return {item.label: item.subtitle for item in screen.items()}

    def test_rows_follow_the_state(self):
        rows = self.labels(system_setup.SetupStatus(installed=False))
        self.assertEqual(rows["System setup"], "Needs a computer once")
        rows = self.labels(system_setup.SetupStatus(installed=True, version="1.5.9", result="ok"))
        self.assertEqual(rows["System setup"], f"Needed for {__version__}")
        self.assertIn("Apply setup", rows)
        rows = self.labels(system_setup.SetupStatus(installed=True, version=__version__,
                                                    result="offline", message="no route"))
        self.assertEqual(rows["System setup"], "Offline: no route")
        rows = self.labels(system_setup.SetupStatus(installed=True, version=__version__, result="ok"))
        self.assertEqual(rows["System setup"], "Up to date")
        self.assertNotIn("Apply setup", rows)
        rows = self.labels(system_setup.SetupStatus(installed=True, version=__version__, result="ok",
                                                    reboot_required=True))
        self.assertEqual(rows["System setup"], "Restart to finish")
        self.assertIn("Restart now", rows)


class CtlTests(unittest.TestCase):
    def test_status_and_check(self):
        from mfruitos import ctl
        status = system_setup.SetupStatus(installed=True, version="1.6.0", result="ok")
        out = io.StringIO()
        with mock.patch.object(system_setup, "read_status", return_value=status), \
                contextlib.redirect_stdout(out):
            self.assertEqual(ctl.main(["system-setup"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual((data["running"], data["version"], data["installed"]),
                         (__version__, "1.6.0", True))
        with mock.patch("subprocess.call", return_value=1) as call:
            self.assertEqual(ctl.main(["system-setup", "check"]), 1)
        self.assertEqual(call.call_args[0][0],
                         ["bash", os.path.join(ROOT, "scripts", "install.sh"), "--check-system"])


if __name__ == "__main__":
    unittest.main()
