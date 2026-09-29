"""Persistent, validated MFruit OS configuration.

The schema below is the single source of truth for defaults. ``config/default.json``
is a generated reference copy (``python3 -m mfruitos.system.settings --dump-defaults``).

Loading rules (see CLAUDE.md §14):
  * unreadable/invalid JSON -> the broken file is preserved as
    ``settings.json.broken-<timestamp>`` and safe defaults are used;
  * one invalid entry falls back to its default without affecting the others;
  * writes are atomic (temp file + fsync + rename).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable

from mfruitos.paths import is_valid_app_id

log = logging.getLogger("mfruitos.settings")

GESTURE_ACTIONS = ("next", "previous", "select", "back", "home", "none")
GESTURE_KEYS = ("single_click", "double_click", "triple_click", "long_press", "quad_click")
LED_COLORS = ("off", "white", "blue", "cyan", "green", "yellow", "orange", "red", "purple", "pink")
TIMEOUT_CHOICES = (0, 15, 30, 60, 120, 300, 600)
DIM_CHOICES = (10, 15, 30, 60, 120)


class Invalid(ValueError):
    pass


def _boolean(value):
    if isinstance(value, bool):
        return value
    raise Invalid("expected true/false")


def _int_range(lo: int, hi: int):
    def check(value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise Invalid("expected an integer")
        if not lo <= value <= hi:
            raise Invalid(f"expected {lo}..{hi}")
        return value
    return check


def _choice(*options):
    def check(value):
        if value not in options or isinstance(value, bool):
            raise Invalid(f"expected one of {options}")
        return value
    return check


def _string(max_len: int):
    def check(value):
        if not isinstance(value, str) or len(value) > max_len:
            raise Invalid(f"expected a string of at most {max_len} characters")
        return value
    return check


def _app_id_or_empty(value):
    if value == "" or is_valid_app_id(value):
        return value
    raise Invalid("expected an app id")


def _id_list(value):
    if not isinstance(value, list) or not all(is_valid_app_id(v) for v in value):
        raise Invalid("expected a list of app ids")
    seen: list[str] = []
    for item in value:
        if item not in seen:
            seen.append(item)
    return seen


def _repo_or_empty(value):
    if value == "":
        return value
    from mfruitos.apps.manifest import normalize_repository, ManifestError
    try:
        return normalize_repository(value)
    except ManifestError as exc:
        raise Invalid(str(exc)) from exc


def _repo_list(value):
    if not isinstance(value, list):
        raise Invalid("expected a list of repositories")
    return [_repo_or_empty(v) for v in value if v]


_action = _choice(*GESTURE_ACTIONS)

# key -> (default, validator)
SCHEMA: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "display.brightness": (80, _int_range(5, 100)),
    "display.auto_dim": (True, _boolean),
    "display.dim_after_sec": (30, _choice(*DIM_CHOICES)),
    "display.dim_level": (15, _int_range(1, 60)),
    "display.screen_timeout_sec": (120, _choice(*TIMEOUT_CHOICES)),
    "display.theme": ("dark", _choice("dark", "light")),
    "display.animation": ("minimal", _choice("minimal", "off")),
    "display.clock_24h": (True, _boolean),
    "button.single_click": ("next", _action),
    "button.double_click": ("previous", _action),
    "button.triple_click": ("none", _action),
    "button.long_press": ("select", _action),
    "button.quad_click": ("back", _action),
    "button.click_gap_ms": (300, _int_range(150, 800)),
    "button.long_press_ms": (700, _int_range(400, 2000)),
    "led.enabled": (True, _boolean),
    "led.idle_color": ("blue", _choice(*LED_COLORS)),
    "led.running_color": ("green", _choice(*LED_COLORS)),
    "led.update_color": ("orange", _choice(*LED_COLORS)),
    "led.error_color": ("red", _choice(*LED_COLORS)),
    "led.brightness": (30, _int_range(0, 100)),
    "audio.device": ("", _string(64)),
    "updater.auto_check": (True, _boolean),
    "updater.check_interval_hours": (12, _int_range(1, 168)),
    "updater.include_prereleases": (False, _boolean),
    "updater.require_checksum": (False, _boolean),
    "updater.keep_versions": (2, _int_range(1, 5)),
    "updater.max_download_mb": (100, _int_range(5, 1024)),
    "updater.github_token": ("", _string(200)),
    "updater.discovery_topic": ("whisplay-app", _string(50)),
    "updater.sources": ([], _repo_list),
    "system.repository": ("https://github.com/Mengkungkao/MFruitOS", _repo_or_empty),
    "system.home_title": ("MFruit OS", _string(20)),
    "system.show_system_pages_on_home": (False, _boolean),
    "developer.enabled": (False, _boolean),
    "developer.debug_logging": (False, _boolean),
    "daemon.socket_path": ("/tmp/whisplay-daemon.sock", _string(200)),
    "daemon.fallback_direct_display": (True, _boolean),
    "daemon.whisplay_root": ("", _string(300)),
    "apps.order": ([], _id_list),
    "apps.default_app": ("", _app_id_or_empty),
}

APP_FLAGS = {"enabled": True, "hidden": False, "autostart": False, "background": False}


def defaults_tree() -> dict:
    tree: dict = {"schema": 1}
    for key, (default, _) in SCHEMA.items():
        section, name = key.split(".", 1)
        tree.setdefault(section, {})[name] = copy.deepcopy(default)
    tree["applications"] = {}
    return tree


def validate_button_map(mapping: dict) -> None:
    """Refuse gesture maps that would lock a one-button user out of the UI."""
    actions = {mapping.get(k) for k in GESTURE_KEYS}
    if "select" not in actions:
        raise Invalid("at least one gesture must be mapped to 'select'")
    if "next" not in actions and "previous" not in actions:
        raise Invalid("at least one gesture must move the selection")


def atomic_write_json(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2, sort_keys=True)
        fp.write("\n")
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)


class Settings:
    """Thread-safe settings store. Mutations are validated and marked dirty.

    ``autosave`` (optional) is called after every change; the runtime uses it
    to debounce writes so repeated edits (e.g. brightness steps) cost one write.
    """

    def __init__(self, path: str | None, autosave: Callable[[], None] | None = None):
        self.path = path
        self.autosave = autosave
        self._lock = threading.RLock()
        self._data = defaults_tree()
        self._dirty = False
        self._listeners: list[Callable[[str], None]] = []
        self.load_errors: list[str] = []

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        self.load_errors = []
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                raw = json.load(fp)
            if not isinstance(raw, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError) as exc:
            preserved = self._preserve_broken_file()
            message = f"settings file unreadable ({exc}); preserved as {preserved}; using defaults"
            log.error(message)
            self.load_errors.append(message)
            return
        with self._lock:
            self._data = self._merge(raw)

    def _preserve_broken_file(self) -> str:
        target = f"{self.path}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(self.path, target)
        except OSError as exc:
            log.error("Could not preserve broken settings file: %s", exc)
            return self.path
        return target

    def _merge(self, raw: dict) -> dict:
        data = defaults_tree()
        for key, (default, validator) in SCHEMA.items():
            section, name = key.split(".", 1)
            section_raw = raw.get(section)
            if not isinstance(section_raw, dict) or name not in section_raw:
                continue
            try:
                data[section][name] = validator(section_raw[name])
            except Invalid as exc:
                message = f"invalid setting {key}={section_raw[name]!r}: {exc}; using default {default!r}"
                log.warning(message)
                self.load_errors.append(message)
        try:
            validate_button_map(data["button"])
        except Invalid as exc:
            message = f"button map rejected ({exc}); restoring default gestures"
            log.warning(message)
            self.load_errors.append(message)
            for key in GESTURE_KEYS:
                data["button"][key] = SCHEMA[f"button.{key}"][0]
        apps_raw = raw.get("applications")
        if isinstance(apps_raw, dict):
            for app_id, flags in apps_raw.items():
                if not is_valid_app_id(app_id) or not isinstance(flags, dict):
                    self.load_errors.append(f"ignored invalid application entry {app_id!r}")
                    continue
                clean = {}
                for flag, default in APP_FLAGS.items():
                    if flag not in flags:
                        continue  # keep "never set" distinguishable from the default
                    value = flags[flag]
                    clean[flag] = value if isinstance(value, bool) else default
                data["applications"][app_id] = clean
        return data

    # --------------------------------------------------------------- access
    def get(self, key: str) -> Any:
        section, name = key.split(".", 1)
        with self._lock:
            return copy.deepcopy(self._data[section][name])

    def set(self, key: str, value: Any) -> None:
        if key not in SCHEMA:
            raise KeyError(key)
        _, validator = SCHEMA[key]
        value = validator(value)
        section, name = key.split(".", 1)
        with self._lock:
            if section == "button" and name in GESTURE_KEYS:
                candidate = dict(self._data["button"], **{name: value})
                validate_button_map(candidate)
            if self._data[section][name] == value:
                return
            self._data[section][name] = value
            self._dirty = True
        self._changed(key)

    def section(self, section: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._data[section])

    def app_flags(self, app_id: str) -> dict:
        with self._lock:
            flags = dict(APP_FLAGS)
            flags.update(self._data["applications"].get(app_id, {}))
            return flags

    def app_flag_explicit(self, app_id: str, flag: str) -> bool | None:
        """The user's own choice for ``flag``, or None if never set."""
        with self._lock:
            return self._data["applications"].get(app_id, {}).get(flag)

    def set_app_flag(self, app_id: str, flag: str, value: bool) -> None:
        if flag not in APP_FLAGS or not isinstance(value, bool):
            raise Invalid(f"bad app flag {flag}={value!r}")
        if not is_valid_app_id(app_id):
            raise Invalid(f"invalid app id {app_id!r}")
        with self._lock:
            entry = self._data["applications"].setdefault(app_id, {})
            if entry.get(flag) == value:
                return
            entry[flag] = value
            if flag == "autostart" and value:
                # Only one foreground app can autostart.
                for other_id, other in self._data["applications"].items():
                    if other_id != app_id:
                        other["autostart"] = False
            self._dirty = True
        self._changed(f"applications.{app_id}.{flag}")

    def forget_app(self, app_id: str) -> None:
        with self._lock:
            removed = self._data["applications"].pop(app_id, None) is not None
            order = self._data["apps"]["order"]
            if app_id in order:
                order.remove(app_id)
                removed = True
            if self._data["apps"]["default_app"] == app_id:
                self._data["apps"]["default_app"] = ""
                removed = True
            if removed:
                self._dirty = True
        if removed:
            self._changed(f"applications.{app_id}")

    def to_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    # ------------------------------------------------------------ listeners
    def add_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _changed(self, key: str) -> None:
        for callback in list(self._listeners):
            try:
                callback(key)
            except Exception:  # listener bugs must not break settings writes
                log.exception("settings listener failed for %s", key)
        if self.autosave:
            self.autosave()

    # ----------------------------------------------------------------- save
    @property
    def dirty(self) -> bool:
        return self._dirty

    def save(self) -> bool:
        if not self.path:
            return False
        with self._lock:
            if not self._dirty and os.path.exists(self.path):
                return False
            data = copy.deepcopy(self._data)
            self._dirty = False
        try:
            atomic_write_json(self.path, data)
        except OSError as exc:
            log.error("Could not save settings to %s: %s", self.path, exc)
            with self._lock:
                self._dirty = True
            return False
        log.debug("Settings saved")
        return True


if __name__ == "__main__":
    if "--dump-defaults" in sys.argv:
        json.dump(defaults_tree(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
