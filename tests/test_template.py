"""The app template (templates/whisplay-app-template) is a correct mFruit OS app.

It is what new apps start from, so it must follow docs/apps/APP_CONTRACT.md: input
through the SDK controller, mFruit OS's chrome, Esc and 4 clicks as the
app's own "back".
"""

import json
import os
import sys
import tempfile
import unittest

from helpers import ROOT

TEMPLATE = os.path.join(ROOT, "templates", "whisplay-app-template")
APP = os.path.join(TEMPLATE, "app")


class FakeApp:
    app_id = "hello-whisplay"
    has_focus = True

    def __init__(self):
        self.frames = []

    def show(self, image):
        self.frames.append(image)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, APP)
        self.addCleanup(sys.path.remove, APP)
        for name in [n for n in sys.modules if n in ("main", "whisplay_app")
                     or n.startswith("mfruit_sdk")]:
            del sys.modules[name]
        import main
        self.main = main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        main.COUNT_FILE = os.path.join(tmp.name, "count.txt")
        main.DATA_DIR = tmp.name
        self.app = FakeApp()
        self.counter = main.Counter(self.app)

    def key(self, name, code, action=1):
        from mfruit_sdk.keys import KeyEvent
        self.counter.input.key_event(KeyEvent("key", name, action, code))

    def test_the_manifest_owns_its_gestures_and_esc(self):
        with open(os.path.join(TEMPLATE, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["exit_gesture"], "none")
        self.assertTrue(manifest["disable_esc_exit_key"])

    def test_keys_count_reset_and_leave(self):
        start = self.counter.count
        self.key("down", 108)
        self.key("down", 108)
        self.key("up", 103)
        self.assertEqual(self.counter.count, start + 1)
        self.key("enter", 28)
        self.assertEqual(self.counter.count, 0)
        self.assertFalse(self.counter.done.is_set())
        self.key("escape", 1)
        self.assertTrue(self.counter.done.is_set())
        self.assertTrue(self.app.frames)

    def test_keys_are_ignored_without_the_screen(self):
        self.app.has_focus = False
        self.key("enter", 28)
        self.key("escape", 1)
        self.assertFalse(self.counter.done.is_set())

    def test_the_screen_has_mfruit_os_chrome(self):
        from mfruit_sdk.status import Status
        image = self.main.render(3, Status(3, 50, False))
        self.assertEqual(image.size, (240, 280))
        self.assertGreater(len(image.crop((0, 0, 240, 32)).getcolors(10000)), 5)
        self.assertGreater(len(image.crop((0, 252, 240, 272)).getcolors(10000)), 5)

    def test_the_sdk_copy_is_current(self):
        import filecmp
        source = os.path.join(ROOT, "mfruitos", "sdk")
        for folder, _, files in os.walk(source):
            if "__pycache__" in folder:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                relative = os.path.relpath(os.path.join(folder, name), source)
                copy = os.path.join(APP, "mfruit_sdk", relative)
                self.assertTrue(filecmp.cmp(os.path.join(folder, name), copy, shallow=False),
                                f"{relative} differs: run scripts/sdk-sync.sh {APP}")


if __name__ == "__main__":
    unittest.main()
