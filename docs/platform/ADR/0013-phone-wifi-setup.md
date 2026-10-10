# ADR 0013: Wi-Fi from a phone with PiSugar's sugar-wifi-conf, run by mFruit OS

Status: Accepted 2026-10-10 (owner's request). IMPLEMENTED and AUTOMATED;
device results are in the [record](../../quality/records/2026-10-10-phone-wifi-setup.md).

## Context

A device without Wi-Fi cannot reach the Fruit Store or updates. Typing a
Wi-Fi password with one button is slow. PiSugar's sugar-wifi-conf is a
Bluetooth Low Energy service that the PiSugar app, PiSugar's WeChat
mini-program and a Web Bluetooth page (pisugar.com/sugar-wifi-conf) use for
several things:

- show the device's Wi-Fi name, IP addresses and model;
- set the Wi-Fi network, with SSID and password guarded by a shared key;
- show *custom info* (shell commands run every *interval* seconds);
- run *custom commands*;
- tunnel SSH over Bluetooth.

Its config file (`custom_config.json`) lists the info items (label of at
most 20 bytes, command, interval) and the commands (label, command). The
owner asked to read and understand that config and to install the tool to
mFruit OS. PiSugar's installer runs it as an always-on root service with the
key "pisugar" and the name "raspberrypi". Its default commands (`shutdown`,
`reboot`) need root. While it runs it forces Bluetooth on, sets the adapter
name, and turns pairing off every second. That last behaviour would break
pairing a Bluetooth keyboard in Settings. The project is GPL v3; mFruit OS is
MIT.

## Decision

- **Install PiSugar's own build, unmodified.** Two releases are pinned, each
  verified against the SHA-256 GitHub publishes for its assets (aarch64,
  armv7, armv6). The newest one that runs on the board's glibc is installed:
  - v2.3.0 (commit `13da415`) needs glibc 2.39, for example Raspberry Pi OS
    trixie.
  - v2.2.3 (commit `2c578f1`) runs from glibc 2.30, for example Bookworm and
    Ubuntu 22.04. On the Orange Pi, v2.3.0 failed with "GLIBC_2.39 not
    found". v2.2.3 lacks v2.3.0's advertising and SSH-tunnel fixes and its
    once-a-second "pairing off" guard.

  `scripts/install.sh` installs it as the user into
  `~/.whisplay-os/system/tools/sugar-wifi-conf/<version>/`, with a `NOTICE`
  (licence, source). It comes from the offline pack when one is
  present (`make-offline-pack.sh` adds it), else from GitHub. A
  checksum mismatch installs nothing. Nothing is installed system-wide, and the
  binary is not committed.
- **Run it only when wanted, as the user** (`system/wifi_setup.py`,
  `WifiSetupService`, owned by the launcher). It runs:
  - while **Settings → Wi-Fi → Phone Setup** is open;
  - or also whenever there is no network (`wifi_setup.mode: offline`);
  - or always;
  - or on `mfruitctl wifi-setup start` over SSH.
  It is never a root service. It changes Wi-Fi through NetworkManager with
  the user's existing polkit rule. A crash restarts it after 5, 15 and 60 s,
  then it is reported as failed.
- **mFruit OS writes the config** (`state/sugar-wifi-conf.json`):
  - info: mFruit OS version, battery (`mfruitctl power level`), CPU
    temperature, memory, up time;
  - commands: *Restart mFruit OS*, and *Reboot* and *Shut down* through the
    power service's safe path, falling back to the sudoers-allowed
    `systemctl`.
  A valid `config/sugar-wifi-conf.json` written by the user replaces it.
- **A key for this device**: 8 random characters (no look-alikes) made on
  first use, shown on the screen, renewable (`wifi_setup.key`). The name is the
  controller's own Bluetooth name unless `wifi_setup.name` is set.
- **Bluetooth is put back**: pairing and power are restored when the tool
  stops. The tool is paused while any Bluetooth settings page is open, so
  keyboards can be paired.
- **Status from its log**: "Ready for a phone", "Phone connected", "Wi-Fi
  set", a wrong key, a failure. The log is copied to `logs/wifi-setup.log`
  with everything a phone typed removed, because the tool logs the Wi-Fi
  password for its deprecated input.
- PiSugar's own `sugar-wifi-config.service`, when present, is stopped and
  disabled by `install.sh`, and enabled again by `uninstall.sh`.
  `--no-wifi-setup` skips all of it.

## Alternatives

- **PiSugar's installer as is**: a root service always advertising with the
  well-known key. It fights the keyboard pairing in Settings, and its
  shutdown/reboot commands fail without root.
- **Write mFruit OS's own BLE service with the same protocol**: possible
  (BlueZ D-Bus), but the owner asked to install sugar-wifi-conf. PiSugar's
  build is the reference implementation the PiSugar app is tested with.
- **Commit the binaries to the repository**: about 10 MB of GPL binaries in an
  MIT repository. Pinned downloads and offline packs give the same offline
  install.

## Consequences

Phone setup works on a fresh device from an offline pack, and the device is
reachable over Bluetooth only while the owner wants it. The key travels
unencrypted over BLE (the tool does not pair), so someone nearby with a BLE
sniffer could capture it while the owner uses it. A new key is one tap. The
SSH tunnel reaches the local sshd without the key, though a normal SSH login
is still required ([Security](../SECURITY.md)). The info and commands run
as the user. The tool's 10 s start-up wait shows as *Starting*. A newer
upstream release needs a new pin (version, digests) in `wifi_setup.py`.

## Compatibility

Nothing changes until `scripts/install.sh` runs. Devices that used PiSugar's
own service keep the same phone experience, but with the device's key and
name instead of "pisugar"/"raspberrypi". The app and the web page ask for the
key. A board without a Bluetooth controller, or with an architecture without
a build, shows *Not available*.

## Validation

`tests/test_wifi_setup.py` covers pins, the offline key matching
`scripts/offline.sh`, install from a pack, the download, a checksum mismatch
and pruning. It also covers config validation and the user's own file, the
key, log redaction and status parsing, the service with a fake process and
Bluetooth (start, stop, restore, crash restarts, pause, new key), and the
runtime's steering and `mfruitctl wifi-setup`. `tests/test_install_setup.py`
covers the installer lines. Device checks W1–W6 are in
[Validation](../../quality/VALIDATION.md#hardware-checklist--wi-fi-from-a-phone).
