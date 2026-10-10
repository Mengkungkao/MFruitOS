# Directory structure

Where each responsibility lives today, which target layer it belongs to
([Architecture](ARCHITECTURE.md#layer-map-current-modules-and-target-layers)),
and where data lives on a device. Files are moved only when a concrete change
justifies it ([Part I §24](DEVELOPMENT_RULES.md#24-source-tree-shaping)).

## Repository

```text
MFruitOS/
├── mfruitos/              the platform (Python package)
├── scripts/               installer, helpers installed on devices, developer tools
├── templates/             whisplay-app-template: a complete mFruit app to start from
├── bundled/connectwifi/   Wi-Fi app shipped with the OS and provisioned on install
├── drivers/whisplay/      Whisplay driver: upstream runtime, daemon, sound card (unmodified)
│                          + mFruit OS install.sh/uninstall.sh (docs/WHISPLAY_DRIVER.md)
├── offline/               (not committed) offline packs from scripts/make-offline-pack.sh
├── config/                default.json (generated defaults), catalog.json (curated apps)
├── contrib/manifests/     draft manifests for companion apps (not release packages)
├── assets/fonts/          Inter (SIL OFL) used by the launcher and the SDK
├── tests/                 unit, integration and real-daemon tests
├── docs/                  platform/, apps/, quality/ (see docs/README.md)
├── manifest.json          mFruit OS's own system package manifest
├── CHANGELOG.md, CONTRIBUTING.md, CONTINUE.md, README.md, LICENSE
└── .github/workflows/     CI (no hardware)
```

## The `mfruitos` package

| Path | Responsibility | Layer |
|---|---|---|
| `__init__.py` | version, OS name, `OS_APP_ID` | core |
| `__main__.py`, `launcher/main.py` | command line entry point | UI |
| `core/application_manager.py` | single launch authority, sessions, `Host` protocol | C |
| `apps/manifest.py` | manifest validation | C |
| `apps/registry.py` | merged app list (packages, daemon apps, daemon pages) | C |
| `updater/installer.py` | install pipeline, rollback, uninstall | C |
| `updater/verifier.py` | checksums and safe archive extraction | C |
| `updater/rollback.py` | version switching, data snapshots, `safe_rmtree`, pruning | C |
| `updater/service.py` | update checks and channels (release, git, catalogue, system) | C |
| `updater/github.py`, `updater/gittrack.py`, `updater/version.py`, `updater/catalog.py` | GitHub API, commit tracking, semver, curated catalogue | C |
| `system/settings.py` | settings schema, validation, atomic persistence | C |
| `system/diagnostics.py`, `system/system_info.py` | checks and system information | C |
| `system/bluetooth.py` | BlueZ discovery, pairing agent, device actions | C (Linux/BlueZ-specific) |
| `system/hardware.py` | backlight and LED policy; battery read from PiSugar's own server (fallback when the power service is not installed) | E (daemon + PiSugar) |
| `system/sdnotify.py` | systemd notify protocol (launcher and power service) | C |
| `system/wifi_setup.py` | Wi-Fi from a phone: installs PiSugar's sugar-wifi-conf (pinned, SHA-256), writes its config, runs and stops it, parses its log ([ADR 0013](ADR/0013-phone-wifi-setup.md)) | C (Linux/BlueZ/NetworkManager-specific) |
| `power/` | power service (own process, `mfruit-power.service`): `service.py` policies, `config.py` (`power.json`, PiSugar import), `server.py` sockets, `compat.py` PiSugar protocol, `client.py`, `__main__.py` CLI ([ADR 0012](ADR/0012-own-power-management.md)) | C |
| `paths.py`, `logs.py`, `provision.py`, `ctl.py` | data layout and path safety, logging, first-install provisioning, `mfruitctl` client | C |
| `daemon/client.py`, `daemon/events.py`, `daemon/framebuffer.py` | whisplay-daemon requests, event stream, shared framebuffer | E |
| `launcher/focus.py` | `ForegroundManager`: Whisplay implementation of `Host`, screen ownership | E |
| `launcher/app_manager/lifecycle.py` | registration, adoption, tickets, run records, process stop | E |
| `launcher/keyhub.py` | key hub socket for apps | E |
| `launcher/direct.py` | recovery display when the daemon unit is down | E |
| `launcher/runtime.py` | composition root: event loop wiring, key routing, rendering, timers | UI |
| `launcher/services.py` | operations screens call (launch, install, update, tests) | UI → C |
| `launcher/loop.py`, `launcher/tasks.py` | event loop with timers; worker lanes | UI |
| `launcher/navigation/` | gesture recognizer, screen router | UI |
| `launcher/control.py`, `launcher/ctl_handlers.py` | `mfruitctl` control socket and commands | UI |
| `launcher/ui/` | painter, components, theme, fonts, icons, RGB565, screens | UI |
| `launcher/preview.py` | offscreen self-test/preview (`launcher/sdnotify.py` re-exports `system/sdnotify.py`) | UI |
| `launcher/power_link.py` | the launcher's link to the power service (event stream, requests) | UI → C |
| `sdk/` | mFruit App SDK, vendored into apps as `mfruit_sdk` ([SDK](../apps/SDK.md)); `sdk/radio/` owns the shared radio store | B |
| `hosts/lora/` | LoRa radio capability: SX126X provisioning, mode pins, readiness, setup CLI | E |
| `hosts/pisugar/` | PiSugar battery boards: `base.Chip` interface, PiSugar 3 / 2 / 2 Pro and SD3078 drivers, detection, stdlib I2C, register-level fakes | E (formal boundary) |

## Scripts

| Script | Runs on | Purpose |
|---|---|---|
| `setup-radio.sh` | device | one-time LoRa radio setup ([Installation](INSTALLATION.md#radio-setup-lora-apps)) |
| `install.sh`, `uninstall.sh`, `update.sh`, `setup-device.sh` | device | install, remove, update from a checkout, read-only prerequisite check ([Installation](INSTALLATION.md)) |
| `mfruit-run` | device (installed to `~/.whisplay-os/bin`) | launch gate and runner for every managed app |
| `mfruitctl` | device | control CLI (`mfruitctl help`) |
| `boot-guard.sh` | device | rolls back a system update that fails to start three times |
| `whisplay-daemon-mfruit.py` | device | starts whisplay-daemon with its UI in the background |
| `mfruit-power-off` | device (root-owned copy in `/usr/lib/systemd/system-shutdown/`) | switches a PiSugar off at the end of a power-off |
| `deploy.sh` | developer machine | make a device's `~/MFruitOS` an exact copy of this checkout (same commit when it is a clone, files mirrored, its `.git` and `offline/` kept), then install (`--sync-only` skips that) |
| `sdk-sync.sh` | developer machine | vendor the SDK into an app; `--check` detects drift |
| `check-app.py` | developer machine | read-only package preflight |
| `check.sh`, `check-docs.py` | developer machine and CI | the CI checks, runnable locally; Markdown link check |

## Tests

| Path | Level ([Part I §19](DEVELOPMENT_RULES.md#19-test-pyramid)) |
|---|---|
| `tests/test_*.py` without a daemon | 1–2: units and services with fakes (`fake_daemon.py`, `helpers.py`) |
| `tests/test_launch_lifecycle.py`, `tests/test_background_ui.py` | 3: real whisplay-daemon code with a simulated board (`tests/real_daemon/`; the bundled `drivers/whisplay`, or `WHISPLAY_SRC`) |
| `tests/fresh_install/` | 4: fresh offline installation in a disposable container (`rehearse.sh`, `verify.sh`, `fakes/`) |
| `tests/test_whisplay_driver.py`, `tests/test_whisplay_driver_install.py` | 1–2: the bundled Whisplay driver on recorded SPI/GPIO; its installer's detection, boot configuration and staged copy |
| `tests/test_installer.py`, `test_update_flows.py`, `test_catalog.py`, `test_install_setup.py`, `test_device_setup.py` | 4: package and installer lifecycles with disposable data |
| `tests/test_pisugar_drivers.py`, `test_power.py`, `test_power_off_hook.py`, `test_battery_ui.py` | 1–2: PiSugar drivers, power service, shutdown hook and launcher power UI against register-level fakes |
| `tests/test_wifi_setup.py` | 1–2: phone Wi-Fi setup with a fake tool process and Bluetooth |

Physical device validation (level 5) is a recorded procedure, not a test file
([Validation](../quality/VALIDATION.md)).

## Data on a device

```text
~/.whisplay-os/                 (WHISPLAY_OS_HOME)
├── apps/<id>/
│   ├── current -> versions/<version>-<random>   active version (atomic swap)
│   ├── versions/               installed versions; the previous one is the code backup
│   ├── data/                   app data, kept across updates and Uninstall
│   ├── backups/data-<version>/ data snapshot taken before hooks ran
│   ├── app.json                install record (versions, source, verified)
│   └── uninstalled.json        only after Uninstall kept the data (then no current/versions)
├── adopted/<id>/               original registrations of adopted daemon apps
├── shared/radio/  (0700)       radio.json, device.json, keys.json, contacts.json (radio apps)
├── bin/                        mfruit-run, mfruitctl, boot-guard.sh, whisplay-daemon-mfruit.py
├── cache/                      GitHub metadata, catalog.json (downloaded Fruit Store list), downloads/
├── config/settings.json        settings ([Configuration](CONFIGURATION.md))
├── config/power.json           power settings, written by the power service only
├── config/sugar-wifi-conf.json optional: your own phone-setup info/commands
├── inbox/                      local packages offered by Fruit Store → Local packages
├── logs/                       launcher.log, updater.log, launch-gate.log, power.log,
│                               wifi-setup.log, <app>.log
├── state/  (0700)              launcher.lock, tickets/, runs/, launch-policy, control.sock,
│                               pending-installs.json (apps queued by install.sh --radio),
│                               keys.sock, power.sock, sugar-wifi-conf.json (generated),
│                               pisugar-services-disabled (PiSugar
│                               services the installer stopped), boot and update markers
└── system/
    ├── current -> versions/…   active mFruit OS version
    ├── versions/               installed mFruit OS versions
    ├── tools/sugar-wifi-conf/<version>/   PiSugar's binary and NOTICE (Wi-Fi from a phone)
    └── app.json                system install record
~/.whisplay-daemon/app/*.json   daemon registrations (changed only through app.register)
```

Code, data, configuration, cache, logs and state stay separate so that an
update can replace code without touching data, and a rollback can restore
code and the data snapshot together.
