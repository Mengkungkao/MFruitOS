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
├── templates/             whisplay-app-template: a complete MFruit app to start from
├── bundled/connectwifi/   Wi-Fi app shipped with the OS and provisioned on install
├── config/                default.json (generated defaults), catalog.json (curated apps)
├── contrib/manifests/     draft manifests for companion apps (not release packages)
├── assets/fonts/          Inter (SIL OFL) used by the launcher and the SDK
├── tests/                 unit, integration and real-daemon tests
├── docs/                  platform/, apps/, quality/ (see docs/README.md)
├── manifest.json          MFruit OS's own system package manifest
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
| `system/hardware.py` | backlight and LED policy, battery read | E (daemon + PiSugar) |
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
| `launcher/preview.py`, `launcher/sdnotify.py` | offscreen self-test/preview; systemd notify | UI |
| `sdk/` | MFruit App SDK, vendored into apps as `mfruit_sdk` ([SDK](../apps/SDK.md)); `sdk/radio/` owns the shared radio store | B |
| `hosts/lora/` | LoRa radio capability: SX126X provisioning, mode pins, readiness, setup CLI | E |

## Scripts

| Script | Runs on | Purpose |
|---|---|---|
| `setup-radio.sh` | device | one-time LoRa radio setup ([Installation](INSTALLATION.md#radio-setup-lora-apps)) |
| `install.sh`, `uninstall.sh`, `update.sh`, `setup-device.sh` | device | install, remove, update from a checkout, read-only prerequisite check ([Installation](INSTALLATION.md)) |
| `mfruit-run` | device (installed to `~/.whisplay-os/bin`) | launch gate and runner for every managed app |
| `mfruitctl` | device | control CLI (`mfruitctl help`) |
| `boot-guard.sh` | device | rolls back a system update that fails to start three times |
| `whisplay-daemon-mfruit.py` | device | starts whisplay-daemon with its UI in the background |
| `deploy.sh` | developer machine | copy a checkout to a device, install, restart |
| `sdk-sync.sh` | developer machine | vendor the SDK into an app; `--check` detects drift |
| `check-app.py` | developer machine | read-only package preflight |
| `check.sh`, `check-docs.py` | developer machine and CI | the CI checks, runnable locally; Markdown link check |

## Tests

| Path | Level ([Part I §19](DEVELOPMENT_RULES.md#19-test-pyramid)) |
|---|---|
| `tests/test_*.py` without a daemon | 1–2: units and services with fakes (`fake_daemon.py`, `helpers.py`) |
| `tests/test_launch_lifecycle.py`, `tests/test_background_ui.py` | 3: real whisplay-daemon code with a simulated board (`tests/real_daemon/`, needs `WHISPLAY_SRC`) |
| `tests/test_installer.py`, `test_update_flows.py`, `test_catalog.py`, `test_install_setup.py`, `test_device_setup.py` | 4: package and installer lifecycles with disposable data |

Physical device validation (level 5) is a recorded procedure, not a test file
([Validation](../quality/VALIDATION.md)).

## Data on a device

```text
~/.whisplay-os/                 (WHISPLAY_OS_HOME)
├── apps/<id>/
│   ├── current -> versions/<version>-<random>   active version (atomic swap)
│   ├── versions/               installed versions; the previous one is the code backup
│   ├── data/                   app data, kept across updates
│   ├── backups/data-<version>/ data snapshot taken before hooks ran
│   └── app.json                install record (versions, source, verified)
├── adopted/<id>/               original registrations of adopted daemon apps
├── shared/radio/  (0700)       radio.json, device.json, keys.json, contacts.json (radio apps)
├── bin/                        mfruit-run, mfruitctl, boot-guard.sh, whisplay-daemon-mfruit.py
├── cache/                      GitHub metadata, downloads/
├── config/settings.json        settings ([Configuration](CONFIGURATION.md))
├── inbox/                      local packages offered by App installer → Local packages
├── logs/                       launcher.log, updater.log, launch-gate.log, <app>.log
├── state/  (0700)              launcher.lock, tickets/, runs/, launch-policy, control.sock,
│                               keys.sock, boot and update markers
└── system/
    ├── current -> versions/…   active MFruit OS version
    ├── versions/               installed MFruit OS versions
    └── app.json                system install record
~/.whisplay-daemon/app/*.json   daemon registrations (changed only through app.register)
```

Code, data, configuration, cache, logs and state stay separate so that an
update can replace code without touching data, and a rollback can restore
code and the data snapshot together.
