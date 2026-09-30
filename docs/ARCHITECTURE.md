# MFruit OS architecture

## Ownership

| Concern | Owner |
|---|---|
| LCD, backlight, RGB LED, button, keyboard, PiSugar | whisplay-daemon |
| Foreground app, framebuffer sessions, app processes | whisplay-daemon |
| Launcher UI, gestures inside the launcher, settings | MFruit OS |
| App packages, versions, updates, registry | MFruit OS |
| App functionality | the apps |

MFruit OS uses only the daemon's documented commands: `health.ping`,
`app.register`, `app.list`, `app.launch`, `app.focus.acquire`,
`app.focus.release`, `app.exit.request`, `framebuffer.acquire`,
`backlight.set`, `led.set`, `led.fade`, `button.get_state`,
`events.subscribe`. All socket code lives in `mfruitos/daemon/client.py`
(requests) and `events.py` (event stream).

## Daemon facts the design depends on

Verified against `daemon/whisplay_daemon.py` (upstream 1066486 and the older
build on the test Pi):

1. **`app.launch` is refused while another app is foreground.** To start an
   app, MFruit OS releases its own focus, then calls `app.launch`.
2. **`desktop_entered`, `screen_locked` and `screen_unlocked` are only sent to
   global subscribers.** MFruit OS subscribes globally, so it also receives
   app-scoped events of every app and filters by `payload.app_id`.
3. **A launch that dies before taking focus produces no event** (the daemon
   silently clears its pending state). While — and only while — a launch is
   pending, MFruit OS polls `app.list` every 0.5 s, bounded by the daemon's
   8 s pending timeout.
4. **Button events are forwarded raw** (`button_pressed`/`button_released`)
   to the foreground app, which interprets them. MFruit OS registers with
   `exit_gesture: "none"` — the daemon's option for an app that owns all
   gestures and provides another way home — so the daemon does not count
   quad-clicks on the launcher itself. Inside launched apps the daemon's
   normal exit gesture applies unchanged.
5. **The daemon does not track processes it did not start.** MFruit OS runs
   from systemd, so it is registered with a launch command that only
   *summons* the running instance (`mfruitctl summon`), never a second copy.
6. **A dead foreground app keeps the screen.** If the launcher died while
   showing its screen, the LCD would freeze on its last frame. Hence the
   systemd watchdog and `ExecStopPost=mfruitctl release`, which asks the
   daemon to reclaim the screen (`app.exit.request` → forced release after
   1.5 s).

7. **The daemon's desktop is a second launcher.** Whenever no app owns the
   screen — including while an app MFruit OS launched is still starting — the
   daemon's desktop handles the button with its *own* selection: a tap moves
   it, a ≥0.7 s release launches it (even while another launch is pending).
   MFruit OS therefore completes every gesture before handing the screen over,
   gates app launches with tickets and closes daemon pages that appear during
   a launch. See [LAUNCH_LIFECYCLE.md](LAUNCH_LIFECYCLE.md).
8. **The daemon can turn a hold into a tap.** Its monitor loop may reset the
   press start just before the release callback runs (more likely while a
   launch is pending, when it redraws the desktop every 100 ms).

## Application lifecycle (`core/application_manager.py`)

The ApplicationManager is the single launch authority and knows nothing about
Whisplay: one session at a time (`IDLE → STARTING → RUNNING → STOPPING`),
refused — never queued — requests while busy, session ids on everything, and
a structured log (`mfruitos.lifecycle`). The UI only calls
`request_launch(app, source)`; the Whisplay host below carries it out.

## Foreground state machine (`launcher/focus.py`)

```
            launch(app)                     app_foreground_acquired
  HOME ────────────────────► APP(pending) ─────────────────────────► APP(foreground)
   ▲   release, app.launch      │  exited early / 9.5 s headless              │
   │                            ▼                                             │
   └──────── acquire ◄──── error screen                desktop_entered ───────┘
   │
   ├── launch(daemon page) ──► SYSTEM ── desktop_entered ──► HOME
   ├── yield_to_desktop ─────► DESKTOP ── summon ──────────► HOME
   ├── screen_locked ────────► LOCKED ─── screen_unlocked ─► HOME
   └── _disconnected ────────► OFFLINE ── _connected ──────► HOME
```

Decisions are made by `reconcile()`, which asks the daemon who is foreground
(`health.ping` → `foreground_app_id`) instead of trusting event order. This
matters: the `app_focus_revoked` produced by MFruit OS's own release can
arrive *after* it has already re-acquired focus (a real bug caught by
`tests/test_focus.py`).

## Threads

