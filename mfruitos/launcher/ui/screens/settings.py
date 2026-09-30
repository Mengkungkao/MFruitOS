"""Settings screens. They only read/write Settings and call runtime services."""

from __future__ import annotations

import os as _os
import platform

from mfruitos import OS_NAME, __version__
from mfruitos.launcher.ui.components import Item, back_item
from mfruitos.launcher.ui.screens.bluetooth import BluetoothScreen
from mfruitos.launcher.ui.screens.apps import ApplicationsScreen
from mfruitos.launcher.ui.screens.base import ListScreen
from mfruitos.launcher.ui.screens.dialogs import ChoiceScreen, LogScreen, RangeScreen, confirm
from mfruitos.system import system_info
from mfruitos.system.settings import (DIM_CHOICES, GESTURE_ACTIONS, GESTURE_KEYS, LED_COLORS,
                                      SCHEMA, TIMEOUT_CHOICES)

GESTURE_LABELS = {"single_click": "Single click", "double_click": "Double click",
                  "triple_click": "Triple click", "long_press": "Long press",
                  "quad_click": "Four clicks"}
ACTION_LABELS = {"next": "Next", "previous": "Previous", "select": "Select", "back": "Back",
                 "home": "Home", "none": "Nothing"}


def seconds_label(value: int) -> str:
    if value == 0:
        return "Never"
    return f"{value} sec" if value < 60 else f"{value // 60} min"


def choice(os, title: str, key: str, options: list[tuple[object, str]]):
    return ChoiceScreen(os, title, options, os.settings.get(key),
                        lambda value: os.settings.set(key, value))


class SettingsScreen(ListScreen):
    title = "Settings"

    def __init__(self, os):
        super().__init__(os)
        self.ssid = ""
        self.bluetooth = "…"

    def on_show(self) -> None:
        def read():
            bt = self.os.bluetooth
            available = bt.available()
            powered = available and bt.powered()
            connected = [d.name for d in bt.devices() if d.connected] if powered else []
            return system_info.wifi_ssid(), (connected[0] if connected else
                                            "On" if powered else "Off" if available else "Unavailable")

        def done(result):
            self.ssid, self.bluetooth = result
            self.redraw()
        self.os.run_task("settings-status", read, done, lane="bluetooth")

    def open_wifi(self) -> None:
        """Open the full network manager directly; keep the small status
        page as a useful fallback on installations that do not have one."""
        wifi = WifiScreen(self.os)
        if (self.os.registry.get("connectwifi") is not None
                or self.os.system_page_available("whisplay-wifi")):
            wifi.choose_network()
        else:
            self.os.push(wifi)

    def items(self) -> list[Item]:
        os = self.os
        apps = os.registry.apps()
        rows = [
            Item("Wi-Fi", self.open_wifi, kind="nav", icon="wifi",
                 subtitle=self.ssid or "Not connected", tile=(46, 140, 255)),
            Item("Bluetooth", lambda: os.push(BluetoothScreen(os)), kind="nav", icon="bluetooth",
                 subtitle=self.bluetooth, tile=(46, 140, 255)),
            Item("Display & Brightness", lambda: os.push(DisplayScreen(os)), kind="nav",
                 icon="display", tile=(46, 140, 255)),
            Item("Sounds", lambda: os.push(AudioScreen(os)), kind="nav", icon="audio", tile=(255, 69, 108)),
            Item("Button", lambda: os.push(ButtonScreen(os)), kind="nav", icon="button", tile=(94, 92, 230)),
            Item("Light", lambda: os.push(LedScreen(os)), kind="nav", icon="led", tile=(255, 149, 0)),
            Item("General", lambda: os.push(GeneralScreen(os)), kind="nav", icon="system", tile=(110, 118, 130)),
            Item("Apps", lambda: os.push(ApplicationsScreen(os)), kind="nav", icon="apps",
                 value=str(len(apps)), tile=(94, 92, 230)),
            Item("Developer", lambda: os.push(DeveloperScreen(os)), kind="nav", icon="developer",
                 value="On" if os.settings.get("developer.enabled") else None, tile=(110, 118, 130)),
            back_item(),
        ]
        return rows


