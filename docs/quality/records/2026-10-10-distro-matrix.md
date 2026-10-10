# 2026-10-10 — Other distributions: Ubuntu, Orange Pi Ubuntu, Ubuntu for Raspberry Pi

The owner asked to test and debug the work so far and make sure installing mFruit
OS works on Ubuntu, Orange Pi Ubuntu and Ubuntu for Raspberry Pi.

- **Revision:** `4ca074f` plus the uncommitted changes listed under "Bugs found and fixed"
- **Host:** Jetson Orin Nano (arm64), Ubuntu 24.04, Linux 6.8.12-tegra; no root,
  no Docker (`tests/distro/run.sh`: user namespaces, distribution root filesystems)
- **Boards:** none for Ubuntu on a Raspberry Pi. The Orange Pi Zero 2W runs
  Ubuntu 22.04 (Orange Pi OS Jammy); the Raspberry Pi Zero 2 W runs
  Raspberry Pi OS Trixie. See "Boards" for what was checked on them.

## Systems

Root filesystems: Canonical's ubuntu-base 22.04.5 and 24.04.5 (SHA256SUMS
checked), Docker Hub's official debian bookworm, trixie and bullseye images
(digest checked), arm64 and one armhf, with each distribution's own packages
(versions read from the roots):

| System | Python | Pillow | numpy | gpiod | libcodec2 | glibc |
|---|---|---|---|---|---|---|
| Ubuntu 22.04 | 3.10.12 | 9.0.1 | 1.21.5 | 1.6.3 | 1.0 | 2.35 |
| Ubuntu 24.04 | 3.12.3 | 10.2.0 | 1.26.4 | 1.6.3 | 1.2 | 2.39 |
| Debian 12 | 3.11.2 | 9.4.0 | 1.24.2 | 1.6.3 | 1.0 | 2.36 |
| Debian 13 | 3.13.5 | 11.1.0 | 2.2.4 | 2.2.0 | 1.2 | 2.41 |
| Debian 13 armhf (32-bit) | 3.13.5 | 11.1.0 | 2.2.4 | 2.2.0 | 1.2 | 2.41 |
| Debian 11 | 3.9.2 | 8.1.2 | 1.19.5 | 1.6.2 | 0.9 | 2.31 |

Tests ran as a normal user (uid 1000, no capabilities) with the checkout
mounted read-only.

## Results before the fixes

| System | mFruit OS `check.sh` | RadioConnect suite |
|---|---|---|
| Ubuntu 22.04 | all checks passed, 658 tests (1 skipped) | 708 passed, 1 failed (a test that assumed the Inter font; fixed), 5 skipped without Inter |
| Ubuntu 24.04 | all checks passed, 658 (1 skipped) | 714 passed |
| Debian 12 | real-daemon tests errored in teardown: `pkill` missing (procps is not in the container image; every board image has it) | 714 passed |
| Debian 13 | all checks passed, 658 (1 skipped) | 714 passed |
| Debian 11 | self-test and most imports failed: `TypeError: unsupported operand type(s) for \|` (installer.py), `ImageDraw` has no `rounded_rectangle` (Pillow 8.1) | collection errors: libcodec2 0.9 lacks `codec2_bytes_per_frame` |

Run as root inside the chroot (the first attempt), `setup-app.sh`'s tests
failed because the script correctly refuses root; that is why the suites run
as a normal user.

## Bugs found and fixed

Each code fix has a regression test. A negative control (the old code put
back, the test run again and seen to fail) was run for 1, 4, 5, 6, 8, 9, 10
(the codec), 11, 12 and 15; for 2 and 7 the failure was shown in a root
filesystem instead (the build, the 32-bit binary); 3 was a missing branch,
seen working in the Orange Pi rehearsal. 13 and 14 were faults in tests.

1. **`whisplay-daemon.service` named a group that does not exist.**
   Evidence: Ubuntu 22.04's `ubuntu-raspi-settings` (`99-gpio.rules`) gives
   gpiomem, I2C, SPI and gpiochip devices to `dialout`; no package creates a
   `gpio` group. systemd v249 `get_supplementary_groups()` fails the exec with
   EXIT_GROUP (216) when a `SupplementaryGroups=` name does not resolve. The
   unit had `SupplementaryGroups=audio video gpio input` fixed in the text, so
   on Ubuntu for Raspberry Pi the daemon would not start (no display). This
   follows from systemd's source and Ubuntu's packages; no board here runs
   Ubuntu on a Raspberry Pi, so it was not seen happen.
   Fix: `daemon_groups` (existing groups only, `dialout` when there is no
   `gpio`); the launcher unit likewise; the power service takes the group of
   `/dev/i2c-*`. Tests: `DaemonServiceGroups`,
   `test_launcher_groups_exist_on_each_system`,
   `test_power_service_gets_the_group_that_owns_the_i2c_devices`.
