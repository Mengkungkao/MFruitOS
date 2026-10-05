"""MFruit OS runtime: wires the daemon, UI, input, timers and services together.

Threads: the event loop (UI thread) owns all state. The daemon event stream,
task workers and control socket only ever ``post`` work to it.
"""

from __future__ import annotations

import logging
import os
import time

from mfruitos import OS_APP_ID, __version__
from mfruitos.apps.manifest import Manifest
from mfruitos.apps.registry import AppEntry, AppRegistry
from mfruitos.core.application_manager import FAILED, HEADLESS, ApplicationManager
from mfruitos.daemon.client import DaemonError, WhisplayDaemonClient
from mfruitos.daemon.events import EventStream
from mfruitos.launcher import sdnotify
from mfruitos.launcher.app_manager.lifecycle import AppLifecycle
from mfruitos.launcher.control import ControlServer
from mfruitos.launcher.direct import DirectDisplay, daemon_unit_state, find_whisplay_root, SAFE_STATES
from mfruitos.launcher.focus import APP, HOME, SYSTEM, ForegroundManager
from mfruitos.launcher.keyhub import KeyHub
from mfruitos.launcher.loop import EventLoop
from mfruitos.launcher.navigation.gestures import GestureRecognizer
from mfruitos.launcher.navigation.router import Router
from mfruitos.launcher.services import ScreenServices
from mfruitos.launcher.tasks import TaskRunner
from mfruitos.launcher.ui.components import StatusInfo, draw_status_bar, draw_toast
from mfruitos.launcher.ui.fonts import Fonts
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.rgb565 import to_rgb565
from mfruitos.launcher.ui.screens.boot import DONE, RUNNING, BootScreen
from mfruitos.launcher.ui.screens.boot import FAILED as STEP_FAILED
from mfruitos.launcher.ui.screens.dialogs import MessageScreen
from mfruitos.launcher.ui.screens.home import HomeScreen
from mfruitos.launcher.ui.theme import get_theme
from mfruitos.logs import set_debug
from mfruitos.paths import Paths
from mfruitos.sdk.keys import DOWN as KEY_DOWN
from mfruitos.sdk.keys import REPEAT as KEY_REPEAT
from mfruitos.sdk.keys import UP as KEY_UP
from mfruitos.sdk.keys import KeyEvent, KeyReader
from mfruitos.system import hardware, system_info
from mfruitos.system.bluetooth import Bluetooth
from mfruitos.system.settings import GESTURE_KEYS, Settings
from mfruitos.updater.github import GitHubClient
from mfruitos.updater.installer import Installer
from mfruitos.updater.service import UpdateService

log = logging.getLogger("mfruitos.runtime")
lifecycle_log = logging.getLogger("mfruitos.lifecycle")

MIN_FRAME_INTERVAL = 0.06
STATUS_REFRESH_SEC = 30.0
TOAST_SEC = 2.2
SAVE_DELAY_SEC = 1.5
FALLBACK_AFTER_SEC = 10.0
FALLBACK_POLL_SEC = 5.0
AUTOSTART_DELAY_SEC = 1.0
UPDATE_TICK_SEC = 600
SCRIPTS = ("mfruit-run", "mfruitctl", "boot-guard.sh", "whisplay-daemon-mfruit.py")
# Keyboard keys -> launcher actions, the same map every MFruit app uses
# (mfruitos/sdk/input.py).
KEY_ACTIONS = {"down": "next", "right": "next", "tab": "next", "up": "previous",
               "left": "previous", "enter": "select", "escape": "back", "home": "home"}


