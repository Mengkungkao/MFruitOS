"""The system package devices update from (scripts/build-release.sh).

A device installs it in Settings > System > System update; this builds the
real archive from the checkout and installs it the way a device does.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from helpers import ROOT, TempHomeTestCase
from mfruitos import __version__
from mfruitos.system.settings import Settings
from mfruitos.updater import rollback
from mfruitos.updater.installer import Installer, InstallRequest


def install_items() -> list:
    text = open(os.path.join(ROOT, "scripts", "install.sh"), encoding="utf-8").read()
    found = re.search(r"for item in (.*?); do", text, re.S)
    return found.group(1).replace("\\\n", " ").split()


def release_items() -> list:
    text = open(os.path.join(ROOT, "scripts", "build-release.sh"), encoding="utf-8").read()
    found = re.search(r"^ITEMS=\((.*?)\)", text, re.S | re.M)
    return found.group(1).split()


class ReleaseContentsTests(unittest.TestCase):
    def test_release_holds_what_install_sh_installs(self):
        self.assertEqual(release_items(), install_items())

    def test_manifest_and_code_agree_on_the_version(self):
        with open(os.path.join(ROOT, "manifest.json"), encoding="utf-8") as fp:
            self.assertEqual(json.load(fp)["version"], __version__)


@unittest.skipUnless(shutil.which("git") and os.path.isdir(os.path.join(ROOT, ".git")),
                     "needs the git checkout")
class ReleasePackageTests(TempHomeTestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="mfrel-")
        subprocess.run(["bash", os.path.join(ROOT, "scripts", "build-release.sh"), cls.out],
                       check=True, capture_output=True, text=True, timeout=300)
        cls.archive = os.path.join(cls.out, f"mfruit-os-{__version__}.tar.gz")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_archive_is_one_folder_without_caches_and_matches_its_checksum(self):
        with tarfile.open(self.archive) as tar:
            names = tar.getnames()
        self.assertTrue(all(n == "mfruit-os" or n.startswith("mfruit-os/") for n in names))
        self.assertIn("mfruit-os/manifest.json", names)
        self.assertIn("mfruit-os/mfruitos/__main__.py", names)
        self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])
        self.assertFalse([n for n in names if n.startswith("mfruit-os/tests/")])
        with open(self.archive + ".sha256", encoding="utf-8") as fp:
            expected = fp.read().split()[0]
        with open(self.archive, "rb") as fp:
            self.assertEqual(hashlib.sha256(fp.read()).hexdigest(), expected)

    def test_a_device_installs_it_as_a_system_update(self):
        old = os.path.join(self.paths.system_dir, "versions", "1.4.0-local20261010235737")
        os.makedirs(old)
        with open(os.path.join(old, "manifest.json"), "w", encoding="utf-8") as fp:
            json.dump({"id": "mfruit-os", "type": "system", "name": "mFruit OS",
                       "version": "1.4.0-local20261010235737",
                       "entrypoint": "mfruitos/__main__.py"}, fp)
        os.symlink("versions/1.4.0-local20261010235737", os.path.join(self.paths.system_dir, "current"))
        with open(self.archive + ".sha256", encoding="utf-8") as fp:
            expected = fp.read().split()[0]
        installer = Installer(self.paths, "1.4.0", Settings(None), None)
        result = installer.run(InstallRequest(repository="", local_path=self.archive,
                                              expected_sha256=expected, mode="system"))
        self.assertTrue(result.restart_required)
        current = rollback.current_target(self.paths.system_dir)
        self.assertIn(f"{__version__}-", current)
        with open(os.path.join(current, "manifest.json"), encoding="utf-8") as fp:
            self.assertEqual(json.load(fp)["version"], __version__)


if __name__ == "__main__":
    unittest.main()
