# Keyboard bridge for plain Whisplay apps and App installer repair — 2026-10-03

## Scope

- Source: `f15afe5` plus the uncommitted working tree of 2026-10-02/03.
- Dev machine as in the [2026-10-02 record](2026-10-02-baseline-and-launch-window.md);
  Raspberry Pi Zero 2 W `jarvis@192.168.0.33`, Whisplay upstream `1066486`.
  Pi times are the Pi's local time.

## Problems (reported by the user)

1. Jump Game and Flappy Bird could not be played or left with a keyboard.
2. App installer showed apps as *Installed* although they were broken.

## Root causes

1. The games (Whisplay `example/`) read Space from `/dev/input` as their button,
   and Esc-to-exit comes from whisplay-daemon's own keyboard reader. Since 1.4.0
   MFruit OS holds every keyboard with `EVIOCGRAB` (RC6), so neither received
   any key. Only SDK apps (key hub) and internal daemon pages had a path.
2. `InstallAppScreen` marked a catalogue app *Installed* whenever its ID was
   registered, including registrations whose working directory is missing
   (Messenger, WalkieTalkie and the dashboard on this Pi), and offered no fix.

## Fix

1. Keep the grab (tty1 stays protected). For a foreground app not connected to
   the key hub, `Runtime._bridge_key` sends Esc and Space to the new wrapper
   command `mfruit.app.key`: Esc runs the daemon's own Esc handling (exit unless
   `disable_esc_exit_key`); Space is broadcast to that app as
   `button_pressed`/`button_released`. Space is not bridged to apps that claim
   Esc (SDK apps).
2. Broken catalogue apps show **Repair**, which reinstalls from the pinned
   catalogue source (a managed package, preferred by `mfruit-run`).

## Results

| Check | Result |
|---|---|
| `test_keys_reach_an_app_that_does_not_use_the_key_hub` (real daemon) before the fix | FAIL: Space never reached the foreground app |
| `test_broken_catalogue_app_is_offered_for_repair_not_shown_installed` before the fix | FAIL: `'Installed' != 'Repair'` |
| `scripts/check.sh`, dev machine, pinned `1066486` | AUTOMATED: all checks, 359 tests passed |
| Pi: `test_background_ui.py` (9) and `test_app_installer_screen.py` | AUTOMATED: passed |
| Pi install | backup `~/mfruit-backups/20261002-155951-before-keyboard-bridge`; active `1.4.0-local20261002160133`; launcher and whisplay-daemon restarted once (wrapper patched `handle_command`); 0 restarts afterwards |
| Pi live, Flappy Bird | idle frame unchanged until `mfruitctl key space`, then changed (game started); `mfruitctl key escape` → `KEY_BRIDGE`, `SESSION_END outcome=exited`, `APP_CLOSED result=exited`, no process left |
| Pi live, Jump Game | same: Space changed the frame; Esc returned Home; process closed |

## Repair of the broken catalogue apps (user's go-ahead)

- Added `mfruitctl catalog [<id>]` (CLI equivalent of Install/Repair; 3 unit
  tests) and installed it: active `1.4.0-local20261002161004`.
- **Incident:** that deploy restarted the launcher at 16:10:36 while an install
  of BTC Dashboard started on the device at 16:09:47 was running its smoke
  test; the job was killed mid-rollback (KI-9). Residue (partial version
  directory, empty `data/`, `apps/.work-24fa216f`) was removed after checking
  that `data/` was empty and nothing had been activated.
- `mfruitctl catalog <id>`, one at a time: BTC Dashboard installed in 48 s,
  Messenger in 36 s, WalkieTalkie in 35 s — all `verified=True`.
- Each launched (foreground within 1–3 s), returned Home on Esc through the key
  hub, `SESSION_END outcome=exited`, `APP_CLOSED result=exited`.
- Radio features of Messenger/WalkieTalkie (LoRa, Codec2, audio) were not
  exercised. AI Chatbot stays broken: it is not in the catalogue.

## Not verified

- A physical keyboard on the Pi (the live checks used `mfruitctl key`, which
  enters the same routing as a real key but does not read a device).
- KI-8: the adopted registration record is left behind after a repair.