class Runtime(ScreenServices):
    def __init__(self, paths: Paths, package_dir: str, socket_path: str | None = None,
                 input_dir: str | None = None):
        self.paths = paths
        paths.ensure()
        self.package_dir = package_dir
        self.loop = EventLoop()
        self.settings = Settings(paths.settings_file, autosave=self._schedule_save)
        self.settings.load()
        self.settings.add_listener(self._on_setting_changed)
        self.client = WhisplayDaemonClient(socket_path or self.settings.get("daemon.socket_path"))
        self.registry = AppRegistry(paths, self.settings, __version__)
        self.lifecycle = AppLifecycle(self.client, paths)
        self.github = GitHubClient(paths.cache_dir, token=self.settings.get("updater.github_token"))
        self.installer = Installer(paths, __version__, self.settings, self.github,
                                   register=self._register_manifest, in_use=self._app_in_use)
        self.updater = UpdateService(paths, self.settings, self.github, self.installer, __version__)
        # The single launch authority (core) and its Whisplay host.
        self.apps = ApplicationManager()
        self.apps.listener = self
        self.apps.context = self._lifecycle_context
        self.focus = ForegroundManager(self.client, self.loop, OS_APP_ID, self, manager=self.apps,
                                       prepare_launch=self.lifecycle.issue_ticket,
                                       run_state=self.lifecycle.run_state,
                                       is_page=self._is_page)
        self.backlight = hardware.BacklightController(self.client, self.settings)
        self.led = hardware.LedController(self.client, self.settings)
        self.tasks = TaskRunner(self.loop.post)
        self.bluetooth = Bluetooth()
        self.router = Router(on_change=self._on_route_change)
        self.hold_armed = False
        self.gestures = GestureRecognizer(self._on_gesture, self.loop.call_later,
                                          on_armed=self._on_hold_armed)
        self._configure_gestures()
        # USB / Bluetooth keyboards, held exclusively (EVIOCGRAB): no key
        # reaches the Linux console -- whose auto-login shell ran whatever
        # was typed for MFruit OS -- or any other reader. Each key goes to
        # whoever owns the screen: MFruit OS, or the foreground app through
        # the key hub (launcher/keyhub.py).
        self.keyhub = KeyHub(paths.keys_socket)
        # ``input_dir`` replaces /dev/input and /sys/class/input (tests pass an
        # empty directory so they never open or grab the machine's keyboards).
        devices = {"input_dir": input_dir, "sys_dir": input_dir} if input_dir else {}
        self.keyboard = KeyReader(lambda event: self.loop.post(self._on_hardware_key, event),
                                  grab=True,
                                  on_devices=lambda devices: self.keyhub.set_devices(devices),
                                  **devices)
        self._keys_owned: set[int] = set()
        self._key_owners: dict[int, str | None] = {}
        self.fonts = Fonts(os.path.join(package_dir, "assets", "fonts"))
        self.status = StatusInfo()
        self.stream = EventStream(self.client.socket_path,
                                  lambda name, payload: self.loop.post(self._on_daemon_event, name, payload))
        self.control = ControlServer(paths.control_socket, self.loop.post, self.handle_control)
        self.home_screen = HomeScreen(self)
        self.boot_screen = BootScreen(self, __version__)
        self.direct: DirectDisplay | None = None
        self.last_image = None
        self.last_launched = ""
        self.exit_code = 0
        self._booting = True
        self._last_frame: bytes | None = None
        self._last_render = 0.0
        self._render_timer = None
        self._save_timer = None
        self._toast: tuple[str, str] | None = None
        self._toast_timer = None
        self._dim_timer = None
        self._off_timer = None
        self._swallow_release = False
        self._daemon_apps: list[dict] | None = None
        self._fallback_timer = None
        self._started_at = time.monotonic()
        self.stats = {"frames": 0, "frames_written": 0, "events": 0}

    # =============================================================== startup
    def start(self) -> None:
        log.info("MFruit OS %s starting (package %s)", __version__, self.package_dir)
        set_debug(self.settings.get("developer.debug_logging"))
        self.install_bin_scripts()
        if not self.lifecycle.acquire_instance_lock():
            raise SystemExit("another MFruit OS instance is already running")
        # Launch gate: only tickets written by this process may start apps.
        self.lifecycle.revoke_all_tickets()
        self.lifecycle.set_gate("gate")
        self.router.set_root(self.boot_screen)
        self.boot_screen.set_step(0, DONE)
        self.boot_screen.set_step(1, RUNNING)
        self.registry.refresh(None)  # offline view first: apps from files
        self.registry.set_latest_versions(self.updater.latest_map())
        self.tasks.start()
        self.control.start()
        self.stream.start()
        try:
            self.keyhub.start()
        except OSError as exc:
            log.error("Key hub unavailable, apps will not get keyboard keys: %s", exc)
        self.keyboard.start()
        self._refresh_status()
        self._fallback_timer = self.loop.call_later(FALLBACK_AFTER_SEC, self._check_fallback)
        sdnotify.notify("READY=1")
        interval = sdnotify.watchdog_interval()
        if interval:
            self._watchdog(interval)

    def run(self) -> int:
        self.start()
        self.loop.run()
        return self.exit_code

    def _watchdog(self, interval: float) -> None:
        sdnotify.notify("WATCHDOG=1")
        self.loop.call_later(interval, self._watchdog, interval)

    def install_bin_scripts(self) -> None:
        """Keep ~/.whisplay-os/bin in sync with the running version (no root needed)."""
        system_current = os.path.join(self.paths.system_dir, "current")
        root = system_current if os.path.realpath(self.package_dir).startswith(
            os.path.realpath(os.path.join(self.paths.system_dir, "versions"))) else self.package_dir
        for name in SCRIPTS:
            source = os.path.join(self.package_dir, "scripts", name)
            target = os.path.join(self.paths.bin_dir, name)
            try:
                with open(source, "r", encoding="utf-8") as fp:
                    content = (fp.read().replace("@MFRUIT_ROOT@", root)
                               .replace("@MFRUIT_HOME@", self.paths.home))
                try:
                    with open(target, "r", encoding="utf-8") as fp:
                        if fp.read() == content:
                            continue
                except FileNotFoundError:
                    pass
                with open(target + ".tmp", "w", encoding="utf-8") as fp:
                    fp.write(content)
                os.chmod(target + ".tmp", 0o755)
                os.replace(target + ".tmp", target)
                log.info("Installed helper %s", target)
            except OSError as exc:
                log.error("Cannot install helper %s: %s", name, exc)

    def _continue_boot(self) -> None:
        """Runs once the daemon granted the screen."""
        boot = self.boot_screen
        boot.set_step(1, DONE)
        boot.set_step(2, DONE if not self.settings.load_errors else STEP_FAILED)
        boot.set_step(3, RUNNING)
        self.refresh_registry(query_daemon=True)
        synced = self.lifecycle.sync_registrations(self.registry.managed())
        adopted = self.lifecycle.adopt_all(self.registry.daemon_registrations())
        if synced or adopted:
            self.refresh_registry(query_daemon=True)
        boot.set_step(3, DONE)
        boot.ready = True
        self.request_render()
        self.loop.call_later(0.35, self._finish_boot)

    def _finish_boot(self) -> None:
        self._booting = False
        self.router.set_root(self.home_screen)
        if self.settings.load_errors:
            self.toast("Settings had errors; defaults used", "error")
        self._check_system_update_state()
        self._maybe_autostart()
        self.install_pending_apps()
        if self.settings.get("updater.auto_check") and self.updater.check_due():
            self.loop.call_later(20.0, lambda: self.check_updates(quiet=True))
        self._schedule_update_checks()

    def _schedule_update_checks(self) -> None:
        # A cheap timestamp comparison; the actual interval lives in check_due().
        def tick():
            if self.settings.get("updater.auto_check") and self.updater.check_due():
                self.check_updates(quiet=True)
            else:
                self.install_pending_apps()
            self.loop.call_later(UPDATE_TICK_SEC, tick)
        self.loop.call_later(UPDATE_TICK_SEC, tick)

    def _check_system_update_state(self) -> None:
        state = self.paths.state_dir
        rollback_note = os.path.join(state, "system_rollback.env")
        if os.path.exists(rollback_note):
            self.push(MessageScreen(self, "Update rolled back",
                                    "The new MFruit OS version failed to start, so the previous "
                                    "version was restored automatically.", tone="warning",
                                    icon="warning"))
            _remove(rollback_note)
        pending = os.path.join(state, "pending_system_update.json")
        if os.path.exists(pending):
            def confirm_success():
                _remove(pending)
                _remove(os.path.join(state, "pending_system_update.env"))
                log.info("System update to %s confirmed healthy", __version__)
                self.toast(f"Updated to {__version__}", "success")
            self.loop.call_later(15.0, confirm_success)

    def _maybe_autostart(self) -> None:
        marker = os.path.join(self.paths.state_dir, "autostart_boot_id")
        boot_id = _read(("/proc/sys/kernel/random/boot_id")).strip() or "unknown"
        if _read(marker).strip() == boot_id:
            return  # already done for this boot (e.g. the launcher restarted)
        try:
            with open(marker, "w", encoding="utf-8") as fp:
                fp.write(boot_id)
        except OSError as exc:
            log.warning("Cannot write autostart marker: %s", exc)
        for entry in self.registry.apps():
            if entry.autostart and entry.launchable:
                log.info("Autostarting %s", entry.id)
                self.loop.call_later(AUTOSTART_DELAY_SEC, self.launch_app, entry.id, "autostart")
                return

    # ============================================================ daemon events
    def _on_daemon_event(self, name: str, payload: dict) -> None:
        self.stats["events"] += 1
        log.debug("event %s %s", name, payload)
        self.focus.on_event(name, payload)

    def _app_in_use(self, app_id: str) -> bool:
        """Is ``app_id`` open or running? Asked from the install worker."""
        session = self.apps.session
        if session is not None and session.app_id == app_id:
            return True
        entry = self.registry.get(app_id)
        return bool(entry and entry.running)

    def _register_manifest(self, manifest: Manifest) -> None:
        """Installer callback (worker thread): register an OS-managed app."""
        entry = AppEntry(id=manifest.id, name=manifest.name, kind="os", env=dict(manifest.env),
                         exit_gesture=manifest.exit_gesture, priority=manifest.priority,
                         disable_esc_exit_key=manifest.disable_esc_exit_key,
                         icon_text="".join(w[0] for w in manifest.name.split()[:2]).upper())
        self.lifecycle.register(entry)

    # FocusListener -------------------------------------------------------------
    def on_daemon_state(self, connected: bool) -> None:
        self.status.daemon_ok = connected
        if connected:
            self._leave_fallback()
            self.lifecycle.register_os(self.package_dir)
        else:
            self._daemon_apps = None
            if self._fallback_timer is None:
                self._fallback_timer = self.loop.call_later(FALLBACK_AFTER_SEC, self._check_fallback)
        self.request_render()

    def on_focus_gained(self) -> None:
        self.keyboard.set_grab(True)          # back from the daemon desktop, if there
        self._last_frame = None
        self.backlight.forget()
        self._update_backlight_hold()
        self.backlight.wake()
        self.led.forget()
        self.led.show(self.led.state if self.led.state in ("update", "error") else "idle", force=True)
        self.gestures.reset()
        self._keys_owned.clear()
        self._swallow_release = False
        self._arm_idle_timers()
        if self._booting:
            self._continue_boot()
        self._refresh_status()
        self._render_now()

    def on_focus_lost(self) -> None:
        self._cancel_idle_timers()
        self.gestures.reset()
        self._keys_owned.clear()

    def on_button(self, pressed: bool) -> None:
        self._on_raw_button(pressed)

    def on_exit_requested(self) -> None:
        top = self.router.top
        if top is not None and not top.modal:
            self.router.home()

    # ApplicationManager listener ---------------------------------------------
    def on_session_running(self, session) -> None:
        self.lifecycle.revoke_ticket(session.app_id)
        entry = self.registry.get(session.app_id)
        if entry is not None:
            entry.running = entry.foreground = True

    def on_session_ended(self, session) -> None:
        self.lifecycle.revoke_ticket(session.app_id)
        from mfruitos.launcher.ui.screens.dialogs import LoadingScreen
        while isinstance(self.router.top, LoadingScreen):
            self.router.pop()
        self._close_app_after_session(session)
        self.refresh_registry(query_daemon=True)
        if self.router.top is self.home_screen:
            self.home_screen.focus_key(session.app_id)
        entry = self.registry.get(session.app_id)
        # Only this session's own run record may explain how it ended.
        exit_info = self.lifecycle.session_exit(session.app_id, session.id)
        if exit_info and exit_info.get("pid"):
            session.pid = session.pid or exit_info["pid"]
        if session.outcome == FAILED:
            if entry is None:
                self.toast(session.detail[:40] or "Launch failed", "error")
            elif exit_info and exit_info.get("exit_code") == 0:
                self.toast(f"{entry.name} finished", "success")  # a task without a screen
            else:
                self.show_app_problem(entry, session.detail, exit_info)
            return
        if session.outcome == HEADLESS:
            self._show_headless(session.app_id)
            return
        self.led.show("idle")
        if entry is not None and exit_info and exit_info.get("exit_code"):
            runtime = (exit_info.get("ended_at") or 0) - (exit_info.get("started_at") or 0)
            if runtime < 10:
                self.show_app_problem(entry, "", exit_info, "Application stopped unexpectedly.")
            else:
                self.toast(f"{entry.name} exited (code {exit_info['exit_code']})", "error")

    def _close_app_after_session(self, session) -> None:
        """Leaving an app closes it completely unless it may keep running."""
        entry = self.registry.get(session.app_id)
        if session.kind != "app" or entry is None or entry.background:
            return
        app_id, session_id = session.app_id, session.id

        def done(result):
            lifecycle_log.info("APP_CLOSED app=%s session=%s result=%s", app_id, session_id, result)
            # Always: the refresh when the session ended can come before the
            # process has gone, and a stale "running" refuses updates, rollback
            # and reset ("Stop the app first") until something else refreshes.
            self.refresh_registry(query_daemon=True)
        self.run_task(f"close-{app_id}", lambda: self.lifecycle.ensure_stopped(app_id, session_id),
                      done, lane="cleanup")

    def _show_headless(self, app_id: str) -> None:
        entry = self.registry.get(app_id)
        name = entry.name if entry else app_id
        from mfruitos.launcher.ui.components import Item, back_item
        actions = [back_item("OK")]
        if entry is not None:
            actions.insert(0, Item("Stop app", lambda: (self.lifecycle.request_stop(entry),
                                                        self.pop()), icon="stop"))
        self.push(MessageScreen(self, name, f"{name} is running but did not open a screen. It may "
                                            "be a background service or still starting.", actions,
                                tone="warning", icon="info"))

    def _is_page(self, app_id: str) -> bool:
        return any(page.id == app_id for page in self.registry.system_pages())

    def _lifecycle_context(self) -> dict:
        top = self.router.top
        context = {"screen": type(top).__name__.replace("Screen", "") if top else "-",
                   "foreground": self.focus.target or ("mfruit-os" if self.focus.has_focus else "-")}
        if top is self.home_screen:
            entries = self.home_screen.entries()
            if entries:
                context["selected"] = entries[min(self.home_screen.selected, len(entries) - 1)].key
        return context

    # =============================================================== input
    def _on_raw_button(self, pressed: bool) -> None:
        lifecycle_log.info("EVENT %s%s app_state=%s", "PRESS" if pressed else "RELEASE",
                           "".join(f" {k}={v}" for k, v in self._lifecycle_context().items()),
                           self.apps.state)
        self.led.button_feedback(pressed)
        top = self.router.top
        hook = getattr(top, "on_raw_button", None)
        if pressed:
            if self.backlight.state != "on" and self.direct is None:
                self.backlight.wake()
                self._swallow_release = True
                self._arm_idle_timers()
                self._render_now()
                return
            self._swallow_release = False
            if hook:
                hook(True)
            self.gestures.press()
        else:
            if self._swallow_release:
                self._swallow_release = False
                return
            if hook:
                hook(False)
            self.gestures.release()
        self._arm_idle_timers()

    def _on_hardware_key(self, event: KeyEvent) -> None:
        """Every keyboard key comes here first (the keyboards are held
        exclusively). A key goes to whoever owned the screen when it went
        down -- MFruit OS or the foreground app -- and so do its repeats and
        its release, even if the screen has changed hands in between."""
        if event.action == KEY_DOWN:
            owner = self._key_route()
            self._key_owners[event.code] = owner
        else:
            owner = self._key_owners.get(event.code)
            if event.action == KEY_UP:
                self._key_owners.pop(event.code, None)
        if owner == OS_APP_ID:
            self._on_key(event)
        elif owner is not None and self._is_page(owner):
            if event.action == KEY_UP or (event.action == KEY_REPEAT and event.value in ("enter", "escape")):
                return
            try:
                self.client.request("mfruit.page.key", {"app_id": owner, "kind": event.kind,
                                                        "value": event.value}, timeout=0.5)
            except DaemonError as exc:
                log.warning("Cannot forward key to %s: %s", owner, exc)
        elif owner is not None:
            if not self.keyhub.send(owner, event):
                self._bridge_key(owner, event)

    def _bridge_key(self, owner: str, event: KeyEvent) -> None:
        """A key for a foreground app that is not listening on the key hub.

        Such apps follow the Whisplay keyboard convention instead: Space is
        their button and the daemon closes them on Esc. MFruit OS holds the
        keyboards, so it forwards those two keys through the daemon wrapper
        (``mfruit.app.key``). Space is not forwarded to apps that claim Esc
        (MFruit SDK apps): they take keys from the hub once connected.
        """
        if event.kind != "key" or event.action == KEY_REPEAT or event.value not in ("escape", "space"):
            return
        if event.value == "escape" and event.action != KEY_DOWN:
            return
        entry = self.registry.get(owner)
        if event.value == "space" and (entry is None or entry.disable_esc_exit_key):
            return
        if event.value == "escape":
            lifecycle_log.info("KEY_BRIDGE app=%s key=escape (app does not use the key hub)", owner)
        try:
            self.client.request("mfruit.app.key", {"app_id": owner, "value": event.value,
                                                   "action": 1 if event.action == KEY_DOWN else 0},
                                timeout=0.5)
        except DaemonError as exc:
            log.warning("Cannot forward %s to %s: %s", event.value, owner, exc)

    def _key_route(self) -> str | None:
        """Who a key pressed now belongs to."""
        if self._output() is not None:
            return OS_APP_ID
        if self.focus.mode in (APP, SYSTEM) and self.focus.target:
            return self.focus.target
        return None                           # the daemon desktop or a lock

    def _on_key(self, event: KeyEvent) -> None:
        """A keyboard key: Up/Down/Tab move, Enter opens, Esc goes back.

        Only keys that went down while MFruit OS owned the screen count: the
        key-up of the Esc that closed an app, or the auto-repeat of the Enter
        that opened one, must not act here (the keyboard is shared).
        """
        if self._output() is None:
            self._keys_owned.clear()
            return
        if event.action == KEY_DOWN:
            self._keys_owned.add(event.code)
        elif event.code not in self._keys_owned:
            return
        elif event.action == KEY_UP:
            self._keys_owned.discard(event.code)
            return
        action = KEY_ACTIONS.get(event.value) if event.kind == "key" else None
        if action is None or (event.action == KEY_REPEAT and action not in ("next", "previous")):
            return
        lifecycle_log.info("EVENT KEY %s -> %s%s", event.value, action,
                           "".join(f" {k}={v}" for k, v in self._lifecycle_context().items()))
        self._arm_idle_timers()
        if self.backlight.state != "on" and self.direct is None:
            self.backlight.wake()
            self._render_now()
            return
        self.dispatch(action)

    def _on_hold_armed(self, armed: bool) -> None:
        """Visual feedback only: the action itself fires when the button is released."""
        self.hold_armed = armed
        self.request_render()

    def _configure_gestures(self) -> None:
        mapping = {k: self.settings.get(f"button.{k}") for k in GESTURE_KEYS}
        self.gestures.configure(mapping, self.settings.get("button.click_gap_ms"),
                                self.settings.get("button.long_press_ms"))

    def _on_gesture(self, gesture: str) -> None:
        lifecycle_log.info("GESTURE %s -> %s", gesture, self.settings.get(f"button.{gesture}"))
        top = self.router.top
        hook = getattr(top, "on_gesture", None)
        if hook is not None and hook(gesture):
            return
        self.dispatch(self.settings.get(f"button.{gesture}"))

    def dispatch(self, action: str) -> None:
        top = self.router.top
        if top is None or action == "none":
            return
        log.debug("action %s on %s", action, type(top).__name__)
        if top.handle(action):
            return
        if action == "back":
            if top.modal:
                self.toast("Please wait…")
            elif not self.router.pop():
                pass
        elif action == "home" and not top.modal:
            self.router.home()

    # ============================================================== rendering
    def _on_route_change(self) -> None:
        self._arm_idle_timers()
        self.request_render()

    def request_render(self) -> None:
        if self._render_timer is not None:
            return
        wait = max(0.0, MIN_FRAME_INTERVAL - (time.monotonic() - self._last_render))
        self._render_timer = self.loop.call_later(wait, self._render_now)

    def _output(self):
        if self.direct is not None and self.direct.attached:
            return self.direct
        if self.focus.has_focus:
            return self.focus.framebuffer
        return None

    def compose(self):
        theme = get_theme(self.settings.get("display.theme"))
        painter = Painter(theme, self.fonts)
        top = self.router.top
        if top is not None:
            top.draw(painter)
            if top.show_status:
                draw_status_bar(painter, self.status, getattr(top, "title", ""))
            top.footer(painter)
        if self._toast:
            draw_toast(painter, *self._toast)
        return painter.image

    def _render_now(self) -> None:
        if self._render_timer is not None:
            self._render_timer.cancel()
            self._render_timer = None
        output = self._output()
        if output is None or (self.backlight.state == "off" and self.direct is None):
            return
        self._last_render = time.monotonic()
        self.stats["frames"] += 1
        image = self.compose()
        self.last_image = image
        frame = to_rgb565(image)
        if frame == self._last_frame:
            return
        if output.write(frame):
            self._last_frame = frame
            self.stats["frames_written"] += 1

    def toast(self, text: str, tone: str = "") -> None:
        self._toast = (text, tone)
        if self._toast_timer is not None:
            self._toast_timer.cancel()
        self._toast_timer = self.loop.call_later(TOAST_SEC, self._clear_toast)
        self.request_render()

    def _clear_toast(self) -> None:
        self._toast = None
        self._toast_timer = None
        self.request_render()

    # ============================================================== timers
    def _refresh_status(self) -> None:
        if getattr(self, "_status_timer", None) is not None:
            self._status_timer.cancel()
        self._status_timer = self.loop.call_later(STATUS_REFRESH_SEC, self._refresh_status)
        if self._output() is None or self.backlight.state == "off":
            return  # nobody is looking; skip the reads
        wifi = system_info.wifi_level()
        if wifi is not None and wifi > 0 and not system_info.has_default_route():
            wifi = 0
        battery, charging = hardware.read_battery()
        changed = (wifi, battery, charging) != (self.status.wifi_level, self.status.battery,
                                                self.status.charging)
        self.status.wifi_level, self.status.battery, self.status.charging = wifi, battery, charging
        busy = self.updater.busy
        if changed or busy != self.status.busy:
            self.status.busy = busy
            self.request_render()

    def _cancel_idle_timers(self) -> None:
        for name in ("_dim_timer", "_off_timer"):
            timer = getattr(self, name)
            if timer is not None:
                timer.cancel()
                setattr(self, name, None)

    def _arm_idle_timers(self) -> None:
        self._cancel_idle_timers()
        if not self.focus.has_focus or self.focus.mode != HOME:
            return
        timeout = self.settings.get("display.screen_timeout_sec")
        dim_after = self.settings.get("display.dim_after_sec")
        if self.settings.get("display.auto_dim") and (timeout == 0 or dim_after < timeout):
            self._dim_timer = self.loop.call_later(dim_after, self._dim)
        if timeout > 0:
            self._off_timer = self.loop.call_later(timeout, self._screen_off)

    def _dim(self) -> None:
        self._dim_timer = None
        if self.focus.has_focus and self.backlight.state == "on":
            self.backlight.dim()

    def _screen_off(self) -> None:
        self._off_timer = None
        top = self.router.top
        if getattr(top, "running", False) and getattr(top, "modal", False):
            self._off_timer = self.loop.call_later(30.0, self._screen_off)
            return  # keep the screen on during an update
        if self.focus.has_focus:
            self.backlight.off()

    def _schedule_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
        # Settings may change from a worker thread (rare); saving is thread-safe.
        if self.loop.in_loop_thread() or self.loop._thread_id is None:
            self._save_timer = self.loop.call_later(SAVE_DELAY_SEC, self._save_settings)
        else:
            self.loop.post(self._schedule_save)

    def _save_settings(self) -> None:
        self._save_timer = None
        self.settings.save()

    def _on_setting_changed(self, key: str) -> None:
        if key.startswith("button."):
            self._configure_gestures()
        elif key.startswith("led."):
            self.led.show(self.led.state, force=True)
        elif key == "developer.debug_logging":
            set_debug(self.settings.get(key))
        elif key == "updater.github_token":
            self.github.token = self.settings.get(key)
        elif key.startswith("display.") and key not in ("display.brightness",):
            self._arm_idle_timers()
        elif key.startswith("applications.") or key.startswith("apps."):
            self.registry.refresh(self._daemon_apps)
        self.request_render()

    # ============================================================== registry
    def refresh_registry(self, query_daemon: bool = True) -> None:
        if query_daemon and self.focus.connected:
            try:
                self._daemon_apps = self.client.list_apps()
            except DaemonError as exc:
                log.warning("app.list failed: %s", exc)
        self.registry.refresh(self._daemon_apps if self.focus.connected else None)
        if query_daemon and self.focus.connected and not self._booting and not self.apps.busy:
            # An app's own installer may have re-registered it with its own
            # launch command since the last scan: route it through the gate again.
            if self.lifecycle.adopt_all(self.registry.daemon_registrations()):
                self.registry.refresh(self._daemon_apps)
        self.registry.set_latest_versions(self.updater.latest_map())
        self._update_backlight_hold()
        self.request_render()

    def _update_backlight_hold(self) -> None:
        """Hold the backlight at 100% while an app with *Keep screen bright*
        keeps running in the background (the per-app ``screen_bright`` flag,
        set by the user or by the app through the SDK). Only while MFruit OS
        owns the screen does this matter; an app on screen sets its own."""
        holders = [e.id for e in self.registry.all()
                   if e.kind != "system" and e.running and e.background and e.screen_bright
                   and not e.foreground]
        if self.backlight.set_hold(bool(holders)):
            log.info("Backlight %s", f"held at 100% for {', '.join(holders)}" if holders
                     else "follows the display settings again")
            if self.focus.has_focus:
                self.backlight.wake()      # to 100%, or back to the user's level
                self._arm_idle_timers()

    # ============================================================== fallback
    def _check_fallback(self) -> None:
        self._fallback_timer = None
        if self.focus.connected or self.direct is not None:
            return
        if not self.settings.get("daemon.fallback_direct_display"):
            return
        state = daemon_unit_state()
        if state not in SAFE_STATES:
            log.info("Daemon unreachable (unit %s); waiting", state)
            self._fallback_timer = self.loop.call_later(FALLBACK_POLL_SEC, self._check_fallback)
            return
        root = find_whisplay_root(self.settings.get("daemon.whisplay_root"))
        if root is None:
            log.error("Daemon is %s and the Whisplay runtime was not found; no display", state)
            return
        display = DirectDisplay(root, lambda pressed: self.loop.post(self._on_raw_button, pressed))
        if not display.open():
            return
        self.direct = display
        from mfruitos.launcher.ui.screens.fallback import DaemonUnavailableScreen
        self.router.set_root(DaemonUnavailableScreen(self, state))
        self._last_frame = None
        self._render_now()
        self.loop.call_later(FALLBACK_POLL_SEC, self._watch_daemon_unit)

    def _watch_daemon_unit(self) -> None:
        if self.direct is None:
            return
        state = daemon_unit_state()
        if state not in SAFE_STATES:
            log.info("Daemon unit is %s; releasing hardware", state)
            self._leave_fallback()
            return
        self.loop.call_later(FALLBACK_POLL_SEC, self._watch_daemon_unit)

    def _leave_fallback(self) -> None:
        if self._fallback_timer is not None:
            self._fallback_timer.cancel()
            self._fallback_timer = None
        if self.direct is None:
            return
        self.direct.close()
        self.direct = None
        self._booting = True
        self.boot_screen = BootScreen(self, __version__)
        self.router.set_root(self.boot_screen)
        self.boot_screen.set_step(0, DONE)
        self.boot_screen.set_step(1, RUNNING)

    def retry_daemon(self, restart: bool) -> None:
        """From the fallback screen: hand hardware back and try the daemon again."""
        from mfruitos.launcher.direct import restart_daemon
        self._leave_fallback()
        self.toast("Retrying…")
        if restart:
            self.run_task("restart-daemon", restart_daemon,
                          lambda ok: None if ok else log.warning("daemon restart not permitted"))
        self._fallback_timer = self.loop.call_later(FALLBACK_AFTER_SEC, self._check_fallback)

    # ============================================================== lifecycle
    def yield_to_desktop(self) -> None:
        self.router.home()
        self.lifecycle.set_gate("open")  # the user drives the daemon desktop directly
        self.keyboard.set_grab(False)    # ... and its keyboard handling too
        self.focus.yield_to_desktop()

    def restart_launcher(self) -> None:
        log.info("Restart requested")
        self.shutdown(exit_code=0)

    def shutdown(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.flush_settings()
        if self.focus.token is not None and self.focus.has_focus:
            try:
                self.client.release_focus(OS_APP_ID, self.focus.token)
            except DaemonError as exc:
                log.warning("Release on shutdown failed: %s", exc)
        self.focus.framebuffer.detach()
        if self.direct is not None:
            self.direct.close()
            self.direct = None
        self.control.stop()
        self.stream.stop()
        self.keyboard.stop()
        self.keyhub.stop()
        self.bluetooth.close()
        self.tasks.stop()
        self.lifecycle.revoke_all_tickets()
        self.lifecycle.release_instance_lock()
        sdnotify.notify("STOPPING=1")
        self.loop.stop()

    # ============================================================== control
    def handle_control(self, cmd: str, args: dict) -> dict:
        from mfruitos.launcher.ctl_handlers import handle
        return handle(self, cmd, args)


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return fp.read()
    except OSError:
        return ""


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("Cannot remove %s: %s", path, exc)
