# Baseline, launch-window investigation, fixes and Pi install — 2026-10-02

## Scope

- **Source:** commit `f15afe5` plus uncommitted working-tree changes of this
  session (documentation restructure, doc-path references in code/tests, the
  launch-window test change). Runtime behavior is unchanged from `cfe8ac2`
  except the text of one updater hint.
- **Dev machine:** Linux 6.8.12 aarch64 (tegra), Python 3.12.3, Pillow 10.2.0,
  whisplay-daemon source vendored in the ai-chatbot repository
  (`~/ai-chatbot/Whisplay`, repository commit `e57cc4c`, 2026-10-01); the
  final local `scripts/check.sh` run used upstream PiSugar/Whisplay `1066486`,
  the revision CI pins.
- **Raspberry Pi Zero 2 W** (`jarvis@192.168.0.33`): Debian 13, aarch64,
  Python 3.13.5, Pillow 11.1.0, whisplay-daemon source `1066486`
  (2026-09-09). Pi times below are the Pi's local time.

## Results

| Check | Command or procedure | Result |
|---|---|---|
| Full suite, dev machine, before changes | `WHISPLAY_SRC=… python3 -m unittest discover -s tests -v` at `cc459e8` | AUTOMATED: 348 passed, 0 skipped, 147 s |
| Original launch-window test, dev machine | 20 × `-k test_press_during_launch_window_page_is_closed` | AUTOMATED: 15 passed, **5 failed** (25%) |
| Diagnostic runs with daemon trace | 8 instrumented runs keeping `daemon.log` | 2 failures; see root cause |
| Revised launch-window tests, dev machine | 20 × (button-path test + deterministic test) | AUTOMATED: 20/20 iterations passed, 0 skipped |
| Negative control | both tests with `ForegroundManager._evict` patched to a no-op | both FAIL (page keeps the screen; requested app never gets it) |
| Full suite, dev machine, after changes | same command | AUTOMATED: 349 passed, 0 skipped, 159 s |
| Full suite, Pi, candidate copy | `~/MFruitOS-candidate`, `WHISPLAY_SRC=/home/jarvis/Whisplay` | AUTOMATED: **349 passed, 0 skipped, 308 s** (log `~/.mfruit-validation/candidate-full-20261002.log`) |
| Revised launch-window tests, Pi | 10 iterations | AUTOMATED: 10/10 passed, 0 skipped (`~/.mfruit-validation/lw-*.log`) |
| Install on the Pi | backup, then `scripts/install.sh --no-service --yes`, `sudo -n systemctl restart whisplay-os.service` | active `1.4.0-local20261002150338`; self-test 39 screens; configuration, apps and preferences preserved |
| Health check, Pi | `mfruitctl status`, `systemctl show` | Home/IDLE, focus held, 9 apps, keyboards `event0`/`event4` grabbed, launcher and daemon active with 0 restarts, no journal errors |
| Live lifecycle, Pi | `mfruitctl launch connectwifi`, then `mfruitctl key escape` through the key hub | STARTING→RUNNING in 1.19 s; `SESSION_END outcome=exited`; `APP_CLOSED result=exited`; no process left; back at Home |
| Sideload folder fix (KI-1), dev machine | 4 new installer tests before the fix | 4 FAIL (escaping symlink installed, no limit, set-uid kept, FIFO gave a confusing copy error); after the fix all pass with 2 new verifier tests |
| Test keyboard isolation (KI-6), Pi | full suite after the fix, counting `cannot grab keyboard` lines | 0 (dozens before) |
| Full suite, Pi, tree with KI-1 and KI-6 fixes | `~/MFruitOS-candidate`, `WHISPLAY_SRC=/home/jarvis/Whisplay` | AUTOMATED: 356 passed, 0 skipped, 309 s (`~/.mfruit-validation/final-full-20261003.log`) |
| `scripts/check.sh`, dev machine, pinned upstream Whisplay `1066486` | the CI command | AUTOMATED: all checks passed (356 tests) |
| Final tree (adds KI-5), dev machine | `scripts/check.sh` with pinned `1066486` | AUTOMATED: 357 passed; the whitespace step first caught a blank line at EOF, fixed, then `--quick` passed |
| Final tree, Pi | full suite in `~/MFruitOS-candidate` | AUTOMATED: 357 passed, 0 skipped, 308 s, 0 keyboard-grab messages (`final2-full-20261003.log`) |
| Final install, Pi | `install.sh --no-service --yes`, restart | active `1.4.0-local20261002153118`; self-test 39 screens; the existing settings file with the removed keys loaded without warnings; Home/IDLE, 0 restarts |
| Final live lifecycle, Pi | `mfruitctl launch connectwifi`, `key escape` | `SESSION_END outcome=exited`, `APP_CLOSED result=exited`, no process left |

Pi backup before installation:
`~/mfruit-backups/20261002-145215-before-docs-restructure/` (`.whisplay-os`,
daemon registrations, service definitions, previous active version
`1.4.0-local20260930185444`, which remains in `system/versions/` for rollback).

## Launch-window investigation

- **Problem:** `test_press_during_launch_window_page_is_closed` intermittently
  did not log `INTRUDER app=whisplay-volume`, although the requested slow app
  opened (reported on the Pi on 2026-10-01).
- **Hypothesis from 2026-10-01:** the second hold began while MFruit OS still
  owned the screen. **Disproved here:** in every diagnostic run the daemon
  state before the hold was `foreground=None pending=slow`.
- **Evidence:** failing run — `BUTTON press` 3.535 s, `BUTTON release`
  4.436 s (held 0.90 s, threshold 0.7 s), no `_launch_app(whisplay-volume)`,
  daemon selection advanced from `whisplay-volume` to `whisplay-system`.
  Passing run — same timings, followed by `_launch_app(whisplay-volume)`.
- **Root cause:** whisplay-daemon `_monitor_loop` resets
  `_button_press_started_at` when it sees the button already released before
  `_on_button_released` acquires `state_lock`; while a launch is pending, the
  loop holds that lock to redraw the desktop every 100 ms, widening the
  window. The release then measures 0 s and the desktop treats the hold as a
  tap. A daemon defect
  ([Host API fact 8](../../platform/HOST_API.md#whisplay-daemon-facts-the-design-depends-on));
  MFruit OS behaved correctly in all runs.
- **Fix (test only):** wait for the observed launch window (`foreground` None,
  `pending` = app) instead of `sleep(0.2)`; start on the first of the
  consecutive daemon pages and hold again while the selection is a page; skip
  with a precise reason only if every hold became a tap; plus a deterministic
  test opening the page through `app.launch` during the window.
- **Hardware validation:** not required for a test-only change; the physical
  launch-window check remains item 6 of the [hardware checklist](../VALIDATION.md).

## Observations

- On the Pi, test runtimes log `cannot grab keyboard eventN: Device or
  resource busy`: tests that start a `Runtime` open real input devices; the
  live launcher already holds them. Recorded as a test-isolation issue.
- Four daemon registrations on the Pi (Messenger, WalkieTalkie, crypto
  dashboard, AI chatbot) are marked broken with *Working directory missing*:
  their checkouts do not exist on this Pi. Pre-existing; not caused by this
  install.

## Not verified

- Physical button, keyboard, display, LED, audio and reboot behavior of the
  new build (no hands-on check in this session).
- The Orange Pi was not tested.
- CI has not run on GitHub yet.