class DisplayScreen(ListScreen):
    title = "Display"

    def items(self) -> list[Item]:
        os = self.os
        s = os.settings
        return [
            Item("Brightness", self._brightness, kind="nav", icon="display",
                 value=f"{s.get('display.brightness')}%"),
            Item("Auto dim", lambda: s.set("display.auto_dim", not s.get("display.auto_dim")),
                 kind="toggle", value=s.get("display.auto_dim")),
            Item("Dim after", lambda: os.push(choice(os, "Dim after", "display.dim_after_sec",
                                                     [(v, seconds_label(v)) for v in DIM_CHOICES])),
                 kind="nav", value=seconds_label(s.get("display.dim_after_sec")),
                 enabled=s.get("display.auto_dim")),
            Item("Screen timeout", lambda: os.push(choice(
                os, "Screen timeout", "display.screen_timeout_sec",
                [(v, seconds_label(v)) for v in TIMEOUT_CHOICES])),
                kind="nav", value=seconds_label(s.get("display.screen_timeout_sec"))),
            Item("Theme", lambda: os.push(choice(os, "Theme", "display.theme",
                                                 [("dark", "Dark"), ("light", "Light")])),
                 kind="nav", value=s.get("display.theme").title()),
            Item("Animation", lambda: os.push(choice(os, "Animation", "display.animation",
                                                     [("minimal", "Minimal"), ("off", "Off")])),
                 kind="nav", value=s.get("display.animation").title()),
            Item("24-hour clock", lambda: s.set("display.clock_24h", not s.get("display.clock_24h")),
                 kind="toggle", value=s.get("display.clock_24h")),
            back_item(),
        ]

    def _brightness(self) -> None:
        os = self.os
        os.push(RangeScreen(os, "Brightness", os.settings.get("display.brightness"), 10, 100, 10,
                            "%", on_change=os.backlight.preview,
                            on_save=lambda v: (os.settings.set("display.brightness", v),
                                               os.backlight.wake())))


class ButtonScreen(ListScreen):
    title = "Button"

    def items(self) -> list[Item]:
        os = self.os
        s = os.settings
        rows = []
        for key in GESTURE_KEYS:
            setting = f"button.{key}"
            rows.append(Item(GESTURE_LABELS[key], lambda k=setting, g=key: os.push(choice(
                os, GESTURE_LABELS[g], k, [(a, ACTION_LABELS[a]) for a in GESTURE_ACTIONS])),
                kind="nav", value=ACTION_LABELS[s.get(setting)]))
        rows += [
            Item("Click speed", lambda: self._range("Click speed", "button.click_gap_ms", 150, 800, 50),
                 kind="nav", value=f"{s.get('button.click_gap_ms')} ms"),
            Item("Hold time", lambda: self._range("Hold time", "button.long_press_ms", 400, 2000, 100),
                 kind="nav", value=f"{s.get('button.long_press_ms')} ms"),
            Item("Test button", lambda: os.open_button_test(), kind="nav", icon="button"),
            Item("Reset gestures", self._reset, icon="rollback"),
            back_item(),
        ]
        return rows

    def _range(self, title, key, low, high, step) -> None:
        os = self.os
        os.push(RangeScreen(os, title, os.settings.get(key), low, high, step, " ms",
                            on_change=lambda v: None,
                            on_save=lambda v: os.settings.set(key, v)))

    def _reset(self) -> None:
        s = self.os.settings
        # Assign "select" first so every intermediate map stays valid.
        order = sorted(GESTURE_KEYS, key=lambda k: SCHEMA[f"button.{k}"][0] != "select")
        for key in order:
            try:
                s.set(f"button.{key}", SCHEMA[f"button.{key}"][0])
            except ValueError:
                pass
        s.set("button.click_gap_ms", SCHEMA["button.click_gap_ms"][0])
        s.set("button.long_press_ms", SCHEMA["button.long_press_ms"][0])
        self.os.toast("Gestures reset")


