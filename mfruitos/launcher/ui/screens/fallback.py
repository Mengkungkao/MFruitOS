"""Shown (via direct display) when whisplay-daemon is not running."""

from __future__ import annotations

from mfruitos.launcher.ui.components import Item
from mfruitos.launcher.ui.screens.dialogs import MessageScreen
from mfruitos.system import diagnostics


class DaemonUnavailableScreen(MessageScreen):
    def __init__(self, os, unit_state: str):
        actions = [
            Item("Retry", lambda: os.retry_daemon(restart=False), icon="refresh"),
            Item("Restart daemon", lambda: os.retry_daemon(restart=True), icon="power"),
            Item("Diagnostics", self._diagnostics, kind="nav", icon="diagnostics"),
        ]
        super().__init__(os, "Hardware service unavailable",
                         f"The service is {unit_state}. Apps need it to run.",
                         actions, tone="error", icon="warning", page="Daemon")

    def handle(self, action: str) -> bool:
        if action in ("back", "home"):
            return True  # nowhere to go back to
        return super().handle(action)

    def _diagnostics(self) -> None:
        results = [diagnostics.check_network(), diagnostics.check_storage(self.os.paths.home),
                   diagnostics.check_audio()]
        lines = [f"{'OK ' if r.ok else 'ERR'} {r.name}: {r.detail}" for r in results]
        lines.append("Logs: journalctl -u whisplay-daemon")
        self.os.show_message("Diagnostics", "\n".join(lines))
