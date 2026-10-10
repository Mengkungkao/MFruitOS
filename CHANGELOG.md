# Changelog

All notable changes to mFruit OS are documented here. Versions follow
[Semantic Versioning](https://semver.org/). App versions are independent of
the OS version.

## Unreleased

### Added (2026-10-10, SDK 1.5.0)
- **SDK 1.5.0:** a list row can show a small status light right after its
  name (`Row(mark=..., mark_hollow=...)`), such as RadioConnect's "this radio
  is in range". Rows without one draw as before.

### Fixed (2026-10-10, battery shown as charging)
- **A PiSugar 2 that cannot sense external power (four LEDs) no longer
  shows "charging" on battery.** Charging was guessed from one-second
  voltage samples, so noise and the voltage recovering after a load (a radio
  transmitting) looked like charging, in the status bar, Settings → Battery
  and every app that reads PiSugar's socket (RadioConnect). The same guess
  cancelled and restarted the low-battery countdown, so the safe shutdown
  could be put off until the battery died. It is now judged from a 0.1 V
  step (plugging in or out, seen within seconds) or three minutes of rising
  minute averages (starting on external power).

### Added (2026-10-10, power management)
- **mFruit OS has its own power management** for PiSugar battery boards
  (PiSugar 3, PiSugar 2 with 4 or 2 LEDs, PiSugar 2 Pro): a new
  `mfruit-power.service` that reads the battery, shuts the device down
  safely when the battery runs low (below 5 % for 30 s while unplugged, with
  an on-screen countdown; connecting power cancels it), lets the PiSugar 3
  power button shut down safely, and switches the battery board off at the
  end of a power-off. Before, the battery was shown only with PiSugar's own
  server installed, nothing protected the SD card at an empty battery, and
  after *Shut down* the board kept the halted Pi powered.
- **Settings → Battery**: level, charging, voltage, board and temperature;
  safe-shutdown level and countdown; double/long press actions (screen on/off,
  power menu, Home); hold to shut down safely; anti-mistouch; power on when
  plugged in; battery protection or charging range; a wake-up alarm and the
  board clock. **Settings → General → Power** opens mFruit OS's own power
  menu (lock, restart, shut down).
- `mfruitctl power` (status, `set KEY VALUE`, `shutdown`, `reboot`, `probe`,
  `clock save|load`); settings in `~/.whisplay-os/config/power.json`.
- The clock is moved forward from the battery board's clock at boot when it
  is not synchronised, and saved to the board once it is.
- whisplay-daemon, apps' status bars and scripts that read PiSugar's socket
  keep working: the power service answers PiSugar's protocol. `install.sh`
  stops PiSugar's own `pisugar-server`/`pisugar-poweroff` and imports their
  settings once; `uninstall.sh` enables them again; `--no-power` keeps them.
  Not verified on a device yet ([ADR 0012](docs/platform/ADR/0012-own-power-management.md)).

### Added (2026-10-10, Wi-Fi from a phone)
- **Settings → Wi-Fi → Phone Setup**: set the device's Wi-Fi from the PiSugar
  app (or pisugar.com/sugar-wifi-conf in Chrome) over Bluetooth. mFruit OS
  installs PiSugar's sugar-wifi-conf (2.3.0, or 2.2.3 on systems older than
  glibc 2.39 such as Ubuntu 22.04; checked by SHA-256, also from offline packs) and runs it only while wanted — on that screen, or also
  when there is no network, or always — with a key made for this device
  (shown on the screen) instead of "pisugar", its own information (version,
  battery, temperature, memory, up time) and commands (restart mFruit OS,
  reboot, shut down safely). Bluetooth is put back as it was, and pairing a
  keyboard in Settings → Bluetooth pauses it. `mfruitctl wifi-setup
  start|stop|status`; `install.sh --no-wifi-setup` skips it. Settings → Wi-Fi
  now opens the Wi-Fi page (network, address, Choose a network…, Phone
  Setup) instead of jumping straight into Connect WiFi
  ([ADR 0013](docs/platform/ADR/0013-phone-wifi-setup.md)).

