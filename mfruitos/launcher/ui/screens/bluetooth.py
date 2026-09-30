"""Bluetooth screens. Blocking BlueZ operations run on one worker lane."""

from __future__ import annotations

from mfruitos.launcher.ui.components import Item, back_item, section
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import MessageScreen, confirm
from mfruitos.system.bluetooth import Prompt, named


class BluetoothScreen(ListScreen):
    title = "Bluetooth"

    def __init__(self, os):
        super().__init__(os)
        self.available = False
        self.powered = False
        self.devices = []
        self.busy = False
        self.status = "Checking…"
        self._shown = False

    def on_show(self):
        # Search once per screen visit; returning from a device refreshes its
        # state without starting another eight-second search.
        search = not self._shown
        self._shown = True
        self.refresh(search)

    def refresh(self, search=False):
        if self.busy:
            return
        self.busy = True
        self.status = "Checking…"

        def read():
            bt = self.os.bluetooth
            available = bt.available()
            powered = available and bt.powered()
            return available, powered, bt.devices() if powered else []

        def done(result):
            self.available, self.powered, self.devices = result
            self.busy = False
            self.status = "" if self.available else "Bluetooth unavailable"
            self.redraw()
            if search and self.powered and self.os.router_top() is self:
                self.search()
        self.os.run_task("bluetooth-status", read, done, self.failed, lane="bluetooth")

    def failed(self, exc):
        self.busy = False
        self.status = str(exc)[:80] or "Bluetooth unavailable"
        self.redraw()

    def search(self):
        if self.busy or not self.powered:
            return
        self.busy = True
        self.status = "Searching…"
        self.redraw()

        def work():
            self.os.bluetooth.search()
            return self.os.bluetooth.devices()

        def done(devices):
            self.devices = devices
            self.busy = False
            self.status = "Search complete"
            self.redraw()
        self.os.run_task("bluetooth-search", work, done, self.failed, lane="bluetooth")

    def toggle(self):
        if self.busy:
            return
        target = not self.powered
        self.busy = True
        self.status = "Turning on…" if target else "Turning off…"

        def done(_):
            self.busy = False
            self.refresh(search=target)
        self.os.run_task("bluetooth-power", lambda: self.os.bluetooth.set_powered(target),
                         done, self.failed, lane="bluetooth")

    def items(self):
        rows = [Item("Bluetooth", self.toggle, kind="toggle", value=self.powered,
                     enabled=self.available and not self.busy, icon="bluetooth")]
        if self.status:
            rows.append(Item(self.status, kind="info", tone="muted"))
        if self.powered:
            rows.append(section("My devices"))
            paired = [d for d in self.devices if d.paired]
            rows.extend(self.device_row(d) for d in paired)
            if not paired:
                rows.append(Item("No paired devices", kind="info", tone="muted"))
            rows.append(section("Other devices"))
            others = [d for d in self.devices if not d.paired and named(d)]
            rows.extend(self.device_row(d) for d in others)
            if not others:
                rows.append(Item("Make your device discoverable", kind="info", tone="muted"))
            rows.append(Item("Search again", self.search, icon="refresh", enabled=not self.busy))
        rows.append(back_item())
        return rows

    def device_row(self, device):
        status = "Connected" if device.connected else "Not connected" if device.paired else "Tap to pair"
        subtitle = " · ".join(part for part in (device.kind, status) if part)
        return Item(device.name or device.address,
                    lambda: self.os.push(BtDeviceScreen(self.os, device)),
                    kind="nav", subtitle=subtitle, icon="bluetooth",
                    data={"id": device.address})


class BtDeviceScreen(ListScreen):
    title = "Device"

    def __init__(self, os, device):
        super().__init__(os)
        self.device = device
        self.busy = False
        self.status = ""
        self.prompt_screen = None

    @property
    def modal(self):
        return self.busy

    def items(self):
        d = self.device
        rows = [Item(d.name or d.address, kind="info", subtitle=d.kind or d.address),
                Item(self.status or ("Connected" if d.connected else "Not connected"), kind="info"),
                section()]
        if self.busy:
            rows.append(Item("Please wait…", kind="info"))
        elif d.paired:
            rows.append(Item("Disconnect" if d.connected else "Connect",
                             lambda: self.operate("disconnect" if d.connected else "connect"),
                             icon="bluetooth"))
            rows.append(Item("Forget This Device", self.forget, kind="danger", icon="trash"))
        else:
            rows.append(Item("Pair", lambda: self.operate("pair"), icon="bluetooth"))
        if not self.busy:
            rows.append(back_item())
        return rows

    def forget(self):
        self.os.push(confirm(self.os, "Forget this device?",
                             "You will need to pair it again to reconnect.", "Forget",
                             lambda: self.operate("forget")))

    def operate(self, action):
        if self.busy:
            return
        self.busy = True
        self.status = {"pair": "Pairing…", "connect": "Connecting…",
                       "disconnect": "Disconnecting…", "forget": "Forgetting…"}[action]
        bt = self.os.bluetooth
        bt.on_prompt = lambda prompt: self.os.loop.post(self.on_prompt, prompt)
        self.redraw()

        def work():
            result = getattr(bt, action)(self.device.address)
            devices = bt.devices()
            return result, devices

        def done(result):
            (ok, message), devices = result
            self.finish()
            self.status = message
            if ok and action == "forget":
                self.os.pop()
            else:
                self.device = next((d for d in devices if d.address == self.device.address), self.device)
                self.os.toast(message, "success" if ok else "error")
            self.redraw()

        def failed(exc):
            self.finish()
            self.status = str(exc)[:80] or "Bluetooth operation failed"
            self.redraw()
        self.os.run_task("bluetooth-" + action, work, done, failed, lane="bluetooth")

    def finish(self):
        self.on_prompt(Prompt("done"))
        self.os.bluetooth.on_prompt = lambda prompt: None
        self.busy = False

    def on_prompt(self, prompt):
        if prompt.kind == "done":
            if self.prompt_screen is not None and self.os.router_top() is self.prompt_screen:
                self.os.pop()
            self.prompt_screen = None
            return
        if not self.busy or self not in list(self.os.router):
            self.os.bluetooth.answer(False)
            return
        screen = PairingScreen(self.os, prompt)
        if self.prompt_screen is not None and self.os.router_top() is self.prompt_screen:
            self.os.router.replace(screen)
        else:
            self.os.push(screen)
        self.prompt_screen = screen


class PairingScreen(MessageScreen):
    modal = True

    def __init__(self, os, prompt):
        self.prompt = prompt
        if prompt.kind == "confirm":
            message = f"Does {prompt.code} match the code on your device?"
            actions = [Item("No", lambda: self.answer(False)), Item("Yes", lambda: self.answer(True))]
        else:
            message = f"Type {prompt.code} on the keyboard, then press Enter."
            actions = [Item("Cancel pairing", os.bluetooth.cancel_pairing)]
        super().__init__(os, "Pairing", message, actions)

    def answer(self, accept):
        self.os.bluetooth.answer(accept)
        self.message = "Finishing pairing…" if accept else "Cancelling…"
        self.actions = [Item("Please wait…", kind="info")]
        self.redraw()

    def handle(self, action):
        if action in ("back", "home"):
            self.os.bluetooth.cancel_pairing()
            return True
        return super().handle(action)
