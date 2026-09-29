"""Logging setup: launcher.log, updater.log and stderr (journald under systemd)."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
MAX_LOG_BYTES = 512 * 1024
LOG_BACKUPS = 2

_file_handlers: list[logging.Handler] = []


def _file_handler(path: str) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def setup_logging(logs_dir: str | None, debug: bool = False, stderr: bool = True) -> None:
    """Configure the ``mfruitos`` logger tree. Safe to call more than once."""
    root = logging.getLogger("mfruitos")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    updater = logging.getLogger("mfruitos.updater")
    for handler in list(updater.handlers):
        updater.removeHandler(handler)
        handler.close()
    _file_handlers.clear()

    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False
    if not stderr and not logs_dir:
        # Silence Python's last-resort stderr handler (e.g. during --self-test).
        root.addHandler(logging.NullHandler())
    if stderr:
        stream = logging.StreamHandler(sys.stderr)
        # journald adds its own timestamp.
        stream.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
        root.addHandler(stream)
    if logs_dir:
        os.makedirs(logs_dir, exist_ok=True)
        launcher = _file_handler(os.path.join(logs_dir, "launcher.log"))
        root.addHandler(launcher)
        _file_handlers.append(launcher)
        # Updater activity is also kept in its own file for easy review.
        updater_file = _file_handler(os.path.join(logs_dir, "updater.log"))
        updater.addHandler(updater_file)
        _file_handlers.append(updater_file)


def set_debug(enabled: bool) -> None:
    logging.getLogger("mfruitos").setLevel(logging.DEBUG if enabled else logging.INFO)


def rotate_if_large(path: str, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Rotate a plain append-only log (per-app logs written by mfruit-run)."""
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
    except FileNotFoundError:
        pass
    except OSError as exc:
        logging.getLogger("mfruitos.logs").warning("Could not rotate %s: %s", path, exc)


def tail(path: str, max_lines: int = 60, max_bytes: int = 16384) -> list[str]:
    """Return the last lines of a text file without reading all of it."""
    try:
        with open(path, "rb") as fp:
            fp.seek(0, os.SEEK_END)
            size = fp.tell()
            fp.seek(max(0, size - max_bytes))
            data = fp.read()
    except FileNotFoundError:
        return []
    except OSError as exc:
        return [f"Cannot read log: {exc}"]
    lines = data.decode("utf-8", "replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # first line is probably partial
    return lines[-max_lines:]
