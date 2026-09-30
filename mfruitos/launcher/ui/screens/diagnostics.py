"""Diagnostics, hardware tests and system information."""

from __future__ import annotations

from mfruitos import OS_NAME, __version__
from mfruitos.launcher.ui.components import FOOTER_Y, Item, back_item
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.screens.base import ListScreen, Screen
from mfruitos.launcher.ui.theme import SCREEN_H, SCREEN_W
from mfruitos.launcher.navigation.gestures import gesture_label
from mfruitos.system import diagnostics, system_info

CHECK_ORDER = ("Hardware service", "Hardware desktop", "Display", "Button", "Keyboard", "RGB LED",
               "Audio", "Network", "Storage", "Internet", "GitHub")


class DiagnosticsScreen(ListScreen):
    title = "Diagnostics"

    def __init__(self, os):
        super().__init__(os)
        self.results: dict[str, diagnostics.CheckResult] = {}
        self.running = False

    def on_show(self) -> None:
        if not self.results and not self.running:
            self.run_all()

    def run_all(self) -> None:
        self.running = True
        self.subtitle = "Running…"
        os = self.os

        def work():
            client = os.client
            results = [
                diagnostics.check_daemon(client),
                diagnostics.check_daemon_ui(),
                diagnostics.check_display(os.focus.has_focus),
                diagnostics.check_button(client),
                diagnostics.check_keyboard(os.keyboard.devices),
                diagnostics.check_led(client, os.led.current),
                diagnostics.check_audio(),
                diagnostics.check_network(),
                diagnostics.check_storage(os.paths.home),
                diagnostics.check_internet(),
            ]
            results.append(diagnostics.check_github(os.github) if results[-1].ok else
                           diagnostics.CheckResult("GitHub", False, "no internet"))
            return results

        def done(results):
            self.results = {r.name: r for r in results}
            self.running = False
            failures = sum(1 for r in results if r.ok is False)
            self.subtitle = "All good" if not failures else f"{failures} problem(s)"
            self.redraw()
        self.os.run_task("diagnostics", work, done)

    def _check_row(self, name: str) -> Item:
        result = self.results.get(name)
        if result is None:
            return Item(name, kind="info", icon="dot", tone="muted",
                        value="…" if self.running else "")
        icon, tone = {True: ("check", "success"), False: ("cross", "error"),
                      None: ("dot", "muted")}[result.ok]
        return Item(name, kind="info", icon=icon, tone=tone, value=result.detail[:22])

    def items(self) -> list[Item]:
        os = self.os
        rows = [self._check_row(name) for name in CHECK_ORDER]
        rows += [
            Item("Test display", lambda: os.push(DisplayTestScreen(os)), kind="nav", icon="display"),
            Item("Test button", os.open_button_test, kind="nav", icon="button"),
            Item("Test LED", os.test_led, icon="led"),
            Item("Test speaker", os.test_speaker, icon="audio"),
            Item("Check daemon", lambda: self._single(lambda: diagnostics.check_daemon(os.client)),
                 icon="system"),
            Item("Check internet", lambda: self._single(diagnostics.check_internet), icon="network"),
            Item("Check GitHub", lambda: self._single(lambda: diagnostics.check_github(os.github)),
                 icon="download"),
            Item("Run all again", self.run_all, icon="refresh", enabled=not self.running),
            back_item(),
        ]
        return rows

    def _single(self, check) -> None:
        def done(result):
            self.results[result.name] = result
            self.os.toast(f"{result.name}: {'OK' if result.ok else result.detail[:24]}",
                          "success" if result.ok else "error")
        self.os.run_task("check", check, done)


