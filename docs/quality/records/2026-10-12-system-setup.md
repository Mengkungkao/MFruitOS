# 2026-10-12 — The system setup follows System updates (1.6.0)

## Problem

After the Fruit Store learned to update mFruit OS (1.5.x,
[record](2026-10-12-store-updates.md)), one part still needed a computer:
what `scripts/install.sh` sets up as root (the **system setup**: launcher and
power units, the daemon drop-in, sudoers and polkit rules, the power-off
shutdown hook, the `i2c-dev` list, the Whisplay driver, packages). A System
update runs as the user and replaces only the code, so a device kept the
system setup of its last `sudo bash scripts/install.sh`. The owner asked
which device lacked what, and to fix it so no computer is needed.

## Evidence

| What | Observed |
|---|---|
| Both boards since 2026-10-11 | files-only installs (`install.sh --no-service`, restart through sudoers): the system part of the distro fixes (9110008) and later never ran there (CONTINUE.md X5, memory notes) |
| Root-level changes since the boards' last system install | 9110008 (2026-10-11): Wi-Fi permission also as a `.pkla` for polkit 0.105 (Ubuntu 22.04, the Orange Pi), units listing only existing groups (+ `dialout`), driver: `make`/`gcc`, `config.txt` `[all]`, sound card build flags; b473f0b (2026-10-10): `i2c-dev` at boot |
| Orange Pi Zero 2W (192.168.0.130) | unreachable from 18:00 (no ARP answer; its battery was at 25 % and falling at 10:40); not checked |
| Raspberry Pi Zero 2 W (192.168.0.33) | answers ping, SSH banner times out (weak Wi-Fi, as all day); per-file check: see below |

Root cause: no component owned keeping the system setup in step with the
installed version; the only path was the installer run by hand with sudo.

## Fix ([ADR 0015](../../platform/ADR/0015-system-setup-from-releases.md))

- `install.sh --check-system` (read-only diff of every root-owned file, unit
  state, packages, driver) and `--system-only` (only the system setup; only
  what differs; only changed services restart; as root with `--user`, never
  running the user's Python).
- `mfruit-system-apply.service` (root, installed by `install.sh`): reads only
  the version from the user's files, downloads that release from the
  repository in root's `/etc/mfruit-os/system.conf`, checks the published
  SHA-256, unpacks plain files into a root-only folder, runs its
  `install.sh --system-only`. One sudoers rule lets the launcher start it.
- The launcher starts it once per version after a System update is confirmed
  healthy; *Settings → General → Software Update → System setup* shows the
  state and applies it; `mfruitctl system-setup [check|apply]`.
- The driver installer writes `~/.whisplay-daemon` as the user (root now runs
  it unattended).

## Tests

| Test | Result |
|---|---|
| `tests/test_system_setup.py` (25): root helpers in install/check mode; whole `install.sh --check-system` (no sudo call, nothing created); `--system-only` as root with command doubles (every file, the record, the status before the launcher restart, the user's Python only through `sudo -u`); `--user` refused for non-root; the service's record/version/checksum/extraction checks; end-to-end with a fake GitHub (URLs, arguments, clean-up, done-once, wrong checksum or version never runs, before 1.6.0 refused, failures recorded); HTTPS-only download; launcher status, trigger, screen rows, `mfruitctl` | PASS |
| `tests/test_install_setup.py`, `tests/test_whisplay_driver_install.py` (adapted; new: own module list kept, daemon settings written through `runuser`) | PASS |
| Negative controls (each protection removed, its test run): user's Python run by root; sudo in check mode; links/devices extracted; checksum skipped; manifest link followed; driver writing the home as root; auto-start without the once-per-version marker; sudoers without the start rule | each FAILS without its protection |
| `scripts/check.sh` (dev machine, Ubuntu 22.04 aarch64, Python 3.12) | All checks passed (740) |

## Device results

Pending at the time of writing; added below as they are made.

## Not verified

- The service against the published v1.6.0 release on a device (needs the
  one-time `--system-only` on a board first, which asks for the owner's
  password).
- The fresh-install rehearsal with the new `verify.sh` checks (Docker on the
  Orange Pi, which is offline).
- A system setup that changes the driver on a board (sound card rebuild,
  restart to finish).
