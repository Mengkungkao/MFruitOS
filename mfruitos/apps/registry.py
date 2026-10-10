"""Application registry — the source of truth for installed applications.

Three sources are merged (never hard-coded):

``os``      packages installed by mFruit OS under ~/.whisplay-os/apps/<id>/
            (``current`` -> versions/<ver>-<tag>/, ``app.json`` install record).
``daemon``  apps registered directly with whisplay-daemon
            (~/.whisplay-daemon/app/*.json or runtime app.register).
``system``  whisplay-daemon's built-in pages (WiFi, Bluetooth, Volume, Power),
            discovered from ``app.list`` — they only exist if the running
            daemon provides them.

A broken app is reported with ``broken`` set; it never prevents other apps
from loading.

An app uninstalled with its data kept is not an app any more: it is listed
by ``leftovers()`` (an OS package folder holding ``uninstalled.json`` and its
data, or an adopted daemon app's record) until its data is deleted.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
from dataclasses import dataclass, field

from mfruitos import OS_APP_ID
from mfruitos.apps.manifest import ManifestError, load_manifest
from mfruitos.paths import Paths, is_valid_app_id
from mfruitos.system.settings import Settings

log = logging.getLogger("mfruitos.registry")

# whisplay-daemon internal pages -> (label, icon name, settings section)
SYSTEM_PAGES = {
    "whisplay-wifi": ("WiFi", "wifi", "network"),
    "whisplay-bluetooth": ("Bluetooth", "bluetooth", "network"),
    "whisplay-volume": ("Volume", "volume", "audio"),
    "whisplay-system": ("Power", "power", "system"),
}

RUN_WRAPPER_NAME = "mfruit-run"
SETTINGS_APPS = frozenset({"connectwifi"})
UNINSTALLED_FILE = "uninstalled.json"   # in apps/<id>/ once uninstalled with data kept
REMOVED_SUFFIX = " (removed)"           # name of a registration a plain daemon cannot drop


@dataclass
class AppEntry:
    id: str
    name: str
    kind: str                      # "os" | "daemon" | "system"
    version: str = ""
    previous_version: str = ""
    description: str = ""
    icon_text: str = ""
    icon_path: str = ""
    repository: str = ""
    branch: str = ""
    entrypoint: str = ""
    install_dir: str = ""
    launch_command: str = ""
    cwd: str = ""
    priority: int = 0
    exit_gesture: str = "quad_click"
    env: dict = field(default_factory=dict)
    disable_esc_exit_key: bool = False
    adopted: bool = False          # daemon app routed through the mFruit launch gate
    background: bool = False       # keep running after the user leaves it
    background_default: bool = False
    screen_bright: bool = False    # backlight held at 100% while it runs in the background
    enabled: bool = True
    hidden: bool = False
    autostart: bool = False
    registered: bool = False       # known to the running daemon
    running: bool = False
    foreground: bool = False
    broken: str = ""               # human-readable reason, empty if OK
    latest_version: str = ""       # set by the updater when newer
    installed_at: str = ""

    @property
    def launchable(self) -> bool:
        return self.enabled and not self.broken

    @property
    def update_available(self) -> bool:
        return bool(self.latest_version)

    @property
    def managed(self) -> bool:
        return self.kind == "os"

    def status(self) -> str:
        """Single most important state, for list tags."""
        if self.broken:
            return "broken"
        if not self.enabled:
            return "disabled"
        if self.running:
            return "running"
        if self.update_available:
            return "update"
        return "installed"


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Cannot read %s: %s", path, exc)
        return None


def is_wrapper_command(command: str, app_id: str) -> bool:
    return RUN_WRAPPER_NAME in command and command.rstrip().endswith(app_id)


def missing_script(command: str, cwd: str) -> str:
    """The script a ``python3 x.py`` / ``bash x.sh`` / ``./x`` command runs, if
    it does not exist (relative to ``cwd``); "" when present or not knowable."""
    try:
        words = shlex.split(command)
    except ValueError:
        return ""
    if not words:
        return ""
    script = ""
    if os.path.basename(words[0]).startswith(("python", "bash", "sh")) and len(words) > 1:
        if not words[1].startswith("-"):
            script = words[1]
    elif "/" in words[0]:
        script = words[0]
    if not script:
        return ""
    path = script if os.path.isabs(script) else os.path.join(cwd or "", script)
    return "" if os.path.exists(path) else script


@dataclass
class Leftover:
    """An uninstalled app whose data mFruit OS still keeps."""
    id: str
    name: str
    kind: str                      # "os" | "daemon"
    version: str = ""
    uninstalled_at: str = ""


class AppRegistry:
    def __init__(self, paths: Paths, settings: Settings, os_version: str):
        self.paths = paths
        self.settings = settings
        self.os_version = os_version
        self._entries: dict[str, AppEntry] = {}
        self._leftovers: dict[str, Leftover] = {}
        self._latest: dict[str, str] = {}
        self.daemon_online = False

    # ------------------------------------------------------------ discovery
    def refresh(self, daemon_apps: list[dict] | None) -> list[AppEntry]:
        """Rescan all sources. ``daemon_apps`` is ``app.list`` or None if offline."""
        entries: dict[str, AppEntry] = {}
        self.daemon_online = daemon_apps is not None
        daemon_files = self._scan_daemon_files()
        live = {a["app_id"]: a for a in (daemon_apps or []) if a.get("app_id")}

        for entry in self._scan_os_apps():
            entries[entry.id] = entry

        daemon_ids = list(live) if daemon_apps is not None else list(daemon_files)
        for app_id in daemon_ids:
            if app_id == OS_APP_ID:
                continue
            info = live.get(app_id, {})
            config = daemon_files.get(app_id, {})
            if not config and str(info.get("display_name", "")).endswith(REMOVED_SUFFIX):
                continue  # uninstalled; a plain daemon keeps it in memory until it restarts
            existing = entries.get(app_id)
            if existing is not None:
                existing.registered = app_id in live
                existing.running = bool(info.get("running"))
                existing.foreground = bool(info.get("foreground"))
                continue
            if app_id in SYSTEM_PAGES:
                if daemon_apps is None:
                    continue  # system pages only exist inside a running daemon
                label, _, _ = SYSTEM_PAGES[app_id]
                entries[app_id] = AppEntry(id=app_id, name=info.get("display_name") or label,
                                           kind="system", registered=True,
                                           icon_text=str(info.get("icon", "")))
                continue
            entries[app_id] = self._daemon_entry(app_id, info, config, app_id in live)

        allowed = set(self.settings.get("apps.installed_ids")) if self.settings.get("apps.clean_menu") else None
        for entry in entries.values():
            flags = self.settings.app_flags(entry.id)
            entry.enabled = flags["enabled"]
            entry.hidden = flags["hidden"]
            entry.autostart = flags["autostart"]
            if allowed is not None and entry.kind != "system" and entry.id not in allowed:
                entry.enabled = False
                entry.autostart = False
            explicit = self.settings.app_flag_explicit(entry.id, "background")
            entry.background = explicit if explicit is not None else entry.background_default
            entry.screen_bright = flags["screen_bright"]
            latest = self._latest.get(entry.id, "")
            entry.latest_version = latest if entry.kind == "os" else ""

        self._entries = entries
        self._leftovers = self._scan_leftovers(entries, daemon_files)
        log.info("Registry: %d apps (%d OS-managed, daemon %s)", len(entries),
                 sum(1 for e in entries.values() if e.kind == "os"),
                 "online" if self.daemon_online else "offline")
        return self.all()

    def daemon_registrations(self) -> dict[str, dict]:
        """Persisted daemon registrations (``~/.whisplay-daemon/app/*.json``)."""
        return self._scan_daemon_files()

    def _adopted_registration(self, app_id: str) -> dict | None:
        return _read_json(os.path.join(self.paths.home, "adopted", app_id, "registration.json"))

    def _scan_leftovers(self, entries: dict, daemon_files: dict) -> dict[str, Leftover]:
        found: dict[str, Leftover] = {}
        for app_id in self._uninstalled_os_ids():
            record = _read_json(os.path.join(self.paths.app_root(app_id), UNINSTALLED_FILE)) or {}
            found[app_id] = Leftover(app_id, str(record.get("name") or app_id), "os",
                                     str(record.get("version") or ""),
                                     str(record.get("uninstalled_at") or ""))
        adopted = os.path.join(self.paths.home, "adopted")
        try:
            names = sorted(os.listdir(adopted))
        except OSError:
            names = []
        for app_id in names:
            if app_id in found or app_id in entries or app_id in daemon_files \
                    or not is_valid_app_id(app_id):
                continue
            record = self._adopted_registration(app_id) or {}
            found[app_id] = Leftover(app_id, str(record.get("display_name") or app_id), "daemon")
        return found

    def _uninstalled_os_ids(self) -> list[str]:
        try:
            names = sorted(os.listdir(self.paths.apps_dir))
        except OSError:
            return []
        return [name for name in names if is_valid_app_id(name)
                and os.path.isfile(os.path.join(self.paths.apps_dir, name, UNINSTALLED_FILE))
                and not os.path.lexists(os.path.join(self.paths.apps_dir, name, "current"))]

    def _scan_daemon_files(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        directory = self.paths.daemon_apps_dir
        try:
            names = sorted(os.listdir(directory))
        except FileNotFoundError:
            return result
        except OSError as exc:
            log.warning("Cannot list %s: %s", directory, exc)
            return result
        for name in names:
            if not name.endswith(".json"):
                continue
            data = _read_json(os.path.join(directory, name))
            if not data:
                continue
            app_id = str(data.get("app_id") or "").strip()
            if app_id and app_id not in result:
                result[app_id] = data
        return result

    def _daemon_entry(self, app_id: str, info: dict, config: dict, registered: bool) -> AppEntry:
        original = None
        if is_wrapper_command(str(config.get("launch_command") or ""), app_id):
            original = self._adopted_registration(app_id)
        if original:
            # Adopted: show the app's own command and folder, not the gate.
            config = dict(config, launch_command=original.get("launch_command", ""),
                          cwd=original.get("cwd", config.get("cwd", "")))
        entry = AppEntry(
            id=app_id,
            name=str(info.get("display_name") or config.get("display_name") or app_id)[:40],
            kind="daemon",
            icon_text=str(info.get("icon", config.get("icon", "")))[:4],
            launch_command=str(config.get("launch_command") or ""),
            cwd=str(config.get("cwd") or ""),
            priority=_as_int(info.get("priority", config.get("priority", 0))),
            exit_gesture=str(info.get("exit_gesture", config.get("exit_gesture", "quad_click"))),
            registered=registered,
            running=bool(info.get("running")),
            foreground=bool(info.get("foreground")),
            adopted=bool(original),
            disable_esc_exit_key=bool(info.get("disable_esc_exit_key",
                                               config.get("disable_esc_exit_key", False))),
        )
        if config:
            if not entry.launch_command:
                entry.broken = "No launch command"
            elif entry.cwd and not os.path.isdir(entry.cwd):
                entry.broken = "Working directory missing"
            elif is_wrapper_command(entry.launch_command, app_id):
                entry.broken = "App files missing (uninstalled?)"
            elif missing_script(entry.launch_command, entry.cwd):
                entry.broken = f"App files missing ({missing_script(entry.launch_command, entry.cwd)})"
        # Optional: a legacy app that ships an mFruit manifest gets richer metadata.
        if entry.cwd and os.path.isfile(os.path.join(entry.cwd, "manifest.json")):
            try:
                manifest = load_manifest(entry.cwd)
                entry.version = manifest.version
                entry.description = manifest.description
                entry.repository = manifest.repository
                if manifest.icon:
                    entry.icon_path = os.path.join(entry.cwd, manifest.icon)
            except ManifestError as exc:
                log.debug("Ignoring manifest in %s: %s", entry.cwd, exc)
        return entry

    def _scan_os_apps(self) -> list[AppEntry]:
        entries: list[AppEntry] = []
        try:
            names = sorted(os.listdir(self.paths.apps_dir))
        except FileNotFoundError:
            return entries
        except OSError as exc:
            log.warning("Cannot list %s: %s", self.paths.apps_dir, exc)
            return entries
        for name in names:
            root = os.path.join(self.paths.apps_dir, name)
            if name.startswith(".") or not os.path.isdir(root):
                continue
            if os.path.isfile(os.path.join(root, UNINSTALLED_FILE)) and \
                    not os.path.lexists(os.path.join(root, "current")):
                continue  # uninstalled, data kept: a leftover, not an app
            if not is_valid_app_id(name):
                log.warning("Ignoring app directory with invalid id: %s", name)
                continue
            entries.append(self._os_entry(name, root))
        return entries

    def _os_entry(self, app_id: str, root: str) -> AppEntry:
        record = _read_json(os.path.join(root, "app.json")) or {}
        current = os.path.join(root, "current")
        entry = AppEntry(id=app_id, name=str(record.get("name") or app_id), kind="os",
                         install_dir=current,
                         repository=str(record.get("repository") or ""),
                         branch=str(record.get("branch") or ""),
                         previous_version=str(record.get("previous_version") or ""),
                         installed_at=str(record.get("installed_at") or ""),
                         version=str(record.get("installed_version") or ""))
        if not os.path.isdir(current):
            entry.broken = "Installation incomplete (no active version)"
            return entry
        try:
            manifest = load_manifest(current, os_version=None)
        except ManifestError as exc:
            entry.broken = f"Invalid manifest: {exc}"
            return entry
        if manifest.id != app_id:
            entry.broken = f"Manifest id '{manifest.id}' does not match folder"
            return entry
        entry.name = manifest.name
        entry.version = manifest.version
        entry.description = manifest.description
        entry.entrypoint = manifest.entrypoint
        entry.priority = manifest.priority
        entry.exit_gesture = manifest.exit_gesture
        entry.env = dict(manifest.env)
        entry.disable_esc_exit_key = manifest.disable_esc_exit_key
        entry.background_default = manifest.background
        entry.repository = entry.repository or manifest.repository
        entry.branch = entry.branch or manifest.branch
        entry.cwd = current
        entry.icon_text = "".join(w[0] for w in manifest.name.split()[:2]).upper()
        if manifest.icon:
            entry.icon_path = os.path.join(current, manifest.icon)
        entrypoint = os.path.join(current, manifest.entrypoint)
        if not os.path.isfile(entrypoint):
            entry.broken = "Entrypoint missing"
        return entry

    # ------------------------------------------------------------- queries
    def all(self) -> list[AppEntry]:
        return self.ordered(self._entries.values())

    def get(self, app_id: str) -> AppEntry | None:
        return self._entries.get(app_id)

    def leftovers(self) -> list[Leftover]:
        """Uninstalled apps whose data is still kept, by name."""
        return sorted(self._leftovers.values(), key=lambda item: item.name.lower())

    def leftover(self, app_id: str) -> Leftover | None:
        return self._leftovers.get(app_id)

    def apps(self) -> list[AppEntry]:
        """Installed applications (excludes daemon system pages)."""
        allowed = self.settings.get("apps.installed_ids") if self.settings.get("apps.clean_menu") else None
        return [e for e in self.all() if e.kind != "system" and (allowed is None or e.id in allowed)]

    def system_pages(self) -> list[AppEntry]:
        return [e for e in self.all() if e.kind == "system"]

    def launcher_entries(self) -> list[AppEntry]:
        """What the Home screen shows: enabled, not hidden, not system pages."""
        return [e for e in self.apps() if e.enabled and not e.hidden and e.id not in SETTINGS_APPS]

    def managed(self) -> list[AppEntry]:
        return [e for e in self.all() if e.kind == "os"]

    def ordered(self, entries) -> list[AppEntry]:
        order = self.settings.get("apps.order")
        position = {app_id: i for i, app_id in enumerate(order)}
        return sorted(entries, key=lambda e: (
            position.get(e.id, len(position)),
            -e.priority, e.name.lower(), e.id))

    def set_latest_versions(self, latest: dict[str, str]) -> None:
        self._latest = dict(latest)
        for entry in self._entries.values():
            entry.latest_version = self._latest.get(entry.id, "") if entry.kind == "os" else ""

    # ------------------------------------------------------------ mutation
    def move(self, app_id: str, delta: int) -> bool:
        """Move an app up (-1) or down (+1) in the launcher order."""
        ids = [e.id for e in self.apps()]
        if app_id not in ids:
            return False
        index = ids.index(app_id)
        target = index + delta
        if not 0 <= target < len(ids):
            return False
        ids[index], ids[target] = ids[target], ids[index]
        self.settings.set("apps.order", ids)
        return True


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
