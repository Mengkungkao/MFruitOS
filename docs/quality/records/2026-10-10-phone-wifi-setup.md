# Wi-Fi from a phone (PiSugar sugar-wifi-conf) — 2026-10-10

## Scope
- Source revision and working-tree state: `30d9ec4` plus this session's
  uncommitted changes.
- Reference read in full: PiSugar/sugar-wifi-conf at `13da415`
  (2026-10-09; the v2.3.0 release assets were rebuilt from it), GPL v3.
- Pinned binaries: v2.3.0 `sugar-wifi-conf-aarch64` (sha256 `6188d4ce…`),
  `-armv7` (`c3323f65…`), `-armv6` (`4f44f529…`), digests as GitHub publishes them.
- Devices: development machine (Jetson Orin Nano, aarch64, Ubuntu-based
  L4T, BlueZ controller used as the "phone" side); Orange Pi Zero 2W (see
  "Device"). Raspberry Pi Zero 2 W offline all session.

## Results
| Check | Command or procedure | Result |
|---|---|---|
| Pins, offline key = `scripts/offline.sh`, install from a pack / download / checksum mismatch / pruning, config validation and the user's file, key, log redaction and status parsing, service lifecycle with a fake process and Bluetooth (start, stop and restore, crash restarts then failure, pause, new key), runtime steering, `mfruitctl wifi-setup` | `python3 -m unittest test_wifi_setup` (from `tests/`) | AUTOMATED: 24 OK |
| Installer lines (as the user, never sudo; option; PiSugar service hand-over; offline packs) and uninstall re-enabling | `tests/test_install_setup.py` | AUTOMATED: OK |

## Device

Orange Pi Zero 2W (Ubuntu 22.04 jammy, glibc 2.35, BlueZ 5.64, aarch64),
build `1.4.0-local20261010122215` installed with `install.sh --no-service`
(backup first: `~/mfruit-backups/20261010-030735-before-power-wifisetup/`),
launcher restarted through its sudoers rule. The "phone" was the
development machine's BlueZ controller running a D-Bus GATT client
(read-only plus wrong-key writes; no Wi-Fi was changed).

| Check | Result |
|---|---|
| First install picked v2.3.0; the tool exited at once: `GLIBC_2.39' not found`; the service showed *Restarting (exit 1)* three times, then *Failed* | DEVICE VERIFIED (found the problem; led to the glibc-based choice) |
| Reinstall picked v2.2.3 (SHA-256 `c1b350f2…` checked), pruned 2.3.0, wrote `NOTICE` | DEVICE VERIFIED |
| Settings → Wi-Fi from phone: *Starting*, then *Ready* ("Advertising as 'orangepi' started"); Device `orangepi` and the key on screen (screenshot) | DEVICE VERIFIED (framebuffer screenshot, not looked at on the LCD) |
| `mfruitctl wifi-setup start/stop/status` over SSH | DEVICE VERIFIED |
| Tool runs as `orangepi` (not root), child of the launcher; pairing turned off while it runs | DEVICE VERIFIED |
| BLE from the dev machine: device found by service UUID; 33 characteristics; service name "PiSugar BLE Wifi Config", model "OrangePi Zero2 W", SSH user, Wi-Fi name and IP notifications; info items mFruit OS 1.4.0, Battery ("no battery", from `mfruitctl power level`), CPU temperature, memory, up time; commands Restart mFruit OS, Reboot, Shut down | DEVICE VERIFIED |
| Wi-Fi request and command request with a wrong key → "Invalid key." both; Wi-Fi unchanged; the test password string not in `wifi-setup.log` | DEVICE VERIFIED |
| Leaving the screen / `stop`: tool ended, Pairable back to yes | DEVICE VERIFIED |
| Started over SSH, then Settings → Bluetooth: tool paused (stopped, Pairable yes); closing Bluetooth settings resumed it | DEVICE VERIFIED |

## Skipped and not verified
- The PiSugar app and the WeChat mini-program on a real phone: not available
  to Claude (NOT VERIFIED).
- Setting a Wi-Fi network over Bluetooth (W4): not done on a device, because
  it would replace the board's working Wi-Fi connection.
- The v2.3.0 build on a glibc 2.39+ system (Raspberry Pi OS trixie): not run
  (the Pi Zero 2 W was offline).
- *Also when there is no Wi-Fi* mode on a device; the LCD itself.

## Issues found
- PiSugar's v2.3.0 release build needs glibc 2.39 (v2.2.3 and earlier: 2.30)
  — [KI-14](../KNOWN_ISSUES.md#ki-14-pisugars-sugar-wifi-conf-v230-build-needs-glibc-239).
