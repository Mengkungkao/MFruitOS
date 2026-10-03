"""App lifecycle: registration with the daemon, launch bookkeeping, stop.

Lifecycle: Installed -> Registered -> Enabled -> Available -> Launch ->
Foreground -> (Background) -> Exit.

Every app the daemon can start is registered with the launch command
``~/.whisplay-os/bin/mfruit-run <app_id>``: OS-managed packages, and daemon
apps MFruit OS has *adopted* (their original registration is saved in
``~/.whisplay-os/adopted/<id>/`` and restored on uninstall).

``mfruit-run`` is the launch gate. While MFruit OS runs it starts an app only
with a one-shot ticket (``state/tickets/<app_id>`` = "<session> <expiry>")
that MFruit OS writes just before asking the daemon to launch that app. The
daemon's own desktop keeps the button while an app starts up; without the
gate a press there could start a second app (root cause RC2). Without a
running MFruit OS the gate is open, so the daemon desktop works as before.

The wrapper records pid, session and exit code in ``state/runs/<app_id>.json``
— the daemon reports neither — so failures are attributed to the right session.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import signal
import time

from mfruitos import OS_APP_ID, OS_NAME
from mfruitos.apps.registry import REMOVED_SUFFIX, RUN_WRAPPER_NAME, AppEntry, is_wrapper_command
from mfruitos.daemon.client import DaemonError, DaemonRequestError, WhisplayDaemonClient
from mfruitos.logs import rotate_if_large
from mfruitos.paths import Paths

log = logging.getLogger("mfruitos.lifecycle")

OS_PRIORITY = 900
TICKET_TTL_SEC = 20
# Registration fields copied verbatim when an app is adopted.
ADOPT_FIELDS = ("icon", "cwd", "env", "exit_gesture", "priority", "use_daemon_default_log",
                "disable_esc_exit_key")


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

    def unregister(self, app_id: str, name: str) -> bool:
        """Remove ``app_id`` from whisplay-daemon. True if it is gone.

        With MFruit OS's daemon wrapper this is ``mfruit.app.unregister``. A
        plain daemon has no such command: ``persist: false`` makes it delete its
        JSON file, and an empty launch command makes the stale in-memory entry
        (named "<name> (removed)", hidden by the registry) harmless until the
        daemon restarts."""
        try:
            self.client.unregister_app(app_id)
            log.info("Unregistered %s from whisplay-daemon", app_id)
            return True
        except DaemonRequestError as exc:
            if not str(exc).startswith("unknown command"):
                log.warning("Could not unregister %s: %s", app_id, exc)
                return False
        except DaemonError as exc:
            log.warning("Could not unregister %s: %s", app_id, exc)
            return False
        try:
            self.client.register_app(app_id, f"{name}{REMOVED_SUFFIX}", launch_command="",
                                     persist=False, priority=-1000)
        except DaemonError as exc:
            log.warning("Could not unregister %s: %s", app_id, exc)
            return False
        return True

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
                # Esc is "back" inside MFruit OS, not "close MFruit OS".
                use_daemon_default_log=True, persist=True, disable_esc_exit_key=True)
        except DaemonError as exc:
            log.warning("Could not register %s: %s", OS_APP_ID, exc)
            return False
        return True

    # ------------------------------------------------------------ launch gate
    @property
    def tickets_dir(self) -> str:
        return os.path.join(self.paths.state_dir, "tickets")

    def issue_ticket(self, session) -> None:
        """Authorise exactly one start of ``session.app_id`` for this session."""
        os.makedirs(self.tickets_dir, mode=0o700, exist_ok=True)
        path = os.path.join(self.tickets_dir, session.app_id)
        with open(path + ".tmp", "w", encoding="utf-8") as fp:
            fp.write(f"{session.id} {int(time.time()) + TICKET_TTL_SEC}\n")
        os.replace(path + ".tmp", path)
        log.info("TICKET app=%s session=%s", session.app_id, session.id)

    def revoke_ticket(self, app_id: str) -> None:
        """An unused ticket must never be claimable later (e.g. by a stray launch)."""
        try:
            os.remove(os.path.join(self.tickets_dir, app_id))
            log.info("TICKET_REVOKED app=%s", app_id)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Cannot revoke ticket for %s: %s", app_id, exc)

    def revoke_all_tickets(self) -> None:
        try:
            names = os.listdir(self.tickets_dir)
        except FileNotFoundError:
            return
        for name in names:
            try:
                os.remove(os.path.join(self.tickets_dir, name))
            except OSError:
                pass

    def set_gate(self, policy: str) -> None:
        """``gate`` (tickets required) or ``open`` (daemon desktop may launch freely)."""
        path = os.path.join(self.paths.state_dir, "launch-policy")
        with open(path + ".tmp", "w", encoding="utf-8") as fp:
            fp.write(policy + "\n")
        os.replace(path + ".tmp", path)
        log.info("LAUNCH_POLICY %s", policy)

    def acquire_instance_lock(self) -> bool:
        """Hold ``state/launcher.lock`` for the life of this process.

        It proves to ``mfruit-run`` that MFruit OS is alive (the kernel releases
        it when the process dies, so a crash never leaves the gate closed) and
        guarantees a single MFruit OS instance.
        """
        import fcntl
        path = os.path.join(self.paths.state_dir, "launcher.lock")
        handle = open(path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._lock_handle = handle
        with open(os.path.join(self.paths.state_dir, "launcher.pid"), "w", encoding="utf-8") as fp:
            fp.write(f"{os.getpid()}\n")
        return True

    def release_instance_lock(self) -> None:
        handle = getattr(self, "_lock_handle", None)
        if handle is not None:
            handle.close()
            self._lock_handle = None
        try:
            os.remove(os.path.join(self.paths.state_dir, "launcher.pid"))
        except OSError:
            pass

    # ------------------------------------------------------------- adoption
    def adopted_dir(self, app_id: str) -> str:
        return os.path.join(self.paths.home, "adopted", app_id)

    def is_adopted(self, app_id: str) -> bool:
        return os.path.isfile(os.path.join(self.adopted_dir(app_id), "registration.json"))

    def adopt(self, registration: dict) -> bool:
        """Route a daemon-registered app through the launch gate.

        The original registration is saved first (``registration.json`` plus
        plain ``command``/``cwd`` files for the sh wrapper), then the daemon entry
        is re-registered with the same fields but ``mfruit-run`` as launch command.
        """
        app_id = str(registration.get("app_id") or "")
        command = str(registration.get("launch_command") or "")
        if not app_id or app_id == OS_APP_ID or not command or is_wrapper_command(command, app_id):
            return False
        directory = self.adopted_dir(app_id)
        os.makedirs(directory, exist_ok=True)
        for name, content in (("registration.json", json.dumps(registration, indent=2)),
                              ("command", command), ("cwd", str(registration.get("cwd") or ""))):
            with open(os.path.join(directory, name + ".tmp"), "w", encoding="utf-8") as fp:
                fp.write(content + "\n")
            os.replace(os.path.join(directory, name + ".tmp"), os.path.join(directory, name))
        fields = {k: registration[k] for k in ADOPT_FIELDS if k in registration}
        try:
            self.client.register_app(app_id, str(registration.get("display_name") or app_id),
                                     launch_command=self.wrapper_command(app_id), persist=True,
                                     **fields)
        except DaemonError as exc:
            log.warning("Could not adopt %s: %s", app_id, exc)
            return False
        log.info("ADOPTED app=%s (original launch command saved in %s)", app_id, directory)
        return True

    def adopt_all(self, daemon_files: dict[str, dict]) -> int:
        """Adopt every persisted daemon app whose launch is not gated yet."""
        count = 0
        for app_id, registration in daemon_files.items():
            command = str(registration.get("launch_command") or "")
            if app_id != OS_APP_ID and command and not is_wrapper_command(command, app_id):
                count += int(self.adopt(registration))
        return count

    def restore_adopted(self) -> int:
        """Give every adopted app its original daemon registration back (uninstall)."""
        root = os.path.join(self.paths.home, "adopted")
        count = 0
        try:
            names = sorted(os.listdir(root))
        except FileNotFoundError:
            return 0
        for app_id in names:
            try:
                with open(os.path.join(root, app_id, "registration.json"), encoding="utf-8") as fp:
                    registration = json.load(fp)
                fields = {k: v for k, v in registration.items() if k not in ("app_id", "display_name")}
                fields["persist"] = True
                self.client.register_app(app_id, registration.get("display_name") or app_id, **fields)
                shutil.rmtree(os.path.join(root, app_id))
                count += 1
                log.info("RESTORED app=%s original launch command", app_id)
            except (OSError, ValueError, DaemonError) as exc:
                log.warning("Could not restore %s: %s", app_id, exc)
        return count

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
        if entry.kind == "system":
            return
        if entry.kind == "os":
            rotate_if_large(self.paths.app_log(entry.id))
        try:
            os.remove(self.run_state_path(entry.id))
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Cannot clear run state for %s: %s", entry.id, exc)

    def session_exit(self, app_id: str, session_id: str) -> dict | None:
        """The exit record of exactly this session, if mfruit-run wrote one."""
        state = self.run_state(app_id)
        if state and state.get("session") == session_id and state.get("state") == "exited":
            return state
        return None

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

    def ensure_stopped(self, app_id: str, session_id: str, grace: float = 3.0) -> str:
        """After the user left an app: make sure its process is gone.

        The app normally exits by itself (it got app_exit_requested). If it is
        still running after ``grace`` seconds, its process group is stopped.
        Returns exited | terminated | killed | unknown (no process record for
        this session, e.g. an app registered without the MFruit gate).
        """
        state = self.run_state(app_id)
        if not state or state.get("session") != session_id:
            return "unknown"
        pid = state.get("pid")
        if state.get("state") == "exited" or not isinstance(pid, int):
            return "exited"
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not self._is_wrapper(pid, app_id):
                return "exited"
            time.sleep(0.2)
        return self._stop_group(pid, app_id)

    def _stop_group(self, pid: int, app_id: str, kill_after: float = 2.0) -> str:
        if pid <= 1 or not self._is_wrapper(pid, app_id):
            return "exited"
        try:
            pgid = os.getpgid(pid)
            if pgid <= 1 or pgid == os.getpgrp() or os.getsid(pid) != pgid:
                log.warning("Refusing to stop %s: unexpected process group %d", app_id, pgid)
                return "unknown"
            log.info("APP_STOP app=%s pgid=%d signal=TERM", app_id, pgid)
            os.killpg(pgid, signal.SIGTERM)
            deadline = time.monotonic() + kill_after
            while time.monotonic() < deadline:
                if not self._is_wrapper(pid, app_id):
                    return "terminated"
                time.sleep(0.1)
            log.warning("APP_STOP app=%s pgid=%d signal=KILL", app_id, pgid)
            os.killpg(pgid, signal.SIGKILL)
            return "killed"
        except ProcessLookupError:
            return "exited"
        except PermissionError as exc:
            log.error("Not allowed to stop %s: %s", app_id, exc)
            return "unknown"

    def force_stop(self, entry: AppEntry, grace: float = 2.0) -> bool:
        """Stop the app's process group now (packages and adopted apps only).

        The pid is only trusted if /proc confirms it is our wrapper for this
        app. The daemon starts launch commands with ``start_new_session=True``
        (via ``sh -c``), so the wrapper's process group is that session's
        group; it is never our own group."""
        if entry.kind != "os" and not entry.adopted:
            return False
        pid = (self.run_state(entry.id) or {}).get("pid")
        if not isinstance(pid, int) or not self._is_wrapper(pid, entry.id):
            log.info("No running wrapper found for %s", entry.id)
            return False
        return self._stop_group(pid, entry.id, grace) in ("exited", "terminated", "killed")

    @staticmethod
    def _is_wrapper(pid: int, app_id: str) -> bool:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fp:
                args = fp.read().split(b"\x00")
        except OSError:
            return False
        joined = b" ".join(args)
        return RUN_WRAPPER_NAME.encode() in joined and app_id.encode() in args
