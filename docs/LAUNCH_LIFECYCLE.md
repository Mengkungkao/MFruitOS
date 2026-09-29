# Application launch lifecycle

How MFruit OS guarantees that selecting an app launches exactly that app,
exactly once — and why the first implementation did not.

```
Home ─ navigate ─ select ─ confirm (hold, release) ─ launch exactly one app
     ─ app runs ─ app exits ─ back to Home
```

## Root causes found (1.0.0)

Found on an Orange Pi Zero 2W with whisplay-daemon (upstream 1066486) and
reproduced with the **real daemon code** (`tests/real_daemon/`, a simulated
board plus fake apps with realistic start-up times).

| # | Cause | Symptom | Evidence |
|---|---|---|---|
| RC1 | *Hold* fired at 0.7 s **while the button was still down**. MFruit OS then handed the screen over, so the **release** went to whoever owned the screen next: (a) whisplay-daemon's own desktop, which treats a ≥0.7 s release as *its* long press and launches **its own selected entry**; (b) a daemon page, which took it as *select* on its first item (Back) and closed; (c) the new app, as a stray `button_released`. | Wrong app opened; two launches; the requested app refused with "another app is already foreground"; Power page opening and closing within a second | Device logs 08:21, 08:43, 08:47; reproduced: one hold → daemon `_launch_app` called for `alpha` **and** `whisplay-system` |
| RC2 | While an app starts up (1.5–7 s on these boards) no app owns the screen, so **the physical button belongs to the daemon's desktop** — an independent launcher with its own selection state. | A press during start-up launched another app or opened a daemon page | Reproduced: a hold during start-up opened the Volume page; the requested app never got the screen |
| RC3 | whisplay-daemon has **one pending-launch slot**; any second launch overwrites it and the first app's `app.focus.acquire` is refused ("another app is pending foreground"). | Apps needing several attempts or giving up | Device log 08:47:12; ConnectWifi/WalkieTalkie logs ("acquired after 3 attempts") |
| RC4 | MFruit OS had **no single-flight rule**: autostart, the control socket or a stale *Retry* could start a launch while another was in progress; timers were not tied to a launch. | Several apps started | Reproduced: three quick requests started `alpha, beta, alpha` |
| RC5 | A follow-up change made MFruit OS "follow" whatever app took the screen, which **masked RC1 as success**. | Wrong app shown as if intended | Device log 08:47:19 |

The fake daemon used by the first test suite modelled neither the daemon's
desktop button handling nor its pending slot — that is why tests passed while
the device misbehaved. The real-daemon harness now runs in the test suite.

## Fixes

1. **Hold fires on release** (`launcher/navigation/gestures.py`). Reaching
   0.7 s only *arms* the hold (the Home card shows "Release to open"); the
   action happens on release, so MFruit OS consumes the whole gesture before
   it hands the screen over. Fixes RC1 (a, b, c).
2. **ApplicationManager** (`core/application_manager.py`) is the single launch
   authority: at most one session; requests while a session exists are
   refused and logged, never queued; every session has an id; reports about
   any other session are dropped as `STALE_EVENT`. Fixes RC4.
3. **Launch gate** (`scripts/mfruit-run`, `launcher/app_manager/lifecycle.py`).
   Every app the daemon can start is registered with
   `~/.whisplay-os/bin/mfruit-run <id>` — MFruit OS packages and daemon apps
   it *adopts* (their original registration is saved under
   `~/.whisplay-os/adopted/<id>/` and restored on uninstall). While MFruit OS
   runs (it holds `state/launcher.lock`), `mfruit-run` starts an app only
   with the one-shot ticket MFruit OS writes just before its own
   `app.launch`; anything else is denied and logged in `logs/launch-gate.log`.
   Fixes RC2 and RC3 for apps. Without MFruit OS the gate is open and the
   daemon desktop behaves exactly as before.
4. **Intruder eviction** (`launcher/focus.py`). Daemon pages open inside the
   daemon without a launch command, so they cannot be gated. If one takes the
   screen while a session is starting, MFruit OS closes it with
   `app.exit.request`; the requested app (which keeps retrying, as Whisplay
   clients do) then gets the screen. Fixes RC2 for pages.
5. **No more "following"** (RC5): a foreign app on screen during a launch is
   an intruder; after a launch it ends the session as `replaced`.
6. **Exit codes per session.** `mfruit-run` records the session id with pid
   and exit code; only the ending session's own record is used, so an old
   process cannot produce an error for a new launch.

## Guarantees and the one residual

| Guarantee | Mechanism | Test |
|---|---|---|
| Selecting (tapping) never launches | taps only move the selection | `test_selection_does_not_launch` |
| The selected app is the one launched | hold fires on release; session target | `test_correct_app_launches`, `test_wrong_app_is_not_launched` |
| Only one app process | single flight + launch gate | `test_duplicate_launch_is_prevented`, `test_press_during_launch_window_cannot_start_a_second_app` |
| No stale input reaches the new app | gesture consumed before hand-over | `test_stale_event_is_ignored` |
| No stale process/timer affects a new launch | session ids | `test_stale_event_is_ignored`, `test_previous_process_cannot_affect_new_session` (core) |
| Exit returns Home | reconcile on `desktop_entered` | `test_app_exit_returns_to_launcher` |
| A crashing app never crashes the launcher | session ends as `failed`, error screen | `test_crashed_app_does_not_crash_launcher` |
| Rapid input is safe | recognizer + single flight | `test_rapid_input_is_safe` |

**Residual:** a *daemon page* (WiFi, Bluetooth, Volume, Power) can appear for
a fraction of a second if the button is held on the daemon's desktop while an
app is starting — the daemon opens pages itself and offers no way to veto
that. MFruit OS closes it immediately and the requested app still opens
(`test_press_during_launch_window_page_is_closed`). Removing this residual
entirely needs the daemon's desktop to stop acting while a launch is pending;
see "Next steps" in the architecture notes.

## Reading the lifecycle log

`~/.whisplay-os/logs/launcher.log` (logger `mfruitos.lifecycle`):

```
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
```

To find what caused a launch, look for the `LAUNCH_REQUEST` and its `source`
(`home`, `retry`, `settings`, `autostart`, `control`); a launch MFruit OS did
not request shows up as `DENIED` in `launch-gate.log` (apps) or `INTRUDER`
(pages). `LAUNCH_REJECTED` lines show refused requests and why.
