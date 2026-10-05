"""Fruit Store: one app's page, and the uninstall / delete / reset questions.

The Fruit Store list itself is ``InstallAppScreen`` (updater.py). Every action
here asks first and then calls a shared service (``uninstall_app``,
``delete_app_data``, ``reset_app``, ``install_app_version``, ``rollback_app``),
the same ones ``mfruitctl`` uses; nothing here touches files or processes.

Removing an app takes two separate steps, each with its own question:

1. **Uninstall** removes the app from the device and keeps its data, so
   installing it again brings everything back.
2. **Delete data** removes what MFruit OS still keeps for it: the data folder,
   logs and records. Offered straight after uninstalling, and later from the
   app's page in the Fruit Store.
"""

from __future__ import annotations

import os as filesystem

from mfruitos.launcher.ui.components import Item, back_item
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import confirm

KIND_TEXT = {"os": "Installed by MFruit OS", "daemon": "Registered with whisplay-daemon"}


def ask_uninstall(os, app_id: str, after=None, after_delete=None) -> None:
    """Question 1 of 2. ``after(kept)`` runs once the app is gone, and
    ``after_delete()`` if its data is then deleted too."""
    app = os.registry.get(app_id)
    if app is None:
        return
    if app.kind == "daemon":
        folder = filesystem.path.basename(app.cwd.rstrip("/")) if app.cwd else "its folder"
        message = f"Removes {app.name} from the menu. Its own files in {folder} stay."
    else:
        message = (f"Removes {app.name} {app.version}. Its data is kept, so installing "
                   "it again brings it back.")

    def uninstall():
        def done(kept):
            os.toast(f"{app.name} uninstalled", "success")
            if after:
                after(kept)
            if kept:
                ask_delete(os, app_id, app.name, first=True, after=after_delete)
        os.uninstall_app(app_id, on_done=done)
    os.push(confirm(os, f"Uninstall {app.name}?", message, "Uninstall", uninstall))


def ask_delete(os, app_id: str, name: str, first: bool = False, after=None) -> None:
    """Question 2 of 2: delete what MFruit OS keeps for an uninstalled app."""
    message = (f"{name} is uninstalled. Also delete its data, logs and records? "
               "This cannot be undone." if first else
               f"Deletes {name}'s data, logs and records kept by MFruit OS. "
               "This cannot be undone.")

    def delete():
        def done(removed):
            os.toast(f"{name} data deleted", "success")
            if after:
                after()
        os.delete_app_data(app_id, on_done=done)
    os.push(confirm(os, f"Delete {name} data?", message, "Delete data", delete,
                    cancel_label="Keep data"))


def ask_reset(os, app_id: str) -> None:
    app = os.registry.get(app_id)
    if app is None:
        return
    message = (f"Deletes everything {app.name} saved and starts it fresh. The app stays. "
               "This cannot be undone.")
    os.push(confirm(os, f"Reset {app.name}?", message, "Reset",
                    lambda: os.reset_app(app_id, on_done=lambda n: os.toast(
                        f"{app.name} reset", "success"))))


class StoreAppScreen(ListScreen):
    """One app in the Fruit Store: installed, or uninstalled with data kept."""

    def __init__(self, os, app_id: str, catalog_item: dict | None = None):
        super().__init__(os)
        self.app_id = app_id
        self.catalog_item = catalog_item

    def on_show(self) -> None:
        app = self.os.registry.get(self.app_id)
        leftover = self.os.registry.leftover(self.app_id)
        if app is None and leftover is None:
            self.os.pop()
            return
        self.title = app.name if app else leftover.name
        self.subtitle = "Fruit Store"

    def items(self) -> list[Item]:
        app = self.os.registry.get(self.app_id)
        if app is not None:
            return self._installed(app)
        leftover = self.os.registry.leftover(self.app_id)
        if leftover is not None:
            return self._leftover(leftover)
        return [back_item()]

    def _installed(self, app) -> list[Item]:
        os = self.os
        info = os.updater.info(app.id)
        rows = [Item("Status", kind="info",
                     value="Problem" if app.broken else app.version or "Installed",
                     subtitle=app.broken or KIND_TEXT.get(app.kind, ""),
                     tone="error" if app.broken else "success")]
        rows.append(Item("Open", lambda: os.launch_app(app.id, source="store"), icon="play",
                         enabled=app.launchable,
                         data={"disabled_reason": app.broken or "App is disabled"}))
        if app.kind == "os":
            from mfruitos.updater import catalog
            newer = catalog.newer_version(self.catalog_item, app.version)
            if info and info.update_available and info.latest:
                rows.append(Item(f"Update to {info.latest}",
                                 lambda: os.install_app_version(app.id, info.latest),
                                 icon="download", tone="accent"))
            elif newer:
                # A newer pinned version in the Fruit Store list (apps without
                # GitHub releases are updated this way).
                rows.append(Item(f"Update to {newer}", lambda: os.push(confirm(
                    os, f"Update to {newer}?", f"Install {app.name} {newer} from the Fruit "
                    "Store. Its data stays, and the current version is restored if "
                    "anything fails.", "Update", lambda: os.install_catalog_app(app.id),
                    danger=False)), icon="download", tone="accent"))
            if app.previous_version:
                rows.append(Item(f"Roll back to {app.previous_version}", lambda: os.push(confirm(
                    os, "Roll back?", f"Switch {app.name} back to {app.previous_version}. "
                    "Its data stays.", "Roll back", lambda: os.rollback_app(app.id),
                    danger=False)), icon="rollback"))
            else:
                rows.append(Item("Roll back", None, icon="rollback", enabled=False,
                                 data={"disabled_reason": "No earlier version on this device"}))
        rows.append(Item("Updates and versions", lambda: os.open_app_updates(app.id),
                         kind="nav", icon="updater"))
        if app.kind == "os":
            rows.append(Item("Reset app", lambda: ask_reset(os, app.id), kind="danger",
                             icon="refresh", subtitle="Delete its data; keep the app"))
        rows.append(Item("Uninstall", lambda: ask_uninstall(
            os, app.id, after=lambda kept: kept or self._leave(),
            after_delete=self._leave), kind="danger",
                         icon="trash", subtitle="Data is kept until you delete it"))
        rows.append(back_item())
        return rows

    def _leave(self) -> None:
        """Back to the Fruit Store once this app is gone (only if still shown)."""
        if self.os.router_top() is self:
            self.os.pop()

    def _leftover(self, leftover) -> list[Item]:
        os = self.os
        rows = [Item("Status", kind="info", value="Uninstalled", tone="muted",
                     subtitle="Its data is kept on this device")]
        if self.catalog_item is not None:
            rows.append(Item("Install again", lambda: os.push(confirm(
                os, f"Install {leftover.name}?", "Download and install it again. "
                "Its kept data is used.", "Install",
                lambda: os.install_catalog_app(leftover.id), danger=False)),
                icon="download", tone="accent"))
        rows.append(Item("Delete data", lambda: ask_delete(os, leftover.id, leftover.name,
                                                           after=self._leave),
                         kind="danger", icon="trash", subtitle="Cannot be undone"))
        rows.append(back_item())
        return rows
