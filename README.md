# mFruit OS

**A compact application platform for small Linux devices.**

mFruit OS turns a Raspberry Pi Zero 2 W, Orange Pi Zero 2W or similar Linux
board with a display HAT into a small device: it boots into a launcher,
installs and updates apps from GitHub with automatic rollback, and is used
entirely with the HAT's single button.

<p>
<img src="docs/screenshots/boot.png" width="160" alt="Boot screen">
<img src="docs/screenshots/home.png" width="160" alt="Home launcher">
<img src="docs/screenshots/settings.png" width="160" alt="Settings">
<img src="docs/screenshots/updater.png" width="160" alt="Updater">
<img src="docs/screenshots/progress.png" width="160" alt="Update in progress">
</p>

It runs **on top of `whisplay-daemon`**, not instead of it. The daemon keeps
owning the LCD, backlight, RGB LED, button and the foreground-app lifecycle;
mFruit OS is a daemon foreground app that draws into the daemon's shared
framebuffer. The daemon, the display driver and the sound card driver ship
with mFruit OS as its [Whisplay driver](docs/WHISPLAY_DRIVER.md), so no
separate Whisplay installation is needed. Keyboard-using apps need mFruit SDK 1.2.0 so they can receive
input through the launcher's key hub; button-only apps retain their integration.

The interface uses mFruit OS names and app descriptions, such as **Radio
Message** beneath Messenger. Hardware integration identifiers, service names
and storage paths remain stable for compatibility with existing installations.

```
┌─────────────────────────────┐
│ mFruit OS                   │  launcher · settings · app manager
│                             │  updater · diagnostics
└──────────────┬──────────────┘
               │ daemon API (/tmp/whisplay-daemon.sock)
┌──────────────▼──────────────┐
│ whisplay-daemon             │  LCD · button · LED · backlight · app lifecycle
│ + sound card (drivers/)     │  mFruit OS Whisplay driver
└──────────────┬──────────────┘
┌──────────────▼──────────────┐
│ Display HAT                 │
└─────────────────────────────┘
```

## Features

- **Launcher** — apps discovered automatically from mFruit OS packages and the
  daemon registry (nothing hard-coded); status badges for running, update
  available and broken apps.
- **One-button navigation** — tap = next, double-click = previous,
  hold and release = open/select, four clicks = back. Configurable; the OS refuses
  mappings that would lock you out.
- **App management** — enable, disable, hide, reorder, default app,
  autostart, stop, force stop, logs, uninstall. Leaving an app closes it
  completely unless it is set to *Keep running*.
- **Updater** — GitHub Releases as the app store: update, downgrade,
  reinstall, rollback, install new apps, discover apps by GitHub topic.
  Installs go through *check → download → verify → backup → install → test →
  activate*; a failure restores the previous version automatically.
- **Existing apps too** — apps installed as `git clone`s get commit-tracking
  updates (fast-forward only, rollback to the previous commit).
- **System** — system info, diagnostics with hardware tests (display, button,
  LED, speaker), display/LED/button/audio settings, daemon WiFi / Bluetooth /
  Volume / Power pages.
- **Power management** — mFruit OS's own service for PiSugar battery boards:
  battery level, safe shutdown before the battery runs empty, the power
  button's safe shutdown, power on when plugged in, wake-up alarm, and the
  board switched off after *Shut down* (Settings → Battery, `mfruitctl power`;
  [ADR 0012](docs/platform/ADR/0012-own-power-management.md)).
- **Wi-Fi from a phone** — Settings → Wi-Fi → Phone Setup runs PiSugar's
  sugar-wifi-conf so the PiSugar app can set the Wi-Fi over Bluetooth, with
  a key made for this device ([ADR 0013](docs/platform/ADR/0013-phone-wifi-setup.md)).
- **Keyboard** — plug in a USB keyboard or pair a Bluetooth one: arrows move,
  Enter opens, Esc goes back, in mFruit OS and in its apps.
- **One user interface** — whisplay-daemon keeps running the hardware in the
  background; mFruit OS is all you see, including its own "Opening <App>"
  screen while an app starts.
- **Deterministic launches** — exactly the selected app opens, once: one
  launch session at a time, and a launch gate stops whisplay-daemon's own
  desktop from starting other apps while one is starting up
  ([lifecycle](docs/platform/LIFECYCLE.md)).
- **Robust** — a crashing app never takes the launcher down; the launcher
  re-takes the screen after apps exit, survives daemon restarts, has a
  systemd watchdog, and a failed OS update is rolled back at the next boot.
- **Offline first** — only the Updater needs the internet.
- **Light** — Python standard library + Pillow (already required by the
  daemon), no web server, no numpy. Measured on an Orange Pi Zero 2W: 35 MB RSS,
  0.01 % CPU while an app is in front; at Home it only redraws when something
  changes (status refreshes are checked every 30 s).

## Quick start

On a Raspberry Pi or Orange Pi Zero 2W with the Whisplay HAT fitted:

```bash
git clone https://github.com/Mengkungkao/MFruitOS.git
cd MFruitOS
bash scripts/install.sh        # also installs the Whisplay driver; reboot if it asks
systemctl status whisplay-os
```

