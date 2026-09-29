"""App lifecycle: registration with the daemon, launch bookkeeping, stop.

Lifecycle: Installed -> Registered -> Enabled -> Available -> Launch ->
Foreground -> (Background) -> Exit.

OS-managed apps are registered with a launch command that runs
``~/.whisplay-os/bin/mfruit-run <app_id>``. The wrapper runs the app's
entrypoint from ``current/``, appends output to ``logs/<app_id>.log`` and
records pid / exit code in ``state/runs/<app_id>.json`` — the daemon does not
report exit codes, and the launcher needs them for "failed to start" screens.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import time

from mfruitos import OS_APP_ID, OS_NAME
from mfruitos.apps.registry import RUN_WRAPPER_NAME, AppEntry
from mfruitos.daemon.client import DaemonError, WhisplayDaemonClient
from mfruitos.logs import rotate_if_large
from mfruitos.paths import Paths

log = logging.getLogger("mfruitos.lifecycle")

OS_PRIORITY = 900


class AppLifecycle:
    def __init__(self, client: WhisplayDaemonClient, paths: Paths, python: str = "python3"):
        self.client = client
        self.paths = paths
        self.python = python

    # -------------------------------------------------------- registration
    def wrapper_command(self, app_id: str) -> str:
        return f"{shlex.quote(os.path.join(self.paths.bin_dir, RUN_WRAPPER_NAME))} {app_id}"

    def registration_for(self, entry: AppEntry) -> dict:
        env = dict(entry.env)
        env["WHISPLAY_APP_ID"] = entry.id
        return {
            "icon": (entry.icon_text or entry.name[:2]).upper()[:3],
            "launch_command": self.wrapper_command(entry.id),
            "cwd": os.path.join(self.paths.app_root(entry.id), "current"),
            "env": env,
            "exit_gesture": entry.exit_gesture,
            "priority": entry.priority,
            "use_daemon_default_log": False,
            "persist": True,
            "disable_esc_exit_key": entry.disable_esc_exit_key,
        }

    def register(self, entry: AppEntry) -> bool:
        try:
            self.client.register_app(entry.id, entry.name, **self.registration_for(entry))
        except DaemonError as exc:
            log.warning("Could not register %s with the daemon: %s", entry.id, exc)
            return False
        log.info("Registered %s with whisplay-daemon", entry.id)
        return True

    def unregister(self, app_id: str, name: str) -> None:
        """The daemon has no unregister command. ``persist: false`` makes it delete
        its JSON file, and an empty launch command makes a stale in-memory entry
        harmless until the daemon restarts."""
        try:
            self.client.register_app(app_id, f"{name} (removed)", launch_command="",
                                     persist=False, priority=-1000)
        except DaemonError as exc:
            log.warning("Could not unregister %s: %s", app_id, exc)

    def sync_registrations(self, managed: list[AppEntry]) -> int:
        """Make sure every healthy OS-managed app is known to the daemon."""
        count = 0
        for entry in managed:
            if entry.broken:
                continue
            if not entry.registered or not self._registration_file_ok(entry):
                count += int(self.register(entry))
        return count

    def _registration_file_ok(self, entry: AppEntry) -> bool:
        path = os.path.join(self.paths.daemon_apps_dir, f"{entry.id}.json")
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            return False
        return data.get("launch_command") == self.wrapper_command(entry.id)

    def register_os(self, package_dir: str) -> bool:
        """Register MFruit OS itself so the daemon desktop can summon it."""
        ctl = os.path.join(self.paths.bin_dir, "mfruitctl")
        try:
            self.client.register_app(
                OS_APP_ID, OS_NAME, icon="OS",
                launch_command=f"{shlex.quote(ctl)} summon",
                cwd=package_dir, exit_gesture="none", priority=OS_PRIORITY,
                use_daemon_default_log=True, persist=True, disable_esc_exit_key=False)
        except DaemonError as exc:
            log.warning("Could not register %s: %s", OS_APP_ID, exc)
            return False
        return True

    # ------------------------------------------------------------- running
    def run_state_path(self, app_id: str) -> str:
        return os.path.join(self.paths.runs_dir, f"{app_id}.json")

    def run_state(self, app_id: str) -> dict | None:
        try:
            with open(self.run_state_path(app_id), "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def prepare_launch(self, entry: AppEntry) -> None:
        if entry.kind != "os":
            return
        rotate_if_large(self.paths.app_log(entry.id))
        try:
            os.remove(self.run_state_path(entry.id))
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Cannot clear run state for %s: %s", entry.id, exc)

    def last_exit(self, entry: AppEntry) -> dict | None:
        """Exit record written by mfruit-run, if this app has one."""
        if entry.kind != "os":
            return None
        state = self.run_state(entry.id)
        if state and state.get("state") == "exited":
            return state
        return None

    def log_path(self, entry: AppEntry) -> str:
        if entry.kind == "os":
            return self.paths.app_log(entry.id)
        return self.paths.daemon_app_log

    def request_stop(self, entry: AppEntry) -> bool:
        try:
            self.client.request_exit(entry.id)
        except DaemonError as exc:
            log.warning("Exit request for %s failed: %s", entry.id, exc)
            return False
        log.info("Requested %s to exit", entry.id)
        return True

    def force_stop(self, entry: AppEntry, grace: float = 2.0) -> bool:
        """SIGTERM then SIGKILL the app's process group (OS-managed apps only).

        The pid is only trusted if /proc confirms it is our wrapper for this
        app. The daemon starts launch commands with ``start_new_session=True``
        (via ``sh -c``), so the wrapper's process group is that session's
        group; it is never our own group."""
        if entry.kind != "os":
            return False
        state = self.run_state(entry.id) or {}
        pid = state.get("pid")
        if not isinstance(pid, int) or pid <= 1 or not self._is_wrapper(pid, entry.id):
            log.info("No running wrapper found for %s", entry.id)
            return False
        try:
            pgid = os.getpgid(pid)
            if pgid <= 1 or pgid == os.getpgrp() or os.getsid(pid) != pgid:
                log.warning("Refusing to kill %s: unexpected process group %d", entry.id, pgid)
                return False
            log.warning("Force-stopping %s (pgid %d)", entry.id, pgid)
            os.killpg(pgid, signal.SIGTERM)
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if not self._is_wrapper(pid, entry.id):
                    return True
                time.sleep(0.1)
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError as exc:
            log.error("Not allowed to stop %s: %s", entry.id, exc)
            return False
        return True

    @staticmethod
    def _is_wrapper(pid: int, app_id: str) -> bool:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fp:
                args = fp.read().split(b"\x00")
        except OSError:
            return False
        joined = b" ".join(args)
        return RUN_WRAPPER_NAME.encode() in joined and app_id.encode() in args
