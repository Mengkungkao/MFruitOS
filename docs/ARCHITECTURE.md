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

## Fallback display

When the daemon's systemd unit is `inactive` or `failed` (never while it is
starting), `launcher/direct.py` opens the official `WhisplayBoard` from the
Whisplay runtime to show *Daemon unavailable* with Retry / Restart daemon /
Diagnostics, and releases the hardware as soon as the unit becomes active
again. This is the only place MFruit OS touches hardware, because without the
daemon there is no framebuffer to show the problem.
