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



class LaunchGateTests(TempHomeTestCase):
    """mfruit-run as the launch gate (root cause RC2)."""

    def setUp(self):
        super().setUp()
        WrapperTests.make_app(self, "demo", "#!/bin/sh\necho ran >> \"$WHISPLAY_OS_APP_DATA/ran\"\nexit 0\n")
        self.lock = None

    def tearDown(self):
        if self.lock:
            self.lock.close()
        super().tearDown()

    def hold_launcher_lock(self):
        import fcntl
        self.lock = open(os.path.join(self.paths.state_dir, "launcher.lock"), "a+")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX)

    def ticket(self, session="s1", ttl=20):
        import time
        os.makedirs(os.path.join(self.paths.state_dir, "tickets"), exist_ok=True)
        with open(os.path.join(self.paths.state_dir, "tickets", "demo"), "w") as fp:
            fp.write(f"{session} {int(time.time()) + ttl}\n")

    def run_gate(self):
        return WrapperTests.run_wrapper(self, "demo")

    def ran(self):
        path = os.path.join(self.paths.app_root("demo"), "data", "ran")
        return open(path).read().count("ran") if os.path.exists(path) else 0

    def gate_log(self):
        path = os.path.join(self.paths.logs_dir, "launch-gate.log")
        return open(path).read() if os.path.exists(path) else ""

    def test_denied_without_ticket_while_launcher_runs(self):
        self.hold_launcher_lock()
        self.assertEqual(self.run_gate().returncode, 0)
        self.assertEqual(self.ran(), 0)
        self.assertIn("DENIED demo", self.gate_log())

    def test_ticket_allows_exactly_one_start(self):
        self.hold_launcher_lock()
        self.ticket("sess42")
        self.run_gate()
        self.assertEqual(self.ran(), 1)
        self.assertEqual(WrapperTests.state(self, "demo")["session"], "sess42")
        self.run_gate()                            # the ticket was consumed
        self.assertEqual(self.ran(), 1)
        self.assertIn("DENIED demo", self.gate_log())

    def test_expired_ticket_denied(self):
        self.hold_launcher_lock()
        self.ticket(ttl=-5)
        self.run_gate()
        self.assertEqual(self.ran(), 0)
        self.assertIn("expired", self.gate_log())

    def test_open_policy_and_no_launcher_allow(self):
        self.run_gate()                            # no MFruit OS running: legacy behaviour
        self.hold_launcher_lock()
        with open(os.path.join(self.paths.state_dir, "launch-policy"), "w") as fp:
            fp.write("open\n")                     # daemon-desktop mode
        self.run_gate()
        self.assertEqual(self.ran(), 2)

    def test_adopted_app_runs_its_original_command(self):
        adopted = os.path.join(self.paths.home, "adopted", "legacy")
        os.makedirs(adopted)
        workdir = os.path.join(self.tmp, "legacy-app")
        os.makedirs(workdir)
        with open(os.path.join(adopted, "command"), "w") as fp:
            fp.write("echo from-legacy > here.txt\n")
        with open(os.path.join(adopted, "cwd"), "w") as fp:
            fp.write(workdir + "\n")
        self.assertEqual(WrapperTests.run_wrapper(self, "legacy").returncode, 0)
        with open(os.path.join(workdir, "here.txt")) as fp:
            self.assertEqual(fp.read().strip(), "from-legacy")


if __name__ == "__main__":
    unittest.main()
