"""Updates for apps that were installed as git checkouts (e.g. ~/WalkieTalkie).

Many existing Whisplay apps are cloned from GitHub and registered with the
daemon directly, without releases. For those, MFruit OS can track the
checked-out branch. This is labelled as *commit tracking* in the UI — it is
not a version number, and semver releases are always preferred when a repo
publishes them.

Safety rules:
* only a clean working tree is updated (tracked files unmodified);
* only fast-forward merges (never rewrites local history);
* git never prompts (GIT_TERMINAL_PROMPT=0, ssh BatchMode) and has timeouts;
* the previous commit is recorded, and a failed update is reset back to it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from mfruitos.apps.manifest import ManifestError, normalize_repository
from mfruitos.system.settings import atomic_write_json

log = logging.getLogger("mfruitos.updater.git")

GIT_TIMEOUT = 25
FETCH_TIMEOUT = 300


class GitError(Exception):
    pass


@dataclass
class Checkout:
    path: str
    remote: str            # as configured (may be ssh)
    repository: str        # canonical https URL, or "" if not GitHub
    branch: str
    head: str
    dirty: bool

    @property
    def short(self) -> str:
        return self.head[:7]

    @property
    def label(self) -> str:
        return f"{self.branch} @ {self.short}"


def _env() -> dict:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true",
                "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=10", "LC_ALL": "C"})
    return env


def git(path: str, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    if shutil.which("git") is None:
        raise GitError("git is not installed")
    try:
        result = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True,
                                timeout=timeout, env=_env(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out") from exc
    except OSError as exc:
        raise GitError(str(exc)) from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise GitError(message[-1] if message else f"git {args[0]} failed")
    return result.stdout.strip()


def _github_https(remote: str) -> str:
    match = re.match(r"^git@github\.com:(.+?)(?:\.git)?/?$", remote)
    if match:
        remote = f"https://github.com/{match.group(1)}"
    remote = re.sub(r"^ssh://git@github\.com/", "https://github.com/", remote)
    try:
        return normalize_repository(remote)
    except ManifestError:
        return ""


def inspect(path: str) -> Checkout | None:
    """Describe the git checkout at ``path`` (must be the work-tree root)."""
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        return None
    try:
        remote = git(path, "remote", "get-url", "origin")
        branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
        head = git(path, "rev-parse", "HEAD")
        dirty = bool(git(path, "status", "--porcelain", "--untracked-files=no"))
    except GitError as exc:
        log.debug("%s is not a usable checkout: %s", path, exc)
        return None
    return Checkout(path, remote, _github_https(remote), branch, head, dirty)


def remote_head(checkout: Checkout) -> str:
    """Commit at the tip of the tracked branch, via ``git ls-remote`` (uses the
    checkout's own credentials, so private repos with SSH keys work too)."""
    if checkout.branch == "HEAD":
        raise GitError("checkout is on a detached HEAD")
    out = git(checkout.path, "ls-remote", "origin", f"refs/heads/{checkout.branch}")
    if not out:
        raise GitError(f"branch {checkout.branch} not found on origin")
    return out.split()[0]


def is_ancestor(path: str, older: str, newer: str) -> bool:
    try:
        git(path, "merge-base", "--is-ancestor", older, newer)
        return True
    except GitError:
        return False


def has_object(path: str, sha: str) -> bool:
    try:
        git(path, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except GitError:
        return False


def check(checkout: Checkout) -> dict:
    """Return {"remote": sha, "update": bool, "state": str}."""
    remote = remote_head(checkout)
    if remote == checkout.head:
        return {"remote": remote, "update": False, "state": "up to date"}
    if has_object(checkout.path, remote) and is_ancestor(checkout.path, remote, checkout.head):
        return {"remote": remote, "update": False, "state": "local is ahead"}
    return {"remote": remote, "update": True, "state": "new commits"}


def update(checkout: Checkout, state_dir: str, app_id: str, progress=None) -> str:
    """Fast-forward the checkout to origin/<branch>; returns the new commit."""
    report = progress or (lambda step, detail, fraction=None: None)
    report("check", "Checking working tree", None)
    current = inspect(checkout.path)
    if current is None:
        raise GitError("folder is no longer a git checkout")
    if current.dirty:
        raise GitError("local changes present; commit or discard them first")
    report("backup", f"Recording {current.short}", None)
    record_backup(state_dir, app_id, current)
    report("download", "git fetch", None)
    git(current.path, "fetch", "--quiet", "origin", current.branch, timeout=FETCH_TIMEOUT)
    report("verify", "Checking fast-forward", None)
    target = git(current.path, "rev-parse", "FETCH_HEAD")
    if not is_ancestor(current.path, current.head, target):
        raise GitError("branch has diverged from origin; update manually")
    report("install", "Fast-forward", None)
    try:
        git(current.path, "merge", "--ff-only", "--quiet", target)
        report("test", "Checking files", None)
        _smoke_test(current.path, current.head, target)
    except GitError as exc:
        log.error("Update of %s failed (%s); resetting to %s", app_id, exc, current.short)
        git(current.path, "reset", "--hard", "--quiet", current.head)
        raise GitError(f"{exc} (rolled back to {current.short})") from exc
    report("activate", f"Now at {target[:7]}", None)
    log.info("Updated %s from %s to %s", app_id, current.short, target[:7])
    return target


def _smoke_test(path: str, old: str, new: str) -> None:
    """Byte-compile changed Python files so a syntax error triggers a rollback."""
    changed = git(path, "diff", "--name-only", "--diff-filter=AM", old, new, "--", "*.py")
    files = [f for f in changed.splitlines() if f][:300]
    if not files:
        return
    for relative in files:
        try:
            with open(os.path.join(path, relative), "rb") as fp:
                compile(fp.read(), relative, "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            raise GitError(f"{relative} does not compile: {exc}"[:120]) from exc
        except OSError as exc:
            raise GitError(f"cannot read {relative}: {exc}") from exc


def record_backup(state_dir: str, app_id: str, checkout: Checkout) -> None:
    path = os.path.join(state_dir, "git-backups", f"{app_id}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_json(path, {"app_id": app_id, "path": checkout.path, "branch": checkout.branch,
                             "previous": checkout.head, "at": time.time()})


def previous_commit(state_dir: str, app_id: str) -> str | None:
    try:
        with open(os.path.join(state_dir, "git-backups", f"{app_id}.json"), "r") as fp:
            data = json.load(fp)
        return data.get("previous") or None
    except (OSError, ValueError):
        return None


def rollback(checkout: Checkout, state_dir: str, app_id: str) -> str:
    previous = previous_commit(state_dir, app_id)
    if not previous:
        raise GitError("no previous commit recorded")
    if checkout.dirty:
        raise GitError("local changes present; commit or discard them first")
    if not has_object(checkout.path, previous):
        raise GitError("previous commit is no longer available")
    git(checkout.path, "reset", "--hard", "--quiet", previous)
    record_backup(state_dir, app_id, checkout)  # allows undoing the rollback
    log.info("Rolled %s back to %s", app_id, previous[:7])
    return previous
