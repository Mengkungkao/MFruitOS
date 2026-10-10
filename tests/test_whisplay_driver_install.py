"""drivers/whisplay/install.sh: board detection, boot configuration and the staged copy.

The functions are sourced from the real script and pointed at a fake root
(SYSROOT) or temporary directories; nothing here needs root or changes the
machine. Package installation, the sound card build and systemd are covered
by device validation (docs/WHISPLAY_DRIVER.md).
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import ROOT

SCRIPT = os.path.join(ROOT, "drivers", "whisplay", "install.sh")


def bash(snippet, **env):
    full = dict(os.environ, **env)
    return subprocess.run(["bash", "-c", f'source "{SCRIPT}"; {snippet}'], env=full,
                          capture_output=True, text=True, timeout=60)


class FakeRoot:
    def __init__(self, test, model="", compatible=(), files=None):
        self.path = tempfile.mkdtemp(prefix="mfruit-sysroot-")
        test.addCleanup(shutil.rmtree, self.path, True)
        dt = os.path.join(self.path, "proc", "device-tree")
        os.makedirs(dt)
        if model:
            with open(os.path.join(dt, "model"), "wb") as fp:
                fp.write(model.encode() + b"\0")
        if compatible:
            with open(os.path.join(dt, "compatible"), "wb") as fp:
                fp.write(b"\0".join(c.encode() for c in compatible) + b"\0")
        for name, text in (files or {}).items():
            full = os.path.join(self.path, name.lstrip("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as fp:
                fp.write(text)

    def file(self, name):
        with open(os.path.join(self.path, name.lstrip("/"))) as fp:
            return fp.read()


class BoardDetection(unittest.TestCase):
    def detect(self, **kwargs):
        root = FakeRoot(self, **kwargs)
        result = bash("detect_platform", SYSROOT=root.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_boards_detected_as_whisplay_does(self):
        self.assertEqual(self.detect(model="Raspberry Pi Zero 2 W Rev 1.0"), "raspberry_pi")
        self.assertEqual(self.detect(model="OrangePi Zero2 W"), "orangepi_zero2w")
        self.assertEqual(self.detect(compatible=["xunlong,orangepi-zero2w", "allwinner,sun50i-h618"]),
                         "orangepi_zero2w")
        self.assertEqual(self.detect(model="Radxa ZERO 3W", compatible=["radxa,zero3w"]), "radxa_zero3w")
        self.assertEqual(self.detect(model="Radxa Cubie A7Z", compatible=["radxa,cubie-a7z"]),
                         "radxa_cubie_a7z")

    def test_orange_pi_zero_3w_trusts_release_files_over_its_generic_device_tree(self):
        self.assertEqual(self.detect(model="sun60iw2", compatible=["xunlong,orangepi-4-pro"],
                                     files={"/etc/orangepi-release": "BOARD=orangepizero3w\n"}),
                         "orangepi_zero3w")
        self.assertEqual(self.detect(files={"/boot/orangepiEnv.txt": "fdtfile=allwinner/orangepi-zero3w.dtb\n"}),
                         "orangepi_zero3w")

    def test_other_boards_are_unknown(self):
        self.assertEqual(self.detect(model="NVIDIA Jetson Orin Nano Developer Kit"), "unknown")
        self.assertEqual(self.detect(), "unknown")

    def test_check_on_an_unsupported_board_exits_3_without_root(self):
        root = FakeRoot(self, model="NVIDIA Jetson")
        result = subprocess.run(["bash", SCRIPT, "--check"], env=dict(os.environ, SYSROOT=root.path),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("not a board the Whisplay driver supports", result.stdout)

    def test_install_refuses_without_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        result = subprocess.run(["bash", SCRIPT, "--user", "nobody"], capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("run as root", result.stderr)


class OrangePiBootConfig(unittest.TestCase):
    ENV = "verbosity=1\noverlays=spi0-spidev uart1\nuser_overlays=lora\nrootdev=UUID=1234\n"

    def enable(self, root):
        return bash('enable_buses orangepi_zero2w >/dev/null; echo "$REBOOT"', SYSROOT=root.path,
                    REBOOT="0")

    def test_zero_2w_overlays_are_set_once_and_others_kept(self):
        root = FakeRoot(self, files={"/boot/orangepiEnv.txt": self.ENV})
        first = self.enable(root)
        self.assertEqual(first.stdout.strip(), "1", first.stderr)
        expected = "verbosity=1\noverlays=uart1 pi-i2c1 spi1-cs0-spidev\nuser_overlays=lora\nrootdev=UUID=1234\n"
        self.assertEqual(root.file("/boot/orangepiEnv.txt"), expected)
        # A second run changes nothing and needs no reboot.
        second = self.enable(root)
        self.assertEqual(second.stdout.strip(), "0", second.stderr)
        self.assertEqual(root.file("/boot/orangepiEnv.txt"), expected)

    def test_zero_2w_without_an_overlays_line_gets_one(self):
        root = FakeRoot(self, files={"/boot/orangepiEnv.txt": "verbosity=1\n"})
        self.assertEqual(self.enable(root).stdout.strip(), "1")
        self.assertEqual(root.file("/boot/orangepiEnv.txt"),
                         "verbosity=1\noverlays=pi-i2c1 spi1-cs0-spidev\n")

    def test_zero_3w_overlays(self):
        root = FakeRoot(self, files={"/boot/orangepiEnv.txt": "overlays=uart2\n"})
        result = bash('enable_buses orangepi_zero3w >/dev/null; echo "$REBOOT"', SYSROOT=root.path, REBOOT="0")
        self.assertEqual(result.stdout.strip(), "1", result.stderr)
        self.assertEqual(root.file("/boot/orangepiEnv.txt"), "overlays=uart2 i2c0 spi3-cs0-cs1-spidev\n")


class RaspberryPiBootConfig(unittest.TestCase):
    """Lines added to config.txt land in its [all] section, on their own line."""

    # Ubuntu 24.04 for Raspberry Pi as shipped (canonical/pi-gadget, branch 24):
    # SPI, I2C and the UART are on already, and it ends in [all].
    UBUNTU_2404 = ("[all]\nkernel=vmlinuz\ncmdline=cmdline.txt\n\n[all]\ndtparam=audio=on\n"
                   "dtparam=i2c_arm=on\ndtparam=spi=on\nenable_uart=1\n\n[cm4]\n"
                   "dtoverlay=dwc2,dr_mode=host\n\n[all]\narm_64bit=1\ndtoverlay=dwc2\n")

    # Only the tools this step uses, so a host's own raspi-config (Raspberry Pi
    # OS has one) is never found, let alone run against its real config.txt.
    TOOLS = ("dirname", "grep", "tail", "tr", "cat", "sed", "awk", "head", "cksum", "sort", "cut")

    def enable(self, text):
        root = FakeRoot(self, model="Raspberry Pi Zero 2 W Rev 1.0",
                        files={"/boot/firmware/config.txt": text})
        tools = os.path.join(root.path, "tools")
        os.makedirs(tools)
        for name in self.TOOLS:
            os.symlink(shutil.which(name), os.path.join(tools, name))
        result = subprocess.run([shutil.which("bash"), "-c", f'source "{SCRIPT}"; enable_buses raspberry_pi >/dev/null'],
                                env=dict(os.environ, SYSROOT=root.path, REBOOT="0", PATH=tools),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("raspi-config", result.stderr)
        return root.file("/boot/firmware/config.txt")

    def test_a_file_ending_in_a_model_filter_gets_an_all_section_first(self):
        text = self.enable("[all]\narm_64bit=1\n\n[cm4]\notg_mode=1\n")
        self.assertTrue(text.endswith("[cm4]\notg_mode=1\n\n[all]\ndtparam=spi=on\n"), text)

    def test_a_missing_final_newline_does_not_join_lines(self):
        text = self.enable("[all]\narm_64bit=1")
        self.assertEqual(text, "[all]\narm_64bit=1\ndtparam=spi=on\n")

    def test_the_stock_ubuntu_file_is_left_as_it_is(self):
        self.assertEqual(self.enable(self.UBUNTU_2404), self.UBUNTU_2404)


class SoundCardBuildFlags(unittest.TestCase):
    """The bundled source calls asoc_substream_to_rtd() before Linux 6.12, a name
    removed in 6.8: kernels 6.8 to 6.11 map it to snd_soc_substream_to_rtd()
    (built against Ubuntu 24.04's 6.8.0-1065-raspi headers, 2026-10-10)."""

    def flags(self, release):
        result = bash(f'soundcard_kcflags "{release}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_only_kernels_6_8_to_6_11_get_the_mapping(self):
        mapped = "-Dasoc_substream_to_rtd=snd_soc_substream_to_rtd"
        for release, expected in (
                ("5.15.0-1110-raspi", ""),          # Ubuntu 22.04: builds as it is
                ("6.1.31-sun50iw9", ""),            # Orange Pi OS
                ("6.6.51+rpt-rpi-v8", ""),          # Raspberry Pi OS Bookworm
                ("6.7.0-1001-raspi", ""),           # both names exist
                ("6.8.0-1065-raspi", mapped),       # Ubuntu 24.04
                ("6.11.0-1004-raspi", mapped),      # Ubuntu 24.10
                ("6.12.25+rpt-rpi-v8", ""),         # the source's own switch
                ("6.18.50+rpt-rpi-v8", ""),         # Raspberry Pi OS Trixie
                ("7.0.0", ""), ("garbage", "")):
            with self.subTest(release=release):
                self.assertEqual(self.flags(release), expected)


class DaemonServiceGroups(unittest.TestCase):
    """whisplay-daemon.service lists only groups that exist: systemd refuses to
    start a unit whose SupplementaryGroups= names a missing group (216/GROUP).
    Ubuntu for Raspberry Pi has no gpio group; its SPI, GPIO and I2C devices
    belong to dialout (ubuntu-raspi-settings 99-gpio.rules)."""

    DATABASES = {
        "raspberry pi os": ("audio video gpio spi i2c input dialout",
                            "audio video gpio spi i2c input"),
        "ubuntu for raspberry pi": ("audio video input dialout", "audio video input dialout"),
        "bare": ("audio video", "audio video"),
    }

    def unit_for(self, groups):
        tmp = tempfile.mkdtemp(prefix="mfruit-daemon-unit-")
        self.addCleanup(shutil.rmtree, tmp, True)
        fakes = os.path.join(tmp, "bin")
        os.makedirs(fakes)
        real_getent = shutil.which("getent")
        with open(os.path.join(fakes, "getent"), "w") as fp:
            fp.write('#!/bin/sh\nif [ "$1" = group ]; then\n'
                     '  for g in $FAKE_GROUPS; do [ "$g" = "$2" ] && { echo "$2:x:1:"; exit 0; }; done\n'
                     f'  exit 2\nfi\nexec {real_getent} "$@"\n')
        with open(os.path.join(fakes, "systemctl"), "w") as fp:
            fp.write("#!/bin/sh\nexit 0\n")
        for name in ("getent", "systemctl"):
            os.chmod(os.path.join(fakes, name), 0o755)
        home = os.path.join(tmp, "home")
        user = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        result = bash(f'UNIT_PATH="{tmp}/whisplay-daemon.service"; BACKUP_DIR="{tmp}/backup"; '
                      f'DRIVER_DIR="{tmp}/driver"; PLATFORM=raspberry_pi; DAEMON_CHANGED=0; '
                      f'getent() {{ if [ "$1" = passwd ]; then echo "{user}:x:$(id -u):$(id -g)::{home}:/bin/sh"; '
                      f'else command getent "$@"; fi; }}; '
                      f'install_daemon_service "{user}" >/dev/null && cat "$UNIT_PATH"',
                      PATH=f"{fakes}:{os.environ['PATH']}", FAKE_GROUPS=groups)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_only_existing_groups_are_listed(self):
        for system, (groups, expected) in self.DATABASES.items():
            with self.subTest(system=system):
                unit = self.unit_for(groups)
                line = next(l for l in unit.splitlines() if l.startswith("SupplementaryGroups="))
                self.assertEqual(line, f"SupplementaryGroups={expected}")
                for listed in line.split("=", 1)[1].split():
                    self.assertIn(listed, groups.split(), f"{listed} does not exist on {system}")


class StagedDriverCopy(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="mfruit-driver-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.target = os.path.join(self.base, "whisplay")

    def install(self):
        result = bash('DAEMON_CHANGED=0; install_driver_files; echo "changed=$DAEMON_CHANGED"',
                      MFRUIT_WHISPLAY_DIR=self.target)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def marker(self, path):
        with open(os.path.join(path, "MFRUIT_DRIVER")) as fp:
            return dict(line.split("=", 1) for line in fp.read().splitlines())

    def test_first_install_then_unchanged(self):
        self.assertIn("changed=1", self.install())
        for name in ("runtime/whisplay.py", "runtime/whisplay_client.py", "daemon/whisplay_daemon.py",
                     "daemon/internal_apps/wifi_app.py", "daemon/img/wifi-strong.png", "LICENSE",
                     "UPSTREAM.md"):
            self.assertTrue(os.path.isfile(os.path.join(self.target, name)), name)
        self.assertFalse(os.path.exists(os.path.join(self.target, "daemon", "tests")))
        self.assertTrue(os.path.isdir(os.path.join(self.target, "daemon", "__pycache__")))
        marker = self.marker(self.target)
        self.assertEqual(marker["upstream"], "c73051e64dc62aced1853d16f33d4614fec5bee4")
        self.assertIn("changed=0", self.install())
        self.assertFalse(os.path.exists(self.target + ".previous"))

    def test_an_update_keeps_the_previous_copy(self):
        self.install()
        marker_path = os.path.join(self.target, "MFRUIT_DRIVER")
        with open(marker_path) as fp:
            old = fp.read().replace("manifest_sha256=", "manifest_sha256=old")
        with open(marker_path, "w") as fp:
            fp.write(old)
        self.assertIn("changed=1", self.install())
        self.assertTrue(self.marker(self.target + ".previous")["manifest_sha256"].startswith("old"))
        self.assertFalse(self.marker(self.target)["manifest_sha256"].startswith("old"))

    def test_a_directory_not_installed_by_mfruit_os_is_moved_aside_not_deleted(self):
        os.makedirs(os.path.join(self.target, "runtime"))
        with open(os.path.join(self.target, "runtime", "mine.txt"), "w") as fp:
            fp.write("user file")
        self.install()
        kept = [d for d in os.listdir(self.base) if d.startswith("whisplay.preexisting-")]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.base, kept[0], "runtime", "mine.txt")) as fp:
            self.assertEqual(fp.read(), "user file")
        self.assertTrue(os.path.isfile(os.path.join(self.target, "MFRUIT_DRIVER")))


class DriverPackages(unittest.TestCase):
    def packages(self, which):
        result = bash(f'echo "${{{which}[@]}}" | tr " " "\\n" | sed "s/.*://"')
        return result.stdout.split()

    def test_the_fonts_the_daemon_draws_with_are_required(self):
        # Without DejaVu Sans the daemon's pages crash on Pillow < 9.2 (Ubuntu 22.04).
        self.assertIn("fonts-dejavu-core", self.packages("REQUIRED"))

    def test_bluetooth_support_is_installed_when_available(self):
        for name in ("bluez", "python3-dbus", "python3-gi"):
            self.assertIn(name, self.packages("OPTIONAL"))

    def test_the_sound_card_build_tools_are_installed(self):
        # Ubuntu for Raspberry Pi has no compiler; Whisplay's sound card installer
        # adds make and gcc on Orange Pi only (rehearsal 2026-10-10: "make: command not found").
        for name in ("make", "gcc"):
            self.assertIn(name, self.packages("OPTIONAL"))

    def test_a_missing_font_file_is_reported_as_its_package(self):
        root = FakeRoot(self, model="OrangePi Zero2 W")
        result = bash("missing_packages required", SYSROOT=root.path)
        self.assertIn("fonts-dejavu-core", result.stdout.split())


class BundledFiles(unittest.TestCase):
    def test_bundled_files_match_upstream_checksums(self):
        result = subprocess.run(["bash", os.path.join(ROOT, "scripts", "whisplay-driver-sync.sh"), "--check"],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_demo_apps_or_external_installers_are_bundled(self):
        driver = os.path.join(ROOT, "drivers", "whisplay")
        for name in ("example", "daemon/default_apps", "install_driver.sh", "script",
                     "daemon/install_whisplay_daemon_service.sh", "packaging"):
            self.assertFalse(os.path.exists(os.path.join(driver, name)), name)


if __name__ == "__main__":
    unittest.main()
