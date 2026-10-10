# Lifecycle

How mFruit OS starts, how it guarantees that selecting an app launches exactly
that app exactly once, and how it takes the screen back. Package lifecycle
(install, update, rollback, uninstall) is in
[apps/UPDATE_ROLLBACK.md](../apps/UPDATE_ROLLBACK.md).

```text
Home ─ navigate ─ select ─ confirm (hold, release) ─ launch exactly one app
     ─ app runs ─ app exits ─ back to Home
```

## Lifecycle invariants

1. **One launch authority.** All launch requests go through
   `ApplicationManager.request_launch(app_id, kind, source)`. It refuses rather
   than queues requests while a session exists. The host executes the request.
2. **Selection is separate from launching.** Moving a selection, rendering,
   refreshing the registry, installing an app or checking updates never
   launches an app. Only an explicit confirmation or configured autostart may
   request it. Newly installed apps have autostart disabled.
3. **Stable identity.** Use the immutable manifest ID, not menu position,
   display name, filename or PID. Every launch creates a new session ID;
   stale timers, process reports and clean-up cannot affect a later session.
4. **One foreground session.** The implemented states are
   `IDLE → STARTING → RUNNING → STOPPING → IDLE`; the outcome is recorded on the
   session. Registry enabled/installed flags are separate from session state.
5. **Consume the complete gesture before handoff.** A long press arms at the
   threshold, shows feedback and selects on release. An old press, release or
   repeat never acts on the next screen owner.
6. **Respect the launch gate.** Keep one-shot tickets, the launcher lock, the
   background daemon desktop and intruder eviction. An unexpected foreground
   app during a pending launch is never adopted as the requested app. Adopting
   an external foreground app while idle is a separate recovery path.
7. **Close apps after exit unless Keep running is set.** Allow the exit
   request and a 3-second grace period, then SIGTERM the matching process
   group, and SIGKILL after 2 more seconds. Use the matching session's
   `state/runs/<id>.json`, never a stale PID; log the result.
8. **Keep keyboard ownership coherent.** Each key press, repeat and release
   stays with the owner of the screen when the key went down.

