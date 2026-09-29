"""Shell helpers: mfruit-run (app wrapper) and boot-guard.sh (system rollback)."""

import json
import os
import subprocess
import unittest

from helpers import ROOT, TempHomeTestCase

SCRIPTS = os.path.join(ROOT, "scripts")


class WrapperTests(TempHomeTestCase):
    def run_wrapper(self, app_id):
        env = dict(os.environ, WHISPLAY_OS_HOME=self.paths.home)
        return subprocess.run(["sh", os.path.join(SCRIPTS, "mfruit-run"), app_id], env=env,
                              capture_output=True, text=True, timeout=20)

    def make_app(self, app_id, body, entry="run.sh"):
        version = os.path.join(self.paths.app_root(app_id), "versions", "1.0.0-x")
        os.makedirs(version)
        with open(os.path.join(version, entry), "w") as fp:
            fp.write(body)
        os.chmod(os.path.join(version, entry), 0o755)
        with open(os.path.join(version, ".mfruit-entrypoint"), "w") as fp:
            fp.write(entry + "\n")
        os.symlink("versions/1.0.0-x", os.path.join(self.paths.app_root(app_id), "current"))

    def state(self, app_id):
        with open(os.path.join(self.paths.runs_dir, f"{app_id}.json")) as fp:
            return json.load(fp)

    def test_records_exit_code_env_and_log(self):
        self.make_app("demo", '#!/bin/sh\necho "id=$WHISPLAY_APP_ID data=$WHISPLAY_OS_APP_DATA"\nexit 3\n')
        result = self.run_wrapper("demo")
        self.assertEqual(result.returncode, 3)
        state = self.state("demo")
        self.assertEqual((state["state"], state["exit_code"]), ("exited", 3))
        with open(self.paths.app_log("demo")) as fp:
            log = fp.read()
        self.assertIn("id=demo", log)
        self.assertIn(os.path.join(self.paths.app_root("demo"), "data"), log)

    def test_python_entrypoint_without_exec_bit(self):
        self.make_app("pyapp", "import sys; sys.exit(0)\n", entry="main.py")
        os.chmod(os.path.join(self.paths.app_root("pyapp"), "current", "main.py"), 0o644)
        self.assertEqual(self.run_wrapper("pyapp").returncode, 0)

    def test_rejects_bad_ids_and_missing_apps(self):
        self.assertEqual(self.run_wrapper("../etc").returncode, 64)
        self.assertEqual(self.run_wrapper("missing").returncode, 127)
        self.assertEqual(self.state("missing")["exit_code"], 127)

    def test_rejects_traversal_entrypoint(self):
        self.make_app("evil", "#!/bin/sh\nexit 0\n")
        with open(os.path.join(self.paths.app_root("evil"), "current", ".mfruit-entrypoint"), "w") as fp:
            fp.write("../../../bin/sh\n")
        self.assertEqual(self.run_wrapper("evil").returncode, 65)


class BootGuardTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.system = self.paths.system_dir
        for name in ("1.0.0-a", "1.1.0-b"):
            os.makedirs(os.path.join(self.system, "versions", name))
        os.symlink("versions/1.1.0-b", os.path.join(self.system, "current"))
        self.pending = os.path.join(self.paths.state_dir, "pending_system_update.env")
        with open(self.pending, "w") as fp:
            fp.write(f"PREVIOUS_DIR={self.system}/versions/1.0.0-a\nATTEMPTS=0\n")

    def guard(self):
        env = dict(os.environ, WHISPLAY_OS_HOME=self.paths.home)
        return subprocess.run(["sh", os.path.join(SCRIPTS, "boot-guard.sh")], env=env,
                              capture_output=True, text=True, timeout=10)

    def current(self):
        return os.readlink(os.path.join(self.system, "current"))

    def test_rolls_back_after_repeated_failures(self):
        for _ in range(3):
            self.assertEqual(self.guard().returncode, 0)
            self.assertEqual(self.current(), "versions/1.1.0-b")
        self.guard()
        self.assertEqual(self.current(), "versions/1.0.0-a")
        self.assertFalse(os.path.exists(self.pending))
        self.assertTrue(os.path.exists(os.path.join(self.paths.state_dir, "system_rollback.env")))

    def test_no_pending_is_noop(self):
        os.remove(self.pending)
        self.assertEqual(self.guard().returncode, 0)
        self.assertEqual(self.current(), "versions/1.1.0-b")

    def test_refuses_rollback_outside_system_dir(self):
        with open(self.pending, "w") as fp:
            fp.write("PREVIOUS_DIR=/etc\nATTEMPTS=9\n")
        self.guard()
        self.assertEqual(self.current(), "versions/1.1.0-b")


if __name__ == "__main__":
    unittest.main()
