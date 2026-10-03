"""Package preflight rejects broken releases without running package code."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT

SCRIPT = Path(ROOT) / "scripts/check-app.py"
TEMPLATE = Path(ROOT) / "templates/whisplay-app-template"
spec = importlib.util.spec_from_file_location("check_app", SCRIPT)
check_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_app)


class CheckAppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mfruit-preflight-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "app"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def change_manifest(self, **changes):
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest.update(changes)
        path.write_text(json.dumps(manifest))

    def errors(self):
        return "\n".join(check_app.check_package(self.root))

    def test_template_passes_without_running_hooks_or_creating_bytecode(self):
        marker = self.root / "hook-ran"
        for name in ("run.sh", "install.sh", "update.sh", "uninstall.sh", "test.sh"):
            (self.root / name).write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.root.rglob("__pycache__")), [])

    def test_malformed_manifest_and_missing_entrypoint_fail(self):
        self.change_manifest(entrypoint="../outside.sh")
        self.assertIn("safe relative path", self.errors())
        self.change_manifest(entrypoint="missing.sh")
        self.assertIn("does not exist", self.errors())
        (self.root / "manifest.json").write_text("{broken")
        self.assertIn("not valid JSON", self.errors())

    def test_app_must_own_back_and_escape_and_declare_smoke_test(self):
        self.change_manifest(exit_gesture="quad_click", disable_esc_exit_key=False, test="")
        errors = self.errors()
        self.assertIn("exit_gesture", errors)
        self.assertIn("disable_esc_exit_key", errors)
        self.assertIn("'test' hook", errors)

    def test_shell_hooks_need_execute_permission_lf_and_shebang(self):
        (self.root / "run.sh").chmod(0o644)
        (self.root / "test.sh").write_bytes(b"#!/bin/sh\r\nexit 0\r\n")
        (self.root / "install.sh").write_text("exit 0\n")
        errors = self.errors()
        self.assertIn("run.sh: hook must be executable", errors)
        self.assertIn("test.sh: hook must use LF", errors)
        self.assertIn("install.sh: hook needs", errors)

    def test_stale_or_missing_sdk_and_rules_fail(self):
        sdk = self.root / "app/mfruit_sdk"
        (sdk / "input.py").write_text("# stale copy\n")
        rules = self.root / check_app.RULES_PATH
        rules.write_text("# stale rules\n")
        self.assertIn("SDK differs", self.errors())
        self.assertIn("differs from MFruit OS docs/apps/APP_CONTRACT.md", self.errors())
        shutil.rmtree(sdk)
        rules.unlink()
        self.assertIn("missing vendored mfruit_sdk", self.errors())
        self.assertIn("missing .claude/rules/mfruit-os-app.md", self.errors())

    def test_extra_sdk_source_fails_but_vendored_marker_is_advisory(self):
        sdk = self.root / "app/mfruit_sdk"
        (sdk / "VENDORED").write_text("metadata may differ\n")
        self.assertEqual(self.errors(), "")
        (sdk / "obsolete.py").write_text("# stale leftover\n")
        self.assertIn("SDK differs", self.errors())

    def test_generated_artifacts_and_live_env_are_rejected_without_reading_secrets(self):
        (self.root / ".env").write_text("API_TOKEN=private-value-never-log\n")
        (self.root / ".env.local").write_text("API_TOKEN=private-value-never-log\n")
        (self.root / ".env.example").write_text("API_TOKEN=\n")
        (self.root / "app/__pycache__").mkdir()
        (self.root / "app/cache.pyc").write_bytes(b"bytecode")
        errors = self.errors()
        self.assertIn(".env: exclude", errors)
        self.assertIn(".env.local: exclude", errors)
        self.assertIn("__pycache__: exclude", errors)
        self.assertIn("cache.pyc: exclude", errors)
        self.assertNotIn(".env.example: exclude", errors)
        self.assertNotIn("private-value-never-log", errors)

    def test_example_env_files_and_git_metadata_are_allowed(self):
        for name in (".env.example", ".env.sample", ".env.template"):
            (self.root / name).write_text("API_TOKEN=\n")
        metadata = self.root / ".git"
        metadata.mkdir()
        (metadata / ".env").write_text("not package content\n")
        self.assertEqual(self.errors(), "")

    def test_missing_icon_and_escaping_hook_are_rejected(self):
        self.change_manifest(icon="missing.png")
        self.assertIn("declared icon must exist", self.errors())
        hook = self.root / "install.sh"
        hook.unlink()
        hook.symlink_to(SCRIPT)
        self.assertIn("install.sh: hook must be a file inside", self.errors())

    def test_cli_failure_exit_code(self):
        self.change_manifest(test="missing.sh")
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
