import json
import os
import random
import unittest

from helpers import ROOT
from PIL import Image

from mfruitos import __version__
from mfruitos.apps.manifest import load_manifest
from mfruitos.launcher.navigation.router import Router
from mfruitos.launcher.ui.rgb565 import from_rgb565, to_rgb565


def reference_rgb565(image):
    out = bytearray()
    for r, g, b in image.getdata():
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += bytes([value >> 8, value & 0xFF])
    return bytes(out)


class Rgb565Tests(unittest.TestCase):
    def test_matches_reference_formula(self):
        rng = random.Random(7)
        image = Image.new("RGB", (40, 30))
        image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                       for _ in range(40 * 30)])
        self.assertEqual(to_rgb565(image), reference_rgb565(image))

    def test_known_colours_and_round_trip(self):
        image = Image.new("RGB", (3, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        data = to_rgb565(image)
        self.assertEqual(data.hex(), "f80007e0001f")
        self.assertEqual(list(from_rgb565(data, 3, 1).getdata()),
                         [(255, 0, 0), (0, 255, 0), (0, 0, 255)])


class RouterTests(unittest.TestCase):
    class S:
        def __init__(self):
            self.events = []

        def on_show(self):
            self.events.append("show")

        def on_hide(self):
            self.events.append("hide")

    def test_root_cannot_be_popped(self):
        router = Router()
        root, child = self.S(), self.S()
        router.set_root(root)
        router.push(child)
        self.assertTrue(router.pop())
        self.assertFalse(router.pop())
        self.assertIs(router.top, root)
        self.assertEqual(child.events, ["show", "hide"])


class PackagingTests(unittest.TestCase):
    def test_os_manifest_matches_version(self):
        manifest = load_manifest(ROOT)
        self.assertEqual(manifest.version, __version__)
        self.assertEqual(manifest.type, "system")

    def test_template_app_is_valid(self):
        manifest = load_manifest(os.path.join(ROOT, "templates", "whisplay-app-template"))
        self.assertEqual(manifest.id, "hello-whisplay")

    def test_changelog_mentions_version(self):
        with open(os.path.join(ROOT, "CHANGELOG.md")) as fp:
            self.assertIn(__version__, fp.read())


class SelfTest(unittest.TestCase):
    def test_every_screen_renders(self):
        from mfruitos.launcher.preview import run_preview
        self.assertEqual(run_preview(None), 0)


if __name__ == "__main__":
    unittest.main()
