# Set up and validate another device

Use this guide for a Raspberry Pi Zero 2 W, Orange Pi Zero 2W, or another
Linux board supported by your Whisplay driver checkout. MFruit OS sits on
top of the working hardware service. Its installer does not configure GPIO
pin mappings, SPI overlays, audio codecs or board-specific drivers.

`scripts/setup-device.sh` checks prerequisites without changing the device
by default. `--install` runs those checks and calls the existing
`scripts/install.sh`; there is one installation implementation.

## 1. Prepare the board and hardware service

1. Install an appropriate systemd-based board image and enable SSH. Use
   Raspberry Pi OS / Debian 12+ or Ubuntu 22.04+ as described in
   [INSTALL.md](../INSTALL.md). Use a normal user with sudo access.
2. Follow the Whisplay driver instructions for that exact board and image.
   Raspberry Pi and Orange Pi require their own GPIO/SPI/audio setup; do not
   copy kernel modules or overlays from a different board. Confirm the LCD,
   button, LED and audio work with the driver's own tests first.
3. Install and start `whisplay-daemon.service` as your normal user. Confirm
   its `WorkingDirectory` points to the Whisplay checkout. Stop standalone
   app services that would compete with the daemon for the display; apps
   will be launched through MFruit OS.
4. Install the Python prerequisites if absent. On the supported
   Debian/Ubuntu-based images:

   ```bash
   sudo apt-get update
   sudo apt-get install python3 python3-pil git
   ```

   Python must be 3.9 or newer. `alsa-utils` is optional for the speaker
   test. App-specific audio, radio, Node, model and network dependencies
   belong to each app's setup instructions. No global pip installation or
   dependency removal is needed for MFruit OS.

Log in as the same user shown by the daemon service:

```bash
ssh your-user@your-device-address
whoami
uname -a
python3 --version
systemctl show whisplay-daemon.service -p User -p WorkingDirectory
systemctl status whisplay-daemon.service --no-pager
```

For the current Orange Pi the SSH address is `orangepi@192.168.1.122`.
Substitute the new board's actual user and address when setting up another
device. Do not run the MFruit OS installer as root.

## 2. Put the chosen MFruit OS checkout on the device

For a published version, clone the repository on the device and check out
the release you intend to test:

```bash
git clone https://github.com/Mengkungkao/MFruitOS.git ~/MFruitOS-candidate
cd ~/MFruitOS-candidate
git log -1 --oneline
```

Local changes may not be published yet. To test your current development
checkout, copy it from the development machine instead. This uses a separate
candidate directory and does not delete files from an existing checkout:

```bash
cd ~/MFruitOS
device_host=your-user@your-device-address
rsync -a --exclude=.git --exclude=__pycache__ --exclude='*.pyc' \
  --exclude=.pytest_cache ./ "$device_host:~/MFruitOS-candidate/"
ssh "$device_host"
cd ~/MFruitOS-candidate
```

Use one of these methods. Record the source commit and any local changes
with your test results. `scripts/deploy.sh user@host` remains available as a
combined copy/install helper; the manual flow here lets you inspect the
preflight result before installation.

## 3. Preserve an existing installation

On an already configured device, return to Home and finish any active
updates. Save the current installation before replacing it:

```bash
backup_path="$HOME/mfruit-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_path"
chmod 700 "$backup_path"
if [ -d "$HOME/.whisplay-os" ]; then
  tar -C "$HOME" -czf "$backup_path/whisplay-os.tar.gz" .whisplay-os
fi
systemctl cat whisplay-daemon.service > "$backup_path/daemon-service.txt"
readlink -f "$HOME/.whisplay-os/system/current"
```

The tar archive covers managed apps, settings, logs and data under the
default MFruit OS home. Separately preserve data in existing companion
checkouts and any custom `WHISPLAY_OS_HOME`; those paths are not included.
For a consistent backup of actively changing app data, stop that app first.

## 4. Check, then install

From the candidate checkout on the device:

```bash
bash scripts/setup-device.sh --check
bash scripts/setup-device.sh --install
```

With no options, `setup-device.sh` also performs only the check. It verifies
Linux, a normal user, Python/Pillow, the source/manifest version, systemd,
the daemon service's user and source directory, and a read-only
`health.ping` through `/tmp/whisplay-daemon.sock`. It exits nonzero with the
failed prerequisite and does not install packages or drivers.

Installation copies a version into `~/.whisplay-os`, preserves existing
settings, installs the launcher service and helper commands, and configures
the daemon's background desktop wrapper. It may restart the hardware
service, closing running apps. See [INSTALL.md](../INSTALL.md) for the exact
files and narrow sudoers permissions created.

For development, use `--install --dev` to run from the checkout; keep that
directory in place. `--no-background-daemon` retains the hardware service's
own desktop between apps. `--yes` forwards the installer's noninteractive
option; it does not bypass sudo authorization. For an offline files-only
installation, use the existing `scripts/install.sh --no-service` directly.

## 5. Verify the launcher automatically