### Changed (2026-10-10)
- The installer loads the `i2c-dev` kernel module for the power service, now
  and at every boot. On Raspberry Pi OS the I2C bus can be on without it, and
  then there is no `/dev/i2c-1` (seen on a Pi Zero 2 W). The power service's
  message now says the module is missing instead of "I2C bus 1 is not enabled".
- `scripts/deploy.sh` keeps one folder per device: the device's `~/MFruitOS`
  becomes an exact copy of the checkout (same commit when it is a git clone,
  removed files removed, its `.git` and offline packs kept); `--sync-only`
  syncs without installing.
- **The name is now "mFruit OS"** (small m) everywhere: screens, the boot
  logo letter, messages, documentation and the mFruit App SDK. Repository,
  folder, service and package names (`MFruitOS`, `mfruitos`, `mfruit-os`,
  `whisplay-os.service`) are unchanged so existing installations keep working.

### Fixed (2026-10-06, AI Chatbot 1.0.2)
- **AI Chatbot no longer loses the microphone after a quick press.** A
  recording stopped within about a second of starting kept running and held
  the microphone, so every later press failed (seen on the Orange Pi).
- **AI Chatbot shows configuration problems on its screen**: an unknown
  ASR/LLM/TTS server in `.env`, Piper selected but not installed, or OpenAI
  rejecting a setting such as the voice model or the key. Before, the
  chatbot silently did not listen or did not speak.

### Changed (2026-10-05, AI Chatbot 1.0.1)
- **AI Chatbot 1.0.1 in the Fruit Store.** Installing it downloads only its
  release archive from github.com/Mengkungkao/ai-chatbot: the font, the emoji
  set and Node.js 20 are inside the package (nothing from PiSugar or
  nodejs.org). A face emoji in a reply now shows the cat face. Devices with
  1.0.0 are offered the update; the `.env` and chat data are kept.

### Added (2026-10-05, AI Chatbot)
- **AI Chatbot is in the Fruit Store** (1.0.0, a release package built by the
  ai-chatbot repository). Fruit Store entries can list `system_packages`;
  `scripts/setup-app.sh <id>` (or `install.sh --app <id>`) installs them once
  with sudo and the device then installs the app by itself. The Store shows
  *Needs setup first* until then. Copy your `.env` to the app's data folder
  (`~/.whisplay-os/apps/whisplay-ai-chatbot/data/.env`).

### Changed (2026-10-05, Fruit Store versions)
- **RadioConnect 0.5.0 in the Fruit Store** (Listen in background); it was
  pinned at 0.4.0.
- **Installed Fruit Store apps get newer versions from the Store list.** When
  the list names a newer version of a native app than the installed one, the
  Store shows *Update* and the app's page *Update to <version>*. Apps without
  GitHub releases (RadioConnect) had no update path before.

### Added (2026-10-05, radio)
- **`install.sh --radio` now finishes the radio by itself.** When the UART
  needs a reboot, a one-time `mfruit-radio-setup.service` writes the module
  settings (e.g. 920 MHz) at the next boot, so `setup-radio.sh` no longer has
  to be run a second time. The Fruit Store apps that need the radio
  (RadioConnect) are queued and the device downloads and installs them once
  the radio is ready.

### Added (2026-10-05)
- **New apps appear in the Fruit Store without an OS update.** The Store
  downloads its list from mFruit OS's GitHub repository when it opens
  (setting `updater.online_catalog`, on by default) and falls back to the
  list shipped with the OS when offline. Entries this OS version cannot
  install are left out; entries can declare `min_os_version`.

### Fixed (2026-10-05)
- **RadioConnect failed to install from the Fruit Store on a freshly
  installed device** ("RadioConnect needs: serial") because the LoRa radio
  was never set up. `scripts/install.sh` now offers the radio setup
  (`--radio`, `--no-radio`), and `setup-radio.sh` has `--no-reboot` so the
  installer handles the reboot.

