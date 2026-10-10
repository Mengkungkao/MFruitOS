# mFruit OS architecture

This document describes the **current implementation** (mFruit OS 1.4.0) and
how it maps onto the **target architecture**. Rules live in
[Development rules](DEVELOPMENT_RULES.md); the migration plan lives in the
[Roadmap](ROADMAP.md). Status words follow
[Part I §20](DEVELOPMENT_RULES.md#20-quality-status-language).

## Current runtime

Today mFruit OS runs **on top of whisplay-daemon**, not instead of it. The
daemon owns the display HAT and the foreground-app lifecycle; mFruit OS is a
daemon foreground app (`mfruit-os`) that draws into the daemon's shared
framebuffer and decides which app runs.

```text
 Apps (ConnectWifi, Messenger, WalkieTalkie, dashboard, chatbot, …)
   │  vendored mFruit App SDK (mfruit_sdk): input, UI chrome, status
   │  keys ◄── state/keys.sock (key hub) ───────────────────┐
   │  frames/button ◄── whisplay-daemon socket               │
   │  battery ◄── /tmp/pisugar-server.sock (PiSugar protocol) ─────────┐
   ▼                                                         │         │
 mFruit OS process (python3 -m mfruitos, whisplay-os.service)          │
   ├─ launcher: event loop, router, screens, gestures, key routing     │
   ├─ core: ApplicationManager (launch authority)                      │
   ├─ apps/updater/system: registry, manifest, installer, settings,    │
   │  diagnostics; PowerLink (battery state, safe-shutdown countdown)  │
   └─ Whisplay host code: focus.py, daemon/ client + events +          │
      framebuffer, app_manager/lifecycle.py, system/hardware.py,       │
      launcher/direct.py                                               │
   │ /tmp/whisplay-daemon.sock        │ state/power.sock (JSON lines)  │
   ▼                                  ▼                                │
 whisplay-daemon                    mfruit-power.service (ADR 0012) ◄──┤
 (Whisplay driver: drivers/whisplay   power/: battery state, safe      │
  → /usr/local/share/whisplay,          shutdown, board settings,      │
  started by whisplay-daemon-mfruit.py) clock, PiSugar protocol ───────┘
   │ LCD, backlight, RGB LED, button,   hosts/pisugar/: PiSugar 3 / 2 /
   │ app processes, focus; battery and    2 Pro drivers, stdlib I2C
   │ its PiSugar home hook through      │
   │ /tmp/pisugar-server.sock           │ I2C
   │ sound card module + overlays       │
   ▼                                    ▼
 Display HAT and board (Raspberry Pi Zero 2 W, Orange Pi Zero 2W), PiSugar battery board
```

### Ownership today

| Concern | Owner |
|---|---|
| LCD, backlight, RGB LED, button | whisplay-daemon |
| Battery board (PiSugar): readings, safe shutdown, board settings, clock, power cut after power-off | mFruit OS power service (`mfruit-power.service`, [ADR 0012](ADR/0012-own-power-management.md)) |
| Wi-Fi from a phone (when PiSugar's sugar-wifi-conf runs, its config and key, putting Bluetooth back) | mFruit OS launcher (`system/wifi_setup.py`, [ADR 0013](ADR/0013-phone-wifi-setup.md)); the tool itself is PiSugar's, unmodified |
| Foreground app, framebuffer sessions, starting app processes | whisplay-daemon |
| Which app may start, and when (launch sessions) | mFruit OS `ApplicationManager` |
| Launch gate, run records, stopping app process groups | mFruit OS `mfruit-run` + `AppLifecycle` |
| Exclusive keyboard capture and per-key routing | mFruit OS (`KeyReader` grab + `KeyHub`); the daemon in Daemon desktop mode |
| Launcher UI, gestures inside the launcher, settings | mFruit OS |
| App packages, versions, updates, registry | mFruit OS |
| App features, app data, app-specific dependencies | each app |

## Layer map: current modules and target layers

The target layers come from [Part I §4](DEVELOPMENT_RULES.md#4-platform-layers).
"Coupling" names what still prevents the module from sitting cleanly in its
layer; it is tracked in the [Roadmap](ROADMAP.md).

| Layer | Current modules | Status and coupling |
|---|---|---|
| A — Applications | separate repositories; `bundled/connectwifi`, `templates/whisplay-app-template` | IMPLEMENTED. Apps still talk to whisplay-daemon directly for frames and button events (via the Whisplay client), which is today's app contract. |
| B — App API / SDK | `mfruitos/sdk/` (vendored into apps as `mfruit_sdk`) | IMPLEMENTED for input, keyboard routing, status and UI chrome. `sdk/daemon.py` is Whisplay-specific. No lifecycle or data-path API yet. See [SDK](../apps/SDK.md). |
| C — Platform core | `core/application_manager.py`; `apps/` (manifest, registry); `updater/`; `power/` (power service, own process); `system/settings.py`, `system/diagnostics.py`, `system/system_info.py`, `system/bluetooth.py`; `logs.py`, `paths.py`, `provision.py` | IMPLEMENTED. `ApplicationManager` is host-independent. Some platform logic is composed in `launcher/runtime.py` and `launcher/services.py`; the registry and provisioning still special-case app IDs (see [known issues](../quality/KNOWN_ISSUES.md)). |
| UI (uses C) | `launcher/` loop, router, gestures, `ui/`, `screens/`, `ctl_handlers.py`, `control.py` | IMPLEMENTED. `runtime.py` is the composition root and also routes keys and hardware events. |
| D — Host interface | `ApplicationManager.Host` protocol (`start`, `stop`); `hosts/pisugar/base.Chip` (battery board) | PARTIAL. Two formal host boundaries. Display, focus, input, LED, backlight and process stop are called on concrete Whisplay classes. See [Host API](HOST_API.md). |
| E — Host implementation | `launcher/focus.py` (`ForegroundManager`), `daemon/` (client, events, framebuffer), `launcher/app_manager/lifecycle.py`, `system/hardware.py`, `launcher/keyhub.py`, `launcher/direct.py`, `scripts/mfruit-run`, `scripts/whisplay-daemon-mfruit.py`; `hosts/pisugar/` (PiSugar drivers and fakes), `scripts/mfruit-power-off`; `hosts/lora/` | IMPLEMENTED for Whisplay only. Not yet grouped as a `WhisplayHost`; no MockHost or TerminalHost exists. |

The detailed file-by-file map is in [Directory structure](DIRECTORY_STRUCTURE.md).

## Main flows

**Launch.** A press reaches mFruit OS as a daemon `button_pressed` event (or a
key from the grabbed keyboard). `GestureRecognizer` turns presses into
gestures; a hold arms at the threshold and selects on release. The router's
top screen handles the action; Home calls `ScreenServices.launch_app`, which
checks the registry entry, shows "Opening <App>" and calls
`ApplicationManager.request_launch`. The manager creates a session and asks
its host (`ForegroundManager`) to start it: write a one-shot ticket, release
mFruit OS's focus, call the daemon's `app.launch`. The daemon runs
`mfruit-run <id>`, which checks the ticket and execs the app. Details and
guarantees: [Lifecycle](LIFECYCLE.md).

**Return.** When the app releases the screen, the daemon emits
`desktop_entered`; `ForegroundManager.reconcile()` asks the daemon who is
foreground, ends the session and re-acquires focus. Unless the app may keep
running, `AppLifecycle.ensure_stopped` stops its process group after a grace
period.

**Install/update.** A screen or `mfruitctl` calls a `ScreenServices` method,
which runs an `UpdateService`/`Installer` job on the `jobs` worker with a
progress screen. On success the registry is refreshed and the app is
registered with the daemon through `mfruit-run`. Details:
[Update and rollback](../apps/UPDATE_ROLLBACK.md).

**Keys.** `KeyReader` holds every keyboard with `EVIOCGRAB`. Each key goes to
whoever owned the screen when it went down: mFruit OS's own navigation, the
foreground app through the key hub, or an internal daemon page through the
wrapper's `mfruit.page.key` command. See [SDK](../apps/SDK.md#keyboard-input-and-the-key-hub).

## Threads

| Thread | Job |
|---|---|
| main (event loop) | all UI and lifecycle state, rendering, timers; sleeps until the next event |
| `daemon-events` | reads the subscription socket, posts events to the loop, reconnects with backoff |
| `task-quick` | system info, diagnostics, release lists |
| `task-jobs` | update checks, installs, uninstalls (one at a time) |
| `task-bluetooth` | serialized BlueZ queries, discovery and device actions |
| `bt-agent` | pairing prompts and asynchronous confirmation replies on GLib |
| `task-cleanup` | app shutdown without blocking other worker lanes |
| `control` | `mfruitctl` socket; handlers run on the loop thread |
| `mfruit-keys` | USB/Bluetooth keyboards; blocks on the devices and inotify, posts keys to the loop |
| `power-events` | subscription to `mfruit-power.service`; posts battery state, low-battery countdown and board presses to the loop, reconnects with backoff |
| `wifi-setup`, `wifi-setup-log` | start/stop of PiSugar's sugar-wifi-conf (Bluetooth changes through the `bluetooth` lane); reading its log into a status; both post to the loop |

The power service is a separate process with one thread (a `selectors`
loop that also samples the board) plus short-lived threads for commands and
PiSugar-protocol tap hooks ([ADR 0012](ADR/0012-own-power-management.md)).

Only the loop thread mutates lifecycle, registry and screen state; other
threads `post` work to it ([Development rules, Part II](DEVELOPMENT_RULES.md#ui-thread-workers-and-resources)).

## Rendering

Screens draw with Pillow into a 240×280 RGB image (`ui/painter.py`), packed
to big-endian RGB565 with lookup tables (`ui/rgb565.py`) and written into the
mapped framebuffer. Measured on a Pi Zero 2 W: about 11–16 ms per frame
without NumPy. Frames render only on change, are coalesced to at most about
16 fps, and are skipped while the backlight is off or another app is in front.
Layout conventions: [Style guide](STYLE_GUIDE.md).

## Settings, Wi-Fi and Bluetooth

Settings screens read cached state; blocking Wi-Fi and Bluetooth queries run on
workers. Bluetooth has its own serial lane, reuses one query bus and one GLib
agent bus, and pairs asynchronously on the agent connection without replacing
the daemon's default agent. Settings → Wi-Fi launches ConnectWifi through
`ApplicationManager` and keeps the Settings stack, so closing it uncovers
Settings. Configuration keys: [Configuration](CONFIGURATION.md).

## Target architecture

PLANNED — this is the direction, not a description of completed modules.

```text
┌──────────────────────────────────────────────┐
│                 mFruit Apps                  │
│                                              │
│  Messenger · WiFi · Dashboard · Future Apps  │
└──────────────────────┬───────────────────────┘
                       │
                  mFruit App API
                       │
┌──────────────────────▼───────────────────────┐
│               mFruit Platform                │
│                                              │
│  ApplicationManager                          │
│  Registry                                    │
│  PackageManager                              │
│  UpdateManager                               │
│  Settings                                    │
│  Diagnostics                                 │
│  Event/Input abstraction                     │
│  Logging                                     │
└──────────────────────┬───────────────────────┘
                       │
                    Host API
              ┌────────┼─────────┐
              │        │         │
              ▼        ▼         ▼
        WhisplayHost  MockHost  FutureHost
              │
      whisplay-daemon
              │
          Hardware
```

```text
App → mFruit SDK → Platform contract → Host
```

How today's code relates to the target boxes:

| Target | Today |
|---|---|
| ApplicationManager | `core/application_manager.py` — IMPLEMENTED, host-independent |
| Registry | `apps/registry.py` — IMPLEMENTED |
| PackageManager | `updater/installer.py`, `verifier.py`, `rollback.py`, `catalog.py` — IMPLEMENTED (not named PackageManager) |
| UpdateManager | `updater/service.py`, `github.py`, `gittrack.py` — IMPLEMENTED (as `UpdateService`) |
| Settings | `system/settings.py` — IMPLEMENTED |
| Diagnostics | `system/diagnostics.py`, `system_info.py` — IMPLEMENTED |
| Event/Input abstraction | `launcher/navigation/gestures.py`, `sdk/keys.py`, key routing in `runtime.py` — IMPLEMENTED for Whisplay; not host-neutral |
| Logging | `logs.py`, structured `mfruitos.lifecycle` log — IMPLEMENTED |
| Host API | `ApplicationManager.Host` only — PARTIAL ([Host API](HOST_API.md)) |
| WhisplayHost | scattered Whisplay classes — IMPLEMENTED, not grouped |
| MockHost | `tests/fake_daemon.py` emulates the daemon for tests only — PLANNED as a host |
| FutureHost | PLANNED |

The extraction order and its acceptance criteria are in the
[Roadmap](ROADMAP.md) and [ADR 0005](ADR/0005-incremental-host-boundary-extraction.md).
