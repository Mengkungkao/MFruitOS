"""Validation of Whisplay app package manifests (``manifest.json``).

A manifest is rejected — never partially trusted — if any required field is
missing or unsafe. See APP_DEVELOPMENT.md for the specification.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from mfruitos import OS_APP_ID
from mfruitos.paths import is_valid_app_id
from mfruitos.updater.version import Version, parse_version

MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 64 * 1024
VALID_EXIT_GESTURES = ("quad_click", "long_press", "none")

# IDs that belong to the OS or to whisplay-daemon's built-in pages.
RESERVED_IDS = {OS_APP_ID, "whisplay-wifi", "whisplay-bluetooth", "whisplay-volume",
                "whisplay-system", "settings", "updater", "system"}

_GITHUB_URL = re.compile(
    r"^(?:https://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
_SHORTHAND = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ManifestError(ValueError):
    pass


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    entrypoint: str
    description: str = ""
    icon: str = ""
    min_os_version: str = ""
    repository: str = ""
    branch: str = ""
    exit_gesture: str = "quad_click"
    priority: int = 0
    env: dict = field(default_factory=dict)
    test: str = ""
    type: str = "app"
    disable_esc_exit_key: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def parsed_version(self) -> Version:
        return Version.parse(self.version)


def repository_parts(url: str) -> tuple[str, str]:
    """Return (owner, repo) for a GitHub repository URL or ``owner/repo``."""
    if not isinstance(url, str):
        raise ManifestError("repository must be a string")
    text = url.strip()
    if text.startswith("http://"):
        raise ManifestError("repository must use HTTPS")
    match = _GITHUB_URL.match(text) or _SHORTHAND.match(text)
    if not match:
        raise ManifestError(f"not a GitHub repository URL: {url!r}")
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo in (".", "..") or not repo:
        raise ManifestError(f"invalid repository name: {url!r}")
    return owner, repo


def normalize_repository(url: str) -> str:
    owner, repo = repository_parts(url)
    return f"https://github.com/{owner}/{repo}"


def same_repository(a: str, b: str) -> bool:
    try:
        return normalize_repository(a).lower() == normalize_repository(b).lower()
    except ManifestError:
        return False


def is_safe_relative_path(path: object) -> bool:
    """Relative, inside the package, no traversal, no shell metacharacters."""
    if not isinstance(path, str) or not path or len(path) > 200:
        return False
    if path.startswith(("/", "~")) or "\\" in path or "\x00" in path:
        return False
    if not re.match(r"^[A-Za-z0-9._/-]+$", path):
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _require_str(data: dict, key: str, max_len: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"missing required field '{key}'")
    value = value.strip()
    if len(value) > max_len:
        raise ManifestError(f"'{key}' is longer than {max_len} characters")
    return value


def _optional_str(data: dict, key: str, max_len: int) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ManifestError(f"'{key}' must be a string")
    if len(value) > max_len:
        raise ManifestError(f"'{key}' is longer than {max_len} characters")
    return value.strip()


def validate_manifest(data: object, package_dir: str | None = None,
                      os_version: str | None = None) -> Manifest:
    """Validate a parsed manifest. With ``package_dir``, also check files exist."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")

    app_id = data.get("id", data.get("app_id"))
    if not is_valid_app_id(app_id):
        raise ManifestError(
            "field 'id' must be 1-48 chars of lowercase letters, digits, '-' or '_'")
    kind = _optional_str(data, "type", 16) or "app"
    if kind not in ("app", "system"):
        raise ManifestError("type must be 'app' or 'system'")
    if kind == "system" and app_id != OS_APP_ID:
        raise ManifestError(f"only '{OS_APP_ID}' may use type 'system'")
    if kind == "app" and app_id in RESERVED_IDS:
        raise ManifestError(f"app id '{app_id}' is reserved")

    name = _require_str(data, "name", 40)
    version = _require_str(data, "version", 64)
    if parse_version(version) is None:
        raise ManifestError(f"version '{version}' is not a semantic version")

    entrypoint = _require_str(data, "entrypoint", 200)
    if not is_safe_relative_path(entrypoint):
        raise ManifestError(f"entrypoint '{entrypoint}' is not a safe relative path")

    icon = _optional_str(data, "icon", 200)
    if icon and not is_safe_relative_path(icon):
        raise ManifestError(f"icon '{icon}' is not a safe relative path")

    test = _optional_str(data, "test", 200)
    if test and not is_safe_relative_path(test):
        raise ManifestError(f"test '{test}' is not a safe relative path")

    min_os = _optional_str(data, "min_os_version", 64)
    if min_os:
        required = parse_version(min_os)
        if required is None:
            raise ManifestError(f"min_os_version '{min_os}' is not a semantic version")
        current = parse_version(os_version) if os_version else None
        if current is not None and required > current:
            raise ManifestError(f"requires MFruit OS {min_os} or newer (running {os_version})")

    repository = _optional_str(data, "repository", 300)
    if repository:
        repository = normalize_repository(repository)

    exit_gesture = _optional_str(data, "exit_gesture", 20) or "quad_click"
    if exit_gesture not in VALID_EXIT_GESTURES:
        raise ManifestError(f"exit_gesture must be one of {VALID_EXIT_GESTURES}")

    priority = data.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int) or not -1000 <= priority <= 999:
        raise ManifestError("priority must be an integer between -1000 and 999")

    env = data.get("env", {}) or {}
    if not isinstance(env, dict):
        raise ManifestError("env must be an object")
    for key, value in env.items():
        if not _ENV_KEY.match(str(key)) or not isinstance(value, str) or len(value) > 1024:
            raise ManifestError(f"invalid env entry {key!r}")

    esc = data.get("disable_esc_exit_key", False)
    if not isinstance(esc, bool):
        raise ManifestError("disable_esc_exit_key must be true or false")

    manifest = Manifest(
        id=app_id, name=name, version=version, entrypoint=entrypoint,
        description=_optional_str(data, "description", 160), icon=icon,
        min_os_version=min_os, repository=repository,
        branch=_optional_str(data, "branch", 100), exit_gesture=exit_gesture,
        priority=priority, env={str(k): v for k, v in env.items()}, test=test,
        type=kind, disable_esc_exit_key=esc, raw=dict(data),
    )
    if package_dir is not None:
        _check_package_files(manifest, package_dir)
    return manifest


def _check_file_inside(package_dir: str, relative: str, label: str) -> str:
    root = os.path.realpath(package_dir)
    target = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([root, target]) != root or target == root:
        raise ManifestError(f"{label} '{relative}' escapes the package directory")
    if not os.path.isfile(target):
        raise ManifestError(f"{label} '{relative}' does not exist in the package")
    return target


def _check_package_files(manifest: Manifest, package_dir: str) -> None:
    _check_file_inside(package_dir, manifest.entrypoint, "entrypoint")
    if manifest.test:
        _check_file_inside(package_dir, manifest.test, "test")
    if manifest.icon:
        try:
            _check_file_inside(package_dir, manifest.icon, "icon")
        except ManifestError:
            manifest.icon = ""  # a missing icon is cosmetic, not fatal


def load_manifest(package_dir: str, os_version: str | None = None) -> Manifest:
    path = os.path.join(package_dir, MANIFEST_NAME)
    try:
        if os.path.getsize(path) > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest.json is too large")
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError as exc:
        raise ManifestError("manifest.json not found") from exc
    except (OSError, ValueError) as exc:
        raise ManifestError(f"manifest.json is not valid JSON: {exc}") from exc
    return validate_manifest(data, package_dir=package_dir, os_version=os_version)
