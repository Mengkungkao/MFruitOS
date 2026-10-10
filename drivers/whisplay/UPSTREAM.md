# Upstream source of the Whisplay driver files

Source: <https://github.com/PiSugar/Whisplay>
Commit: `c73051e64dc62aced1853d16f33d4614fec5bee4` (2026-10-01, "Use PiSugar 3 power button for daemon home")

The files below are copied **unmodified**; `upstream.sha256` records their
checksums and `scripts/check.sh` verifies them. mFruit OS's own changes to
daemon behaviour live in `scripts/whisplay-daemon-mfruit.py`, never in these
files. `install.sh` and `uninstall.sh` in this directory are mFruit OS code
that replaces Whisplay's installers. How the driver works:
[docs/WHISPLAY_DRIVER.md](../../docs/WHISPLAY_DRIVER.md).

## Licences

- The Whisplay repository is licensed under the Apache License 2.0
  ([LICENSE](LICENSE), copied from upstream).
- The sound card kernel sources under `audio/whisplay-soundcard/src/` carry
  their own `SPDX-License-Identifier: GPL-2.0-only` (or `GPL-2.0`) headers and
  remain under that licence; `src/vendor/linux-6.6/` holds Linux 6.6 build
  inputs (see its README). They are built into a separate kernel module and
  are not linked with mFruit OS (MIT).

## What was taken, and why

| Upstream path | What it does | Why mFruit OS needs it |
|---|---|---|
| `runtime/whisplay.py` | `WhisplayBoard`: board detection, 40-pin → gpiochip line maps, ST7789 LCD init and drawing over SPI, backlight and RGB LED (software PWM), button polling | the hardware driver used by the daemon and by the launcher's recovery display |
| `runtime/whisplay_client.py` | client library for apps talking to the daemon (frames, button, LED) | existing apps (RadioConnect, the crypto dashboard, Messenger, WalkieTalkie) import it from `/usr/local/share/whisplay/runtime` |
| `daemon/*.py`, `daemon/internal_apps/*.py`, `daemon/img/wifi-*.png` | `whisplay-daemon`: owns the LCD, backlight, LED, button and focus; app registry and socket API; WiFi, Bluetooth, Volume and Power pages; keyboard reader; PiSugar integration | the hardware service mFruit OS runs on ([Host API](../../docs/platform/HOST_API.md)) |
| `daemon/tests/*.py` | upstream unit tests for the daemon | run by `scripts/check.sh` against this copy |
| `audio/whisplay-soundcard/src/` | `snd-soc-whisplay-soundcard` kernel module (WM8960 and ES8389 codecs), Makefile, DT overlays for each board, Linux 6.6 build inputs for the Orange Pi Zero 3W | speaker and microphone |
| `audio/whisplay-soundcard/configs/asound*.conf` | ALSA configuration naming the card `whisplaysound` | default audio device for apps |
| `audio/whisplay-soundcard/scripts/install.sh` | builds and installs the module and overlay, enables I2C/I2S, ALSA config, boot volume service | run by `install.sh` (board-specific kernel header handling) |
| `audio/whisplay-soundcard/scripts/uninstall.sh`, `recover-a7z-i2c.sh` | removes the sound card; Cubie A7Z I2C recovery helper used by the sound installer | removal path; A7Z support |
| `LICENSE` | Apache License 2.0 | licence requirement |

## What was left out, and why

| Upstream path | Reason |
|---|---|
| `install_driver.sh`, `script/install_*.sh` | replaced by `install.sh` (same steps, no prompt, idempotent) |
| `daemon/install_whisplay_daemon_service.sh` | replaced by `install.sh` (keeps existing daemon settings; no demo app registrations; no `ffmpeg`, which only the MP4 demo needs) |
| `daemon/default_apps/` | registrations of the demo apps below |
| `example/` | demo applications (Flappy Bird, Jump, MP4 player) and a hardware test program; applications, not driver |
| `daemon/skills/`, `README*.md`, `APP_INTEGRATION*.md`, `daemon/img/screenshots/` | documentation |
| `packaging/pi-gen/`, `.github/` | Whisplay's own OS image build and CI |
| `audio/WM8960-Audio-HAT.zip` | legacy driver archive, not referenced by any installer |
| `audio/whisplay-soundcard/scripts/kill-stale-audio.sh` | lab and calibration helper |

## Updating to a newer upstream commit

```bash
bash scripts/whisplay-driver-sync.sh /path/to/Whisplay   # copy + new checksums + this commit line
bash scripts/check.sh                                     # includes the real-daemon tests
```

Then review the upstream diff (`git -C /path/to/Whisplay diff <old>..<new>`)
for changes to the left-out installers that `install.sh` must follow, and
record the device validation (docs/quality/VALIDATION.md).
