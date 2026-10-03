# Whisplay driver

MFruit OS includes the driver for the PiSugar Whisplay HAT. A fresh
installation no longer needs a separate `git clone` of
[PiSugar/Whisplay](https://github.com/PiSugar/Whisplay) or its installers:
`bash scripts/install.sh` sets up the driver on a supported board. Decision
record: [ADR 0008](platform/ADR/0008-bundled-whisplay-driver.md).

```text
MFruit OS ──► MFruit OS Whisplay driver (drivers/whisplay) ──► Whisplay HAT
              whisplay-daemon + runtime + sound card
```

## What the driver does

| Part | Function |
|---|---|
| `runtime/whisplay.py` (`WhisplayBoard`) | Detects the board, maps the 40-pin header to GPIO lines, initialises the ST7789 LCD (240 × 280, RGB565) over SPI and draws frames, drives the backlight and RGB LED (software PWM), reads the button |
| `daemon/` (`whisplay-daemon`) | Owns the hardware for everyone: LCD, backlight, LED, button, foreground app and shared framebuffer; app registry and socket API `/tmp/whisplay-daemon.sock`; WiFi, Bluetooth, Volume and Power pages; USB/Bluetooth keyboard reader; PiSugar integration ([Host API](platform/HOST_API.md)) |
| `runtime/whisplay_client.py` | Client library that daemon apps use for frames, button and LED |
| `audio/whisplay-soundcard/` | `snd-soc-whisplay-soundcard` kernel module for the WM8960 or ES8389 codec, device-tree overlays per board, ALSA card `whisplaysound`, boot volume service |
| `install.sh`, `uninstall.sh` | MFruit OS code: board detection, buses, packages, sound card build, device access, systemd unit, update, rollback and removal |

These files are copied unmodified from Whisplay commit `c73051e`, and
`scripts/check.sh` verifies them against checksums. MFruit OS's own changes
to daemon behaviour stay in `scripts/whisplay-daemon-mfruit.py`. What was
copied, what was left out (the demo apps, Whisplay's image builder, docs) and
the licences: [drivers/whisplay/UPSTREAM.md](../drivers/whisplay/UPSTREAM.md).

| Whisplay component | Before | MFruit OS now |
|---|---|---|
| Display (ST7789 over SPI) | `~/Whisplay/runtime/whisplay.py` | `/usr/local/share/whisplay/runtime/whisplay.py` (same code) |
| SPI | `raspi-config do_spi` / Orange Pi `spi1-cs0-spidev` overlay by Whisplay's installer | `drivers/whisplay/install.sh` (same settings) |
| GPIO (DC, reset, backlight, LED, button) | Whisplay runtime via libgpiod | same runtime, same pins |
| Audio and microphone | Whisplay sound card installer | the same installer, run by `drivers/whisplay/install.sh` |
| Button | daemon from `~/Whisplay` | daemon from `/usr/local/share/whisplay` |
| LED and backlight | daemon from `~/Whisplay` | daemon from `/usr/local/share/whisplay` |
| Device tree | Whisplay installers (I2C, I2S, SPI, sound card overlay) | `drivers/whisplay/install.sh` (same overlays) |
| Startup | `whisplay-daemon.service` written by Whisplay | `whisplay-daemon.service` written by MFruit OS (same settings) |
| Shutdown | daemon's Power page (sudoers rule from Whisplay) | same page, same sudoers rule from MFruit OS |

## Where it lives

| What | Where |
|---|---|
| Source in this repository | [`drivers/whisplay/`](../drivers/whisplay/) |
| Runtime and daemon on the device | `/usr/local/share/whisplay/` (root-owned; `MFRUIT_DRIVER` records the version; `/usr/local/share/whisplay.previous` is the copy before the last update) |
| Service | `/etc/systemd/system/whisplay-daemon.service`; MFruit OS's drop-in `whisplay-daemon.service.d/mfruit-os.conf` starts it through `whisplay-daemon-mfruit.py` |
| Kernel module | `/lib/modules/$(uname -r)/kernel/sound/soc/codecs/snd-soc-whisplay-soundcard.ko` |
| Overlays | Raspberry Pi: `/boot/firmware/overlays/whisplay-soundcard.dtbo` and `config.txt`; Orange Pi: `/boot/overlay-user/` and `/boot/orangepiEnv.txt`; Radxa: `/boot/dtbo/` |
| ALSA configuration | `/etc/asound.conf` (`whisplaysound`); `whisplay-soundcard-warmup.service` sets speaker and mic to 80 at boot |
| Daemon settings and app registrations (user data, never overwritten) | `~/.whisplay-daemon/` |
| Replaced service unit | `/var/backups/mfruitos/whisplay-daemon.service.<time>` |

## How MFruit OS sets it up and starts it

`scripts/install.sh` runs `sudo bash drivers/whisplay/install.sh --user <you>`
unless `--no-driver` or `--no-service` is given. It needs no internet when the
packages are present or an [offline pack](#offline-installation) is next to the
code. The driver installer:

1. detects the board (Raspberry Pi, Orange Pi Zero 2W or Zero 3W, Radxa ZERO
   3W, Radxa Cubie A7Z); on any other board it changes nothing and MFruit OS
   carries on without it;
2. installs missing packages: `python3-spidev`, `python3-libgpiod`,
   `python3-pil`, `alsa-utils` and `fonts-dejavu-core` (the daemon's pages
   need the font: with Pillow before 9.2 they crash without it), and when
   available `python3-numpy`, `python3-smbus`, `i2c-tools`, `bluez`,
   `python3-dbus` and `python3-gi` (Bluetooth page and pairing);
3. enables the LCD's SPI bus and the codec's I2C/I2S buses;
4. builds and installs the sound card driver, unless it is already installed
   for the running kernel (`--rebuild-audio` forces a rebuild); if that fails
   (no internet, no matching pack), the rest still installs and the problem
   is reported;
5. on Orange Pi, gives the `gpio` group access to the GPIO and SPI devices;
6. allows the daemon's Power page to run `systemctl poweroff` and `reboot`;
7. copies the runtime and daemon to `/usr/local/share/whisplay` through a
   staged, compiled copy, and keeps the previous copy;
8. writes and enables `whisplay-daemon.service`, keeping existing daemon
   settings.

When steps 3 to 5 changed something, both services are enabled and the
installer asks "Reboot now?" (`--reboot` reboots without asking; with `--yes`
it only says so). At every boot the kernel loads the overlays and
the sound card. systemd then starts `whisplay-daemon`, whose `WhisplayBoard()`
resets and initialises the LCD, LED and button, and then `whisplay-os` (MFruit
OS, `After=whisplay-daemon`).

**Existing installations** that used `~/Whisplay` change over on the next
`scripts/install.sh`. The sound card is kept (same driver source), the service
moves to `/usr/local/share/whisplay`, and `~/Whisplay` itself is not touched.
Apps registered from it, such as Whisplay's games, keep working while it
exists. New installations no longer get Whisplay's demo games.

## Offline installation

The MFruit OS code, including this driver, is complete in the repository. Two
things cannot be: Debian packages that a fresh image lacks, and the kernel
headers and build tools for the sound card module, which is built for the
board's own kernel. An **offline pack** carries both, so a board installs
with no internet:

1. Once per OS image, on a board **with** internet running that image
   (flash it, `sudo apt-get update`, do not upgrade the kernel):

   ```bash
   bash scripts/make-offline-pack.sh --archive
   ```

   This writes `offline/<board>-<os>-<release>-<arch>/` (about 200 MB: the
   packages with all their dependencies as a local apt repository, and the
   files the sound card build downloads) and the same as a `.tar.gz`. It
   installs nothing. Keep the `.tar.gz`, for example as an asset of a GitHub
   release of your MFruitOS repository (`offline/` is not committed).
2. For each offline board: download the MFruitOS code (GitHub *Download ZIP*
   or a release), put it on the SD card or a USB stick, and unpack the pack
   into `MFruitOS/offline/`. On a Raspberry Pi the FAT boot partition is
   writable from any computer: copy `MFruitOS` there, then on the board run
   `cp -r /boot/firmware/MFruitOS ~/`.
3. On the board: `cd ~/MFruitOS && bash scripts/install.sh`. It reports
   `offline pack: …` and installs packages and builds the sound card from the
   pack, then asks for the reboot as usual.

A pack is used only on the same board type, OS release and architecture. apt
installs from it only what the board lacks or has in an older version. The
sound card is built for the kernel the pack was made on: on a Raspberry Pi
running another kernel, everything else installs and the sound card is
skipped with a warning (Orange Pi Zero 2W packs use Whisplay's pinned
`6.1.31-sun50iw9` headers). Without a pack and without internet, the
installation still finishes when the image already has the packages; only
the sound card waits for a later run with internet or a pack.

## Hardware interfaces

| Signal | Header pin | Raspberry Pi | Orange Pi Zero 2W |
|---|---|---|---|
| LCD SPI | 19, 21, 23, 24 | `/dev/spidev0.0`, 100 MHz | `/dev/spidev1.0`, 48 MHz |
| LCD data/command | 13 | BCM 27 | PH3 |
| LCD reset | 7 | BCM 4 | PI13 |
| Backlight (low = on) | 15 | BCM 22 | PI5 |
| RGB LED red, green, blue (low = on) | 22, 18, 16 | BCM 25, 24, 23 | PI6, PH4, PI14 |
| Button (high = pressed) | 11 | BCM 17 | PH2 |
| Codec I2C (WM8960 `0x1a` or ES8389 `0x10`) | 3, 5 | I2C1 | I2C1 (`/dev/i2c-2`) |
| Codec I2S | 12, 35, 38, 40 | I2S | I2S0 |

Orange Pi Zero 3W and the Radxa boards use the same header pins on their own
chips (`runtime/whisplay.py`). Orange Pi Zero 3W and Radxa Cubie A7Z need
Whisplay V2 hardware.

## How to test

A whole fresh installation, offline, in a disposable container on an arm64
Docker host such as the board itself:
`bash tests/fresh_install/rehearse.sh offline/<pack> --suite`
([Testing](quality/TESTING.md#fresh-install-rehearsal)).

Without hardware (CI does the same): `bash scripts/check.sh`. It verifies the
copied files against their checksums and runs Whisplay's daemon unit tests,
`tests/test_whisplay_driver.py` (what the driver sends over SPI and GPIO on Pi
and Orange Pi, with both libgpiod APIs),
`tests/test_whisplay_driver_install.py` (board detection, boot configuration,
staged copy), and the real-daemon tests against the bundled daemon.

On the device:

```bash
bash drivers/whisplay/install.sh --check       # read-only: packages, SPI, sound card, files, service
systemctl status whisplay-daemon --no-pager
aplay -l | grep -i whisplay
amixer -c whisplaysound cget name='speaker'
speaker-test -D whisplaysound -c 2 -t sine -l 1
arecord -D whisplaysound -f S16_LE -r 48000 -c 2 -d 3 /tmp/mic.wav && aplay -D whisplaysound /tmp/mic.wav
```

Then use **Settings > General > Diagnostics** (display, button, LED and speaker tests)
and the hardware checklist in [Validation](quality/VALIDATION.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Black screen after installing | `--check`: was a reboot requested? Then `journalctl -u whisplay-daemon -n 80` |
| `whisplay-daemon` restarts, `/dev/spidev*` missing | SPI not enabled or no reboot yet: run `sudo bash drivers/whisplay/install.sh --user $USER` again, then reboot |
| No sound, `whisplaysound` missing in `aplay -l` | after a kernel upgrade the module must be rebuilt: rerun `scripts/install.sh` (it rebuilds for the new kernel); `dmesg \| grep -i -e wm8960 -e es8389 -e whisplay` |
| Permission denied on GPIO/SPI (Orange Pi) | log out and in, or reboot, after being added to the `gpio` group |
| `offline pack:` is not shown | the pack must be in `MFruitOS/offline/<name>/` with its `pack.env`, for this board, OS release (`/etc/os-release`) and `dpkg --print-architecture` |
| Offline: "not in the offline pack" | the pack was made for another image or kernel; make one on a board running this image |
| A driver update misbehaves | `sudo bash drivers/whisplay/install.sh --rollback` restores `/usr/local/share/whisplay.previous` |

More: [Troubleshooting](quality/TROUBLESHOOTING.md).

## Update and removal

The driver changes only when `scripts/install.sh` (or `scripts/update.sh`)
runs. The in-app system update updates the launcher only, because it runs
without root. To use a newer Whisplay commit, a developer runs
`scripts/whisplay-driver-sync.sh` ([UPSTREAM.md](../drivers/whisplay/UPSTREAM.md)).
To remove the driver, run `sudo bash drivers/whisplay/uninstall.sh` (add
`--audio` to also remove the sound card). Daemon settings and app
registrations are kept.
