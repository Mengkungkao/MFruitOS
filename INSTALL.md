# Installing MFruit OS

## Requirements

| | |
|---|---|
| Board | Raspberry Pi Zero 2 W (primary target), Orange Pi Zero 2W, or another board supported by Whisplay |
| HAT | PiSugar Whisplay |
| OS | Raspberry Pi OS / Debian 12+, Ubuntu 22.04+ (systemd) |
| Python | 3.9 or newer |
| Whisplay | [PiSugar/Whisplay](https://github.com/PiSugar/Whisplay) with `whisplay-daemon.service` installed and running |
| Packages | Pillow (`python3-pil`, already required by the daemon). Optional: `git` (updates for git-installed apps), `alsa-utils` (speaker test) |

MFruit OS has no other dependencies: no numpy, no web server, no desktop stack.

## Install

Log in as the user that runs `whisplay-daemon` (not root) and run:

```bash
git clone https://github.com/Mengkungkao/MFruitOS.git
cd MFruitOS
bash scripts/install.sh
```

The installer:

1. checks the OS, Python, Pillow, the Whisplay runtime and `whisplay-daemon`;
2. copies the code to `~/.whisplay-os/system/versions/<version>-local<date>`
   and points `~/.whisplay-os/system/current` at it (the previous version stays
   and is restored if the new one fails its self-test);
3. creates `~/.whisplay-os/{config,apps,cache,logs,state,…}` and a default
   `config/settings.json` (an existing one is kept);
4. installs the helpers `mfruit-run`, `mfruitctl` and `boot-guard.sh` into
   `~/.whisplay-os/bin` and links `/usr/local/bin/mfruitctl`;
5. adds a systemd drop-in, `/etc/systemd/system/whisplay-daemon.service.d/mfruit-os.conf`,
   that starts whisplay-daemon through `~/.whisplay-os/bin/whisplay-daemon-mfruit.py`
   so the daemon's own user interface stays in the background while MFruit OS
   runs (the daemon is restarted once, which closes running apps);
6. adds `/etc/sudoers.d/whisplay-os`, which allows exactly two commands without
   a password: `systemctl restart whisplay-daemon.service` and
   `systemctl restart whisplay-os.service` (used by *Restart daemon* on the
   fallback screen);
7. creates, enables and starts `whisplay-os.service`.

`sudo` is used only for steps 4–7. Options:

| Option | Effect |
|---|---|
| `--no-service` | install files only; start manually with `PYTHONPATH=~/.whisplay-os/system/current python3 -m mfruitos` |
| `--no-background-daemon` | keep whisplay-daemon's own desktop visible between apps |
| `--dev` | run directly from the checkout (for development) |
| `--yes` | non-interactive |

From a development machine you can push a checkout to a device and install it:

```bash
scripts/deploy.sh pi@192.168.0.33
```

## The service

```
whisplay-daemon.service  →  whisplay-os.service  →  MFruit OS  →  apps
```

- `After=`/`Wants=whisplay-daemon.service`; runs as your user, never root.
- `Restart=always` (3 s) and a 60 s systemd watchdog: a hung launcher is restarted.
- `ExecStartPre` runs `boot-guard.sh`: after a system update, if the new version
  fails to start three times, the previous version is re-activated.
- `ExecStopPost` runs `mfruitctl release`: if the launcher died while showing
  its screen, the daemon is asked to take the screen back, so the device never
  stays frozen.

```bash
systemctl status whisplay-os
journalctl -u whisplay-os -f
tail -f ~/.whisplay-os/logs/launcher.log
```

## Updating

- **On the device:** *Settings → System → System update* (or *Updater →
  MFruit OS*) installs a newer GitHub release of MFruit OS and restarts.
- **From a checkout:** `bash scripts/update.sh` (fast-forward `git pull`, then
  re-install).

Either way the previous version is kept for rollback.

## Uninstalling

```bash
bash scripts/uninstall.sh          # remove the service and code, keep apps and settings
bash scripts/uninstall.sh --purge  # also delete ~/.whisplay-os (apps, data, logs)
```

`whisplay-daemon` and apps registered directly with it are never touched; its
own desktop is available again after uninstalling.

## Troubleshooting

| Symptom | What to check |
|---|---|
| The daemon's "Opening app…" / desktop still appears | Run `install.sh` again (adds the drop-in); Settings → System → Diagnostics shows *Hardware desktop: background* when active. |
| Screen shows the hardware desktop, not MFruit OS | `systemctl status whisplay-os`; pick **MFruit OS** on the hardware desktop to bring it back (Developer → *Daemon desktop* switches there on purpose). |
| "Hardware service unavailable" | The daemon service is stopped or failed: `journalctl -u whisplay-daemon -n 50`. *Retry* waits for it, *Restart daemon* restarts it. |
| An app shows "Application failed to start" | *Logs* on that screen, or `~/.whisplay-os/logs/<app>.log` (MFruit OS apps) / `~/.whisplay-daemon/daemon-app.log` (daemon apps). |
| Updater says "Internet unavailable" | Check the network; the check is retried automatically after 10 minutes. |
| "GitHub rate limit reached" | Anonymous API access allows 60 requests per hour per IP address. An update check costs one request per app with a repository; release lists are reused for 5 minutes. Add a token as `updater.github_token` in `settings.json` for 5000/hour. |
| Settings reset to defaults | A corrupt `settings.json` is kept as `settings.json.broken-<date>` and logged; fix or delete it. |
| Button feels slow | Single clicks wait for the double-click window (300 ms). Lower *Settings → Button → Click speed*, or set *Double click* and *Triple click* to *Nothing*: single clicks then act immediately. |

Useful commands:

```bash
mfruitctl status
mfruitctl screenshot /tmp/screen.png      # exactly what MFruit OS is drawing
python3 -m mfruitos --self-test           # (with PYTHONPATH set) offline render test
```

## Upgrading to 1.4.0

Update all keyboard apps to SDK 1.2.0 before restarting MFruit OS. The launcher
now grabs keyboards exclusively; older direct-input apps otherwise receive no
keys. Install the updated daemon wrapper and restart whisplay-daemon as well
so built-in Volume, Power and Wi-Fi pages receive forwarded keyboard input.
