"""Handlers for control-socket commands (run on the UI thread)."""

from __future__ import annotations

import base64
import io
import os

from mfruitos import __version__

GESTURES = ("single_click", "double_click", "triple_click", "long_press", "quad_click")
ACTIONS = ("next", "previous", "select", "back", "home")


def handle(rt, cmd: str, args: dict) -> dict:
    handler = COMMANDS.get(cmd)
    if handler is None:
        return {"ok": False, "error": f"unknown command {cmd!r}", "commands": sorted(COMMANDS)}
    return handler(rt, args)


def _status(rt, args):
    return {"ok": True, "version": __version__, "focus": rt.focus.describe(),
            "screens": [type(s).__name__ for s in rt.router],
            "title": getattr(rt.router.top, "title", ""),
            "backlight": rt.backlight.state, "apps": len(rt.registry.apps()),
            "updates": rt.updater.update_count(), "direct_display": rt.direct is not None,
            "stats": dict(rt.stats, loop_wakeups=rt.loop.wakeups),
            "session": rt.apps.describe()}


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


def _jobs(rt, args):
    return {"ok": True, "active": dict(rt.tasks.active)}


def _restart(rt, args):
    rt.loop.call_later(0.2, rt.restart_launcher)
    return {"ok": True}


COMMANDS = {
    "status": _status, "ping": _status, "summon": _summon, "gesture": _gesture,
    "action": _action, "button": _button, "screenshot": _screenshot, "apps": _apps,
    "launch": _launch, "reload": _reload, "check-updates": _check, "install": _install,
    "sideload": _sideload, "jobs": _jobs, "restart": _restart,
}
