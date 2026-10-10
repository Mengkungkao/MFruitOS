# Testing mFruit OS

How to test the platform. Testing an app is in [apps/TESTING.md](../apps/TESTING.md);
physical validation and records are in [Validation](VALIDATION.md).

Run commands from the repository root on Linux. Linux is required for the
process, socket, shell and real-daemon paths; a Windows-only run is not Linux
or device evidence.

## One command

```bash
bash scripts/check.sh            # what CI runs
bash scripts/check.sh --quick    # skip the full unit suite
```

It runs: Python syntax for 3.9 (and no `X | Y` type unions evaluated at run
time, which need 3.10), the unit and integration suite (including the
real-daemon tests against the bundled daemon), the offscreen self-test, shell
syntax, the Whisplay driver checksums and Whisplay's own daemon unit tests,
the template package preflight, the SDK copy check, the Markdown link check
and whitespace checks.

## The levels ([Part I §19](../platform/DEVELOPMENT_RULES.md#19-test-pyramid))

| Level | What | Where | Hardware |
|---|---|---|---|
| 1 Unit | manifest, settings, versions, verifier, gestures, application manager, SDK, the Whisplay driver on recorded SPI/GPIO | most `tests/test_*.py`, `test_whisplay_driver.py`, `test_whisplay_driver_install.py` | none |
| 2 Integration | runtime with fakes: focus, screens, registry, provisioning, installer flows | `test_runtime.py`, `test_focus.py`, `test_screen_services.py`, … with `fake_daemon.py` | none |
| 3 Real host contract | the real whisplay-daemon code with a simulated board and fake apps | `test_launch_lifecycle.py`, `test_background_ui.py` (`tests/real_daemon/`) | none; uses the bundled daemon |
| 4 Package lifecycle | install, update, failed update, rollback, uninstall, installer reruns with disposable homes | `test_installer.py`, `test_update_flows.py`, `test_catalog.py`, `test_install_setup.py`, `test_device_setup.py` | none |
| 5 Device | display, button, keyboard, Bluetooth, audio, radio, LED, reboot | [Validation](VALIDATION.md) | the board |

## Commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests            # full suite
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_manifest.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_launch_lifecycle.py -k launch_window
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --self-test                   # import + render every screen
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --preview /tmp/mfruit-preview # write screen PNGs
```

`--self-test` and `--preview` render offline; they are not an interactive
headless launcher and not a physical test.

### Power management without hardware

The PiSugar drivers and the power service are tested against register-level
fakes (`mfruitos/hosts/pisugar/fake.py`); nothing touches a real I2C bus. To
try the service by hand on any Linux machine, run it against a simulated
board in a scratch home (short path: Unix socket paths are limited to about
107 bytes):

```bash
H=$(mktemp -d /tmp/mfp-XXXX)
python3 -m mfruitos.power --home "$H" serve --fake pisugar3 &   # or pisugar2-2led, pisugar2-pro
python3 -m mfruitos.power --home "$H" status --details
printf 'get battery\n' | nc -U -q1 "$H/state/pisugar-server.sock"
```

With `--fake` nothing is powered off and the clock is not changed: commands
are logged as "dry run". Physical checks are the
[power checklist](VALIDATION.md#hardware-checklist--power-management).

### Real-daemon tests

They run the daemon bundled in `drivers/whisplay`
([Whisplay driver](../WHISPLAY_DRIVER.md)). `WHISPLAY_SRC` substitutes another
Whisplay checkout (for example a newer upstream before syncing); a
`WHISPLAY_SRC` without a daemon skips them (the Python 3.9 CI job does this). **Never run two
real-daemon suites at once** on one machine: they share fake-app clean-up.
These tests start the launcher in-process with an empty input-device
directory (`helpers.NO_INPUT_DEVICES`), so they never touch the machine's
keyboards.

Record the Whisplay revision with results (`drivers/whisplay/UPSTREAM.md`); daemon semantics differ between
builds ([Host API](../platform/HOST_API.md#whisplay-daemon-facts-the-design-depends-on)).

### Fresh-install rehearsal

`bash tests/fresh_install/rehearse.sh <offline pack> [--suite]` installs mFruit
OS from scratch, offline, in a disposable container of the pack's OS image
(run it on a Docker host of the pack's architecture, for example the board):
stock image plus what the board image has (python3, sudo, kmod, systemd,
udev), then `bash scripts/install.sh --yes` with **no network**, then
`tests/fresh_install/verify.sh` (packages, sound card modules built for the
board's kernel, overlays, boot configuration, units, sudoers, provisioning,
self-test) and, with `--suite`, the real-daemon tests against the installed
driver. Faked are only the device tree, systemd and the reported kernel
release (`tests/fresh_install/fakes/`). It needs an offline pack and Docker,
so CI does not run it; record its results. It does not replace a boot on
real hardware.

### Other distributions

`bash tests/distro/run.sh` runs the suite on Ubuntu 22.04 and 24.04 and Debian
12 and 13 with each distribution's own Python, Pillow, gpiod and codec
packages, without root or Docker (user namespaces; the host is not changed):

```bash
bash tests/distro/run.sh prepare ubuntu-24.04   # download, verify, unpack, packages (once)
bash tests/distro/run.sh check ubuntu-24.04     # scripts/check.sh as a normal user
bash tests/distro/run.sh install ubuntu-24.04   # install.sh --no-service twice, then the self-test
APP_DIR=~/RadioConnect bash tests/distro/run.sh user ubuntu-24.04 \
  bash -c 'cd /src/app && MFRUIT_FONT_DIR=/src/MFruitOS/assets/fonts python3 -m pytest -q -p no:cacheprovider'
```

`MFRUIT_DISTRO_ARCH=armhf` runs a 32-bit system on an arm64 host whose CPU
runs 32-bit code (as 32-bit Raspberry Pi OS does on a 64-bit kernel).
The checkout is mounted read-only, so a test that writes into the source tree
fails there. Containers have no systemd, udev, kernel or hardware: the
[tested systems](../platform/INSTALLATION.md#tested-systems) table says what
this covers and what still needs a board.

## Timing-sensitive tests

Synchronize on observable state (daemon state, session state, files), never on
a sleep ([Regression policy](REGRESSION_POLICY.md)). Before calling a timing
test stable, repeat it (for example 20 iterations) and record the counts.

## Reporting results

State the revision, machine, Python/Pillow/daemon versions, the exact command,
totals and skips. A focused pass is not a full-suite pass; an automated pass
is not device verification. Durable results go into a
[dated record](records/README.md).