2. **The sound card did not build on Ubuntu for Raspberry Pi.** Simulated
   Raspberry Pi on Ubuntu 24.04: Whisplay's sound card installer installs the
   kernel headers but adds `make`/`gcc` only on Orange Pi, and Ubuntu Server
   has no compiler: "make: command not found". With them, the source failed:
   `implicit declaration of function 'asoc_substream_to_rtd'` (removed in
   Linux 6.8; the source switches names only at 6.12). Fix: the driver
   installs `make` and `gcc`; on kernels 6.8 to 6.11 it builds with
   `KCFLAGS=-Dasoc_substream_to_rtd=snd_soc_substream_to_rtd`, leaving the
   bundled files unchanged (KI-19). The module then built
   (vermagic `6.8.0-1065-raspi`); Ubuntu 22.04's 5.15.0-1110-raspi headers
   build it without the mapping. Tests: `SoundCardBuildFlags`,
   `test_the_sound_card_build_tools_are_installed`.
3. **Wi-Fi permission ignored by polkit 0.105.** Ubuntu 22.04 (and the Orange
   Pi) runs polkit 0.105, which reads `.pkla` files, not the JavaScript rule
   the installer wrote. NetworkManager's defaults for a process outside a
   login session are `auth_admin` for scan and connect, so on a fresh 22.04
   board the launcher could not scan or join. The Orange Pi allows it today,
   most likely through ConnectWifi's own installer, which writes a `.pkla` for
   polkit 0.105 (its README; the folder is root-only, so not confirmed).
   Fix: the grant is also written as
   `/etc/polkit-1/localauthority/50-local.d/49-mfruit-wifi.pkla` where `.pkla`
   files are read, removed by `uninstall.sh`, and the installer asks
   NetworkManager from a session-less `systemd-run --user` unit whether it
   works. Tests: `test_old_polkit_gets_the_grant_as_a_pkla_file_too` and three
   more.
4. **Python 3.9.** `Progress = Callable[[str, str, float | None], None]` in
   `mfruitos/updater/installer.py` is evaluated at import and needs Python
   3.10; `check.sh`'s 3.9 step only parsed syntax. Fix: `Optional[float]`;
   `check.sh` now rejects `X | Y` unions evaluated at run time (negative
   control: it flags the old line). With Pillow 9.0.1 (a venv on Debian 11)
   the whole suite passes on Python 3.9.2: 670 tests.
5. **Pillow 8.1 accepted.** Debian 11 / Raspberry Pi OS Bullseye ship Pillow
   8.1.2, which lacks `rounded_rectangle`; the installer accepted it and failed
   only at the self-test. Fix: the installer and `setup-device.sh` require
   Pillow 9.0 and say why. Test:
   `test_a_pillow_older_than_9_stops_before_anything_is_copied`.
6. **A failed first install claimed a restore.** `readlink -f` answers for a
   missing `system/current` when its folder exists, so `PREVIOUS` was set on a
   first install; a failing self-test then "restored" it, which made
   `system/current` a link to itself (`ln -sfn` of its own path; the
   negative control showed the false "previous version restored"). Fix: only
   an existing link counts; a failed first install removes the link. Test:
   `test_a_failed_first_install_activates_nothing_and_claims_no_restore`.
7. **32-bit system on a 64-bit kernel.** Phone Wi-Fi setup chose the build
   from `platform.machine()` (the kernel), which reports aarch64 under a
   32-bit Raspberry Pi OS on a 64-bit kernel; it now uses the userland's word
   size. Test: `test_a_32_bit_system_on_a_64_bit_kernel_gets_the_32_bit_build`.
8. **`config.txt` appends.** Lines were added at the end whatever section the
   file ended in, and without a final newline joined the last line
   (`arm_64bit=1dtparam=spi=on` in the negative control). Stock Raspberry Pi
   OS and Ubuntu files end in `[all]` (Ubuntu's assembled from
   canonical/pi-gadget `classic-22.04` and `24`), so stock images were not
   affected. Fix: `ensure_all_section` (driver, before its own and Whisplay's
   appends) and the same in `setup-radio.sh`. Tests: `RaspberryPiBootConfig`.
9. **`uninstall.sh`** deleted `$OS_HOME/system` and `$OS_HOME/bin` without
   checking; a `WHISPLAY_OS_HOME` set to the home folder would have lost
   `~/bin` (shellcheck SC2115). It now deletes only where mFruit OS code is.
   Test: `test_uninstall_deletes_code_only_where_mfruit_os_code_is`.
10. **RadioConnect:** `codec2.available()` raised `AttributeError` with
    libcodec2 0.9 instead of answering False (the app would fail instead of
    running without voice); and a new test counted the green signal number as
    the in-range light when DejaVu replaced Inter. Tests:
    `tests/test_codec2_load.py`, the narrowed `test_link_status_ui` check.
