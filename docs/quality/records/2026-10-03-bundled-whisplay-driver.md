# 2026-10-03 — Bundled Whisplay driver and offline installation

| | |
|---|---|
| Date | 2026-10-03 |
| Revision | uncommitted work on top of `3413c72` |
| Whisplay | PiSugar/Whisplay `c73051e64dc62aced1853d16f33d4614fec5bee4` copied into `drivers/whisplay` |
| Dev machine | Ubuntu 24.04 (noble) arm64, Python 3.12 |
| Device | Orange Pi Zero 2W `orangepi@192.168.0.130`: Ubuntu 22.04 (jammy) arm64, kernel `6.1.31-sun50iw9`, Python 3.10.12, Pillow 9.0.1, libgpiod Python API v1; `~/Whisplay` clean at `c73051e`; live MFruit OS `1.4.0-local20261003055500` (not changed) |
| Not reachable | Raspberry Pi Zero 2 W `jarvis@192.168.0.33` (SSH timed out) |

Request: replace the external Whisplay driver with an MFruit OS-owned one
([ADR 0008](../../platform/ADR/0008-bundled-whisplay-driver.md),
[Whisplay driver](../../WHISPLAY_DRIVER.md)); later in the session, the
owner added that installation must also work offline.

## Results

| Check | Command | Result |
|---|---|---|
| Baseline before changes, external checkout | `WHISPLAY_SRC=<upstream c73051e clone> python3 -m unittest discover -s tests` | AUTOMATED: 428 passed, 0 skipped |
| Copied files equal upstream | `bash scripts/whisplay-driver-sync.sh --check` | AUTOMATED: 48 files OK; negative control (one edited byte) fails |
| Driver on recorded SPI/GPIO | `tests/test_whisplay_driver.py` | AUTOMATED: 11 passed; negative control (MADCTL byte, SPI speed) fails 4 |
| Installer detection, boot config, staged copy | `tests/test_whisplay_driver_install.py` | AUTOMATED: 13 passed; negative controls (duplicate overlay, deleting a foreign directory) fail 3 |
| Offline packs | `tests/test_offline_install.py` | AUTOMATED: 9 passed; negative controls (no epoch rename, fatal sound card failure) fail |
| Whisplay's daemon unit tests | `python3 -m unittest discover -s drivers/whisplay/daemon/tests …` | AUTOMATED: 7 passed |
| Full checks, dev machine, no external checkout | `bash scripts/check.sh` | AUTOMATED: all checks passed, 461 tests, 0 skipped (real-daemon tests on the bundled daemon) |
| Full suite on the Orange Pi | `~/MFruitOS-candidate`: `python3 -m unittest discover -s tests` | AUTOMATED: 460 of 461 passed. The failure was a test still asserting the old `apt-get` command line; fixed, then that file, the driver, offline and upstream tests passed on the device; 0 skipped |
| Running driver = bundled driver | on the device: `cd ~/Whisplay && sha256sum -c ~/MFruitOS-candidate/drivers/whisplay/upstream.sha256` | all 48 files identical to the checkout the device's `whisplay-daemon` runs (`--whisplay /home/orangepi/Whisplay`) |
| Read-only driver check | `bash drivers/whisplay/install.sh --check` | board `orangepi_zero2w`; SPI `/dev/spidev1.0`, sound card installed and loaded, daemon active; reports `python3-smbus` missing (optional), files not yet in `/usr/local/share/whisplay`, service still on `~/Whisplay`: what an install would change |
| Offline pack on the device | `bash scripts/make-offline-pack.sh --archive` | 395 packages, 207 MB (+ 205 MB `.tar.gz`); the three Orange Pi downloads match Whisplay's pinned SHA-256 |
| Pack completeness | `apt-get -s install <every package the installers request>` with only the pack as source | resolves on a minimal consistent system (170 packages: 139 to install), on an empty package database (236) and on the device (1: `python3-smbus`) |
| Offline shims | the pack's `wget`/`apt-get` shims with the real pinned URLs and the Orange Pi sound installer's `apt-get install` line | files served and verified; apt resolves from the pack |

A first pack excluded `required`/`important` packages, assuming every image
has them; the minimal-system simulation showed it unresolvable (e.g.
`python3` in the jammy archive is `important`, but its newer dependencies are
needed). Packs now carry the full dependency closure.

## Device tests without sudo (later the same day)

The privileged install could not run: Claude Code's permission system blocks
using a password typed into the chat, so the owner runs that step. Tests that
need no root, on the Orange Pi's current driver (`~/Whisplay`, whose 48 files
are identical to `drivers/whisplay`):

| Test | Result |
|---|---|
| `drivers/whisplay/install.sh --check` | as before: SPI, sound card installed and loaded, daemon active; the two FAILs are the steps the install performs |
| Services | `whisplay-daemon`, `whisplay-os` active; `whisplay-soundcard-warmup` ran at boot with result `success` |
| Display pipeline | `mfruitctl screenshot` 240×280; a simulated tap moved the Home selection; back again gives a byte-identical frame (found KI-10) |
| Speaker | card `whisplaysound` = WM8960; speaker and mic mixer at 80; a 1 s 440 Hz tone played with exit 0 (audibility NOT VERIFIED) |
| Microphone | 2 s capture at 48 kHz: left channel RMS 572, peak 2285; right channel silent |
| Full suite on the device | AUTOMATED: 461 passed, 0 skipped |

Backup before the install: `~/mfruit-backups/20261003-072228-before-bundled-driver`
(MFruit OS home, daemon home, unit, data checksums, boot environment, ALSA
config, audio file listing).

