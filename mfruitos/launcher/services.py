"""Operations the screens call on the runtime (``self.os`` in screens).

Kept separate from runtime.py so the core loop stays readable. Everything
here runs on the UI thread; blocking work is handed to ``run_task``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from mfruitos import OS_APP_ID, OS_NAME
from mfruitos.apps.registry import AppEntry
from mfruitos.launcher.navigation.gestures import gesture_label
from mfruitos.launcher.ui.components import Item, back_item
from mfruitos.launcher.ui.screens.dialogs import MessageScreen, ProgressScreen
from mfruitos.system import diagnostics
from mfruitos.system.settings import GESTURE_KEYS
from mfruitos.updater.installer import STEP_LABELS, STEPS, InstallError

log = logging.getLogger("mfruitos.services")

GESTURE_PRIORITY = ("single_click", "long_press", "double_click", "triple_click", "quad_click")
LED_TEST_SEQUENCE = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)]


class ScreenServices:
    # ------------------------------------------------------------ navigation
    def push(self, screen) -> None:
        self.router.push(screen)

    def pop(self) -> None:
        self.router.pop()

    def pop_to_type(self, screen_type) -> None:
        if not self.router.pop_to(screen_type):
            self.router.home()

    def router_top(self):
        return self.router.top

    def show_message(self, title: str, message: str, tone: str = "", icon: str = "") -> None:
        self.push(MessageScreen(self, title, message, tone=tone, icon=icon))

    def hints(self, select: str = "select", back: bool = True) -> list[tuple[str, str]]:
        if getattr(self, "hold_armed", False) and self.settings.get("button.long_press") == "select":
            return [("release", f"to {select}")]
        mapping = {k: self.settings.get(f"button.{k}") for k in GESTURE_KEYS}

        def gesture_for(action: str) -> str | None:
            for key in GESTURE_PRIORITY:
                if mapping.get(key) == action:
                    return gesture_label(key)
            return None
        wanted = [("next", "next"), ("select", select)]
        wanted.append(("back", "back") if back else ("previous", "prev"))
        return [(g, label) for action, label in wanted if (g := gesture_for(action))]

    # ------------------------------------------------------------ tasks
    def run_task(self, name: str, fn: Callable[[], Any], on_done=None, on_error=None,
                 lane: str = "quick") -> None:
        def default_error(exc):
            self.toast(str(exc)[:40] or "Failed", "error")
        self.tasks.submit(name, fn, on_done, on_error or default_error, lane)

    def start_job(self, title: str, work: Callable[[Callable], Any],
                  success: Callable[[Any], str], log_path: str = "",
                  on_success: Callable[[Any], None] | None = None,
                  steps: tuple = STEPS) -> ProgressScreen:
        """Run an install-type job with a progress screen and LED feedback."""
        if self.tasks.busy("jobs"):
            self.toast("Another update is running")
            return None
        screen = ProgressScreen(self, title, [(s, STEP_LABELS.get(s, s.title())) for s in steps])
        self.push(screen)
        self.led.show("update")
        self.backlight.wake()

        def progress(step, detail, fraction=None):
            self.loop.post(screen.update, step, detail, fraction)

        def done(result):
            screen.finish(True, success(result), log_path)
            self.led.show("idle")
            if on_success:
                on_success(result)
            self.refresh_registry(query_daemon=True)

        def failed(exc):
            if isinstance(exc, InstallError):
                text = exc.message
                if exc.rolled_back:
                    text += " Previous version restored."
            else:
                text = str(exc)[:160] or exc.__class__.__name__
            screen.finish(False, text, log_path or os.path.join(self.paths.logs_dir, "updater.log"))
            self.led.show("error")
            self.loop.call_later(8.0, lambda: self.led.show("idle"))
            self.refresh_registry(query_daemon=True)
        self.tasks.submit(title, lambda: work(progress), done, failed, lane="jobs")
        return screen

    # ------------------------------------------------------------ launching
    def launch_app(self, app_id: str, source: str = "home") -> bool:
        """Ask the ApplicationManager to launch ``app_id``. The UI never starts
        processes or talks to the daemon itself."""
        entry = self.registry.get(app_id)
        if entry is None:
            self.toast("App not found", "error")
            return False
        if not entry.enabled:
            self.toast("App is disabled")
            return False
        if entry.broken:
            self.show_app_problem(entry, entry.broken)
            return False
        if not self.focus.connected:
            self.toast("Daemon unavailable", "error")
            return False
        if self.apps.busy:
            self.apps.request_launch(app_id, "app", source)  # refused and logged
            return False
        self.flush_settings()
        self.lifecycle.prepare_launch(entry)
        self.backlight.wake()
        self.led.show("running")
        self.last_launched = app_id
        # Wi-Fi is part of Settings: retain that page until its first frame.
        # Other apps keep the "Opening <app>" handoff screen. The daemon retains
        # whichever frame we draw here while the app starts.
        loading = None
        if app_id != "connectwifi":
            from mfruitos.launcher.ui.screens.dialogs import LoadingScreen
            loading = LoadingScreen(self, entry.id, entry.name, entry.icon_text, entry.icon_path)
            self.router.push(loading)
        self._render_now()
        ok, _ = self.apps.request_launch(app_id, "app", source)
        if not ok and loading is not None and self.router.top is loading:
            self.router.pop()
        return ok

    def open_system_page(self, page_id: str, source: str = "settings") -> bool:
        if not self.focus.connected:
            self.toast("Daemon unavailable", "error")
            return False
        if not self.apps.busy:
            self.flush_settings()
            self.backlight.wake()
        ok, _ = self.apps.request_launch(page_id, "page", source)
        return ok

    def system_page_available(self, page_id: str) -> bool:
        return any(p.id == page_id for p in self.registry.system_pages())

    def open_home_entry(self, entry) -> None:
        from mfruitos.launcher.ui.screens.settings import SettingsScreen
        from mfruitos.launcher.ui.screens.updater import UpdaterScreen, InstallAppScreen
        if entry.key == "os.settings":
            self.push(SettingsScreen(self))
        elif entry.key == "os.installer":
            self.push(InstallAppScreen(self))
        elif entry.key == "os.updater":
            self.push(UpdaterScreen(self))
        elif entry.kind == "system":
            self.open_system_page(entry.key, source="home")
        else:
            self.launch_app(entry.key, source="home")

    def show_app_problem(self, entry: AppEntry, reason: str, exit_info: dict | None = None,
                         title_text: str = "Application failed to start.") -> None:
        from mfruitos.launcher.ui.screens.dialogs import LogScreen
        detail = reason
        if exit_info and exit_info.get("exit_code") is not None:
            detail = f"Error: exit code {exit_info['exit_code']}"
        message = f"{title_text}\n{detail}"
        actions = [Item("Retry", lambda: (self.pop(), self.launch_app(entry.id, source="retry")),
                        icon="refresh",
                        enabled=entry.launchable),
                   Item("Logs", lambda: self.push(LogScreen(self, f"{entry.name} log",
                                                            self.lifecycle.log_path(entry))),
                        kind="nav", icon="list"),
                   back_item()]
        self.led.show("error")
        self.loop.call_later(6.0, lambda: self.led.show("idle"))
        self.push(MessageScreen(self, entry.name, message, actions, tone="error", icon="warning"))

    # ------------------------------------------------------------ screens
    def open_app_updates(self, app_id: str) -> None:
        from mfruitos.launcher.ui.screens.updater import AppUpdateScreen
        self.push(AppUpdateScreen(self, app_id))

    def open_system_update(self) -> None:
        from mfruitos.launcher.ui.screens.updater import SystemUpdateScreen
        self.push(SystemUpdateScreen(self))

    def open_diagnostics(self) -> None:
        from mfruitos.launcher.ui.screens.diagnostics import DiagnosticsScreen
        self.push(DiagnosticsScreen(self))

    def open_system_info(self) -> None:
        from mfruitos.launcher.ui.screens.diagnostics import SystemInfoScreen
        self.push(SystemInfoScreen(self))

    def open_button_test(self) -> None:
        from mfruitos.launcher.ui.screens.diagnostics import ButtonTestScreen
        self.push(ButtonTestScreen(self))

    def open_sideload(self) -> None:
        from mfruitos.launcher.ui.screens.updater import LocalPackagesScreen
        self.push(LocalPackagesScreen(self))

    # ------------------------------------------------------------ updater
    def updates_available_count(self) -> int:
        return self.updater.update_count()

    def updater_summary(self) -> str:
        from mfruitos.launcher.ui.screens.updater import when
        if self.updater.busy:
            return "Checking for updates…"
        if self.updater.online is False:
            return "Offline · last check " + when(self.updater.last_check)
        if not self.updater.last_check:
            return "Not checked yet"
        return "Up to date · " + when(self.updater.last_check)

    def check_updates(self, quiet: bool = False) -> None:
        if self.tasks.busy("jobs"):
            if not quiet:
                self.toast("Updater is busy")
            return
        entries = [e for e in self.registry.apps() if e.kind in ("os", "daemon")]

        def done(_):
            self.registry.set_latest_versions(self.updater.latest_map())
            self.request_render()
            if quiet:
                return
            if self.updater.online is False:
                self.toast("Internet unavailable", "error")
            else:
                count = self.updater.update_count()
                errors = any(i.error for i in self.updater.infos().values())
                self.toast(f"{count} update{'s' if count != 1 else ''} available" if count
                           else "Check update details" if errors else "Everything is up to date",
                           "success" if not count and not errors else "")
        self.updater.busy = True
        self.request_render()
        self.tasks.submit("check-updates", lambda: self.updater.check(entries), done,
                          lambda exc: (setattr(self.updater, "busy", False),
                                       self.toast(str(exc)[:40], "error")), lane="jobs")

    def install_app_version(self, app_id: str, version: str) -> None:
        entry = self.registry.get(app_id)
        if entry is None:
            return
        if entry.running:
            self.toast("Stop the app before updating")
            return
        self.start_job(f"{entry.name} {version}",
                       lambda progress: self.updater.install_version(entry, version, progress),
                       lambda r: f"{r.name} {r.version} installed" + (
                           "" if r.verified else " (no checksum published)"),
                       log_path=self.paths.app_log(app_id),
                       on_success=lambda r: self.updater.mark_installed(r.app_id, r.version))

    def install_from_repository(self, repository: str) -> None:
        self.start_job("Install app",
                       lambda progress: self.updater.install_from_repository(repository, progress),
                       lambda r: f"{r.name} {r.version} installed",
                       on_success=lambda r: self._after_new_install(r.app_id, r.version))

    def sideload(self, path: str) -> None:
        self.start_job("Install package", lambda progress: self.updater.sideload(path, progress),
                       lambda r: f"{r.name} {r.version} installed",
                       on_success=lambda r: self._after_new_install(r.app_id, r.version))

    def _after_new_install(self, app_id: str, version: str) -> None:
        self.enable_installed_app(app_id)
        self.updater.mark_installed(app_id, version)
        self.refresh_registry(query_daemon=True)
        self.home_screen.focus_key(app_id)

    def enable_installed_app(self, app_id: str) -> None:
        ids = self.settings.get("apps.installed_ids")
        if app_id not in ids:
            self.settings.set("apps.installed_ids", ids + [app_id])
        self.settings.set_app_flag(app_id, "enabled", True)
        self.settings.set_app_flag(app_id, "hidden", False)
        self.settings.set_app_flag(app_id, "autostart", False)
        self.flush_settings()

    def restore_catalog_app(self, app_id: str) -> None:
        entry = self.registry.get(app_id)
        if entry is None or entry.broken:
            self.toast("App files are missing", "error")
            return
        self.enable_installed_app(app_id)
        self.refresh_registry(query_daemon=True)
        self.home_screen.focus_key(app_id)
        self.toast(f"{entry.name} added to Apps", "success")

    def install_catalog_app(self, app_id: str) -> None:
        self.start_job("Install app", lambda progress: self.updater.install_catalog(app_id, progress),
                       lambda r: f"{r.name} installed",
                       on_success=lambda r: self._after_new_install(r.app_id, r.version))

    def update_all(self) -> None:
        targets = [(a, self.updater.info(a.id)) for a in self.registry.apps()]
        targets = [(a, i) for a, i in targets if i and i.update_available and not i.error]
        if any(a.running for a, _ in targets):
            self.toast("Stop running apps before updating")
            return
        system = self.updater.info(OS_APP_ID)

        def work(progress):
            done = []
            for app, info in targets:
                progress("check", f"{app.name}", None)
                if info.channel == "release":
                    result = self.updater.install_version(app, info.latest, progress)
                    self.updater.mark_installed(result.app_id, result.version)
                elif info.channel == "git":
                    self.updater.git_update(app, progress)
                done.append(app.name)
            return done
        extra = " MFruit OS itself is updated from System update." if (
            system and system.update_available) else ""
        self.start_job("Update all", work,
                       lambda names: f"Updated {len(names)} app(s).{extra}")

    def update_system(self, version: str) -> None:
        def on_success(result):
            self.toast("Restarting…")
            self.loop.call_later(2.5, self.restart_launcher)
        self.start_job(f"{OS_NAME} {version}",
                       lambda progress: self.updater.update_system(version, progress),
                       lambda r: f"{OS_NAME} {r.version} installed. Restarting…",
                       on_success=on_success)

    def rollback_app(self, app_id: str) -> None:
        entry = self.registry.get(app_id)
        if entry is None:
            return
        if entry.running:
            self.toast("Stop the app before rolling back")
            return
        self.start_job("Roll back app",
                       lambda progress: self.installer.rollback_to_previous(app_id),
                       lambda version: f"Rolled back to {version}",
                       on_success=lambda version: self.updater.mark_installed(app_id, version),
                       steps=("activate",))

    def rollback_system(self) -> None:
        self.start_job("Roll back system",
                       lambda progress: self.installer.rollback_to_previous(OS_APP_ID, system=True),
                       lambda version: f"MFruit OS {version} restored. Restarting…",
                       on_success=lambda _: self.loop.call_later(2.5, self.restart_launcher),
                       steps=("activate",))

    def git_update(self, app_id: str) -> None:
        entry = self.registry.get(app_id)
        if entry is None:
            return
        if entry.running:
            self.toast("Stop the app before updating")
            return
        self.start_job(f"Update {entry.name}",
                       lambda progress: self.updater.git_update(entry, progress),
                       lambda sha: f"{entry.name} updated to {sha}",
                       steps=("check", "backup", "download", "verify", "install", "test", "activate"))

    def git_rollback(self, app_id: str) -> None:
        entry = self.registry.get(app_id)
        if entry is None:
            return
        if entry.running:
            self.toast("Stop the app before rolling back")
            return
        self.start_job("Roll back app", lambda progress: self.updater.git_rollback(entry),
                       lambda sha: f"Rolled back to {sha}", steps=("activate",))

    # ------------------------------------------------------------ hardware tests
    def test_led(self) -> None:
        sequence = list(LED_TEST_SEQUENCE)

        def step():
            if not sequence:
                self.led.show(self.led.state, force=True)
                return
            self.led.set_rgb(sequence.pop(0), force=True)
            self.loop.call_later(0.6, step)
        self.toast("LED: red, green, blue, white")
        step()

    def test_speaker(self) -> None:
        device = self.settings.get("audio.device")
        self.toast("Playing test tone…")
        self.run_task("speaker", lambda: diagnostics.play_tone(self.paths.cache_dir, device),
                      lambda r: self.toast("Tone played" if r.ok else r.detail[:36],
                                           "success" if r.ok else "error"))

    def check_internet(self) -> None:
        self.run_task("internet", diagnostics.check_internet,
                      lambda r: self.toast("Internet reachable" if r.ok else r.detail[:36],
                                           "success" if r.ok else "error"))

    # ------------------------------------------------------------ misc
    def flush_settings(self) -> None:
        if self.settings.dirty:
            self.settings.save()