### Added (2026-10-04)
- **Apps can keep running in the background with the screen held bright.**
  New per-app *Keep screen bright* in Settings > Apps, and SDK 1.4.0
  `mfruit_sdk.background`, so an app can offer the switch itself (RadioConnect
  0.5.0: *Listen in background*). While such an app runs in the background,
  the backlight stays at 100%: on the LoRa HAT the backlight pin is the
  radio's mode pin, and dimming leaves the radio deaf.
- `scripts/radio-link-test.py`: over-the-air link test between two boards.

### Fixed (2026-10-04, found on the reinstalled boards)
- **Bluetooth "org.bluez.Error.Failure"** on a fresh Raspberry Pi OS: Bluetooth
  was soft-blocked (rfkill). Turning it on in Settings now lifts the block and
  waits for BlueZ instead of racing it (`org.bluez.Error.Busy`); a hard block or
  missing permission is explained. The first install also lifts the block.
- **Wi-Fi app not working** when its registration pointed to a removed
  checkout: provisioning now installs the bundled Wi-Fi app in that case, and
  the launcher re-registers a managed app whose registration points to another
  folder.

### Whisplay driver included
- **No separate Whisplay installation.** mFruit OS now carries the Whisplay
  HAT driver in `drivers/whisplay`: the display, button and LED driver, the
  `whisplay-daemon` hardware service and the sound card driver, copied
  unmodified from PiSugar/Whisplay `c73051e`. `scripts/install.sh` installs it
  on a supported board (packages, SPI/I2C/I2S, sound card, service) without
  questions and asks for a reboot when needed (`--no-driver` skips it).
  Existing devices switch `whisplay-daemon` to `/usr/local/share/whisplay` on
  the next install; `~/Whisplay`, the daemon's settings and app registrations
  are left as they are. New installs no longer get Whisplay's demo games.
  [Whisplay driver](docs/WHISPLAY_DRIVER.md).
- Tests and CI use the bundled daemon instead of cloning Whisplay.
- **Offline installation:** `scripts/make-offline-pack.sh` (run once on a board
  with internet) makes a pack of the packages and sound card build files for
  that OS image; with the pack in `MFruitOS/offline/`, `scripts/install.sh`
  needs no internet. A sound card that cannot be built no longer stops the
  installation: the display, button and LED are installed and the problem is
  reported.
- The installer asks to reboot when the driver needs it (`--reboot` without
  asking) and builds the sound card in a temporary copy, so no build files
  end up in the checkout.
- Fixed: on a fresh image without DejaVu fonts (Ubuntu 22.04, Pillow 9.0) the
  daemon's own screens crashed; the driver now installs `fonts-dejavu-core`,
  and Bluetooth support (`bluez`, `python3-dbus`, `python3-gi`) when
  available. Found by the new fresh-install rehearsal
  (`tests/fresh_install/rehearse.sh`).

