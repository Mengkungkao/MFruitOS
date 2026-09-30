import os
import shutil
import subprocess
import unittest

from helpers import TempHomeTestCase
from mfruitos.updater import gittrack


def run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


@unittest.skipIf(shutil.which("git") is None, "git not installed")
class GitTrackTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.origin = os.path.join(self.tmp, "origin.git")
        self.dev = os.path.join(self.tmp, "dev")
        self.app = os.path.join(self.tmp, "app")
        run(self.tmp, "init", "--bare", "-b", "main", self.origin)
        run(self.tmp, "clone", self.origin, self.dev)
        self.commit("main.py", "print('v1')\n", "v1")
        run(self.dev, "push", "origin", "HEAD:main")
        run(self.tmp, "clone", self.origin, self.app)

    def commit(self, name, content, message):
        with open(os.path.join(self.dev, name), "w") as fp:
            fp.write(content)
        run(self.dev, "add", name)
        run(self.dev, "commit", "-m", message)

    def push(self, name, content, message):
        self.commit(name, content, message)
        run(self.dev, "push", "origin", "HEAD:main")

    def test_inspect_and_up_to_date(self):
        checkout = gittrack.inspect(self.app)
        self.assertEqual(checkout.branch, "main")
        self.assertFalse(checkout.dirty)
        self.assertFalse(gittrack.check(checkout)["update"])
        self.assertIsNone(gittrack.inspect(self.tmp))

    def test_update_fast_forward_and_rollback(self):
        self.push("main.py", "print('v2')\n", "v2")
        checkout = gittrack.inspect(self.app)
        self.assertTrue(gittrack.check(checkout)["update"])
        old = checkout.head
        gittrack.update(checkout, self.paths.state_dir, "demo")
        after = gittrack.inspect(self.app)
        self.assertNotEqual(after.head, old)
        self.assertFalse(gittrack.check(after)["update"])
        gittrack.rollback(after, self.paths.state_dir, "demo")
        self.assertEqual(gittrack.inspect(self.app).head, old)

    def test_nested_app_and_worktree_are_detected(self):
        nested = os.path.join(self.app, "nested")
        os.makedirs(nested)
        self.assertEqual(gittrack.inspect(nested).path, self.app)
        linked = os.path.join(self.tmp, "linked")
        run(self.app, "worktree", "add", "-b", "linked", linked)
        self.assertEqual(gittrack.inspect(linked).path, linked)

    def test_noop_and_failed_updates_preserve_previous_commit(self):
        original = gittrack.inspect(self.app).head
        self.push("main.py", "print('v2')\n", "v2")
        gittrack.update(gittrack.inspect(self.app), self.paths.state_dir, "demo")
        gittrack.update(gittrack.inspect(self.app), self.paths.state_dir, "demo")
        self.assertEqual(gittrack.previous_commit(self.paths.state_dir, "demo"), original)
        self.push("main.py", "def broken(:\n", "broken")
        with self.assertRaises(gittrack.GitError):
            gittrack.update(gittrack.inspect(self.app), self.paths.state_dir, "demo")
        self.assertEqual(gittrack.previous_commit(self.paths.state_dir, "demo"), original)
        gittrack.rollback(gittrack.inspect(self.app), self.paths.state_dir, "demo")
        self.assertEqual(gittrack.inspect(self.app).head, original)

    def test_dirty_tree_refused(self):
        self.push("main.py", "print('v2')\n", "v2")
        with open(os.path.join(self.app, "main.py"), "w") as fp:
            fp.write("local edit\n")
        checkout = gittrack.inspect(self.app)
        with self.assertRaises(gittrack.GitError):
            gittrack.update(checkout, self.paths.state_dir, "demo")
        with open(os.path.join(self.app, "main.py")) as fp:
            self.assertEqual(fp.read(), "local edit\n")

    def test_syntax_error_rolls_back(self):
        self.push("main.py", "def broken(:\n", "broken")
        checkout = gittrack.inspect(self.app)
        with self.assertRaises(gittrack.GitError) as ctx:
            gittrack.update(checkout, self.paths.state_dir, "demo")
        self.assertIn("rolled back", str(ctx.exception))
        self.assertEqual(gittrack.inspect(self.app).head, checkout.head)

    def test_diverged_refused(self):
        self.push("main.py", "print('remote')\n", "remote")
        with open(os.path.join(self.app, "local.txt"), "w") as fp:
            fp.write("x")
        run(self.app, "add", "local.txt")
        run(self.app, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "local")
        checkout = gittrack.inspect(self.app)
        with self.assertRaises(gittrack.GitError) as ctx:
            gittrack.update(checkout, self.paths.state_dir, "demo")
        self.assertIn("diverged", str(ctx.exception))

    def test_github_remote_normalised(self):
        self.assertEqual(gittrack._github_https("git@github.com:Mengkungkao/Messenger.git"),
                         "https://github.com/Mengkungkao/Messenger")
        self.assertEqual(gittrack._github_https("https://github.com/a/b.git"), "https://github.com/a/b")
        self.assertEqual(gittrack._github_https("/local/path"), "")


if __name__ == "__main__":
    unittest.main()