```bash
systemctl is-active whisplay-daemon.service whisplay-os.service
mfruitctl status
mfruitctl apps
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --self-test
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --preview /tmp/mfruit-preview
mfruitctl screenshot /tmp/mfruit-home.png
journalctl -u whisplay-os.service -n 80 --no-pager
```

Expect both services to be active, the launcher at Home, and the self-test
to exit successfully. Previews and `mfruitctl screenshot` show MFruit OS's
rendering; they do not verify the physical LCD or an app's separate shared
framebuffer. Copy PNGs back with `scp` if needed.

From the full source checkout, run the test suite when validating code:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

The real-daemon harness needs a compatible Whisplay checkout. If it is not
under `~/Whisplay` or `~/ai-chatbot/Whisplay`, set `WHISPLAY_SRC` to its path.
Read the result's skipped tests as well as failures; missing prerequisites
do not count as passed coverage. Run only one MFruit OS integration suite
at a time.

At Home, `mfruitctl key down`, `mfruitctl key enter` and `mfruitctl back`
exercise launcher navigation over SSH. They do not validate physical input.
`mfruitctl check` checks for updates; it does not install them.

## 6. Install and test an app

Start with the supplied template before adding hardware-heavy companions:

```bash
python3 scripts/check-app.py templates/whisplay-app-template
mfruitctl sideload "$PWD/templates/whisplay-app-template"
mfruitctl jobs
mfruitctl apps
mfruitctl launch hello-whisplay
```

Wait for the installation job to finish successfully before launching. The
package checker reads the entire package directory: ignored caches and real
`.env` files still fail the release check. Use a clean staging directory
for a package copied from an active development checkout.

Test the counter with button and keyboard, leave it, reopen it and confirm
its value persists. Follow [APP_RULES.md](APP_RULES.md) for app creation,
development, production and integration checks. A companion discovered
through the daemon registry may still need its own manifest, repeatable
installer/build and smoke test before it is a native release package.

On the device, verify these physical behaviours separately:

- Button: tap next, double-click previous, hold then release selects,
  four clicks backs out, and visible Back rows select correctly.
- Keyboard: arrows/Tab, Enter and Esc; USB hotplug and Bluetooth pairing,
  reconnect and cancellation. Keys held across an app switch must not act
  in the newly opened app.
- Display and LED: rounded-corner content, status/footer, dim/wake and
  expected colours. A wake-only press must not select a menu item.
- Audio/radio/network: actual sound, recording and message delivery for
  apps that use them. Credentials and a second radio/device may be required.
- Boot: reboot once, observe startup and confirm Home and both services
  return. Record unexpected reboots or repeated service restarts.

## 7. Debug a failure

```bash
systemctl status whisplay-os.service whisplay-daemon.service --no-pager
journalctl -u whisplay-os.service -u whisplay-daemon.service -n 150 --no-pager
tail -n 100 ~/.whisplay-os/logs/launcher.log
tail -n 100 ~/.whisplay-os/logs/updater.log
tail -n 100 ~/.whisplay-os/logs/hello-whisplay.log
```

Use the actual app id in the last filename. Existing daemon-managed apps
may log to `~/.whisplay-daemon/daemon-app.log` or their own app log instead.
If the daemon check fails, fix its service/driver first. If the app fails,
read its log and dependency checks before reinstalling it.

To run the launcher interactively from the candidate checkout:

```bash
sudo systemctl stop whisplay-os.service
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --debug
# Press Ctrl-C when finished, then:
sudo systemctl start whisplay-os.service
```

Keep whisplay-daemon running. Stop the launcher service before starting a
second launcher process, and restart it after the debug session.

## 8. Update, roll back or remove

For a clean Git checkout, `bash scripts/update.sh` fast-forwards the branch
and reinstalls it. For a copied checkout, transfer the intended candidate
again and use `setup-device.sh --check` followed by `--install`. Updating
the OS and all keyboard apps together keeps their SDK/key-hub contract in
sync. Preserve local edits before using Git updates.

Managed apps expose **Updater → app → Roll back** when a previous version
is available. Test updates and rollback with disposable app data before
production; manual version rollback does not promise to reverse every data
migration. Failed installation restores the installer's data snapshot.

For an OS installed from a checkout, inspect retained versions:

```bash
readlink -f ~/.whisplay-os/system/current
ls -1 ~/.whisplay-os/system/versions
```

Choose a known good retained directory and run its `scripts/install.sh`
with Bash as the same user. This reinstalls its helpers and service wrapper
along with its code. Do not choose a path solely because its name is older;
use your recorded successful validation. Release updates also have the
boot guard described in [INSTALL.md](../INSTALL.md).

To remove MFruit OS while keeping managed app files, settings and logs:

```bash
bash ~/MFruitOS-candidate/scripts/uninstall.sh
```

The uninstaller restores adopted app registrations and the daemon desktop.
`--purge` additionally deletes managed apps, data and logs under the MFruit
OS home; use it only when those files are intentionally being discarded.
Remove a disposable native test app through its **Apps → app → Uninstall**
screen after checking its data-removal confirmation.

Record the source version, board/image, dependency versions, automatic test
counts, manual results and remaining failures. An SSH pass alone is not a
physical hardware sign-off.