### Fixed
- Keyboards work again in plain Whisplay apps such as Jump Game and Flappy
  Bird: mFruit OS holds the keyboards, so it now forwards **Esc** (leave the
  app, as the daemon does) and **Space** (the app's button) to foreground apps
  that do not use the key hub. Restart whisplay-daemon once after updating so
  its wrapper provides the new `mfruit.app.key` command.
- App installer: an app that is registered but whose files are missing shows
  **Repair** (reinstall from the catalogue) instead of a misleading *Installed*.
- `mfruitctl key space` for testing; `mfruitctl catalog [<id>]` lists the
  curated catalogue with each app's status and installs or repairs an entry.
- Removed the *Settings → Display → 24-hour clock* toggle, which had no
  visible effect since the status bar dropped the clock, together with the
  unused `display.clock_24h` and `system.home_title` settings and the
  per-minute clock wake-up. Existing settings files still load.
- Sideloaded package **folders** now get the same safety checks as archives
  before they are copied: symlinks must stay inside the package, special files
  are refused, file-count and size limits apply, and set-uid/set-gid and
  group/world-write bits are removed. Previously an escaping symlink or a
  set-uid file in a folder was installed as is.

### Fruit Store
- **RadioConnect is in the Fruit Store; Messenger and WalkieTalkie are not.**
  RadioConnect replaces both. Copies already installed stay on the device, and
  their pages in the Fruit Store still uninstall and delete them.
- **Native catalogue entries:** `"native": true` installs an mFruit OS package
  exactly as published (own manifest and hooks), pinned by commit and SHA-256.
- **The App installer is now the Fruit Store:** each app has a page to open,
  update, roll back, reset, uninstall and delete it.
- **Uninstall and delete are two steps, each confirmed:** Uninstall removes the
  app and keeps its data (installing it again brings it back); Delete data
  removes what mFruit OS still keeps. Reset app empties an installed app's data.
  Also `mfruitctl uninstall|delete|reset|rollback <app_id>`.
- **Daemon apps can be removed:** apps registered directly with whisplay-daemon
  (such as the leftover *WiFi Config*) can be uninstalled; their own files stay.
- **Leftover daemon apps are shown as broken:** an app whose script no longer
  exists (WiFi Config's `wifi_config_app.py`) says *App files missing*.
- A failed reinstall over kept data restores that data instead of deleting it.
- **No installing over an open app:** an install, sideload or update of an app
  that is open is refused ("close it, then install again"). Before, a sideload
  replaced its code under the running process.
- **No stale "running" after an app closes:** the app list is refreshed once
  the process has gone. Before, an app that exited on its own could stay
  "running" and roll back, update and reset were refused.
- `mfruitctl rollback` reports a roll back that could not start, instead of
  "started".

### Radio
- **Radio no longer deaf behind the Whisplay LCD:** the daemon wrapper parks the
  LCD's DC line low after each frame. With the LoRa HAT's stock jumpers that line
  is the radio's M1, and upstream Whisplay left it high, so Messenger and
  WalkieTalkie showed "Radio deaf: check M0/M1" and nothing was sent or heard.
- **LoRa radio setup for radio apps:** `scripts/setup-radio.sh` sets up the
  SX126X HAT once (packages including Codec2, UART, serial console, `dialout`,
  reboot handling) and provisions the module, by default for AU915 (920 MHz,
  2400 bps). The App installer and `mfruitctl catalog` show **Needs radio setup
  first** for WalkieTalkie and Messenger until it has run.
- **Shared radio identity:** SDK 1.3.0 adds `mfruit_sdk.radio`, one store for the
  radio settings, Device ID, pairing keys and contact names that every radio
  app uses, so pairing once works in every radio app.

### Tests
- The launch-window daemon-page test no longer fails intermittently (5 of 20
  runs before). Root cause: whisplay-daemon sometimes treats a hold as a tap
  while a launch is pending, so no page opened; mFruit OS was correct. The
  test now waits on the observed daemon state and retries across daemon
  pages, and a new deterministic test opens the page through the daemon API.
- Regression tests for sideloaded folders (escaping symlinks, special files,
  limits, permissions, ignored payload).
- Test runtimes no longer open or grab the machine's real keyboards
  (`Runtime(input_dir=…)` points them at an empty directory).

### Documentation and tooling
- The project constitution is now the canonical rule set
  (`docs/platform/DEVELOPMENT_RULES.md`); documentation is reorganized into
  `docs/platform/`, `docs/apps/` and `docs/quality/` with one canonical
  document per topic, new architecture/host API/configuration/security/
  directory-structure docs, ADRs, and dated records under
  `docs/quality/records/`. Old paths cited by app repositories keep pointer
  files.
- The app rules are now the **app contract** (`docs/apps/APP_CONTRACT.md`);
  `scripts/check-app.py` compares app copies with it. Apps must refresh
  `.claude/rules/mfruit-os-app.md` (the template copy is updated).
- `scripts/check.sh` runs the CI checks locally; `scripts/check-docs.py`
  checks Markdown links and anchors; GitHub Actions CI runs them, the full
  suite with real-daemon tests against a pinned Whisplay revision, and a
  Python 3.9 job.
- `CLAUDE.md` and `AGENTS.md` point coding agents at the rules.

### Earlier unreleased work
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

- mFruit OS branding in app labels, diagnostics, CLI help and package errors.
  Messenger's app description is Radio Message. Existing hardware identifiers,
  service names, paths and launch behavior stay compatible.
- Grouped Settings with coloured icon tiles, Wi-Fi and Bluetooth first, and
  About, Software Update, diagnostics and power under General.
- Settings → Wi-Fi now opens Connect WiFi directly as one mFruit-styled
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
- SDK 1.2.0: mFruit OS exclusively grabs keyboards and routes each key to
  the foreground owner through its key hub. This prevents keys reaching tty1's
  autologin shell and accidentally executing a launcher restart.
- Deploy the matching SDK to keyboard apps with this release. Daemon desktop
  mode releases the keyboard grab; returning to mFruit OS takes it again.

## [1.3.0] - 2026-09-30

### Added
- **The mFruit App SDK 1.1.0** (`mfruitos/sdk/`, copied into apps as `mfruit_sdk`
  with `scripts/sdk-sync.sh`): one input controller for the button and USB or
  Bluetooth keyboards, and mFruit OS's look — status bar (page name, WiFi,
  battery), footer hints, lists, toast, text field, theme, fonts, RGB565.
  Keys count only while the app has the screen, and only keys pressed while
  it did. Talk screens talk on a hold or Space.
- **Keyboard control in mFruit OS**: arrows move, Enter opens, Esc goes back.
  mFruit OS registers with `disable_esc_exit_key`, so Esc is its "back" rather
  than the daemon's close.
- `docs/APP_RULES.md`: the rules every mFruit OS app follows (controls,
  registration, screen layout, tests), also used as a Claude rule in each app.
- The app template is an mFruit app: SDK controls and look, Esc and four
  clicks as its own "back".
- `mfruit-run` exports `MFRUIT_HOME` and `MFRUIT_SESSION` to apps.
- Diagnostics lists the keyboards being read; `mfruitctl status` shows them
  too, and `mfruitctl key <name>` types a key through the keyboard path.

### Changed
- A keyboard plugged in or paired later is found at once (inotify); nothing
  polls while idle, in the keyboard reader or the button worker.

### Apps converted (their own repositories)
- Crypto dashboard, WalkieTalkie, Messenger: mFruit OS controls (menus and
  lists: tap next · 2× previous · hold open · 4× back; hold or Space talks on
  talk screens), keyboard support, mFruit OS status bar and footer.
- AI chatbot: typed questions from a keyboard (Enter asks, Space held talks,
  Esc clears or leaves), mFruit OS status bar and footer hints.

## [1.2.0] - 2026-09-29

### Added
- **Whisplay's own user interface runs in the background.** `install.sh`
  starts whisplay-daemon through `whisplay-daemon-mfruit.py` (systemd
  drop-in): while mFruit OS runs, the daemon no longer draws its desktop or
  its "Opening app…" modal and ignores the button when no app owns the
  screen. It behaves normally when mFruit OS is not running or in
  Developer → Daemon desktop. Opt out with `install.sh --no-background-daemon`.
- "Opening <App>" loading screen, shown until the app draws its first frame.
- Leaving an app closes it completely (exit request, then its process group
  is stopped after 3 s). Per-app **Keep running** setting for apps that must
  stay on; manifests can default it with `"background": true`.
- Diagnostics shows whether the Whisplay UI is in the background.

### Changed
- Status bar: page name on the left, WiFi strength and battery on the right;
  the "mFruit OS" title row and the clock are gone, every list shows one more
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
  ticket from mFruit OS (`mfruit-run` launch gate); daemon pages opened in
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
  and restored by `uninstall.sh`. With mFruit OS stopped they launch exactly
  as before.
- mFruit OS refuses to start a second instance (`state/launcher.lock`).
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
