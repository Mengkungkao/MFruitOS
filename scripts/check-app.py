#!/usr/bin/env python3
"""Read-only preflight for a native MFruit OS app source/release directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys

# Validation must not leave bytecode in either the OS or the app being checked.
if __name__ == "__main__":
    sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mfruitos import __version__  # noqa: E402
from mfruitos.apps.manifest import ManifestError, load_manifest  # noqa: E402

# Each app carries a byte-identical copy of the canonical app contract.
RULES_PATH = Path(".claude/rules/mfruit-os-app.md")
CONTRACT_PATH = Path("docs/apps/APP_CONTRACT.md")
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
              ".venv", "node_modules"}
ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}


def _inside(path: Path, root: Path) -> bool:
    return os.path.commonpath((root, path.resolve())) == str(root)


def _sdk_files(root: Path) -> dict[str, bytes]:
    result = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in CACHE_DIRS)
        for name in sorted(names):
            if name == "VENDORED" or name.endswith((".pyc", ".pyo")):
                continue
            path = Path(folder) / name
            if not _inside(path, root) or not path.is_file():
                raise ValueError(f"invalid SDK file: {path.relative_to(root)}")
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def check_package(directory: str | Path) -> list[str]:
    """Return actionable errors without importing or running any app code."""
    errors = []
    try:
        root = Path(directory).resolve()
    except (OSError, RuntimeError) as exc:
        return [f"cannot resolve package directory: {exc}"]
    if not root.is_dir():
        return [f"package directory not found: {root}"]
    try:
        if not _inside(root / "manifest.json", root):
            return ["manifest.json must be inside the package"]
        manifest = load_manifest(str(root), os_version=__version__)
    except (ManifestError, OSError, RuntimeError) as exc:
        return [str(exc)]

    if manifest.type != "app":
        errors.append("manifest type must be 'app' for this app preflight")
    if manifest.exit_gesture != "none":
        errors.append("manifest exit_gesture must be 'none' (the app owns Back)")
    if not manifest.disable_esc_exit_key:
        errors.append("manifest disable_esc_exit_key must be true (the app owns Esc)")
    if not manifest.test:
        errors.append("manifest must declare a fast, non-interactive 'test' hook")
    if manifest.raw.get("icon") and not manifest.icon:
        errors.append("declared icon must exist inside the package")

    hooks = {manifest.entrypoint}
    if manifest.test:
        hooks.add(manifest.test)
    hooks.update(name for name in ("install.sh", "update.sh", "uninstall.sh")
                 if (root / name).exists())
    for name in sorted(hooks):
        path = root / name
        try:
            if not _inside(path, root) or not path.is_file():
                errors.append(f"{name}: hook must be a file inside the package")
                continue
            if not path.stat().st_mode & stat.S_IXUSR:
                errors.append(f"{name}: hook must be executable (chmod +x)")
            data = path.read_bytes()
            if b"\r" in data:
                errors.append(f"{name}: hook must use LF line endings")
            if not data.startswith(b"#!"):
                errors.append(f"{name}: hook needs an interpreter shebang")
        except (OSError, RuntimeError) as exc:
            errors.append(f"{name}: cannot inspect hook: {exc}")

    sdk_dirs = []
    try:
        for folder, dirs, names in os.walk(root):
            # A source checkout may be checked directly; Git metadata is not payload.
            dirs[:] = sorted(d for d in dirs if d != ".git")
            for name in sorted(dirs + names):
                path = Path(folder) / name
                relative = path.relative_to(root).as_posix()
                if not _inside(path, root):
                    errors.append(f"{relative}: link escapes the package")
                    continue
                if name in CACHE_DIRS or name.endswith((".pyc", ".pyo")) or name == ".DS_Store":
                    errors.append(f"{relative}: exclude generated cache/dependency artifacts")
                if (name == ".env" or name.startswith(".env.")) and name not in ENV_EXAMPLES:
                    errors.append(f"{relative}: exclude live environment files; ship .env.example instead")
                if name == "mfruit_sdk" and path.is_dir():
                    sdk_dirs.append(path)
            dirs[:] = [d for d in dirs if d not in CACHE_DIRS and not (Path(folder) / d).is_symlink()]

        if not sdk_dirs:
            errors.append("missing vendored mfruit_sdk; copy it with scripts/sdk-sync.sh")
        canonical = _sdk_files(ROOT / "mfruitos/sdk")
        for sdk in sdk_dirs:
            if _sdk_files(sdk) != canonical:
                errors.append(f"{sdk.relative_to(root)}: SDK differs; run scripts/sdk-sync.sh {sdk.parent}")

        rules = root / RULES_PATH
        if not rules.is_file():
            errors.append(f"missing {RULES_PATH}; copy docs/apps/APP_CONTRACT.md from MFruit OS")
        elif not _inside(rules, root):
            errors.append(f"{RULES_PATH}: rules must be inside the package")
        elif rules.read_bytes() != (ROOT / CONTRACT_PATH).read_bytes():
            errors.append(f"{RULES_PATH}: differs from MFruit OS docs/apps/APP_CONTRACT.md")
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"cannot inspect package contents: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only package preflight: manifest, hooks, SDK, app rules and common packaging artifacts.",
        epilog="No app code or package scripts are executed. Git metadata is ignored; other contents are checked. "
               "This is not a secret scanner or production certification. Run the declared smoke test and "
               "controls/rendering tests separately, then verify launch/exit, UI and physical hardware on the device.",
    )
    parser.add_argument("package_dir", help="native app directory containing manifest.json")
    args = parser.parse_args()
    errors = check_package(args.package_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"App preflight failed ({len(errors)} issue(s)).", file=sys.stderr)
        return 1
    print(f"App package preflight passed: {Path(args.package_dir).resolve()}")
    print("Still required: smoke test, controls/rendering tests, and device launch/exit and hardware checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
