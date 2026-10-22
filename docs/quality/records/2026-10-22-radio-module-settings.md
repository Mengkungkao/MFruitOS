# 2026-10-22 — A new board found no radio to pair with

## Problem

The owner set up a new Orange Pi Zero 2W (`opi2w`, 192.168.0.248, mFruit OS
1.6.1 from a fresh `install.sh` with the radio, RadioConnect 0.6.0 from the
Fruit Store) and tried to pair it with the older Orange Pi (`orangepi`,
192.168.0.130, mFruit OS `1.6.1-local20261013112924`, RadioConnect 0.6.0).
Pairing on either board showed no radio.

## Evidence

| What | Observed |
|---|---|
| Both apps | RadioConnect 0.6.0 on both; only `app/main.py` (pairing channel order) and `app/audio/codec2.py` differ between the two builds, neither on the air path |
| Shared settings | identical `radio.json`: 920 MHz, 2400 bps, 22 dBm, net 0, `/dev/ttyS0`; same privacy channel (5) during the last attempt |
| Logs, 15:22-15:31 | both boards in pairing at the same time (15:29:09-15:31:14), each sending `pair` every 3 s; no `rx` line on either board all day |
| Old board, 2026-10-16/17 | paired and talking with the Pi Zero at 920 MHz until 00:04:58 (power cut mid-line); next boot 2026-10-22 15:21 |
| New module | answers the channel-level query (`reports_level: true`); the old one never did |
| Registers (read-only dump, `C1 00 09`, run by the owner with sudo; daemon stopped about 3 s) | new board `c1 00 09 00 00 00 62 20 46 c3 00 00`: 920 MHz (ch 70), fixed transmission, signal byte, channel level on. Old board `c1 00 09 00 00 00 62 00 12 03 00 00`: **868 MHz (ch 18), transparent, no signal byte, no channel level**: the E22 factory settings |
| Product info (`C1 80 07`) | the same on both: `c1 80 07 00 22 10 16 0b 00 00` (same module model and firmware) |
| Old board's record | `radio.json` provisioned 2026-10-05, 920 MHz: RadioConnect showed and used 920 MHz |
| Also seen | both boards share `/etc/machine-id` and the root file system UUID (flashed from the same Orange Pi image; not involved here) |

## Root cause

The two radios were on different frequencies: the old board's module was on
its factory settings (868 MHz, transparent), the new one on mFruit OS's
(920 MHz, addressed). Why the old module lost its settings between
2026-10-17 and 2026-10-22 is **not known**: no mFruit OS or RadioConnect
code writes module registers outside provisioning, and a swapped or replaced
module would look the same.

The platform fault is that this went unnoticed. The module keeps its settings
in its own memory, and after the first setup everything trusted
`radio.json`: nothing read the module again, `setup-radio.sh` skipped it when
`radio.json` matched ("already provisioned"), and provisioning compared only
the frequency on read-back. Every screen kept saying 920 MHz.

## Fix (mFruit OS 1.6.2, uncommitted)

- `sx126x.differences()`: every readable register (address, net id, serial
  and air speed, packet size, power, channel level, frequency, transmission,
  signal byte); the two key registers are write-only and not compared.
- `python3 -m mfruitos.hosts.lora ensure`: reads the module, writes the
  recorded settings only where it differs, requires the whole read-back to
  match; a new `provisioned_at` when written (RadioConnect then asks for the
  channel level again); result in `shared/radio/module.json`.
- `mfruit-radio-setup.service` runs it at **every boot**, as the user (groups
  of the serial port and GPIO chip), before whisplay-daemon; it no longer
  disables itself and no longer runs as root.
- `setup-radio.sh`: records the settings and installs the boot check; always
  compares the module (no skip on `radio.json`); `--check` reports the last
  boot check; root Python without bytecode (KI-15).
- `install.sh` system setup (also from System updates): installs the boot
  check wherever `radio.json` exists; `--check-system` reports it.
- Readiness: a module that did not answer or did not take its settings is a
  missing requirement for radio apps.
- `provision`: compares first, writes only differences, full read-back;
  files handed to the owner without following links.

## Validation

| Check | Result |
|---|---|
| `tests/test_radio_host.py` (19), `tests/test_autoinstall.py` (15), `tests/test_system_setup.py` (26) | pass. Fixtures are the two boards' real register dumps |
| Negative control: new radio tests on the old `mfruitos/hosts/lora` | 13 of 19 fail, including `test_the_whole_read_back_must_match_not_only_the_frequency` (the old provisioning accepted a module still sending transparently) |
| Negative control: installer tests on the old `install.sh` | both new checks fail |
| Rendered unit | `systemd-analyze verify` clean on the dev machine; on both boards it renders `User=orangepi`, `SupplementaryGroups=dialout gpio` |
| Fixed code on both boards (Python 3.10), as the user with the daemon running | `ensure` refuses ("run with sudo"), exit 2, nothing touched |
| `bash scripts/check.sh` (dev machine, final tree) | all checks passed, 763 tests |

| Old board, `try-boot-check.sh` (unit from `~/mfruit-radio-fix`), reboot 16:28:19 | DEVICE VERIFIED: `mfruit-radio-setup.service` as `orangepi` found `frequency 868 (wanted 920)`, transparent, no signal byte, no channel level; wrote and read back 920 MHz, fixed, signal byte, channel level (16:28:31.68); whisplay-daemon started after it (16:28:31.84); `module.json` `restored`, new `provisioned_at`; no root-owned bytecode left in `system/current` |
| Pairing after the boot check | DEVICE VERIFIED: 16:29:25 the new board heard `pair` from orangepi (-31 dBm); 16:29:46 paired both ways (pair-request/pair-accept at -32/-33 dBm) |

NOT VERIFIED on a device: the boot check on the new board (`try-boot-check.sh`
not run there: it still has the old one-time unit, disabled, and root-owned
bytecode), a System update installing the boot check, and the unit pointing at
`system/current` (on the old board it runs `~/mfruit-radio-fix` until 1.6.2 is
installed).
