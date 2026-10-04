"""Handlers for control-socket commands (run on the UI thread)."""

from __future__ import annotations

import base64
import io
import logging
import os

from mfruitos import __version__

log = logging.getLogger("mfruitos.control")
# app.background: the per-app flags an app may change for itself, by request name.
APP_BACKGROUND_FLAGS = {"keep_running": "background", "screen_bright": "screen_bright"}

GESTURES = ("single_click", "double_click", "triple_click", "long_press", "quad_click")
ACTIONS = ("next", "previous", "select", "back", "home")
# Keyboard key -> its Linux key code, for "key": a press and release through
# the same path a real keyboard takes (Runtime._on_key).
KEY_CODES = {"up": 103, "down": 108, "left": 105, "right": 106, "tab": 15, "enter": 28,
             "escape": 1, "home": 102, "space": 57}


def handle(rt, cmd: str, args: dict) -> dict:
    handler = COMMANDS.get(cmd)
    if handler is None:
        return {"ok": False, "error": f"unknown command {cmd!r}", "commands": sorted(COMMANDS)}
    return handler(rt, args)


def _status(rt, args):
    return {"ok": True, "version": __version__, "focus": rt.focus.describe(),
            "screens": [type(s).__name__ for s in rt.router],
            "title": getattr(rt.router.top, "title", ""),
            "backlight": rt.backlight.state, "backlight_hold": rt.backlight.hold,
            "apps": len(rt.registry.apps()),
            "updates": rt.updater.update_count(), "direct_display": rt.direct is not None,
            "stats": dict(rt.stats, loop_wakeups=rt.loop.wakeups),
            "session": rt.apps.describe(), "keyboards": rt.keyboard.devices}


def _summon(rt, args):
    rt.lifecycle.set_gate("gate")
    rt.focus.summon()
    return {"ok": True}


def _gesture(rt, args):
    name = args.get("name", "")
    if name not in GESTURES:
        return {"ok": False, "error": f"gesture must be one of {GESTURES}"}
    rt._on_gesture(name)
    return {"ok": True}


def _action(rt, args):
    name = args.get("name", "")
    if name not in ACTIONS:
        return {"ok": False, "error": f"action must be one of {ACTIONS}"}
    rt.dispatch(name)
    return {"ok": True}


def _button(rt, args):
    """Raw press/release, exercising the real gesture recognizer."""
    rt._on_raw_button(bool(args.get("pressed")))
    return {"ok": True}


def _key(rt, args):
    """A key press and release, as if typed on a keyboard on the board: routed
    to whoever owns the screen, MFruit OS or the foreground app."""
    from mfruitos.sdk.keys import DOWN, UP, KeyEvent
    name = args.get("name", "")
    code = KEY_CODES.get(name)
    if code is None:
        return {"ok": False, "error": f"key must be one of {sorted(KEY_CODES)}"}
    rt._on_hardware_key(KeyEvent("key", name, DOWN, code))
    rt._on_hardware_key(KeyEvent("key", name, UP, code))
    return {"ok": True}


def _screenshot(rt, args):
    image = rt.compose()
    path = args.get("path")
    if path:
        image.save(os.path.expanduser(path))
        return {"ok": True, "path": path}
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {"ok": True, "png_base64": base64.b64encode(buffer.getvalue()).decode()}


def _apps(rt, args):
    return {"ok": True, "apps": [
        {"id": a.id, "name": a.name, "kind": a.kind, "version": a.version, "status": a.status(),
         "enabled": a.enabled, "hidden": a.hidden, "running": a.running, "broken": a.broken}
        for a in rt.registry.apps()]}


def _launch(rt, args):
    app_id = args.get("app_id", "")
    if rt.registry.get(app_id) is None:
        return {"ok": False, "error": f"unknown app {app_id!r}"}
    if rt.apps.busy:
        rt.apps.request_launch(app_id, "app", "control")  # refused and logged
        return {"ok": False, "error": f"busy: {rt.apps.describe()}"}
    rt.router.home()
    return {"ok": rt.launch_app(app_id, source="control")}


def _reload(rt, args):
    rt.refresh_registry(query_daemon=True)
    return {"ok": True, "apps": len(rt.registry.apps())}


def _check(rt, args):
    rt.check_updates(quiet=False)
    return {"ok": True, "message": "update check started"}


def _install(rt, args):
    repo = args.get("repository", "")
    if not repo:
        return {"ok": False, "error": "repository required"}
    rt.router.home()
    rt.install_from_repository(repo)
    return {"ok": True, "message": "install started; progress is shown on the device"}


def _sideload(rt, args):
    path = os.path.abspath(os.path.expanduser(args.get("path", "")))
    if not os.path.exists(path):
        return {"ok": False, "error": f"{path} does not exist"}
    rt.router.home()
    rt.sideload(path)
    return {"ok": True, "message": "install started; progress is shown on the device"}


