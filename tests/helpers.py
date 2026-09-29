"""Shared test helpers."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mfruitos.paths import Paths  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TempHomeTestCase(unittest.TestCase):
    """Gives each test an isolated ~/.whisplay-os and ~/.whisplay-daemon."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mfruit-test-")
        self.paths = Paths(home=os.path.join(self.tmp, "os"),
                           daemon_home=os.path.join(self.tmp, "daemon"))
        self.paths.ensure()
        os.makedirs(self.paths.daemon_apps_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_json(self, path: str, data) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        return path


def make_package(directory: str, app_id: str = "weather", version: str = "1.0.0",
                 install_sh: str | None = "#!/bin/sh\nexit 0\n", test_sh: str | None = None,
                 extra_manifest: dict | None = None, run_sh: str = "#!/bin/sh\necho run\n") -> str:
    """Create a valid app package directory and return its path."""
    os.makedirs(os.path.join(directory, "assets"), exist_ok=True)
    manifest = {
        "id": app_id, "name": app_id.title(), "version": version,
        "description": f"{app_id} app", "entrypoint": "run.sh",
        "repository": f"https://github.com/example/whisplay-{app_id}",
    }
    if test_sh is not None:
        manifest["test"] = "test.sh"
    manifest.update(extra_manifest or {})
    with open(os.path.join(directory, "manifest.json"), "w") as fp:
        json.dump(manifest, fp)
    files = {"run.sh": run_sh}
    if install_sh is not None:
        files["install.sh"] = install_sh
    if test_sh is not None:
        files["test.sh"] = test_sh
    for name, body in files.items():
        path = os.path.join(directory, name)
        with open(path, "w") as fp:
            fp.write(body)
        os.chmod(path, 0o755)
    return directory
