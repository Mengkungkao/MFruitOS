# Changelog

All notable changes to MFruit OS are documented here. Versions follow
[Semantic Versioning](https://semver.org/). App versions are independent of
the OS version.

## Unreleased

- Home App installer with checksum-pinned source packages, package-local
  dependency environments and restoration of saved apps to the menu.
- Bundled ConnectWifi and an initial menu with available starter games.
  Repeated installation preserves existing Wi-Fi packages, apps, settings
  and launch policy; daemon system pages remain accessible in clean-menu mode.
- Validate catalogue Python entry targets and generate UTF-8/LF scripts.
  Remove stale curated-menu IDs when forgetting an app.
- Check Python venv support before installing files, clean up the Wi-Fi
  polkit rule on uninstall, and end daemon startup grace after launcher handoff.
- Add focused installer, catalogue, provisioning, navigation and startup tests.
  Full Linux and live-device validation for this follow-up remains pending.

## [1.4.0] - 2026-09-30

- Canonical app creation/development/production rules, native package preflight,
  and a device setup checker with a manual installation/debug/recovery guide.
- Keep documentation in installed versions; close test fixture resources and
  remove tracked Python bytecode.

- MFruit OS branding in app labels, diagnostics, CLI help and package errors.
  Messenger's app description is Radio Message. Existing hardware identifiers,
  service names, paths and launch behavior stay compatible.
- Grouped Settings with coloured icon tiles, Wi-Fi and Bluetooth first, and
  About, Software Update, diagnostics and power under General.
- Settings → Wi-Fi now opens Connect WiFi directly as one MFruit-styled
  network manager, with connection/IP status, nearby and hidden networks,
  saved-profile joining, password recovery and phone setup in one flow. It
  returns to Settings on exit, stays in Apps for management and leaves Home.
- Wi-Fi opens directly without the Connect WiFi loading screen. It now uses
  shared SDK gestures: tap next, double previous, hold/release select, four
  clicks back; explicit Back to Settings rows remain available.
- The RGB light gives white button feedback. Connect WiFi also uses it for
  Wi-Fi signal, scanning/connecting activity and success/failure, while
  honoring the existing Light switch and brightness.
- Bluetooth device groups, discovery, power, connect/disconnect, confirmed
  forgetting, passkey display and numeric confirmation. Blocking operations
  use a separate worker; the pairing agent does not replace the daemon's agent.
- Bluetooth recovery: reuse slow agent startup, report discovery failures,
  preserve completed device actions if refreshing status fails, and ignore
  pairing callbacks from an earlier operation.
- Closing Bluetooth cancels pending pairing on its existing agent connection
  and releases the waiting worker immediately. Queued pairing cannot start
  after shutdown.
- Enforce LF source/script line endings across checkouts so Windows-origin
  copies cannot break the Linux launch gate; refresh boot and Settings images.
- Boot draws only the centred logo on a dark background; startup steps stay
  in the log and configuration errors remain visible after boot.
- SDK 1.2.0: MFruit OS exclusively grabs keyboards and routes each key to
  the foreground owner through its key hub. This prevents keys reaching tty1's
  autologin shell and accidentally executing a launcher restart.
- Deploy the matching SDK to keyboard apps with this release. Daemon desktop
  mode releases the keyboard grab; returning to MFruit OS takes it again.

## [1.3.0] - 2026-09-30

### Added
- **The MFruit App SDK 1.1.0** (`mfruitos/sdk/`, copied into apps as `mfruit_sdk`
  with `scripts/sdk-sync.sh`): one input controller for the button and USB or
  Bluetooth keyboards, and MFruit OS's look — status bar (page name, WiFi,
  battery), footer hints, lists, toast, text field, theme, fonts, RGB565.
  Keys count only while the app has the screen, and only keys pressed while
  it did. Talk screens talk on a hold or Space.
- **Keyboard control in MFruit OS**: arrows move, Enter opens, Esc goes back.
  MFruit OS registers with `disable_esc_exit_key`, so Esc is its "back" rather
  than the daemon's close.
- `docs/APP_RULES.md`: the rules every MFruit OS app follows (controls,
  registration, screen layout, tests), also used as a Claude rule in each app.
- The app template is an MFruit app: SDK controls and look, Esc and four
  clicks as its own "back".
- `mfruit-run` exports `MFRUIT_HOME` and `MFRUIT_SESSION` to apps.
- Diagnostics lists the keyboards being read; `mfruitctl status` shows them
  too, and `mfruitctl key <name>` types a key through the keyboard path.

### Changed
- A keyboard plugged in or paired later is found at once (inotify); nothing
  polls while idle, in the keyboard reader or the button worker.

### Apps converted (their own repositories)
- Crypto dashboard, WalkieTalkie, Messenger: MFruit OS controls (menus and
  lists: tap next · 2× previous · hold open · 4× back; hold or Space talks on
  talk screens), keyboard support, MFruit OS status bar and footer.
- AI chatbot: typed questions from a keyboard (Enter asks, Space held talks,
  Esc clears or leaves), MFruit OS status bar and footer hints.

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
