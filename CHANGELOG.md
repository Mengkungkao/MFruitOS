# Changelog

All notable changes to MFruit OS are documented here. Versions follow
[Semantic Versioning](https://semver.org/). App versions are independent of
the OS version.

## [1.2.0] - 2026-09-29

### Added
- **Whisplay's own user interface runs in the background.** `install.sh`
  starts whisplay-daemon through `whisplay-daemon-mfruit.py` (systemd
  drop-in): while MFruit OS runs, the daemon no longer draws its desktop or
  its "Opening app…" modal and ignores the button when no app owns the
  screen. It behaves normally when MFruit OS is not running or in
  Developer → Daemon desktop. Opt out with `install.sh --no-background-daemon`.
- "Opening <App>" loading screen, shown until the app draws its first frame.
- Leaving an app closes it completely (exit request, then its process group
  is stopped after 3 s). Per-app **Keep running** setting for apps that must
  stay on; manifests can default it with `"background": true`.
- Diagnostics shows whether the Whisplay UI is in the background.

### Changed
- Status bar: page name on the left, WiFi strength and battery on the right;
  the "MFruit OS" title row and the clock are gone, every list shows one more
  row. Dialogs show a short page label and a full heading.
- Screens render about 6× faster (text is rasterised once and cached):
  a frame takes ~16 ms instead of ~100 ms on a Pi Zero 2 W.
- Home scrolls in whole rows.

## [1.1.0] - 2026-09-29

Launch lifecycle fixes. Root causes and evidence: docs/LAUNCH_LIFECYCLE.md.

### Fixed
- Holding the button to open an app could open a **different** app, open two,
  or immediately close a daemon page: the hold fired while the button was
  still down and its release reached whisplay-daemon's own desktop (RC1).
  A hold now arms at 0.7 s ("Release to open") and fires on release.
- Pressing the button while an app was starting could start a second app
  from the daemon's desktop (RC2/RC3). Every app launch now needs a one-shot
  ticket from MFruit OS (`mfruit-run` launch gate); daemon pages opened in
  that window are closed and the requested app still opens.
- Launch requests from any source could overlap (RC4). A new core
  ApplicationManager allows one session at a time and ignores reports from
  old sessions.
- Removed the 1.0.0 "hand-off" behaviour that followed whatever app took the
  screen and masked the problem (RC5).
- An old run's exit code could be shown as the error of a new launch.

### Changed
- Daemon-registered apps are *adopted*: their daemon entry runs through
  `mfruit-run`; the original registration is kept in `~/.whisplay-os/adopted/`
  and restored by `uninstall.sh`. With MFruit OS stopped they launch exactly
  as before.
- MFruit OS refuses to start a second instance (`state/launcher.lock`).
- Structured lifecycle log (EVENT, GESTURE, LAUNCH_REQUEST, STATE, TICKET,
  PROCESS_STARTED, INTRUDER, SESSION_END, STALE_EVENT, LAUNCH_REJECTED).

### Tests
- Real-daemon test harness (`tests/real_daemon/`): runs whisplay-daemon's own
  code with a simulated board and realistic app start-up times.

## [1.0.0] - 2026-09-29

First release.

### Core OS
- Runs as a whisplay-daemon foreground app (`mfruit-os`); the daemon keeps
  ownership of LCD, backlight, LED, button and app lifecycle.
- Boot screen with real startup steps; Home launcher with status bar (clock,
  WiFi, PiSugar battery), app cards and status badges.
- Single-button navigation: tap = next, double = previous, hold = select,
  four clicks = back. All gestures configurable; configurations that would
  make *select* unreachable are refused.
- Screen auto-dim and timeout, dark and light themes.
- Daemon pages (WiFi, Bluetooth, Volume, Power) surfaced in Settings when the
  running daemon provides them.
- Automatic recovery: re-takes the screen after apps exit, crash or are
  revoked; survives daemon restarts and screen locks.
- Fallback display when whisplay-daemon is stopped, with Retry / Restart
  daemon / Diagnostics.

### App management
- Registry merging OS-managed packages, daemon-registered apps and daemon pages.
- Enable, disable, hide, reorder, default app, autostart, stop, force stop,
  per-app logs, uninstall.
- `mfruit-run` wrapper records exit codes; failed launches show
  "Application failed to start" with Retry / Logs / Back.

### Updater
- GitHub Releases (and semver tags) as the distribution source, ETag-cached.
- Safe pipeline: check, download, verify, backup, install, test, activate;
  automatic rollback on failure; the running version is never overwritten.
- Upgrade, downgrade, reinstall, rollback, install from GitHub, discovery by
  topic, local sideload.
- SHA-256 verification from GitHub asset digests or `SHA256SUMS` files.
- Commit tracking for existing apps installed as git checkouts.
- System self-update with a boot guard that rolls back a version that fails
  to start three times.

### Tooling
- `install.sh`, `uninstall.sh`, `update.sh`, `deploy.sh`, systemd unit with
  watchdog, `mfruitctl` command-line control.
- App template (`templates/whisplay-app-template`), documentation, unit and
  integration tests (fake daemon, end-to-end runtime).
