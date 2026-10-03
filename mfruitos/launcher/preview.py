"""Offscreen rendering of every screen, with sample data and no daemon.

``python3 -m mfruitos --self-test`` uses this to prove a (new) installation
imports and renders correctly — it is the TEST step of a system update.
``python3 -m mfruitos --preview DIR`` also writes each screen as a PNG.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from types import SimpleNamespace

from mfruitos import OS_APP_ID, __version__
from mfruitos.paths import Paths, package_root

log = logging.getLogger("mfruitos.preview")

SAMPLE_DAEMON_APPS = [
    ("whisplay-lora-messenger", "Messenger", "MS", 45, True),
    ("whisplay-lora-walkie", "WalkieTalkie", "WT", 45, False),
    ("whisplay-crypto-dashboard", "BTC Dashboard", "BTC", 40, False),
    ("whisplay-ai-chatbot", "AI Chatbot", "AI", 0, False),
]


def _setup_home(tmp: str) -> Paths:
    paths = Paths(os.path.join(tmp, "os"), os.path.join(tmp, "daemon"))
    paths.ensure()
    os.makedirs(paths.daemon_apps_dir, exist_ok=True)
    for app_id, name, icon, priority, _ in SAMPLE_DAEMON_APPS:
        with open(os.path.join(paths.daemon_apps_dir, f"{app_id}.json"), "w") as fp:
            json.dump({"app_id": app_id, "display_name": name, "icon": icon,
                       "launch_command": "./run.sh", "cwd": tmp, "priority": priority}, fp)
    # One OS-managed app, laid out exactly as the installer does it.
    root = os.path.join(paths.apps_dir, "weather")
    version_dir = os.path.join(root, "versions", "1.2.0-abc123")
    os.makedirs(version_dir)
    os.makedirs(os.path.join(root, "data"))
    with open(os.path.join(version_dir, "manifest.json"), "w") as fp:
        json.dump({"id": "weather", "name": "Weather", "version": "1.2.0",
                   "description": "Local forecast", "entrypoint": "run.sh",
                   "repository": "https://github.com/example/whisplay-weather"}, fp)
    with open(os.path.join(version_dir, "run.sh"), "w") as fp:
        fp.write("#!/bin/sh\n")
    os.chmod(os.path.join(version_dir, "run.sh"), 0o755)
    os.symlink("versions/1.2.0-abc123", os.path.join(root, "current"))
    with open(os.path.join(root, "app.json"), "w") as fp:
        json.dump({"installed_version": "1.2.0", "previous_version": "1.1.0",
                   "repository": "https://github.com/example/whisplay-weather"}, fp)
    return paths


def run_preview(outdir: str | None) -> int:
    from mfruitos.launcher.runtime import Runtime
    from mfruitos.launcher.ui.screens import (apps, bluetooth, diagnostics, dialogs, fallback, settings,
                                              updater)
    from mfruitos.system.bluetooth import BtDevice, Prompt
    from mfruitos.launcher.ui.screens.boot import DONE, RUNNING
    from mfruitos.system.diagnostics import CheckResult
    from mfruitos.updater.github import Release
    from mfruitos.updater.service import UpdateInfo

    tmp = tempfile.mkdtemp(prefix="mfruit-preview-")
    try:
        paths = _setup_home(tmp)
        rt = Runtime(paths, package_root(), socket_path=os.path.join(tmp, "no-daemon.sock"))
        # Previews must not scan or alter the host's Bluetooth hardware.
        keyboard = BtDevice("00:11:22:33:44:55", "My Keyboard", paired=True,
                            connected=True, icon="input-keyboard")
        speaker = BtDevice("00:11:22:33:44:66", "Living Room", icon="audio-card")
        rt.bluetooth = SimpleNamespace(available=lambda: True, powered=lambda: True,
                                       devices=lambda: [keyboard, speaker], search=lambda: None,
                                       cancel_pairing=lambda: None, answer=lambda accept: None)
        rt.status.wifi_level, rt.status.battery = 3, 82
        live = [{"app_id": a, "display_name": n, "icon": i, "priority": p, "running": r}
                for a, n, i, p, r in SAMPLE_DAEMON_APPS]
        live += [{"app_id": "weather", "display_name": "Weather"},
                 {"app_id": "whisplay-wifi", "display_name": "WiFi"},
                 {"app_id": "whisplay-volume", "display_name": "Volume"}]
        rt._daemon_apps = live
        rt.focus.connected = True
        rt.registry.refresh(live)
        now = time.time()
        rt.updater.last_check = now
        rt.updater.online = True
        rt.updater._infos = {
            OS_APP_ID: UpdateInfo(OS_APP_ID, "MFruit OS", "system", installed=__version__,
                                  latest=__version__, checked_at=now),
            "weather": UpdateInfo("weather", "Weather", "release", installed="1.2.0",
                                  latest="1.3.0", update_available=True, checked_at=now),
            "whisplay-lora-walkie": UpdateInfo("whisplay-lora-walkie", "WalkieTalkie", "git",
                                               installed="main @ 0b35885",
                                               latest="main @ 4c1d2e9", update_available=True),
        }
        rt.registry.set_latest_versions(rt.updater.latest_map())
        rt.settings.set("developer.enabled", True)

        frames: list[tuple[str, object]] = []

        def shot(name, screen=None, keep=False):
            if screen is not None:
                rt.router.push(screen)
            rt.loop.run_once()  # deliver results of inline background tasks
            frames.append((name, rt.compose()))
            if screen is not None and not keep:
                rt.router.pop()

        boot = rt.boot_screen
        rt.router.set_root(boot)
        boot.set_step(0, DONE)
        boot.set_step(1, DONE)
        boot.set_step(2, RUNNING)
        shot("01-boot")
        rt.router.set_root(rt.home_screen)
        shot("02-home")
        rt.home_screen.focus_key("weather")
        shot("03-home-update")
        rt.settings.set("display.theme", "light")
        shot("04-home-light")
        rt.settings.set("display.theme", "dark")
        rt.home_screen.selected = 0

        shot("10-settings", settings.SettingsScreen(rt))
        shot("11-applications", apps.ApplicationsScreen(rt))
        detail = apps.AppDetailScreen(rt, "weather")
        shot("12-app-detail", detail)
        for name, cls in (("13-display", settings.DisplayScreen), ("14-button", settings.ButtonScreen),
                          ("15-led", settings.LedScreen), ("16-audio", settings.AudioScreen),
                          ("17-wifi", settings.WifiScreen), ("18-general", settings.GeneralScreen),
                          ("19-developer", settings.DeveloperScreen), ("20-about", settings.AboutScreen)):
            shot(name, cls(rt))
        shot("21-brightness", dialogs.RangeScreen(rt, "Brightness", 60, 10, 100, 10, "%",
                                                  lambda v: None, lambda v: None))
        shot("22-bluetooth", bluetooth.BluetoothScreen(rt))
        shot("23-bt-device", bluetooth.BtDeviceScreen(rt, keyboard))
        shot("24-bt-passkey", bluetooth.PairingScreen(rt, Prompt("passkey", "123456")))
        shot("25-bt-confirm", bluetooth.PairingScreen(rt, Prompt("confirm", "123456")))

        shot("30-updater", updater.UpdaterScreen(rt))
        shot("31-app-update", updater.AppUpdateScreen(rt, "weather"))
        shot("32-git-update", updater.AppUpdateScreen(rt, "whisplay-lora-walkie"))
        shot("37-install-app", updater.InstallAppScreen(rt))
        shot("38-local-packages", updater.LocalPackagesScreen(rt))
        versions = updater.VersionListScreen(rt, "weather")
        versions.releases = [Release(v, f"v{v}", published_at=f"2026-0{i + 1}-01")
                             for i, v in enumerate(["1.3.0", "1.2.0", "1.1.0", "1.0.0"])]
        shot("33-versions", versions)
        discover = updater.DiscoverScreen(rt)
        discover.results = [{"full_name": "example/whisplay-weather", "description": "Forecast",
                             "stars": 12},
                            {"full_name": "someone/whisplay-clock", "description": "Big clock",
                             "stars": 3}]
        shot("34-discover", discover)
        shot("35-system-update", updater.SystemUpdateScreen(rt))
        rt.updater.online = False
        shot("36-updater-offline", updater.UpdaterScreen(rt))
        rt.updater.online = True

        progress = dialogs.ProgressScreen(rt, "Weather 1.3.0",
                                          [(s, s.title()) for s in ("check", "download", "verify",
                                                                    "backup", "install", "test",
                                                                    "activate")])
        rt.router.push(progress)
        progress.update("download", "412 KB", 0.45)
        shot("40-progress")
        progress.update("install", "Running install.sh", None)
        progress.finish(False, "install.sh failed (exit code 1). Previous version restored.",
                        "/tmp/x.log")
        shot("41-progress-failed")
        rt.router.pop()
        shot("42-confirm", dialogs.confirm(rt, "Remove Weather?",
                                           "This will delete:\n  Application files\n  Configuration\n  Cache",
                                           "Remove", lambda: None))
        entry = rt.registry.get("weather")
        rt.show_app_problem(entry, "", {"exit_code": 1})
        shot("43-app-error")
        rt.router.pop()

        diag = diagnostics.DiagnosticsScreen(rt)
        diag.results = {n: CheckResult(n, ok, d) for n, ok, d in [
            ("Hardware service", True, "4 ms"), ("Display", True, "OK"),
            ("Button", True, "released"), ("RGB LED", True, "OK"), ("Audio", True, "wm8960"),
            ("Network", True, "192.168.0.33"), ("Storage", True, "15.1 GB free"),
            ("Internet", True, "reachable"), ("GitHub", False, "rate limited")]}
        shot("50-diagnostics", diag)
        sysinfo = diagnostics.SystemInfoScreen(rt)
        rt.router.push(sysinfo)
        shot("51-system-info")
        rt.router.pop()
        test = diagnostics.ButtonTestScreen(rt)
        test.history = ["hold  long press", "2×  double click"]
        test.pressed = True
        shot("52-button-test", test)
        shot("53-fallback", fallback.DaemonUnavailableScreen(rt, "failed"))
        log_path = os.path.join(paths.logs_dir, "sample.log")
        with open(log_path, "w") as fp:
            fp.write("\n".join(f"2026-09-29 17:4{i % 10} INFO     mfruitos.runtime: line {i}"
                               for i in range(30)) + "\n2026-09-29 17:49 ERROR    boom\n")
        shot("54-log", dialogs.LogScreen(rt, "Launcher log", log_path))
        rt.toast("Moved up")
        shot("55-toast")

        if outdir:
            os.makedirs(outdir, exist_ok=True)
            for name, image in frames:
                image.save(os.path.join(outdir, f"{name}.png"))
        print(f"self-test OK: MFruit OS {__version__}, rendered {len(frames)} screens")
        return 0
    except Exception:
        log.exception("self-test failed")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
