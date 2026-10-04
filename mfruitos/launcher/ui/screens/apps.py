"""Settings > Applications and the per-app detail screen."""

from __future__ import annotations

from mfruitos.apps.registry import AppEntry
from mfruitos.launcher.ui.components import Item, back_item
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import LogScreen, MessageScreen, confirm

STATUS_TAGS = {
    "broken": ("Broken", "error"),
    "disabled": ("Off", "muted"),
    "running": ("Running", "success"),
    "update": ("Update", "accent"),
    "installed": ("On", None),
}
KIND_LABELS = {"os": "Package", "daemon": "Daemon app", "system": "Daemon page"}


def status_tag(app: AppEntry) -> tuple[str, str | None]:
    label, tone = STATUS_TAGS[app.status()]
    if app.status() == "installed" and app.hidden:
        return ("Hidden", "muted")
    return label, tone


class ApplicationsScreen(ListScreen):
    title = "Applications"

    def on_show(self) -> None:
        self.subtitle = f"{len(self.os.registry.apps())} installed"

    def items(self) -> list[Item]:
        rows = []
        for app in self.os.registry.apps():
            label, tone = status_tag(app)
            rows.append(Item(app.name, lambda a=app.id: self.os.push(AppDetailScreen(self.os, a)),
                             kind="nav", value=label, tone=tone, data={"id": app.id}))
        rows.append(back_item())
        return rows


class AppDetailScreen(ListScreen):
    def __init__(self, os, app_id: str):
        super().__init__(os)
        self.app_id = app_id

    @property
    def app(self) -> AppEntry | None:
        return self.os.registry.get(self.app_id)

    def on_show(self) -> None:
        app = self.app
        if app is None:
            self.os.pop()
            return
        self.title = app.name
        self.subtitle = app.version or ""

    def handle(self, action: str) -> bool:
        if self.app is None:
            self.os.pop()
            return True
        return super().handle(action)

    def items(self) -> list[Item]:
        app = self.app
        if app is None:
            return [back_item()]
        os = self.os
        settings = os.settings
        label, tone = status_tag(app)
        kind = KIND_LABELS.get(app.kind, "")
        rows = [Item("Status", kind="info", value=label, tone=tone,
                     subtitle=f"{kind} · {app.version}" if app.version else kind)]
        if app.broken:
            rows.append(Item("Problem", kind="info", subtitle=app.broken, tone="error", icon="warning"))
        rows.append(Item("Open", lambda: os.launch_app(app.id, source="settings"), icon="play",
                         enabled=app.launchable,
                         data={"disabled_reason": "App is disabled" if not app.enabled else app.broken}))
        rows.append(Item("Enabled", self._toggle_enabled, kind="toggle", value=app.enabled))
        rows.append(Item("Show on Home", lambda: self._flag("hidden", not app.hidden),
                         kind="toggle", value=not app.hidden))
        rows.append(Item("Default app", self._toggle_default, kind="toggle",
                         value=settings.get("apps.default_app") == app.id))
        rows.append(Item("Autostart", lambda: self._flag("autostart", not app.autostart),
                         kind="toggle", value=app.autostart))
        rows.append(Item("Keep running", lambda: self._flag("background", not app.background),
                         kind="toggle", value=app.background,
                         subtitle="Stays on when you leave it" if app.background
                         else "Closed completely when you leave it"))
        rows.append(Item("Keep screen bright", lambda: self._flag("screen_bright", not app.screen_bright),
                         kind="toggle", value=app.screen_bright,
                         subtitle="100% while it runs in background" if app.screen_bright
                         else "Dims as usual in background"))
        rows.append(Item("Move up", lambda: self._move(-1), icon="up"))
        rows.append(Item("Move down", lambda: self._move(1), icon="down"))
        if app.running:
            rows.append(Item("Stop", self._stop, icon="stop"))
            if app.kind == "os":
                rows.append(Item("Force stop", self._force_stop, kind="danger", icon="stop"))
        rows.append(Item("Logs", lambda: os.push(LogScreen(os, f"{app.name} log",
                                                           os.lifecycle.log_path(app))),
                         kind="nav", icon="list"))
        if app.kind in ("os", "daemon"):
            rows.append(Item("Updates", lambda: os.open_app_updates(app.id), kind="nav",
                             icon="updater",
                             value="Available" if app.update_available else None, tone="accent"))
        if app.kind in ("os", "daemon"):
            rows.append(Item("Uninstall", self._uninstall, kind="danger", icon="trash"))
        rows.append(back_item())
        return rows

    # ------------------------------------------------------------ actions
    def _flag(self, flag: str, value: bool) -> None:
        self.os.settings.set_app_flag(self.app_id, flag, value)
        self.os.refresh_registry(query_daemon=False)

    def _toggle_enabled(self) -> None:
        app = self.app
        self._flag("enabled", not app.enabled)
        self.os.toast("Enabled" if not app.enabled else "Disabled — hidden from Home")

    def _toggle_default(self) -> None:
        settings = self.os.settings
        current = settings.get("apps.default_app")
        settings.set("apps.default_app", "" if current == self.app_id else self.app_id)

    def _move(self, delta: int) -> None:
        if self.os.registry.move(self.app_id, delta):
            self.os.refresh_registry(query_daemon=False)
            self.os.toast("Moved up" if delta < 0 else "Moved down")
        else:
            self.os.toast("Already at the " + ("top" if delta < 0 else "bottom"))

    def _stop(self) -> None:
        if self.os.lifecycle.request_stop(self.app):
            self.os.toast("Stop requested")
            self.os.loop.call_later(2.0, lambda: self.os.refresh_registry(query_daemon=True))
        else:
            self.os.toast("Daemon did not accept the request", "error")

    def _force_stop(self) -> None:
        app = self.app

        def run():
            return self.os.lifecycle.force_stop(app)

        def done(stopped):
            self.os.toast("Stopped" if stopped else "Not running")
            self.os.refresh_registry(query_daemon=True)
        self.os.push(confirm(self.os, "Force stop?",
                             f"{app.name} will be terminated without saving.", "Force stop",
                             lambda: self.os.run_task("force-stop", run, done)))

    def _uninstall(self) -> None:
        """The Fruit Store's two questions: uninstall (data kept), then delete."""
        from mfruitos.launcher.ui.screens.store import ask_uninstall
        ask_uninstall(self.os, self.app_id,
                      after=lambda kept: self.os.pop_to_type(ApplicationsScreen))
