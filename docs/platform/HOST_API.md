# Host API

A **host** is everything MFruit OS needs from the device underneath it:
screen ownership, frame output, input, indicators, status and app processes.
Today there is one host, whisplay-daemon on a Whisplay HAT, and most of its
contract is **implicit**: platform code calls concrete Whisplay classes. This
document records that contract as it exists, so it can be extracted into
explicit interfaces one boundary at a time
([Part I §25](DEVELOPMENT_RULES.md#25-current-whisplay-migration-strategy),
[ADR 0005](ADR/0005-incremental-host-boundary-extraction.md)).

## Formal interface today

`mfruitos/core/application_manager.py` defines the only explicit host
boundary:

```python
class Host(Protocol):
    def start(self, session: Session) -> None: ...   # put the app or page on screen
    def stop(self, session: Session) -> None: ...    # ask it to leave
```

The host reports back to the manager with the session ID it was given:
`process_started(session_id, pid)`, `on_foreground(session_id)` and
`on_ended(session_id, outcome, detail, exit_code)`. Reports for any other
session are dropped as `STALE_EVENT`. Outcomes: `exited`, `failed`,
`headless`, `replaced`. `ForegroundManager` (`launcher/focus.py`) is the
Whisplay implementation; `tests/test_application_manager.py` drives the
manager with a fake host.

## Implicit contract (Whisplay implementation)

| Capability | What the platform needs | Whisplay implementation today | Formal? |
|---|---|---|---|
| Launch session | start/stop a session, report foreground and end | `ForegroundManager.start/stop` → daemon `app.launch`, `app.exit.request` | Yes (`Host`) |
| Screen ownership | take, release and re-check the screen | `ForegroundManager.acquire/_release_own/reconcile` → `app.focus.acquire`, `app.focus.release`, `health.ping` (`foreground_app_id`) | No |
| Frame output | write a 240×280 big-endian RGB565 frame | `daemon/framebuffer.Framebuffer.write` (mmap of `framebuffer.acquire`); `launcher/direct.DirectDisplay.write` in fallback. Both expose `attached` and `write(frame) -> bool`, selected by `Runtime._output()` | No (duck-typed) |
| Button | press and release edges while MFruit OS owns the screen | daemon `button_pressed`/`button_released` events for `mfruit-os` → `FocusListener.on_button`; fallback: `WhisplayBoard` callbacks | No |
| Keyboard | exclusive capture, key events, device list | `sdk/keys.KeyReader` (evdev, `EVIOCGRAB`, inotify) — Linux, not daemon-specific | No |
| Backlight | brightness, dim, off | `system/hardware.BacklightController` → `backlight.set` | No |
| RGB LED | colour per platform state, button feedback | `system/hardware.LedController` → `led.set` (`led.fade` available in the client) | No |
| Battery | percent and charging | `system/hardware.read_battery` → pisugar-server socket (not the daemon) | No |
| Wi-Fi level | 0–3 signal for the status bar | `system/system_info.wifi_level` (`/proc/net/wireless`) | No |
| System pages | open the host's own settings pages | daemon internal pages (`whisplay-wifi`, `whisplay-bluetooth`, `whisplay-volume`, `whisplay-system`) launched as session kind `page` | Via `Host` |
| App registration | make an app launchable through the gate | `AppLifecycle.register/adopt/restore_adopted` → `app.register` with `mfruit-run <id>` | No |
| App processes | start, run record, stop the process group | daemon starts the launch command; `scripts/mfruit-run` writes `state/runs/<id>.json`; `AppLifecycle.ensure_stopped/force_stop` signal the process group | No |
| Launch gate | only the platform may start apps while it runs | `state/launcher.lock` (flock), `state/tickets/<id>`, `state/launch-policy`, checked by `mfruit-run` | No |
| Event stream | lifecycle and focus events, connect/disconnect | `daemon/events.EventStream` (global `events.subscribe`; synthetic `_connected`/`_disconnected`) | No |
| Page key input | keys for an internal daemon page | wrapper command `mfruit.page.key` | No |
| Keyboard bridge for apps without the key hub | Esc and Space for foreground apps that read keys the Whisplay way | `Runtime._bridge_key` → wrapper command `mfruit.app.key`: Esc runs the daemon's own Esc handling (closes the app unless `disable_esc_exit_key`), Space is broadcast as `button_pressed`/`button_released` to that app | No |
| Recovery display | show recovery UI when the host service is down | `launcher/direct.DirectDisplay` | No |
| LoRa radio | provision the shared SX126X module, report readiness | `hosts/lora/` (`sx126x`, `modelines`, `readiness`, CLI), `scripts/setup-radio.sh`; settings in the shared radio store ([ADR 0007](ADR/0007-shared-radio-capability.md)) | Yes (module boundary) |

## whisplay-daemon facts the design depends on

Verified against `daemon/whisplay_daemon.py` (upstream 1066486, the older Pi
build, and the copy vendored in the user's ai-chatbot repository at its commit
`e57cc4c`, used in the 2026-10-02 dev-machine baseline). A host replacing the
daemon must either provide the same semantics or the platform must change.

1. **`app.launch` is refused while another app is foreground.** To start an
   app, MFruit OS releases its own focus first, then calls `app.launch`.
2. **`desktop_entered`, `screen_locked` and `screen_unlocked` are sent only to
   global subscribers.** MFruit OS subscribes globally, so it also receives
   every app's scoped events and filters by `payload.app_id`.
3. **A launch that dies before taking focus produces no event.** While — and
   only while — a launch is pending, MFruit OS polls `app.list` every 0.25 s,
   bounded by the daemon's 8 s pending timeout.
4. **Button events are forwarded raw** to the foreground app. MFruit OS
   registers with `exit_gesture: "none"`, so the daemon does not count
   quad-clicks on the launcher; inside launched apps the app's registered
   exit gesture applies.
5. **The daemon does not track processes it did not start.** MFruit OS runs
   from systemd and registers a launch command that only summons the running
   instance (`mfruitctl summon`).
6. **A dead foreground app keeps the screen.** Hence the systemd watchdog and
   `ExecStopPost=mfruitctl release`, which asks the daemon to reclaim it.
7. **The daemon's desktop is a second launcher.** Whenever no app owns the
   screen — including while an app MFruit OS launched is still starting — the
   desktop handles the button with its own selection: a tap moves it, a
   release after ≥0.7 s launches it. MFruit OS completes every gesture before
   handing the screen over, gates app launches with tickets and evicts daemon
   pages that appear during a launch ([Lifecycle](LIFECYCLE.md)).
8. **The daemon can turn a hold into a tap.** `_monitor_loop` resets the press
   start when it sees the button already up before `_on_button_released` has
   taken the state lock; the release then measures 0 s. While a launch is
   pending the loop holds that lock to redraw the desktop every 100 ms, which
   widens the window. Evidence: 2026-10-02 trace, press 3.535 s → release
   4.436 s, no `_launch_app`, selection advanced
   ([record](../quality/records/2026-10-02-baseline-and-launch-window.md)).
   This is a daemon defect; MFruit OS must not depend on a desktop hold being
   recognized.

## Daemon commands used

`health.ping`, `app.register`, `app.list`, `app.launch`, `app.focus.acquire`,
`app.focus.release`, `app.exit.request`, `framebuffer.acquire`,
`backlight.set`, `led.set`, `led.fade`, `button.get_state`,
`events.subscribe`, plus the wrapper's `mfruit.page.key` and `mfruit.app.key`. The protocol is a
Unix socket (default `/tmp/whisplay-daemon.sock`) with one JSON request and
one JSON response per line; every request uses a fresh connection with a
timeout (`daemon/client.py`).

## Whisplay user interface in the background

`scripts/whisplay-daemon-mfruit.py` starts the unmodified daemon from the
Whisplay checkout (systemd drop-in written by `install.sh`) and patches five
`WhisplayDaemon` methods. The patches act only while MFruit OS holds
`state/launcher.lock` (checked through `/proc/locks`, never by taking the
lock), during a bounded start-up grace period, and not in Daemon desktop mode:

| Method | While MFruit OS runs |
|---|---|
| `_render_desktop` | draws nothing; the LCD keeps the last frame |
| `_on_button_pressed` / `_on_button_released` | ignored when no app owns the screen |
| `_handle_keyboard_action` | ignored when no app owns the screen |
| `_release_focus` | first draws the releasing owner's final frame |

So during an app's start-up the LCD shows MFruit OS's "Opening <App>" screen
and a press does nothing. `tests/test_background_ui.py` tests this against
the real daemon code, including a negative control without the wrapper. The
launch-window tests in `tests/test_launch_lifecycle.py` run **without** the
wrapper to cover installations using `--no-background-daemon`.

### LCD DC line parked low (always)

One patch applies whether or not MFruit OS runs: `park_dc_low` wraps
`WhisplayBoard._send_data` and `_send_data_bytes` so the LCD's data/command
line (BOARD 13: BCM 27 on a Pi, PH3 on an Orange Pi) is lowered after each
transfer. With the SX126X LoRa HAT's stock M0/M1 jumpers that line is the
module's **M1**; upstream Whisplay leaves it high after every frame, which holds
the radio in configuration mode (it neither sends nor hears; the radio apps
report "Radio deaf: check M0/M1"). The display samples DC only while SPI
clocks. During a frame (about 11 ms) the radio is still deaf; only rewiring
M0/M1 to free GPIOs removes that. This replaces WalkieTalkie's
`docs/whisplay-dc-fix.patch`, which edited the Whisplay checkout.
`tests/test_dc_park.py` covers it, including the real `runtime/whisplay.py`.

## Fallback display

When the daemon's systemd unit is `inactive` or `failed` (never while it is
starting), `launcher/direct.py` opens the official `WhisplayBoard` from the
Whisplay runtime to show *Daemon unavailable* with Retry / Restart daemon /
Diagnostics, and releases the hardware as soon as the unit becomes active
again. It is the only path that drives the HAT directly: without the daemon
there is no framebuffer in which to show the problem.

## Planned host interfaces

PLANNED — not implemented. The groups below follow the capabilities above and
the extraction sequence in [Part I §25](DEVELOPMENT_RULES.md#25-current-whisplay-migration-strategy):

| Step | Boundary | Starting point today |
|---|---|---|
| 1 | Formalize host interfaces around existing behavior | this document; `ApplicationManager.Host` |
| 2 | Daemon transport behind a `WhisplayHost` | `daemon/client.py`, `daemon/events.py` |
| 3 | Foreground/focus | `launcher/focus.py` |
| 4 | Input (button, keyboard routing) | `FocusListener.on_button`, `Runtime._on_hardware_key`, `sdk/keys.py` |
| 5 | Display/framebuffer | `Framebuffer`, `DirectDisplay`, `Runtime._output()` |
| 6 | LED, backlight, audio, power, battery | `system/hardware.py`, `system/diagnostics.py`, daemon pages |
| 7 | MockHost | `tests/fake_daemon.py` (test double today) |
| 8 | Shared contract tests against both hosts | `tests/test_focus.py`, `tests/test_launch_lifecycle.py` |

Each step keeps the Whisplay path working and is accepted only with its
regression coverage ([Roadmap](ROADMAP.md)).