11. **RadioConnect pairing across privacy channels** failed once on Debian 11
    (`test_radios_on_different_channels_pair_and_end_up_on_one`). The asker
    added the contact and showed Talk before it joined the other radio's
    channel, and the test read the channel in between. The channel is now
    joined first. Negative control: with a 0.2 s delay at that point the old
    order failed 3 of 3 runs, the new one passed 3 of 3.
12. **KI-16** (found while deploying): an app with *Keep running*, or adopted
    after a launcher restart, stayed "running" in the launcher after it
    exited; installs were refused. `_close_app_after_session` skipped those
    apps' clean-up refresh. Fix: watch the process (never stop it), then
    refresh. Tests: `tests/test_app_close_refresh.py`; device check below.
13. **The rehearsal's own expectation** looked for a reboot message the
    installer stopped printing in an earlier change (`verify.sh`).
14. **A new test reached the host's `raspi-config`.** On the Pi Zero
    (Raspberry Pi OS) two `RaspberryPiBootConfig` tests failed: the driver's
    SPI step finds `raspi-config` there and called it (as a normal user it
    refused; the board's `config.txt` was unchanged, dated 2026-10-05). The
    tests now run that step with only the tools it needs on `PATH`.

## Simulated Raspberry Pi on Ubuntu 24.04

Root filesystem as above, a fake device tree (`Raspberry Pi Zero 2 W Rev
1.0`), Ubuntu 24.04's own `config.txt` and `cmdline.txt` (canonical/pi-gadget
branch `24`), `uname -r` reporting `6.8.0-1065-raspi`, and
`tests/fresh_install/fakes` for systemd and udev. `SYSROOT=/fakeroot bash
drivers/whisplay/install.sh --user piuser --restart-later`, as root:

- packages from Ubuntu's archive, including `linux-headers-6.8.0-1065-raspi`;
- `[*] kernel 6.8.0-1065-raspi: building with -Dasoc_substream_to_rtd=...`,
  all 8 sound card steps, `snd-soc-whisplay-soundcard.ko` with vermagic
  `6.8.0-1065-raspi`, `whisplay-soundcard.dtbo` in `/boot/firmware/overlays`,
  `dtparam=i2s=on` and `dtoverlay=whisplay-soundcard` in the final `[all]`
  section, `/etc/asound.conf`;
- `whisplay-daemon.service` with `SupplementaryGroups=audio video i2c input dialout`;
- status: reboot required, no audio failure.

The single mapped uid made some package scripts fail (dbus's
`dpkg-statoverride` hands a file to `messagebus`); for the second run
`messagebus` was given uid and gid 0 in that root and `dpkg --configure -a`
run. That is the environment, not the installer.

## Netplan (Ubuntu Server)

