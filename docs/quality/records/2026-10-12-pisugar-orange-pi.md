# 2026-10-12 — PiSugar 2 on the Orange Pi Zero 2W: no battery shown

## Problem

The owner moved the PiSugar 2 from the Raspberry Pi Zero 2 W to the Orange
Pi Zero 2W. The Orange Pi showed no battery: the status bar had no level and
Settings → Battery said "No battery board".

## Evidence

| What | Observed (Orange Pi Zero 2W, Ubuntu 22.04, mFruit OS `1.4.0-local20261010235849`) |
|---|---|
| Power service log | "no PiSugar battery board found on I2C bus 1", at every start since 2026-10-10 |
| `power.json` | `"i2c_bus": 1` (the default, written back with every save) |
| I2C adapters (`/sys/bus/i2c/devices`) | `i2c-0` PMIC (`7081400`), **`i2c-1` DesignWare HDMI**, `i2c-2` `5002400` (header pins 3/5, overlay `pi-i2c1`; WM8960 bound at `2-001a`), `i2c-3` `5002c00` (every read times out after ~4 s) |
| Device tree | `__symbols__/i2c1` → `/soc/i2c@5002400` = `i2c-2`; on the Pi Zero `i2c1` → `/soc/i2c@7e804000` = `i2c-1` |
| `mfruitctl power set i2c_bus` 2, 3, 0 (via the service) | not found on any |
| Read-only scan (one register read per address, `docker` root for `/dev/i2c-*`, since the login user is not in the `i2c` group) | bus 2: **0x32 answers** (PiSugar 2 clock), **0x75 no answer** (battery chip), 0x1a held by the codec driver; bus 0: PMIC only; bus 3: timeouts |
| After the fix, 00:19 | the service found the board on bus 2 and the battery chip answered: PiSugar 2, 84%, 4.014 V, −0.389 A |

## Root causes

1. **Software:** the power service only looked on bus 1, the Raspberry Pi's
   header bus. On the Orange Pi Zero 2W bus 1 is the HDMI port; the header is
   bus 2. The board could never be found there.
2. **Hardware state, not explained:** at 00:05 the PiSugar 2's battery chip
   (0x75) gave no answer while its clock (0x32) did; by 00:19 it answered.
   The Pi Zero showed the same "no board" after its 2026-10-10 17:04 boot.
   What silences the chip (battery, switch, spring-pin contact, sleep) was not
   observed. PiSugar's own advice for a missing 0x75 is to reseat the board.

## Fix (mFruit OS, uncommitted)

- `hosts/pisugar/i2c.header_bus()`: the 40-pin header's bus is the adapter
  whose device-tree node is the one labelled `i2c1` (bus 1 on the Pi, bus 2
  on the Orange Pi Zero 2W).
- `power/service.py`: when no board answers on the configured bus, the header
  bus is tried; a board found there has its bus saved to `power.json`, which
  the shutdown hook (`scripts/mfruit-power-off`) also reads, so the hook needs
  no reinstall.
- `hosts/pisugar/detect.BatteryChipSilent`: clock answers, battery chip gives
  no reading. The status says so (`error`, new field `board_silent`), the
  service looks again every 30 s (logged once), and Settings shows
  "PiSugar 2: no battery reading" / "PiSugar 2: no reading" instead of "No
  battery board".

## Tests

| Test | Result |
|---|---|
| `test_pisugar_drivers`: header bus on Pi-like and Orange-Pi-like sysfs, unknown tree; silent chip told apart, still read-only | PASS |
| `test_power`: board on the header bus found and its bus saved; without the header bus not found; both empty names both buses; silent chip re-checked every 30 s until it answers | PASS |
| `test_battery_ui`: Settings and Battery labels for a silent board | PASS |
| Negative controls (scratch copy): no header fallback, no silent detection, no 30 s re-check, old UI labels | each fails its tests |
| `scripts/check.sh` | All checks passed (689 tests) |

## Device (Orange Pi Zero 2W)

- Backup `~/mfruit-backups/20261012-001900-before-pisugar-bus/`; `deploy.sh
  --no-service` → `1.4.0-local20261012001910`; launcher restarted via sudoers.
- The power service restarted itself on the update, logged "Battery board
  found on I2C bus 2, not bus 1; using bus 2 from now on", saved `i2c_bus: 2`;
  `mfruitctl screenshot` shows 84% in the status bar. DEVICE VERIFIED.
- The model stays `auto`, so the board is read only ("PiSugar 2", LED count
  unknown) until `model` is set to `pisugar2-4led` or `pisugar2-2led`.

## Not verified

- The silent-chip message and 30 s re-check on the device (the chip answered
  by the time the new code ran; automated tests only).
- The shutdown hook switching the board off on the Orange Pi (KI-13).
- Why the battery chip was silent at 00:05.
- Raspberry Pi behaviour after the change on a board (unchanged by design:
  the header bus there is the default bus 1; covered by tests).