class DisplayTestScreen(Screen):
    """Full-screen colour cycle through the daemon framebuffer. Any input exits."""
    show_status = False
    COLORS = [((255, 0, 0), "Red"), ((0, 255, 0), "Green"), ((0, 0, 255), "Blue"),
              ((255, 255, 255), "White"), ((0, 0, 0), "Black"), (None, "Gradient")]

    def __init__(self, os):
        super().__init__(os)
        self.index = 0
        self._timer = None

    def on_show(self) -> None:
        self._timer = self.os.loop.call_later(1.2, self._advance)

    def on_hide(self) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def _advance(self) -> None:
        self.index += 1
        if self.index >= len(self.COLORS):
            self.os.pop()
            self.os.toast("Display test complete", "success")
            return
        self.redraw()
        self._timer = self.os.loop.call_later(1.2, self._advance)

    def handle(self, action: str) -> bool:
        self.os.pop()
        return True

    def footer(self, p: Painter) -> None:
        pass

    def draw(self, p: Painter) -> None:
        color, label = self.COLORS[self.index]
        if color is None:
            for x in range(SCREEN_W):
                v = int(255 * x / (SCREEN_W - 1))
                p.draw.line([(x, 0), (x, SCREEN_H // 3)], fill=(v, 0, 0))
                p.draw.line([(x, SCREEN_H // 3), (x, 2 * SCREEN_H // 3)], fill=(0, v, 0))
                p.draw.line([(x, 2 * SCREEN_H // 3), (x, SCREEN_H)], fill=(0, 0, v))
            return
        p.rect((0, 0, SCREEN_W, SCREEN_H), color)
        text = (0, 0, 0) if sum(color) > 300 else (255, 255, 255)
        p.text(SCREEN_W // 2, SCREEN_H // 2, label, 20, "bold", text, anchor="mm")


class ButtonTestScreen(Screen):
    """Shows raw button state and recognised gestures. Four clicks exit."""
    title = "Button test"

    def __init__(self, os):
        super().__init__(os)
        self.pressed = False
        self.presses = 0
        self.history: list[str] = []

    def on_raw_button(self, pressed: bool) -> None:
        self.pressed = pressed
        if pressed:
            self.presses += 1
        self.redraw()

    def on_gesture(self, gesture: str) -> bool:
        self.history = ([gesture_label(gesture) + "  " + gesture.replace("_", " ")] + self.history)[:4]
        self.redraw()
        if gesture == "quad_click":
            self.os.pop()
        return True

    def handle(self, action: str) -> bool:
        return True

    def footer(self, p: Painter) -> None:
        p.text(SCREEN_W // 2, FOOTER_Y, "four clicks to exit", 11, "regular", p.theme.text_faint,
               anchor="ma")

    def draw(self, p: Painter) -> None:
        t = p.theme
        cx, cy = SCREEN_W // 2, 98
        p.text(cx, 48, f"{self.presses} presses", 12, "medium", t.text_muted, anchor="ma")
        color = t.accent if self.pressed else t.surface_hi
        p.draw.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=color)
        p.text(cx, cy, "DOWN" if self.pressed else "UP", 14, "bold",
               (255, 255, 255) if self.pressed else t.text_muted, anchor="mm")
        y = 160
        if not self.history:
            p.text(cx, y + 20, "Press the button", 14, "medium", t.text_muted, anchor="mm")
        for index, line in enumerate(self.history):
            p.text(cx, y, line, 15 if index == 0 else 13, "semibold" if index == 0 else "regular",
                   t.text if index == 0 else t.text_faint, anchor="ma")
            y += 22


class SystemInfoScreen(ListScreen):
    title = "System"
    REFRESH_SEC = 5.0

    def __init__(self, os):
        super().__init__(os)
        self.info: dict = {}
        self._timer = None

    def on_show(self) -> None:
        self._refresh()

    def on_hide(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _refresh(self) -> None:
        self._timer = None

        def done(info):
            self.info = info
            self.redraw()
            if self.os.router_top() is self:
                self._timer = self.os.loop.call_later(self.REFRESH_SEC, self._refresh)
        self.os.run_task("sysinfo", system_info.gather, done)

    def items(self) -> list[Item]:
        i = self.info
        if not i:
            return [Item("Reading…", kind="info"), back_item()]
        temp = i.get("temperature_c")
        rows = [
            Item(OS_NAME, kind="info", value=__version__),
            Item("Device", kind="info", subtitle=i["model"]),
            Item("CPU", kind="info", subtitle=f"{i['cpu']} × {i['cores']} · load {i['load']:.2f}"),
            Item("RAM", kind="info", value=f"{i['ram_used_mb']} / {i['ram_total_mb']} MB"),
            Item("Storage", kind="info",
                 value=f"{i['disk_used_gb']:.1f} / {i['disk_total_gb']:.0f} GB"),
            Item("Temperature", kind="info", value=f"{temp:.0f}°C" if temp is not None else "—",
                 tone="warning" if temp and temp >= 70 else None),
            Item("Uptime", kind="info", value=system_info.format_duration(i["uptime"])),
            Item("Network", kind="info", value="Connected" if i["online"] else "Offline",
                 tone="success" if i["online"] else "warning"),
            Item("IP", kind="info", value=i["ip"] or "—"),
            Item("Hostname", kind="info", value=i["hostname"]),
            Item("Kernel", kind="info", value=i["kernel"].split("-")[0]),
            back_item(),
        ]
        return rows