class LedScreen(ListScreen):
    title = "LED"

    def items(self) -> list[Item]:
        os = self.os
        s = os.settings
        colors = [(c, c.title()) for c in LED_COLORS]
        rows = [Item("Status LED", lambda: s.set("led.enabled", not s.get("led.enabled")),
                     kind="toggle", value=s.get("led.enabled"))]
        for state, label in (("idle", "Idle colour"), ("running", "Running colour"),
                             ("update", "Update colour"), ("error", "Error colour")):
            key = f"led.{state}_color"
            rows.append(Item(label, lambda k=key, l=label: os.push(choice(os, l, k, colors)),
                             kind="nav", value=s.get(key).title(), enabled=s.get("led.enabled")))
        rows += [
            Item("Brightness", self._brightness, kind="nav", value=f"{s.get('led.brightness')}%",
                 enabled=s.get("led.enabled")),
            Item("Test LED", os.test_led, icon="led"),
            back_item(),
        ]
        return rows

    def _brightness(self) -> None:
        os = self.os

        def preview(value):
            color = os.led.color_for("idle")
            base = os.settings.get("led.brightness") or 1
            os.led.set_rgb(tuple(min(255, int(c * value / max(1, base))) for c in color))

        os.push(RangeScreen(os, "LED brightness", os.settings.get("led.brightness"), 0, 100, 10,
                            "%", on_change=preview,
                            on_save=lambda v: (os.settings.set("led.brightness", v),
                                               os.led.show("idle", force=True))))


class AudioScreen(ListScreen):
    title = "Audio"
    DEVICES = [("", "System default"), ("whisplaysound", "whisplaysound"),
               ("plughw:0,0", "Card 0"), ("plughw:1,0", "Card 1")]

    def items(self) -> list[Item]:
        os = self.os
        s = os.settings
        device = s.get("audio.device")
        label = next((l for v, l in self.DEVICES if v == device), device or "System default")
        rows = []
        if os.system_page_available("whisplay-volume"):
            rows.append(Item("Volume", lambda: os.open_system_page("whisplay-volume"), kind="nav",
                             icon="volume", subtitle="Daemon volume page"))
        rows += [
            Item("Test speaker", os.test_speaker, icon="play"),
            Item("Output", lambda: os.push(choice(os, "Output device", "audio.device",
                                                         self.DEVICES)),
                 kind="nav", value=label),
            back_item(),
        ]
        return rows


class WifiScreen(ListScreen):
    title = "Wi-Fi"

    def __init__(self, os):
        super().__init__(os)
        self.ip = self.ssid = ""
        self.internet = "Not checked"

    def on_show(self) -> None:
        def done(result):
            self.ip, self.ssid = result
            self.redraw()
        self.os.run_task("wifi-status", lambda: (system_info.local_ip(), system_info.wifi_ssid()), done)

    def choose_network(self) -> None:
        if self.os.registry.get("connectwifi") is not None:
            self.os.launch_app("connectwifi", source="settings")
        elif self.os.system_page_available("whisplay-wifi"):
            self.os.open_system_page("whisplay-wifi")
        else:
            self.os.show_message("Wi-Fi", "Install Connect WiFi to choose a network.")

    def check_internet(self) -> None:
        from mfruitos.system.diagnostics import check_internet
        self.internet = "Checking…"
        self.redraw()

        def done(result):
            self.internet = "Reachable" if result.ok else "Unavailable"
            self.redraw()

        def failed(exc):
            self.internet = "Check failed"
            self.os.toast(str(exc)[:40], "error")
            self.redraw()
        self.os.run_task("internet", check_internet, done, failed)

    def items(self) -> list[Item]:
        rows = [
            Item("Network", kind="info", subtitle=self.ssid or "Not connected", icon="wifi"),
            Item("IP address", kind="info", value=self.ip or "—"),
            Item("Internet", kind="info", value=self.internet),
            Item("Choose a network…", self.choose_network, kind="nav", icon="wifi"),
            Item("Check internet", self.check_internet, icon="network"),
            back_item(),
        ]
        return rows


