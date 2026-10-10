"""Settings > Wi-Fi > Phone Setup: PiSugar's sugar-wifi-conf, run by mFruit OS.

While this screen is in the stack the runtime keeps the tool running
(``wifi_setup.want("screen")``); the screen only shows its state and the
key a phone needs (docs/platform/ADR/0013-phone-wifi-setup.md).
"""

from __future__ import annotations

from mfruitos.launcher.ui.components import Item, back_item, section
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import ChoiceScreen, confirm
from mfruitos.system import system_info, wifi_setup

# Long form (Settings row), short form (value column of this screen).
STATUS_TEXT = {
    wifi_setup.OFF: "Off", wifi_setup.UNAVAILABLE: "Not available",
    wifi_setup.STARTING: "Starting…", wifi_setup.WAITING: "Ready for a phone",
    wifi_setup.PHONE: "Phone connected", wifi_setup.DONE: "Wi-Fi set",
    wifi_setup.FAILED: "Failed",
}
STATUS_SHORT = {
    wifi_setup.OFF: "Off", wifi_setup.UNAVAILABLE: "—", wifi_setup.STARTING: "Starting",
    wifi_setup.WAITING: "Ready", wifi_setup.PHONE: "Connected", wifi_setup.DONE: "Wi-Fi set",
    wifi_setup.FAILED: "Failed",
}
STATUS_TONE = {wifi_setup.DONE: "success", wifi_setup.FAILED: "error",
               wifi_setup.UNAVAILABLE: "warning"}
MODE_TEXT = {"screen": "This screen only", "offline": "When offline", "always": "Always"}


class PhoneSetupScreen(ListScreen):
    title = "Phone Setup"

    def __init__(self, os):
        super().__init__(os)
        self.ssid = ""
        self.ip = ""

    def on_show(self) -> None:
        self.refresh_network()

    def on_wifi_setup_change(self) -> None:
        if self.os.wifi_setup.state == wifi_setup.DONE:
            self.refresh_network()
        self.redraw()

    def refresh_network(self) -> None:
        def done(result):
            self.ip, self.ssid = result
            self.redraw()
        self.os.run_task("phone-setup-network",
                         lambda: (system_info.local_ip() or "", system_info.wifi_ssid(max_age=0) or ""),
                         done, lambda exc: None)

    def _new_key(self) -> None:
        def renew():
            self.os.wifi_setup.renew_key()
            self.os.toast("New key made")
        self.os.push(confirm(self.os, "New key?", "Phones then need the new key.", "New key",
                             renew, danger=False))

    def _mode(self) -> None:
        settings = self.os.settings
        self.os.push(ChoiceScreen(self.os, "Run it", list(MODE_TEXT.items()),
                                  settings.get("wifi_setup.mode"),
                                  lambda value: settings.set("wifi_setup.mode", value)))

    def items(self) -> list[Item]:
        service = self.os.wifi_setup
        state = service.state
        rows = [Item("Open the PiSugar app", kind="info", icon="bluetooth",
                     subtitle="and choose this device"),
                Item("Or in Chrome", kind="info", subtitle="pisugar.com/sugar-wifi-conf")]
        ok, reason = service.available()
        if not ok:
            rows += [Item("Not installed" if "install" in reason else "Not available",
                          kind="info", icon="warning", tone="warning", subtitle=reason),
                     back_item()]
            return rows
        rows += [
            Item("Device", kind="info", value=service.advertised or service.name() or "…"),
            Item("Key", kind="info", value=service.key()),
            Item("Status", kind="info", value=STATUS_SHORT.get(state, state),
                 subtitle=service.detail or None, tone=STATUS_TONE.get(state)),
            Item("Wi-Fi", kind="info", value=self.ssid or "Not connected",
                 subtitle=self.ip or None),
            section(),
            Item("Run it", self._mode, kind="nav",
                 value=MODE_TEXT.get(self.os.settings.get("wifi_setup.mode"), "")),
            Item("New key", self._new_key, icon="refresh"),
            back_item(),
        ]
        return rows