| Thread | Job |
|---|---|
| main (event loop) | all UI state, rendering, timers; sleeps until the next event |
| `daemon-events` | reads the subscription socket, posts events to the loop, reconnects with backoff |
| `task-quick` | system info, diagnostics, release lists |
| `task-jobs` | update checks, installs, uninstalls (one at a time) |
| `control` | `mfruitctl` socket; handlers run on the loop thread |
| `mfruit-keys` | USB / Bluetooth keyboards; blocks on the devices and inotify, posts keys to the loop |

## Rendering

Screens draw with Pillow into a 240×280 RGB image (`ui/painter.py`), which is
packed to big-endian RGB565 with lookup tables and two 8-bit planes
(`ui/rgb565.py`) and written into the mapped framebuffer. Measured on a Pi
Zero 2 W: 11 ms per frame, no numpy (numpy would cost ~11 MB RSS and 0.4 s
start-up). Frames are rendered only on change, coalesced to at most ~16 fps,
and skipped while the backlight is off or another app is in front.

## Update pipeline

See [APP_DEVELOPMENT.md](../APP_DEVELOPMENT.md#how-updates-are-installed).
Layout per package:

```
apps/<id>/current -> versions/1.2.0-a1b2c3     atomic symlink swap
apps/<id>/versions/1.1.0-9f8e7d/               previous version = code backup
apps/<id>/data/                                survives updates
apps/<id>/backups/data-1.1.0/                  snapshot for rollback
apps/<id>/app.json                             install record
```

MFruit OS updates itself with the same pipeline (`system/versions`,
`system/current`). The TEST step runs `python3 -m mfruitos --self-test` from
the new folder. After activation the launcher restarts; `boot-guard.sh`
(plain sh, so it works even if the new Python code cannot start) rolls back
after three failed starts, and the launcher confirms a healthy update after
15 s.

## Whisplay's user interface in the background

`scripts/whisplay-daemon-mfruit.py` starts the unmodified daemon from the
Whisplay checkout (systemd drop-in written by `install.sh`) and patches five
methods of `WhisplayDaemon`, active only while MFruit OS holds
`state/launcher.lock` (checked by reading `/proc/locks`, never by taking the
lock) and is not in "Daemon desktop" mode:

| Method | While MFruit OS runs |
|---|---|
| `_render_desktop` | draws nothing (the LCD keeps the last frame) |
| `_on_button_pressed` / `_on_button_released` | ignored when no app owns the screen |
| `_handle_keyboard_action` | ignored when no app owns the screen |
| `_release_focus` | first draws the releasing owner's final frame |

So during an app's start-up the LCD shows MFruit OS's "Opening <App>" screen,
and a press in that window does nothing at all (it used to reach the daemon's
own launcher). Tested against the real daemon code in
`tests/test_background_ui.py`, including a negative control without the wrapper.

## Keyboards and the MFruit App SDK

whisplay-daemon reads USB and Bluetooth keyboards too, but gives keys only to
its own pages; for an external app it acts on Esc alone (it closes the app
unless the app registered `disable_esc_exit_key`). So MFruit OS and every
MFruit app read keyboards themselves, with `mfruitos/sdk/keys.py`:

- Only devices with letter keys count (not the Orange Pi's power button, ADC
  keys or IR receiver). `/dev/input` is watched with inotify, so a keyboard
  plugged in or paired later is found at once, and nothing polls while idle.
- Nobody grabs a device, so **every process sees every key**. Each reader acts
  only while its program owns the screen, and only on keys whose press it saw
  while it did: the key-up of the Esc that closed an app, or the auto-repeat
  of the Enter that opened one, is ignored by whoever has the screen next.
- MFruit OS maps ↑/← previous, ↓/→/Tab next, Enter select, Esc back, Home
  home (`Runtime._on_key`), and registers itself with `disable_esc_exit_key`.

Apps get the same controls and MFruit OS's look from the MFruit App SDK
(`mfruitos/sdk/`, copied into each app as `mfruit_sdk` by
`scripts/sdk-sync.sh`): `InputController` turns the button and the keyboard
into next / previous / select / back actions (plus talk on talk screens), and
`mfruit_sdk.ui` draws the status bar, lists and footer hints. The contract is
[APP_RULES.md](APP_RULES.md).

## Fallback display

When the daemon's systemd unit is `inactive` or `failed` (never while it is
starting), `launcher/direct.py` opens the official `WhisplayBoard` from the
Whisplay runtime to show *Daemon unavailable* with Retry / Restart daemon /
Diagnostics, and releases the hardware as soon as the unit becomes active
again. This is the only place MFruit OS touches hardware, because without the
daemon there is no framebuffer to show the problem.