No internet on the board? Copy the code and an offline pack onto the SD card:
[offline installation](docs/WHISPLAY_DRIVER.md#offline-installation).

See [the installation guide](docs/platform/INSTALLATION.md) for board
preparation, the read-only `bash scripts/setup-device.sh --check`, the system
changes the installer makes, updating, rollback and uninstalling.

## Using it

| Gesture (default) | Keyboard | Action |
|---|---|---|
| tap | Down, Right, Tab | next item |
| double-click | Up, Left | previous item |
| hold 0.7 s, then release | Enter | open / select (the screen shows "Release to open" once armed) |
| four quick clicks | Esc | back |

Every screen shows its gestures in the footer and ends with a **Back** row.
Apps built with the mFruit App SDK use the same controls, button and
keyboard: four quick clicks (or Esc) go back a screen, and from an app's
first screen they leave it; mFruit OS then takes the screen back. A
keyboard, USB or Bluetooth, is picked up as soon as it is plugged in or
paired, and only the app on screen reads it.

From a shell (`ssh` to the device):

```bash
mfruitctl status                              # launcher state
mfruitctl apps                                # installed apps
mfruitctl install github.com/user/whisplay-weather
mfruitctl sideload ~/my-app                   # local package or folder
mfruitctl screenshot /tmp/screen.png          # what the LCD shows
mfruitctl help
```

## Building apps

Any compatible daemon app works. To make it installable and updatable through
mFruit OS, add a `manifest.json` and publish GitHub releases. Start from
[`templates/whisplay-app-template`](templates/whisplay-app-template) and read
[Getting started](docs/apps/GETTING_STARTED.md): the [mFruit App SDK](docs/apps/SDK.md)
gives your app mFruit OS's controls (button and keyboard) and look, and the
[app contract](docs/apps/APP_CONTRACT.md) lists the rules mFruit apps follow.

```json
{
  "id": "weather",
  "name": "Weather",
  "version": "1.0.0",
  "description": "Weather information",
  "entrypoint": "run.sh",
  "icon": "assets/icon.png",
  "min_os_version": "1.4.0",
  "repository": "https://github.com/example/whisplay-weather",
  "exit_gesture": "none",
  "disable_esc_exit_key": true
}
```

## Files on the device

```
~/.whisplay-os/
├── apps/<id>/      installed packages (versions/, current -> active version, data/)
├── bin/            mfruit-run, mfruitctl, boot-guard.sh
├── cache/          GitHub metadata, downloads
├── config/         settings.json, power.json
├── logs/           launcher.log, updater.log, power.log, <app>.log
├── state/          run state, control socket
└── system/         mFruit OS itself (versions/, current)
```

mFruit OS reads `~/.whisplay-daemon/app/` to discover daemon apps and only
changes daemon registrations through the daemon's own `app.register` API.

## Project layout

```
mfruitos/
├── core/         ApplicationManager: the single launch authority
├── apps/         manifest validation, registry
├── updater/      installer, verifier, rollback, GitHub, commit tracking, catalogue
├── system/       settings, diagnostics, Bluetooth, hardware policy
├── power/        power service (mfruit-power.service): battery, safe shutdown, PiSugar protocol
├── daemon/       whisplay-daemon client, event stream, framebuffer (the only socket code)
├── launcher/     runtime, focus/host, event loop, gestures, UI and screens
├── hosts/        hardware drivers: pisugar/ (battery boards), lora/ (radio)
└── sdk/          the mFruit App SDK (vendored into apps as mfruit_sdk)
scripts/          install.sh, uninstall.sh, mfruit-run, mfruitctl, check.sh, check-app.py, sdk-sync.sh …
templates/        whisplay-app-template (an mFruit app built on the SDK)
tests/            unit, integration, real-daemon and package-lifecycle tests
docs/             platform/, apps/, quality/
```

Details: [directory structure](docs/platform/DIRECTORY_STRUCTURE.md). Run all
checks with `bash scripts/check.sh` and preview every screen without hardware
with `python3 -m mfruitos --preview /tmp/screens`.

## Documentation

- [Documentation home](docs/README.md) — three domains, one canonical document per topic
- [Platform / OS development](docs/platform/README.md) — [development rules](docs/platform/DEVELOPMENT_RULES.md) (the project constitution), architecture, lifecycle, host API, installation, configuration, security, roadmap, ADRs
- [App development](docs/apps/README.md) — getting started, app contract, manifest, SDK, UI, packaging, install/update/rollback, testing, publishing, migration
- [Quality](docs/quality/README.md) — testing, validation, known issues, troubleshooting, records
- [CONTRIBUTING.md](CONTRIBUTING.md) — from clone to submitted change
- [CHANGELOG.md](CHANGELOG.md)

## License

MIT — see [LICENSE](LICENSE). The bundled Inter font is under the SIL Open Font License.
# mFruit OS

## Settings and keyboard input (1.4.0)

Settings groups Wi-Fi and Bluetooth first, then display, sound, button and light.
General contains About, Software Update, diagnostics and power. Connect WiFi
opens from Settings > Wi-Fi > Choose a network and returns there when closed.
Bluetooth shows saved and nearby devices with pairing codes and confirmation.
Boot displays only the logo on a dark background.

Deploy SDK 1.2.0 to all keyboard apps together with mFruit OS 1.4.0. mFruit OS
holds keyboards exclusively, preventing typed keys from reaching the console
shell, and forwards keys to the foreground app. Daemon pages receive forwarded
keys through the mFruit wrapper; Developer > Daemon desktop releases the grab.