## Changeover on the Orange Pi (owner ran the install, 2026-10-03 17:23 UTC)

The owner ran `cd ~/MFruitOS-candidate && bash scripts/install.sh` (log
`~/mfruit-install-driver.log`). Then, without sudo:

| Check (VALIDATION D-number) | Result |
|---|---|
| Install | one sudo prompt, no questions, no reboot needed; `python3-smbus` installed **from the offline pack** (`Get:1 file:…/debs`); overlays and sound card left as they were; old unit saved to `/var/backups/mfruitos`; daemon and launcher restarted; self-test OK |
| D1 `install.sh --check` | DEVICE: all `OK`, exit 0 |
| Daemon | runs `whisplay-daemon-mfruit.py --whisplay /usr/local/share/whisplay`; wrapper patches applied (`_render_desktop` … `_send_data_bytes`); no errors in its log |
| D2 data and configuration | DEVICE: daemon settings and every app registration unchanged except MFruit OS's own (`cwd` → the new launcher version, expected); `~/Whisplay` unchanged; sound card module and overlay files not rebuilt; `orangepiEnv.txt`, `asound.conf`, sound cards unchanged |
| Lifecycle on the new daemon | `mfruitctl launch radioconnect`: the daemon reported RadioConnect in front; `app.exit.request` → back to MFruit OS; process gone; log `LAUNCH_REQUEST` → `SESSION_END outcome=exited` → `APP_CLOSED` |
| D6 runtime for apps | `whisplay_client` imports from `/usr/local/share/whisplay/runtime` (apps that search `~/Whisplay` first still use the identical copy there) |
| Microphone after the switch | 1 s capture: RMS 707, peak 4239 |

Found during the check (not caused by this change): Flappy Bird is disabled
in this board's settings, so the launch was refused as designed; ConnectWifi
is broken here ("Working directory missing": its registration points to a
removed `~/ConnectWifi` checkout, already missing before the install).
Cosmetic log issues fixed afterwards: an apt `_apt` sandbox warning
(`APT::Sandbox::User=root` for the pack) and the driver's "restart it" note
when `scripts/install.sh` restarts the daemon itself (`--restart-later`).

Before the owner wipes the board: all git checkouts there are clean and
pushed; the board's data (`~/.whisplay-os`, including the shared radio keys
and contacts, `~/.whisplay-daemon`, `~/mfruit-backups`) and the offline pack
were copied to the dev machine, `~/mfruit-backups/orangepi-20261003-before-wipe/`
(pack checksum verified).

## Fresh offline install rehearsal (2026-10-04, on the Orange Pi's Docker)

`bash tests/fresh_install/rehearse.sh offline/orangepi_zero2w-ubuntu-jammy-arm64 --suite`:
stock `ubuntu:22.04` arm64 + python3, sudo, kmod, systemd, udev; then
`bash scripts/install.sh --yes` as user `orangepi` with `--network none`.

| Run | Result |
|---|---|
| 1, 2 | harness bugs (docker `commit -q`; `SUDO_USER=root` from starting the user shell with sudo, so the installer refused root as designed; a `check` name clash in `verify.sh`) |
| 3 | install exit 0, all verify checks passed except "user in gpio group" (the check read the running session's groups; fixed to read the group database). **Real-daemon tests against the installed driver failed:** `daemon_renderer` uses DejaVu Sans; without it Pillow 9.0.1's fallback font has no `getbbox`, so the daemon desktop and pages crash on a fresh image. Upstream Whisplay assumes the font too |
| 4 (after the fix: `fonts-dejavu-core` required; `bluez`, `python3-dbus`, `python3-gi` optional; pack rebuilt: 400 packages, 208 MB) | AUTOMATED in the container: install exit 0, **47 of 47 checks passed**, among them: everything from the pack with no network, `snd-soc-whisplay-soundcard.ko` and `snd-soc-wm8960.ko` compiled for `6.1.31-sun50iw9` (vermagic matches), overlay compiled, `orangepiEnv.txt` overlays, `/etc/modules`, ALSA config, units and wrapper drop-in, sudoers valid, MFruit OS self-test, Wi-Fi app provisioned, no build files in the checkout. Real-daemon tests against `/usr/local/share/whisplay`: `test_background_ui`, `test_launch_lifecycle`, `test_daemon_unregister`, `test_dc_park` all OK. 6 min 21 s |

Not covered by the rehearsal: the reboot, a real device tree, the LCD, loading
the modules and the sound card on the board (fresh install on hardware is
still to do).

## Skipped and not verified

- The changeover above is the only privileged run. NOT VERIFIED: a fresh
  install (buses, sound card build, reboot) on either board, a full offline
  install from a pack on a fresh image, `--rollback`, `uninstall.sh`.
- NOT VERIFIED physically (needs a person at the board): D3 display looks
  as before, D4 Diagnostics tests and backlight, D5 audible playback, D7
  Power page reboot/shutdown, D8 rollback
  ([Validation](../VALIDATION.md#whisplay-driver-bundled-since-2026-10-03)).
- Raspberry Pi: no offline pack built (board offline); its sound card build
  offline depends on the pack's kernel headers matching the board's kernel.
- Orange Pi Zero 3W, Radxa ZERO 3W and Radxa Cubie A7Z: installer paths
  follow Whisplay's, never run.

## Left on the device

`~/MFruitOS-candidate` (new candidate; the previous one moved to
`~/MFruitOS-candidate.prev-20261003164237`), with the offline pack under
`~/MFruitOS-candidate/offline/` (about 410 MB in total; safe to delete). The
live installation, `~/Whisplay`, services and daemon settings were not
changed.