Keep the screen stack, focus state and application session explicit. No event
may produce duplicate actions or replay a queued launch later. Do not hide a
race with longer debounce windows or sleeps
([Part I §7](DEVELOPMENT_RULES.md#7-user-experience-rules)).

## Application sessions (`core/application_manager.py`)

The ApplicationManager knows nothing about Whisplay. One session at a time;
requests while busy are refused and logged (`LAUNCH_REJECTED`), never queued;
every session has an ID and every host report carries it. Session kinds:
`app`, `page` (a host settings page) and `external` (an app found on screen
that mFruit OS did not launch, for example after a launcher restart).
Sources recorded on `LAUNCH_REQUEST`: `home`, `retry`, `settings`,
`autostart`, `control`.

| Outcome | Meaning |
|---|---|
| `exited` | the app left the screen normally |
| `failed` | it never showed a screen (crash, refused, blocked) |
| `headless` | it runs but never took the screen within the pending timeout |
| `replaced` | another app took the screen from it |

## Foreground state machine (`launcher/focus.py`)

```text
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
(`health.ping` → `foreground_app_id`) instead of trusting event order: the
`app_focus_revoked` caused by mFruit OS's own release can arrive *after* it has
re-acquired focus (caught by `tests/test_focus.py`).

## Launch gate and intruder eviction

- **Hold fires on release** (`launcher/navigation/gestures.py`): reaching the
  threshold only arms the hold ("Release to open"), so mFruit OS consumes the
  whole gesture before handing the screen over.
- **Tickets** (`scripts/mfruit-run`, `launcher/app_manager/lifecycle.py`):
  every app the daemon can start is registered with
  `~/.whisplay-os/bin/mfruit-run <id>` — packages mFruit OS installed and
  daemon apps it *adopted* (original registration saved under
  `~/.whisplay-os/adopted/<id>/`, restored on uninstall). While mFruit OS holds
  `state/launcher.lock`, `mfruit-run` starts an app only with the one-shot
  ticket written just before mFruit OS's own `app.launch`; anything else is
  `DENIED` in `logs/launch-gate.log`. Without mFruit OS the gate is open.
- **Intruder eviction** (`launcher/focus.py`): daemon pages open inside the
  daemon without a launch command and cannot be gated. A foreign app or page
  that takes the screen while a session is starting is closed with
  `app.exit.request`; the requested app keeps retrying and gets the screen.
- **Run records:** `mfruit-run` records the session ID with pid and exit code;
  only the ending session's own record explains how it ended.

## Guarantees and tests

| Guarantee | Mechanism | Test |
|---|---|---|
| Selecting (tapping) never launches | taps only move the selection | `test_selection_does_not_launch` |
| The selected app is the one launched | hold fires on release; session target | `test_correct_app_launches`, `test_wrong_app_is_not_launched` |
| Only one app process | single flight + launch gate | `test_duplicate_launch_is_prevented`, `test_press_during_launch_window_cannot_start_a_second_app` |
| A daemon page that appears during a launch is closed and the requested app wins | intruder eviction | `test_page_opened_by_another_client_during_launch_window_is_closed` (deterministic), `test_press_during_launch_window_page_is_closed` (button path) |
| No stale input reaches the new app | gesture consumed before hand-over | `test_stale_event_is_ignored` |
| No stale process or timer affects a new launch | session IDs | `test_stale_event_is_ignored`, `test_previous_process_cannot_affect_new_session` |
| Exit returns Home | reconcile on `desktop_entered` | `test_app_exit_returns_to_launcher` |
| A crashing app never crashes the launcher | session ends `failed`, error screen | `test_crashed_app_does_not_crash_launcher` |
| Rapid input is safe | recognizer + single flight | `test_rapid_input_is_safe` |

The launch-window tests run against the real daemon without the background
wrapper. With the wrapper installed (the default) the daemon desktop ignores
the button while mFruit OS runs, so a press during a launch does nothing.

**Residual without the wrapper:** a daemon page can appear for a fraction of a
second when the button is held on the daemon's desktop during an app's
start-up; mFruit OS closes it and the requested app still opens.

## Leaving an app

When the session ends, `Runtime.on_session_ended` removes the loading screen,
refreshes the registry and, unless the app is a `background` app or the user
chose *Keep running*, runs `AppLifecycle.ensure_stopped` on the `cleanup`
worker (invariant 7). A failed start within 10 seconds shows *Application
failed to start* with Retry / Logs / Back.

## Launcher lifecycle

1. **Service start.** systemd runs `boot-guard.sh` (`ExecStartPre`), then
   `python3 -m mfruitos`. The runtime takes `state/launcher.lock` (single
   instance; also proves to `mfruit-run` that the gate is active), revokes old
   tickets, sets the launch policy to `gate`, and shows the boot screen.
2. **Boot.** Once the daemon grants focus: load settings (errors are shown, not
   fatal), refresh the registry, register managed apps and adopt daemon apps
   through `mfruit-run`, then show Home. A pending system update is confirmed
   after 15 healthy seconds; a rollback note from the boot guard is shown.
3. **Autostart.** At most once per boot ID, the configured autostart app is
   launched through `ApplicationManager` with source `autostart`.
4. **Daemon loss.** On `_disconnected` the session ends and the state becomes
   OFFLINE; after 10 s with the daemon unit `inactive`/`failed`, the fallback
   display may take over ([Host API](HOST_API.md#fallback-display)).
5. **Shutdown.** Settings are flushed, focus released, sockets and workers
   stopped, tickets revoked and the lock released. `ExecStopPost=mfruitctl
   release` makes the daemon reclaim a frozen screen. The systemd watchdog
   restarts a hung launcher.

## Reading the lifecycle log

`~/.whisplay-os/logs/launcher.log` (logger `mfruitos.lifecycle`):

```text
EVENT PRESS screen=Home foreground=mfruit-os selected=alpha app_state=IDLE
EVENT RELEASE screen=Home foreground=mfruit-os selected=alpha app_state=IDLE
GESTURE long_press -> select
LAUNCH_REQUEST app=alpha kind=app source=home session=09db5fdb screen=Home selected=alpha
STATE alpha IDLE -> STARTING session=09db5fdb
TICKET app=alpha session=09db5fdb
DAEMON_LAUNCH app=alpha session=09db5fdb
PROCESS_STARTED app=alpha pid=111862 session=09db5fdb
INTRUDER app=whisplay-volume during session=09db5fdb (starting alpha); closing it …
STATE alpha STARTING -> RUNNING session=09db5fdb
SESSION_END app=alpha session=09db5fdb outcome=exited exit_code=0 detail=-
STATE alpha RUNNING -> IDLE session=09db5fdb
APP_CLOSED app=alpha session=09db5fdb result=exited
```

To find what caused a launch, look for `LAUNCH_REQUEST` and its `source`. A
launch mFruit OS did not request appears as `DENIED` in `launch-gate.log`
(apps) or `INTRUDER` (pages). `LAUNCH_REJECTED` shows refused requests and why;
`LAUNCH_REFUSED_BY_DAEMON` records who held the screen when the daemon refused.

## Root-cause history

The mechanisms above exist because of these confirmed defects. Evidence was
gathered on an Orange Pi Zero 2W with whisplay-daemon upstream 1066486 and
reproduced with the real daemon code in `tests/real_daemon/`.

| # | Cause | Symptom | Fix |
|---|---|---|---|
| RC1 | *Hold* fired at 0.7 s while the button was still down; the release reached the next screen owner (daemon desktop, a page, or the new app) | wrong app opened; two launches; a page opened and closed within a second | hold fires on release (1.1.0) |
| RC2 | while an app starts, the daemon desktop owns the button and acts as an independent launcher | a press during start-up launched another app or opened a page | launch gate tickets; intruder eviction; background wrapper (1.2.0) |
| RC3 | the daemon has one pending-launch slot; a second launch overwrites it | apps needing several focus attempts or giving up | single flight + gate |
| RC4 | no single-flight rule in mFruit OS | autostart, control socket or a stale Retry started overlapping launches | `ApplicationManager` (1.1.0) |
| RC5 | mFruit OS "followed" whatever app took the screen | RC1 masked as success | removed; a foreign app during a launch is an intruder |
| RC6 | keyboards were not grabbed; tty1's autologin shell executed typed keys | a launcher restart that looked like an updater crash | `EVIOCGRAB` and per-key ownership routing (1.4.0) |

The first fake daemon modelled neither the daemon desktop's button handling
nor its pending slot, which is why early tests passed while the device
misbehaved; the real-daemon harness now runs in the suite. The 2026-10-02
investigation of the intermittent `test_press_during_launch_window_page_is_closed`
failure found a daemon defect (a hold recognized as a tap,
[Host API fact 8](HOST_API.md#whisplay-daemon-facts-the-design-depends-on)),
not an mFruit OS defect; the test now synchronizes on observed daemon state
([record](../quality/records/2026-10-02-baseline-and-launch-window.md)).
