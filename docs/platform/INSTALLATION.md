# Installing MFruit OS

This is the canonical guide for preparing a board, installing, verifying,
updating, rolling back and removing MFruit OS. Failures are diagnosed with
[Troubleshooting](../quality/TROUBLESHOOTING.md); physical checks are in
[Validation](../quality/VALIDATION.md).

The installer follows **check → install → verify → start → health check**
([Part I §14](DEVELOPMENT_RULES.md#14-installation-architecture)). On a
supported board it also installs the bundled
[Whisplay driver](../WHISPLAY_DRIVER.md) (SPI/I2C/I2S, sound card,
`whisplay-daemon`); no separate Whisplay checkout or installer is needed.

## Requirements

| | |
|---|---|
| Board | Raspberry Pi Zero 2 W (primary target), Orange Pi Zero 2W; the driver also supports Orange Pi Zero 3W, Radxa ZERO 3W and Radxa Cubie A7Z (not validated with MFruit OS) |
| HAT | PiSugar Whisplay |
| OS | Raspberry Pi OS / Debian 12+, Ubuntu 22.04+ (systemd) |
| Python | 3.9 or newer |
| Hardware service | installed by MFruit OS: [Whisplay driver](../WHISPLAY_DRIVER.md) (`whisplay-daemon.service` runs as your normal user) |
| Network | needed on the first install for missing packages and the sound card build (kernel headers), unless an [offline pack](../WHISPLAY_DRIVER.md#offline-installation) is next to the code |
| Packages | Pillow (`python3-pil`), Python venv support (`python3-venv`), NetworkManager for Wi-Fi. Optional: `git` (updates for git-installed apps), `alsa-utils` (speaker test) |

Catalogue apps install their own dependencies into package-local
environments. The launcher needs no NumPy, web server or desktop stack.

## 1. Prepare the board

1. Install the board's official systemd-based image (Raspberry Pi OS; Orange
   Pi OS with Linux `6.1.31-sun50iw9` for the Zero 2W, Debian 1.0.2 or Ubuntu 22.04), enable SSH and
   use a normal user with sudo. Fit the Whisplay HAT.
2. Stop standalone app services that would compete for the display.
3. Log in as that user. The Whisplay driver is installed by MFruit OS in
   step 5; its own read-only check is
   `bash drivers/whisplay/install.sh --check` ([Whisplay driver](../WHISPLAY_DRIVER.md)).

A device prepared earlier with a PiSugar/Whisplay checkout needs nothing
extra: the next install moves `whisplay-daemon` to the bundled driver and
leaves the checkout in place.

Do not run the MFruit OS installer as root.

## 2. Get the source onto the device

Without internet on the board, copy the code and an offline pack onto the
SD card or a USB stick instead ([Offline installation](../WHISPLAY_DRIVER.md#offline-installation)).

For a published version:

```bash
git clone https://github.com/Mengkungkao/MFruitOS.git ~/MFruitOS
cd ~/MFruitOS
git log -1 --oneline
```

To test an unpublished development checkout, copy it into a separate
candidate directory (this deletes nothing on the device):

```bash
cd ~/MFruitOS
device_host=your-user@your-device-address
rsync -a --exclude=.git --exclude=__pycache__ --exclude='*.pyc' \
  --exclude=.pytest_cache ./ "$device_host:~/MFruitOS-candidate/"
```

`scripts/deploy.sh user@host` combines copy, install and restart for
development. Record the source commit and local changes with your results.

## 3. Preserve an existing installation

On a configured device, finish active updates and return to Home, then save
the current state:

```bash
backup_path="$HOME/mfruit-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_path" && chmod 700 "$backup_path"
[ -d "$HOME/.whisplay-os" ] && tar -C "$HOME" -czf "$backup_path/whisplay-os.tar.gz" .whisplay-os
systemctl cat whisplay-daemon.service > "$backup_path/daemon-service.txt"
readlink -f "$HOME/.whisplay-os/system/current"
```

The archive covers managed apps, settings, logs and data under the default
MFruit OS home. Data in companion app checkouts and a custom
`WHISPLAY_OS_HOME` must be preserved separately. Stop an app before backing up
data it is actively changing.

## 4. Check

```bash
bash scripts/setup-device.sh --check
```

Read-only: verifies Linux, a normal user, Python/Pillow, the source and
manifest version and systemd, reports the Whisplay driver's state, and, when
`whisplay-daemon` is installed, its user and a `health.ping` through
`/tmp/whisplay-daemon.sock`. It exits non-zero naming the failed prerequisite
and installs nothing.

## 5. Install

```bash
bash scripts/install.sh            # or: bash scripts/setup-device.sh --install
```

| Option | Effect |
|---|---|
| `--no-service` | install files only (no driver, no systemd changes); start manually with `PYTHONPATH=~/.whisplay-os/system/current python3 -m mfruitos` |
| `--no-driver` | do not install or update the Whisplay driver |
| `--reboot` | reboot without asking when the driver needs it (otherwise it asks; with `--yes` it only says so) |
| `--no-background-daemon` | keep whisplay-daemon's own desktop visible between apps |
| `--dev` | run directly from the checkout (development; keep the directory in place) |
| `--yes` | non-interactive; does not bypass sudo authorization |

What the installer does, in order:

1. Checks the OS, Python, Pillow and venv support; missing Pillow/venv
   packages are installed with `apt-get` before any file is copied.
   Then runs `sudo bash drivers/whisplay/install.sh` on a supported board
   ([what it changes](../WHISPLAY_DRIVER.md#how-mfruit-os-sets-it-up-and-starts-it)).
2. Copies the code to `~/.whisplay-os/system/versions/<version>-local<date>`
   and points `system/current` at it; the previous version is recorded for
   rollback.
3. Creates `~/.whisplay-os/{config,apps,cache,logs,state,bin,inbox,…}` and a
   default `config/settings.json`; an existing settings file is kept.
4. Installs `mfruit-run`, `mfruitctl` and `boot-guard.sh` into
   `~/.whisplay-os/bin` and runs the offline self-test.
5. Provisions bundled ConnectWifi when no Wi-Fi app exists; a first install
   seeds the Apps menu with available starter games, Fruit Store and
   Settings. Reruns preserve existing apps, settings, order and launch policy.
6. With the service: the system changes listed below, then enables and starts
   `whisplay-os.service`. When the driver enabled a bus or the sound card, the
   services are only enabled and the installer asks to reboot; after the
   reboot everything starts by itself.

### System changes and why they are needed

| Change | Why | Removed by `uninstall.sh` |
|---|---|---|
| `apt-get install python3-pil python3-venv network-manager` when missing | launcher rendering, package-local app environments, Wi-Fi settings | no (shared system packages) |
| Whisplay driver: packages, boot overlays, sound card module and ALSA config, Orange Pi `gpio` udev rule, `/etc/sudoers.d/whisplay-daemon-power`, `/usr/local/share/whisplay`, `whisplay-daemon.service` ([details](../WHISPLAY_DRIVER.md#where-it-lives)) | the display, button, LED and audio | no; `sudo bash drivers/whisplay/uninstall.sh [--audio]` |
| `/etc/systemd/system/whisplay-os.service` | runs the launcher as your user after the daemon, with `Restart=always`, a 60 s watchdog, `ExecStartPre=boot-guard.sh`, `ExecStopPost=mfruitctl release` | yes |
| `/etc/systemd/system/whisplay-daemon.service.d/mfruit-os.conf` (skipped with `--no-background-daemon`) | starts the daemon through `whisplay-daemon-mfruit.py` so its own UI stays in the background ([Host API](HOST_API.md#whisplay-user-interface-in-the-background)); the daemon restarts once, closing running apps | yes |
| `/etc/sudoers.d/whisplay-os` | allows exactly `systemctl restart whisplay-daemon.service` and `systemctl restart whisplay-os.service` without a password (*Restart daemon* on the fallback screen), validated with `visudo -c` | yes |
| `/etc/polkit-1/rules.d/49-mfruit-wifi.rules` | grants the target user the listed NetworkManager scan/control/settings actions, because the service has no interactive polkit session | yes |
| `/usr/local/bin/mfruitctl` symlink | `mfruitctl` on the PATH | yes |

No other system files are changed by MFruit OS itself. Adopted daemon app registrations are
changed only through the daemon's `app.register` API and are restored on
uninstall ([Lifecycle](LIFECYCLE.md#launch-gate-and-intruder-eviction)).

## 6. Verify and health check

```bash
systemctl is-active whisplay-daemon.service whisplay-os.service
mfruitctl status
mfruitctl apps
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --self-test
mfruitctl screenshot /tmp/mfruit-home.png
journalctl -u whisplay-os.service -n 80 --no-pager
```

Expect both services active, the launcher at Home and the self-test passing.
Screenshots and previews show MFruit OS's rendering; they do not verify the
physical LCD ([Validation](../quality/VALIDATION.md)). At Home, `mfruitctl key
down`, `mfruitctl key enter` and `mfruitctl back` exercise navigation over SSH;
they do not validate physical input.

## The service

```text
whisplay-daemon.service  →  whisplay-os.service  →  MFruit OS  →  apps
```

```bash
systemctl status whisplay-os
journalctl -u whisplay-os -f
tail -f ~/.whisplay-os/logs/launcher.log
```

To run the launcher interactively, stop the service first, keep the daemon
running, and restore the service afterwards:

```bash
sudo systemctl stop whisplay-os.service
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --debug   # Ctrl-C to stop
sudo systemctl start whisplay-os.service
```

## Updating MFruit OS

- **On the device:** *Settings → General → Software Update* (or *Fruit Store →
  Updates → MFruit OS*) installs a published GitHub release and restarts.
  **Versions** selects a release; **Roll back** restores the saved local build.
- **From a checkout:** `bash scripts/update.sh` (fast-forward `git pull`, then
  reinstall). For a copied checkout, transfer the candidate again and repeat
  steps 4–6.

A system update runs the new version's self-test before activation, keeps the
previous version, and arms the boot guard: if the new version fails to start
three times, `boot-guard.sh` (plain `sh`) switches `system/current` back and
the launcher reports the rollback. A healthy start is confirmed after 15 s.
Update the OS and all keyboard apps together so their SDK and key-hub
contract match ([SDK](../apps/SDK.md)). MFruit OS has no published releases at
the time of writing, so on-device version selection has nothing to offer yet.

### Manual rollback of a checkout installation

```bash
readlink -f ~/.whisplay-os/system/current
ls -1 ~/.whisplay-os/system/versions
```

Choose a retained directory recorded as good in your validation notes (not
merely the oldest) and run its `scripts/install.sh` as the same user; this
reinstalls its helpers and service wrapper with its code.

## Uninstalling and recovery

```bash
bash scripts/uninstall.sh          # remove service and code; keep apps, settings, logs
bash scripts/uninstall.sh --purge  # also delete ~/.whisplay-os (apps, data, logs)
```

The uninstaller removes the files listed above, restores adopted app
registrations and the daemon desktop. The Whisplay driver (`whisplay-daemon`)
and apps registered directly with it are never removed; the driver has its own
`drivers/whisplay/uninstall.sh`. Use `--purge` only when managed apps and
their data are intentionally being discarded.

## Radio setup (LoRa apps)

Radio apps such as RadioConnect need the Waveshare SX126X LoRa HAT set
up once per device ([ADR 0007](ADR/0007-shared-radio-capability.md)). Remove
the HAT's M0/M1 jumpers first (those pins are also the Whisplay LCD's). Then,
over SSH as your normal user:

```bash
bash ~/.whisplay-os/system/current/scripts/setup-radio.sh --check   # report only
bash ~/.whisplay-os/system/current/scripts/setup-radio.sh           # asks before each change
```

Options: `--band au915|eu868|us915` (default `au915`, 920 MHz), `--frequency`,
`--air-speed` (default 2400), `--yes`. Use a band that is legal where you
are, and the same band, frequency and air rate on every radio.

| Change | Why | Undo |
|---|---|---|
| `apt-get install python3-serial python3-cryptography python3-numpy python3-yaml alsa-utils gpiod python3-libgpiod libcodec2-*` | serial port, encryption, voice codec, mode pins | shared system packages; remove by hand if unwanted |
| Raspberry Pi: `enable_uart=1` in `config.txt`; serial console removed from `cmdline.txt` (backups `*.mfruit.bak`); `serial-getty@ttyS0` disabled | the HAT talks on `/dev/ttyS0`; a console there corrupts packets | restore the `.mfruit.bak` files |
| Orange Pi: `console=` (and `extraargs`) in `orangepiEnv.txt`/`armbianEnv.txt` (backup `*.mfruit.bak`); `serial-getty@ttyS0` masked | same | restore the backup, `systemctl unmask serial-getty@ttyS0` |
| user added to `dialout` | apps open the serial port | `sudo gpasswd -d $USER dialout` |
| module registers written (persistent): band frequency, air rate, power | every radio must match | run the setup again with other values |
| `~/.whisplay-os/shared/radio/radio.json` | the settings every radio app reads | written again by the next setup |

UART and console changes need a reboot; the script stops, asks to reboot, and
continues provisioning when run again. Provisioning stops whisplay-daemon for
a few seconds (closing an open app). Afterwards the launcher is restarted
unless an install job is running. `mfruitctl catalog` then shows the radio
apps without missing requirements.

## Upgrade notes

**1.4.0:** update all keyboard apps to SDK 1.2.0 before restarting MFruit OS.
The launcher grabs keyboards exclusively; older direct-input apps otherwise
receive no keys. Reinstall so the updated daemon wrapper is used, which
forwards keyboard input to the daemon's Volume, Power and Wi-Fi pages.
