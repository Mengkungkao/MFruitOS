"""Filesystem layout of mFruit OS and path-safety helpers.

Runtime data lives under ``~/.whisplay-os`` (override with WHISPLAY_OS_HOME)::

    ~/.whisplay-os/
    ├── apps/<id>/          OS-managed apps (versions/, current -> versions/…, data/)
    ├── bin/                stable helper scripts referenced by daemon launch commands
    ├── cache/              GitHub metadata, downloads
    ├── config/settings.json
    ├── logs/               launcher.log, updater.log, <app>.log
    ├── state/              run state, control socket, boot markers
    └── system/             the OS itself (versions/, current -> versions/…)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

DEFAULT_OS_HOME = "~/.whisplay-os"
DEFAULT_DAEMON_HOME = "~/.whisplay-daemon"

APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")

# Directories that must never be deleted or used as an install target, even
# if a bug produces them as a path.
_PROTECTED = {"/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/opt",
              "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp",
              "/usr", "/var"}


def is_valid_app_id(app_id: object) -> bool:
    return isinstance(app_id, str) and bool(APP_ID_PATTERN.match(app_id))


def package_root() -> str:
    """Directory that contains the ``mfruitos`` package, ``assets/`` and ``config/``."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_within(path: str, root: str) -> bool:
    """True if ``path`` resolves strictly inside ``root`` (never equal to it)."""
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    if real_path == real_root:
        return False
    try:
        return os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:
        return False


def is_protected(path: str) -> bool:
    real = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    return real in _PROTECTED or real == home


@dataclass(frozen=True)
class Paths:
    home: str
    daemon_home: str

    @property
    def config_dir(self) -> str:
        return os.path.join(self.home, "config")

    @property
    def settings_file(self) -> str:
        return os.path.join(self.config_dir, "settings.json")

    @property
    def apps_dir(self) -> str:
        return os.path.join(self.home, "apps")

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.home, "cache")

    @property
    def downloads_dir(self) -> str:
        return os.path.join(self.cache_dir, "downloads")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.home, "logs")

    @property
    def state_dir(self) -> str:
        return os.path.join(self.home, "state")

    @property
    def runs_dir(self) -> str:
        return os.path.join(self.state_dir, "runs")

    @property
    def system_dir(self) -> str:
        return os.path.join(self.home, "system")

    @property
    def bin_dir(self) -> str:
        return os.path.join(self.home, "bin")

    @property
    def control_socket(self) -> str:
        return os.path.join(self.state_dir, "control.sock")

    @property
    def keys_socket(self) -> str:
        """The key hub apps take their keyboard keys from (launcher/keyhub.py)."""
        return os.path.join(self.state_dir, "keys.sock")

    @property
    def daemon_apps_dir(self) -> str:
        return os.path.join(self.daemon_home, "app")

    @property
    def daemon_app_log(self) -> str:
        return os.path.join(self.daemon_home, "daemon-app.log")

    def app_root(self, app_id: str) -> str:
        if not is_valid_app_id(app_id):
            raise ValueError(f"invalid app id: {app_id!r}")
        return os.path.join(self.apps_dir, app_id)

    def app_log(self, app_id: str) -> str:
        if not is_valid_app_id(app_id):
            raise ValueError(f"invalid app id: {app_id!r}")
        return os.path.join(self.logs_dir, f"{app_id}.log")

    def ensure(self) -> None:
        for path in (self.home, self.config_dir, self.apps_dir, self.cache_dir,
                     self.downloads_dir, self.logs_dir, self.system_dir, self.bin_dir):
            os.makedirs(path, exist_ok=True)
        # state holds the control socket; keep it private to the user.
        for path in (self.state_dir, self.runs_dir):
            os.makedirs(path, mode=0o700, exist_ok=True)


def resolve_paths(home: str | None = None, daemon_home: str | None = None) -> Paths:
    home = home or os.environ.get("WHISPLAY_OS_HOME") or DEFAULT_OS_HOME
    daemon_home = daemon_home or os.environ.get("WHISPLAY_DAEMON_HOME") or DEFAULT_DAEMON_HOME
    return Paths(
        home=os.path.abspath(os.path.expanduser(home)),
        daemon_home=os.path.abspath(os.path.expanduser(daemon_home)),
    )
