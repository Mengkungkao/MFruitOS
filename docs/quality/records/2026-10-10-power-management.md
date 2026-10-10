# Own power management and the rename to mFruit OS — 2026-10-10

## Scope
- Source revision and working-tree state: `30d9ec4` plus this session's
  uncommitted changes (power management, rename, phone Wi-Fi setup).
- Device / OS / architecture: development machine (NVIDIA Jetson Orin Nano,
  Ubuntu 22.04-based L4T, aarch64, Python 3.12.3). Orange Pi Zero 2W:
  see "Device" below. Raspberry Pi Zero 2 W: offline all session (no route).
- Python, Pillow, whisplay-daemon revision: bundled Whisplay `c73051e`
  (unmodified).
- Reference read in full: PiSugar/pisugar-power-manager-rs at `ea025c2`
  (2026-10-03), GPL v3. mFruit OS's implementation is independent (MIT); no
  code copied.

## Results
| Check | Command or procedure | Result |
|---|---|---|
| Baseline before changes | `bash scripts/check.sh` | AUTOMATED: all checks, 521 tests OK |
| Rename `MFruit` → `mFruit` (841 occurrences, 177 files; upstream driver files untouched) | `bash scripts/check.sh` | AUTOMATED: all checks, 521 tests OK; driver checksums unchanged |
| PiSugar drivers against register-level fakes (incl. negative control: writes without opening the PiSugar 3 write protection are lost) | `python3 -m unittest tests.test_pisugar_drivers` | AUTOMATED: 31 OK |
| Power service: levels, low-battery countdown/cancel/off/retry, soft shutdown, presses, read failures, probing, settings, charging range, wake alarm in UTC, clock rules, config file rules, PiSugar config import, PiSugar protocol, sockets, events, tap hooks | `python3 -m unittest tests.test_power` | AUTOMATED: 39 OK |
| Contract: the bundled daemon's own `PiSugarManager` (battery read, custom-hook check, hook install, start-up clean-up) against the power service's PiSugar socket; SDK and launcher battery reads | in `tests.test_power` | AUTOMATED: OK |
| Shutdown hook (`scripts/mfruit-power-off`) on PiSugar 3, PiSugar 2, PiSugar 2 Pro fakes; reboot/halt untouched; settings and kill switch | `python3 -m unittest tests.test_power_off_hook` | AUTOMATED: 4 OK |
| Launcher: PowerLink, status bar, low-battery dialog, shutting-down screen, board button actions, power menu, Settings rows, Battery page, wake-alarm flow, `mfruitctl power` | `python3 -m unittest tests.test_battery_ui` (from `tests/`) | AUTOMATED: 15 OK (found and fixed a closure bug that made every switch use the last row's value) |
| Installer/uninstaller power parts, rendered unit through `systemd-analyze verify` | `tests/test_install_setup.py` | AUTOMATED: OK |
| Full suite after power management | `bash scripts/check.sh` | AUTOMATED: all checks, 616 tests OK |
| Full suite, final tree (power, rename, phone Wi-Fi setup) | `bash scripts/check.sh` | AUTOMATED: all checks, 644 tests OK |
| Service end to end with a simulated PiSugar 3 | `python3 -m mfruitos.power --home <tmp> serve --fake pisugar3`, then `status --details` and PiSugar-protocol requests | AUTOMATED (manual run on the dev machine): status, protocol answers, refused `force_shutdown`, clean SIGTERM stop |

## Device (Orange Pi Zero 2W, no PiSugar)

Build `1.4.0-local20261010122215` (files only, `--no-service`); the power
service run by hand as `orangepi` (its unit needs the owner's sudo).

| Check | Result |
|---|---|
| New test modules on the board (Python 3.10.12, Pillow 9.0.1): 136 tests | AUTOMATED on the device: OK |
| Full suite on the board, final build (`python3 -m unittest discover -s tests` in `~/MFruitOS-candidate`) | AUTOMATED on the device: 644 tests OK in 242.6 s |
| Power service without the `i2c` group: status `present: false` with "no permission for /dev/i2c-1: … i2c group"; retries after 5, 15 and 60 s, then stops | DEVICE VERIFIED |
| PiSugar socket answers (`get battery` → the reason, `get version` → `mfruit-power 1.4.0`); both sockets 0600 | DEVICE VERIFIED |
| Launcher subscribes to the power events; Settings → Battery shows *No battery board* with the reason (screenshot) | DEVICE VERIFIED (screenshot) |
| After an OS install the running power service logs "mFruit OS was updated; restarting the power service" and exits | DEVICE VERIFIED (systemd restart itself not, the unit is not installed) |
| SIGTERM: sockets removed | DEVICE VERIFIED |

### Later the same day: installed with the owner's sudo

The owner ran the full installer (12:36): `mfruit-power.service`, the
shutdown hook and the sudoers line installed; the service active with the
`i2c` group and reporting "no PiSugar battery board found on I2C bus 1"
(the bus is now readable; the Orange Pi has no PiSugar) — DEVICE VERIFIED.

The update watch did not fire under systemd: the unit's working directory
is the resolved version, so the imported code's path never changed after an
install. Fixed to follow the `system/current` link (`active_code`), with a
regression test whose old-code run fails. On the device after the fix: an
install at 12:52:25, "mFruit OS was updated; restarting the power service" at
12:52:56, systemd started the new code at 12:53:00 — DEVICE VERIFIED.

### Bug: no /dev/i2c-1 on the Pi Zero 2 W

- **Problem:** after the owner's install (build `1.4.0-local20261010133846`)
  the power service logged "I2C bus 1 is not enabled (/dev/i2c-1 is missing)"
  and stopped looking for a board.
- **Expected:** the service opens `/dev/i2c-1`, or names the real cause.
- **Evidence (read on the Pi, Raspberry Pi OS trixie, kernel 6.18.50):**
  `dtparam=i2c_arm=on` in `config.txt`; bus `i2c-1` (bcm2835) in
  `/sys/bus/i2c/devices` with the sound codec on it; no `/dev/i2c-*`;
  `i2c_dev` not in `/sys/module`; no list in `/etc/modules` or
  `/etc/modules-load.d` names it.
- **Root cause:** `/dev/i2c-N` comes from the `i2c-dev` module. Raspberry Pi OS
  loads it only through raspi-config's I2C switch. The Whisplay driver turns
  the bus on in the boot config, and nothing loaded the module.
- **Fix:** the installer's power section runs `modprobe i2c-dev` and lists it
  in `/etc/modules-load.d/mfruit-power.conf` unless a list already has it; a
  failure warns and the install goes on. `uninstall.sh` removes the list file.
  `explain()` reports a bus that exists without its device file as the missing
  module (checked in `/sys/bus/i2c/devices`, which both boards have).
- **Regression tests:** `test_install_setup` (module loaded and listed, not
  listed twice, a failed modprobe only warns, uninstall removes the file) and
  `test_pisugar_drivers` (the reason names the module). Each fails with the
  old code.
- **Hardware validation:** DEVICE VERIFIED on the Pi Zero 2 W. The owner ran
  the installer (build `1.4.0-local20261010143048`). Afterwards `/dev/i2c-1`
  and `/dev/i2c-2` exist (`root:i2c`), `i2c_dev` is loaded, and
  `/etc/modules-load.d/mfruit-power.conf` lists it. Not yet checked across a
  reboot.
- **Compatibility:** boards that already have `/dev/i2c-*` (the Orange Pi)
  only get the list file or the "already loaded" line.

### First run on a PiSugar 2 (Pi Zero 2 W)

With the device file in place the service found the owner's PiSugar 2 at
14:31:23 ("Battery board: PiSugar 2 on I2C bus 1") and set the board's clock
from the system clock. `mfruitctl power status` read the following:

| Field | Value |
|---|---|
| model | PiSugar 2 |
| level | 38.2 %, rising to 38.7 % over about a minute |
| voltage | 3.851 to 3.854 V |
| charging | true (decided from the rising voltage; this board cannot sense external power) |
| current | −0.39 A |

Detection, reading and the clock write are DEVICE VERIFIED (checklist P1,
except the status bar, which was not looked at). The current's sign is NOT
VERIFIED. The ADR calls it output current, but it read negative while the
battery was charging, so a reading on battery power is needed before trusting
it. The update restart before this run exited with status 75 as designed, and
systemd restarted it. systemd logs that as "Failed with result 'exit-code'",
which is only noise in the journal.

## Skipped and not verified
- Physical checks not performed: every item of the
  [power hardware checklist](../VALIDATION.md#hardware-checklist--power-management)
  (P1–P8). No board with a PiSugar was reachable: the Raspberry Pi Zero 2 W
  was offline; the Orange Pi has no PiSugar service and its user is not in the
  `i2c` group, so its bus could not even be scanned without sudo.
- `mfruit-power.service`, the shutdown hook and the new sudoers line were not
  installed on a device: that needs the owner's sudo password.
- PiSugar 3 button timing (long press versus the hardware power-off hold) is
  unknown; the long-press action defaults to Nothing.

## Issues found
- During development: with power management set to `none` the service still
  opened the I2C bus; fixed (the bus is not opened), covered by
  `test_model_none_does_not_touch_the_bus`.
- Preview screenshots showed the development machine's own Wi-Fi name; the
  preview now uses sample network values (`docs/screenshots/settings.png`
  re-rendered before anything was committed).