`netplan generate --root-dir` on Ubuntu 22.04 with a cloud-init style Wi-Fi
configuration writes `ENV{NM_UNMANAGED}="1"` for `wlan0` ("on NetworkManager
deny-list"): installing NetworkManager does not take Wi-Fi from
systemd-networkd, so SSH over Wi-Fi stays up, but Settings → Wi-Fi cannot use
the interface. With an extra file setting `renderer: NetworkManager`, the same
command writes `netplan-wlan0-HomeWifi.nmconnection` with the same network and
marks `wlan0` managed. The installer does not change the network stack; it
detects the case and prints those steps
([Installation](../../platform/INSTALLATION.md#ubuntu-server-wi-fi-and-netplan)).

## Files-only installs

`bash scripts/install.sh --no-service --yes`, twice, as the normal user:

| System | Result |
|---|---|
| Ubuntu 22.04 | both runs passed; 2 versions kept; self-test OK (46 screens); sugar-wifi-conf 2.2.3 |
| Ubuntu 24.04 | both runs passed; 2 kept; self-test OK; sugar-wifi-conf 2.3.0 |
| Debian 12 | both runs passed; 2 kept; self-test OK; sugar-wifi-conf 2.2.3 |
| Debian 13 | both runs passed; 2 kept; self-test OK; sugar-wifi-conf 2.3.0 |
| Debian 11 | stops at once: "Pillow 9.0 or newer is required; this system has 8.1.2"; nothing installed |

Each installed sugar-wifi-conf binary ran (`--help`, exit 0) on its system.

## 32-bit system on a 64-bit kernel

Docker Hub's debian trixie `arm/v7` image runs natively on this host (it
executes 32-bit ARM code); inside it `uname -m` says `aarch64` while Python is
32-bit, as with 32-bit Raspberry Pi OS on a Pi Zero 2 W. The old phone setup
choice there was `sugar-wifi-conf-aarch64`, which cannot start ("required file
not found": no 64-bit loader); the fixed one installed
`sugar-wifi-conf-armv7` 2.3.0, which runs.

## Orange Pi: fresh offline install in a container

On the Orange Pi Zero 2W (Ubuntu 22.04, Docker 27.0.3):
`scripts/make-offline-pack.sh` (212 MB, changes nothing on the board), then
`tests/fresh_install/rehearse.sh <pack> --suite`: a fresh `ubuntu:22.04`
container, no network, `bash scripts/install.sh --yes` with sudo, then
`tests/fresh_install/verify.sh` and the real-daemon tests against the
installed driver. Second run (with this record's checks added): install exit
0, 55 checks passed and none failed (polkit 0.105 got the `.pkla`; all three
units name only existing groups; the sound card module built for
6.1.31-sun50iw9), `test_background_ui`, `test_launch_lifecycle`,
`test_daemon_unregister`, `test_dc_park` OK. The first run's only failure was
the stale reboot-message expectation (13). No containers were left; the
`ubuntu:22.04` image stays in the board's Docker.

## Boards

Read-only and suite checks from a copy of this tree, then a files-only
install (`scripts/deploy.sh <host> --no-service`, backups first in
`~/mfruit-backups/20261010-2350-before-distro-fixes/` and
`~/mfruit-backups/20261010-2400-before-distro-fixes/`) and a launcher restart
through the existing sudoers rule. The system part of the installer (sudo) was
not run on either board.

| Board | Checks |
|---|---|
| Orange Pi Zero 2W, Ubuntu 22.04, Python 3.10.12, Pillow 9.0.1 | `setup-device.sh --check` passes (new Pillow check, Wi-Fi: NetworkManager manages it and allows session-less scans); the full suite 674 tests OK; build `1.4.0-local20261010235849` installed, self-test OK |
| Raspberry Pi Zero 2 W, Raspberry Pi OS Trixie (6.18.50+rpt), Python 3.13.5, Pillow 11.1.0 | `setup-device.sh --check` passes (`make`/`gcc` present; only `i2c-tools` optional missing); the full suite 674 tests with 2 failures (14, fixed; the 22 driver installer tests then passed there); build `1.4.0-local20261010235737` installed, self-test OK |

KI-16 on both boards (`tests/device/keep_running_exit.py`: launch RadioConnect, which has *Keep
running* on, ask it to exit through the daemon, time mFruit OS's listing):

| Board | Adopted after a launcher restart | Launched by mFruit OS |
|---|---|---|
| Pi Zero 2 W | listed not running after 1.0 s | after 1.0 s |
| Orange Pi | after 1.1 s | after 0.8 s |

Both logged `APP_LEFT ... process=exited`; before the fix the flag stayed
`true` until `mfruitctl reload`. RadioConnect was opened again afterwards on
both boards, as it was before. Neither board has pytest, so RadioConnect's
suite ran in the roots with the same Python and Pillow.

The Pi Zero's PiSugar did not appear on I2C bus 1 during this work (nothing
answered a read-only scan after its 17:04 boot), so the charging judgement of
the earlier record is still not checked on a board.

## Results after the fixes

The last full run, 2026-10-11 00:00 to 01:00, on the final source (only
documentation and `tests/distro/run.sh` changed during it), as the normal user:

| System | mFruit OS `check.sh` | RadioConnect suite |
|---|---|---|
| Ubuntu 22.04 | all checks passed, 681 tests | 716 passed |
| Ubuntu 24.04 | all checks passed, 681 | 716 passed |
| Debian 12 | all checks passed, 681 | 716 passed |
| Debian 13 | all checks passed, 681 | 716 passed |
| Debian 13 armhf (32-bit) | all checks passed, 681 | 715 passed, 1 failed (15, a test race; fixed); after the fix 716 passed in 3 of 3 runs |
| Debian 11, Python 3.9.2 with Pillow 9.0.1 | all checks passed, 681 | 711 passed, 5 skipped (no usable codec2: 0.9) |

The dev machine's own `check.sh`: all checks passed, 681 tests.

15. **A RadioConnect test raced its receive threads.**
    `test_radios_on_the_same_other_channel_hear_each_other` checked Bob's
    counter the moment Carol had the message; each radio handles a packet on
    its own thread, and under load Bob had not yet. With Bob slowed by 0.3 s
    the old check failed and the new one passed. Fix: `wait_for` the counter
    (bounded) in that test and in three others that slept a fixed 0.3 or
    0.6 s before checking another radio's counter.

## Not verified

- Anything on a Raspberry Pi running Ubuntu (KI-17): module loading, the
  codec, the LCD and button through `dialout`, the daemon starting, Bluetooth,
  Wi-Fi after the netplan hand-over.
- The installer's system part (sudo, systemd, polkit, NetworkManager) on any
  real board after these changes: neither board has been reinstalled.
- A 32-bit system on a board (only in a container).