def _catalog(rt, args):
    """List the curated catalogue, or install/repair one entry (the App
    installer's Install and Repair, from a shell)."""
    from mfruitos.updater import catalog
    app_id = args.get("app_id", "")
    if not app_id:
        rows = []
        home = getattr(getattr(rt, "paths", None), "home", None)
        for item in catalog.entries():
            entry = rt.registry.get(item["id"])
            status = "available" if entry is None else "broken" if entry.broken else "installed"
            rows.append({"id": item["id"], "name": item["name"], "status": status,
                         "detail": entry.broken if entry is not None and entry.broken else "",
                         "requires": catalog.requirements(item),
                         "missing": catalog.missing_requirements(item, home)})
        return {"ok": True, "catalog": rows}
    try:
        catalog.get(app_id)
    except catalog.CatalogError as exc:
        return {"ok": False, "error": str(exc)}
    entry = rt.registry.get(app_id)
    if entry is not None and entry.running:
        return {"ok": False, "error": f"{app_id} is running; stop it first"}
    if rt.tasks.busy("jobs"):
        return {"ok": False, "error": f"busy: {rt.tasks.active.get('jobs')}"}
    rt.router.home()
    rt.install_catalog_app(app_id)
    return {"ok": True, "message": "install started; progress is shown on the device; "
                                   "follow it with 'mfruitctl jobs'"}


def _package_action(rt, args, action: str):
    """uninstall / delete / reset / rollback: the Fruit Store's actions from a
    shell, through the same services, without the questions (the shell user
    asked explicitly)."""
    app_id = args.get("app_id", "")
    if not app_id:
        return {"ok": False, "error": "app id required"}
    if rt.tasks.busy("jobs"):
        return {"ok": False, "error": f"busy: {rt.tasks.active.get('jobs')}"}
    entry = rt.registry.get(app_id)
    if action == "delete":
        if entry is not None:
            return {"ok": False, "error": f"{app_id} is installed; uninstall it first"}
        if rt.registry.leftover(app_id) is None:
            return {"ok": False, "error": f"nothing is kept for {app_id}"}
        started = rt.delete_app_data(app_id)
    elif entry is None:
        return {"ok": False, "error": f"{app_id} is not installed"}
    elif action == "uninstall":
        started = rt.uninstall_app(app_id)
    elif action == "reset":
        started = rt.reset_app(app_id)
    else:
        if not entry.previous_version:
            return {"ok": False, "error": f"{app_id} has no earlier version to roll back to"}
        rt.router.home()
        started = rt.rollback_app(app_id)
    if not started:
        return {"ok": False, "error": f"{action} refused for {app_id} (see the launcher log)"}
    return {"ok": True, "message": f"{action} started; follow it with 'mfruitctl jobs' and "
                                   "'mfruitctl apps'"}


def _app_background(rt, args):
    """An app reads or changes its own *Keep running* and *Keep screen bright*
    (SDK ``background``, ADR 0009). No other flag, no other effect.

    The control socket is the user's own (mode 0600); MFruit OS cannot tell
    which of the user's processes asks, so this is a convenience contract, not
    a permission boundary (docs/platform/SECURITY.md)."""
    app_id = args.get("app_id")
    entry = rt.registry.get(app_id) if isinstance(app_id, str) else None
    if entry is None or entry.kind == "system":
        return {"ok": False, "error": f"unknown app {app_id!r}"}
    changes = {}
    for name, flag in APP_BACKGROUND_FLAGS.items():
        if name in args:
            if not isinstance(args[name], bool):
                return {"ok": False, "error": f"{name} must be true or false"}
            changes[flag] = args[name]
    if changes:
        for flag, value in changes.items():
            rt.settings.set_app_flag(app_id, flag, value)
        log.info("APP_BACKGROUND app=%s %s (requested by the app)", app_id,
                 " ".join(f"{k}={v}" for k, v in changes.items()))
        rt.refresh_registry(query_daemon=False)
        entry = rt.registry.get(app_id) or entry
    return {"ok": True, "app_id": app_id, "keep_running": entry.background,
            "screen_bright": entry.screen_bright}


def _jobs(rt, args):
    return {"ok": True, "active": dict(rt.tasks.active)}


def _restart(rt, args):
    rt.loop.call_later(0.2, rt.restart_launcher)
    return {"ok": True}


COMMANDS = {
    "status": _status, "ping": _status, "summon": _summon, "gesture": _gesture,
    "action": _action, "button": _button, "key": _key, "screenshot": _screenshot,
    "apps": _apps,
    "launch": _launch, "reload": _reload, "check-updates": _check, "install": _install,
    "sideload": _sideload, "catalog": _catalog, "jobs": _jobs, "restart": _restart,
    "app.background": _app_background,
    "uninstall": lambda rt, args: _package_action(rt, args, "uninstall"),
    "delete": lambda rt, args: _package_action(rt, args, "delete"),
    "reset": lambda rt, args: _package_action(rt, args, "reset"),
    "rollback": lambda rt, args: _package_action(rt, args, "rollback"),
}
