# Testing MFruit OS

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

It runs: Python syntax for 3.9, the unit and integration suite (including the
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

`bash tests/fresh_install/rehearse.sh <offline pack> [--suite]` installs MFruit
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

## Timing-sensitive tests

Synchronize on observable state (daemon state, session state, files), never on
a sleep ([Regression policy](REGRESSION_POLICY.md)). Before calling a timing
test stable, repeat it (for example 20 iterations) and record the counts.

## Reporting results

State the revision, machine, Python/Pillow/daemon versions, the exact command,
totals and skips. A focused pass is not a full-suite pass; an automated pass
is not device verification. Durable results go into a
[dated record](records/README.md).
