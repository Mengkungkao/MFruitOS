"""Offline packs (scripts/offline.sh, scripts/make-offline-pack.sh).

apt runs for real against a pack built from test .deb files, in simulation
mode with a private state directory, so nothing is installed and no root or
network is needed. The sound card installer is replaced by a recording
script. A real pack on a board is covered by device validation
(docs/WHISPLAY_DRIVER.md#offline-installation).
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest

from helpers import ROOT

OFFLINE = os.path.join(ROOT, "scripts", "offline.sh")
MAKE_PACK = os.path.join(ROOT, "scripts", "make-offline-pack.sh")
DRIVER = os.path.join(ROOT, "drivers", "whisplay", "install.sh")
SOUND_INSTALLER = os.path.join(ROOT, "drivers", "whisplay", "audio", "whisplay-soundcard", "scripts",
                               "install.sh")
HAVE_APT = all(shutil.which(tool) for tool in ("apt-get", "dpkg-deb", "dpkg"))


def bash(script, snippet, **env):
    return subprocess.run(["bash", "-c", f'source "{script}"; {snippet}'], env=dict(os.environ, **env),
                          capture_output=True, text=True, timeout=120)


def arch():
    return subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True).stdout.strip()


class Pack:
    def __init__(self, test, platform="raspberry_pi", codename="trixie", os_id="debian"):
        self.root = tempfile.mkdtemp(prefix="mfruit-offline-")
        test.addCleanup(shutil.rmtree, self.root, True)
        self.path = os.path.join(self.root, f"{platform}-{os_id}-{codename}-x")
        os.makedirs(os.path.join(self.path, "debs"))
        os.makedirs(os.path.join(self.path, "files"))
        with open(os.path.join(self.path, "pack.env"), "w") as fp:
            fp.write(f"PLATFORM={platform}\nOS_ID={os_id}\nOS_CODENAME={codename}\nARCH={arch()}\n"
                     f"KERNEL=6.12.0-test\nCREATED=2026-10-03\n")

    def deb(self, name, version="1.0", depends="", filename=None):
        build = tempfile.mkdtemp(prefix="mfruit-deb-")
        os.makedirs(os.path.join(build, "DEBIAN"))
        control = f"Package: {name}\nVersion: {version}\nArchitecture: all\nMaintainer: t <t@t>\nDescription: t\n"
        if depends:
            control += f"Depends: {depends}\n"
        with open(os.path.join(build, "DEBIAN", "control"), "w") as fp:
            fp.write(control)
        target = os.path.join(self.path, "debs", filename or f"{name}_{version}_all.deb")
        subprocess.run(["dpkg-deb", "--build", build, target], check=True, capture_output=True)
        shutil.rmtree(build)

    def index(self):
        result = bash(OFFLINE, f'write_packages_index "{self.path}/debs"')
        assert result.returncode == 0, result.stderr

    def file(self, url, content):
        key = bash(OFFLINE, f'offline_file_key "{url}"').stdout
        with open(os.path.join(self.path, "files", key), "w") as fp:
            fp.write(content)


def fake_apt(test, status):
    """apt-get that simulates against an empty dpkg database (a bare system)."""
    path = os.path.join(tempfile.mkdtemp(prefix="mfruit-apt-"), "apt-get")
    test.addCleanup(shutil.rmtree, os.path.dirname(path), True)
    with open(path, "w") as fp:
        fp.write('#!/bin/sh\nsim=""\nfor a in "$@"; do [ "$a" = install ] && sim=-s; done\n'
                 f'exec {shutil.which("apt-get")} -o Debug::NoLocking=1 -o Dir::State::status={status} '
                 '$sim "$@"\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


@unittest.skipUnless(HAVE_APT, "needs apt-get, dpkg and dpkg-deb")
class LocalRepository(unittest.TestCase):
    def test_apt_resolves_missing_packages_and_their_dependencies_from_the_pack_only(self):
        pack = Pack(self)
        pack.deb("mfruit-test-b")
        pack.deb("mfruit-test-a", depends="mfruit-test-b (>= 1.0)")
        pack.deb("mfruit-test-epoch", version="2:3.0", filename="mfruit-test-epoch_2%3a3.0_all.deb")
        pack.index()
        self.assertTrue(os.path.isfile(os.path.join(pack.path, "debs", "mfruit-test-epoch_2_3.0_all.deb")))
        status = os.path.join(pack.root, "status")
        open(status, "w").close()
        apt = fake_apt(self, status)
        result = bash(OFFLINE, f'REAL_APT_GET="{apt}"; offline_apt "{pack.path}" install -y '
                               "--no-install-recommends mfruit-test-a mfruit-test-epoch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in ("Inst mfruit-test-b (1.0", "Inst mfruit-test-a (1.0", "Inst mfruit-test-epoch (2:3.0"):
            self.assertIn(line, result.stdout, result.stdout + result.stderr)

    def test_a_package_missing_from_the_pack_fails_instead_of_going_online(self):
        pack = Pack(self)
        pack.deb("mfruit-test-a", depends="mfruit-test-not-packed")
        pack.index()
        status = os.path.join(pack.root, "status")
        open(status, "w").close()
        result = bash(OFFLINE, f'REAL_APT_GET="{fake_apt(self, status)}"; '
                               f'offline_apt "{pack.path}" install -y mfruit-test-a')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mfruit-test-not-packed", result.stdout + result.stderr)


class Shims(unittest.TestCase):
    def test_wget_is_served_from_the_pack_and_apt_get_sees_only_the_pack(self):
        pack = Pack(self)
        url = "https://example.invalid/kheaders.tar.xz"
        pack.file(url, "headers")
        shims = bash(OFFLINE, f'offline_shims "{pack.path}"').stdout.strip()
        self.addCleanup(shutil.rmtree, shims, True)
        out = os.path.join(pack.root, "out")
        # The upstream installer passes -O before or after the URL.
        for args in (["-q", "--show-progress", "-O", out, url], ["-q", url, "-O", out]):
            result = subprocess.run([os.path.join(shims, "wget"), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(out) as fp:
                self.assertEqual(fp.read(), "headers")
        result = subprocess.run([os.path.join(shims, "wget"), "-q", "-O", out, "https://example.invalid/other"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 4)
        self.assertIn("not in the offline pack", result.stderr)
        with open(os.path.join(shims, "apt-get")) as fp:
            apt = fp.read()
        self.assertIn("Dir::Etc::SourceList=", apt)
        with open(os.path.join(shims, "apt-state", "sources.list")) as fp:
            self.assertEqual(fp.read(), f"deb [trusted=yes] file:{pack.path}/debs ./\n")


class FindPack(unittest.TestCase):
    def sysroot(self, codename):
        root = tempfile.mkdtemp(prefix="mfruit-sysroot-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "proc", "device-tree"))
        os.makedirs(os.path.join(root, "etc"))
        with open(os.path.join(root, "proc", "device-tree", "model"), "wb") as fp:
            fp.write(b"Raspberry Pi Zero 2 W Rev 1.0\0")
        with open(os.path.join(root, "etc", "os-release"), "w") as fp:
            fp.write(f'ID=debian\nVERSION_CODENAME={codename}\n')
        return root

    def find(self, pack, codename):
        return subprocess.run(["bash", OFFLINE, "find"], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, SYSROOT=self.sysroot(codename), MFRUIT_OFFLINE_DIR=pack.root))

    def test_the_pack_for_this_board_and_release_is_found(self):
        pack = Pack(self, codename="trixie")
        result = self.find(pack, "trixie")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, pack.path), result.stderr)

    def test_a_pack_for_another_release_or_board_is_ignored(self):
        self.assertEqual(self.find(Pack(self, codename="bookworm"), "trixie").returncode, 1)
        self.assertEqual(self.find(Pack(self, platform="orangepi_zero2w"), "trixie").returncode, 1)


class SoundCardStep(unittest.TestCase):
    def fake_installer(self, exit_code):
        root = tempfile.mkdtemp(prefix="mfruit-sound-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "scripts"))
        log = os.path.join(root, "seen")
        with open(os.path.join(root, "scripts", "install.sh"), "w") as fp:
            fp.write(f'echo "platform=$WHISPLAY_PLATFORM apt=$(command -v apt-get) wget=$(command -v wget) '
                     f'script=$0" > {log}\n'
                     f"exit {exit_code}\n")
        return root, log

    def run_step(self, sound_dir, pack=""):
        return bash(DRIVER, f'SOUNDCARD_DIR="{sound_dir}"; PACK="{pack}"; REBUILD_AUDIO=1; REBOOT=0; '
                            'AUDIO_FAILED=0; install_audio raspberry_pi; echo "reboot=$REBOOT failed=$AUDIO_FAILED"')

    def test_with_a_pack_the_installer_gets_the_offline_shims(self):
        pack = Pack(self)
        sound, log = self.fake_installer(0)
        result = self.run_step(sound, pack.path)
        self.assertIn("reboot=1 failed=0", result.stdout, result.stderr)
        with open(log) as fp:
            seen = fp.read()
        self.assertIn("platform=raspberry_pi", seen)
        apt = seen.split("apt=")[1].split()[0]
        self.assertTrue(apt.endswith("/apt-get") and not apt.startswith("/usr/"), seen)
        self.assertEqual(os.path.dirname(apt), os.path.dirname(seen.split("wget=")[1].split()[0]))
        self.assertFalse(os.path.exists(os.path.dirname(apt)), "shims are removed afterwards")
        # It runs from a temporary copy (it builds in its own folder), removed afterwards.
        script = seen.split("script=")[1].split()[0]
        self.assertNotEqual(os.path.dirname(os.path.dirname(script)), sound)
        self.assertFalse(os.path.exists(script))

    def test_a_failed_sound_card_build_does_not_stop_the_installation(self):
        sound, _ = self.fake_installer(100)
        result = self.run_step(sound)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reboot=0 failed=1", result.stdout)
        self.assertIn("display, button and LED still work", result.stderr)


class PackContentsFollowWhisplay(unittest.TestCase):
    """make-offline-pack.sh repeats what the sound card installer fetches; keep them in step."""

    def setUp(self):
        with open(SOUND_INSTALLER) as fp:
            self.installer = fp.read()

    def test_downloads_are_the_ones_the_installer_makes(self):
        for platform in ("orangepi_zero2w", "orangepi_zero3w", "radxa_cubie_a7z"):
            urls = bash(MAKE_PACK, f"pack_urls {platform} 6.1.31-sun50iw9").stdout.split()
            self.assertTrue(urls, platform)
            for url in urls:
                if platform == "radxa_cubie_a7z":
                    self.assertIn("raw.githubusercontent.com/torvalds/linux/v${kernel_series}/sound/soc/codecs/"
                                  + os.path.basename(url), self.installer)
                elif platform == "orangepi_zero2w" and not url.endswith(".tar.xz"):
                    base, name = url.rsplit("/", 1)
                    self.assertIn(f'source_base="{base}"', self.installer)
                    self.assertIn(f'"$source_base/{name}"', self.installer)
                else:
                    self.assertIn(f'headers_url="{url}"', self.installer)

    def test_packages_include_what_the_installer_asks_apt_for(self):
        for platform in ("raspberry_pi", "orangepi_zero2w"):
            packages = bash(MAKE_PACK, f"pack_packages {platform} 6.1.31").stdout.split()
            for name in ("device-tree-compiler", "alsa-utils", "libasound2-plugins", "sox"):
                self.assertIn(name, packages)
                self.assertIn(name, self.installer)
        self.assertIn("raspberrypi-kernel-headers", bash(MAKE_PACK, "pack_packages raspberry_pi 6.1").stdout)
        self.assertIn("raspberrypi-kernel-headers", self.installer)
        for name in ("wget", "xz-utils", "make", "gcc", "kmod"):
            self.assertIn(name, bash(MAKE_PACK, "pack_packages orangepi_zero2w 6.1").stdout.split())
        # MFruit OS's own packages and the driver's are in every pack.
        packages = bash(MAKE_PACK, "pack_packages raspberry_pi 6.1").stdout.split()
        for name in ("python3-pil", "python3-venv", "network-manager", "python3-spidev", "python3-libgpiod"):
            self.assertIn(name, packages)


if __name__ == "__main__":
    unittest.main()