class GeneralScreen(ListScreen):
    title = "General"

    def items(self) -> list[Item]:
        os = self.os
        rows = [
            Item("About", lambda: os.push(AboutScreen(os)), kind="nav", icon="info"),
            Item("Software Update", os.open_system_update, kind="nav", icon="updater",
                 value=__version__),
            Item("System info", os.open_system_info, kind="nav", icon="info"),
            Item("Diagnostics", os.open_diagnostics, kind="nav", icon="diagnostics"),
        ]
        if os.system_page_available("whisplay-system"):
            rows.append(Item("Power", lambda: os.open_system_page("whisplay-system"), kind="nav",
                             icon="power", subtitle="Lock, reboot, shut down"))
        rows += [
            Item("Restart launcher", lambda: os.push(confirm(
                os, "Restart launcher?", "MFruit OS will restart. Running apps keep running.",
                "Restart", os.restart_launcher, danger=False)), icon="refresh"),
            back_item(),
        ]
        return rows


class DeveloperScreen(ListScreen):
    title = "Developer"

    def items(self) -> list[Item]:
        os = self.os
        s = os.settings
        enabled = s.get("developer.enabled")
        rows = [Item("Developer mode", lambda: s.set("developer.enabled", not enabled),
                     kind="toggle", value=enabled)]
        if not enabled:
            rows.append(Item("Tools appear when enabled", kind="info", tone="muted"))
            rows.append(back_item())
            return rows
        paths = os.paths
        rows += [
            Item("Debug logging", lambda: s.set("developer.debug_logging",
                                                not s.get("developer.debug_logging")),
                 kind="toggle", value=s.get("developer.debug_logging")),
            Item("Launcher log", lambda: os.push(LogScreen(
                os, "Launcher log", _os.path.join(paths.logs_dir, "launcher.log"))),
                kind="nav", icon="list"),
            Item("Updater log", lambda: os.push(LogScreen(
                os, "Updater log", _os.path.join(paths.logs_dir, "updater.log"))),
                kind="nav", icon="list"),
            Item("Daemon app log", lambda: os.push(LogScreen(os, "Daemon app log",
                                                             paths.daemon_app_log)),
                 kind="nav", icon="list"),
            Item("Application logs", lambda: os.push(AppLogsScreen(os)), kind="nav", icon="list"),
            Item("Reload apps", lambda: (os.refresh_registry(query_daemon=True),
                                         os.toast(f"{len(os.registry.apps())} apps loaded")),
                 icon="refresh"),
            Item("Install local package", os.open_sideload, kind="nav", icon="package"),
            Item("Shell access", lambda: os.show_message(
                "Shell access", _shell_help()), kind="nav", icon="developer"),
            Item("Daemon desktop", lambda: os.push(confirm(
                os, "Daemon desktop?",
                "Show whisplay-daemon's own desktop. Pick 'MFruit OS' there to come back.",
                "Switch", os.yield_to_desktop, danger=False)), icon="apps"),
            Item("Restart launcher", os.restart_launcher, icon="refresh"),
            back_item(),
        ]
        return rows


def _shell_help() -> str:
    user = _os.environ.get("USER") or _os.environ.get("LOGNAME") or "pi"
    ip = system_info.local_ip() or "<device-ip>"
    return (f"Connect from a computer on the same network:\n  ssh {user}@{ip}\n"
            "Control MFruit OS from the shell with:\n  ~/.whisplay-os/bin/mfruitctl help")


class AppLogsScreen(ListScreen):
    title = "App logs"

    def items(self) -> list[Item]:
        os = self.os
        rows = [Item(app.name, lambda a=app: os.push(LogScreen(os, a.name, os.lifecycle.log_path(a))),
                     kind="nav", value="own" if app.kind == "os" else "daemon")
                for app in os.registry.apps()]
        rows.append(back_item())
        return rows


class AboutScreen(ListScreen):
    title = "About"

    def items(self) -> list[Item]:
        os = self.os
        repo = os.settings.get("system.repository") or "—"
        return [
            Item(OS_NAME, kind="info", value=__version__, icon="info"),
            Item("Daemon", kind="info", value="Connected" if os.focus.connected else "Offline",
                 tone="success" if os.focus.connected else "warning"),
            Item("Device", kind="info", subtitle=system_info.device_model()),
            Item("Python", kind="info", value=platform.python_version()),
            Item("Source", kind="info", subtitle=repo.replace("https://", "")),
            Item("License", kind="info", value="MIT"),
            back_item(),
        ]
