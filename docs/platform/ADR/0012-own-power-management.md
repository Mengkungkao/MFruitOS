# ADR 0012: mFruit OS has its own power management

Status: Accepted 2026-10-10 (owner's request). IMPLEMENTED and AUTOMATED;
the PiSugar hardware paths are NOT VERIFIED on a device.

## Context

mFruit OS showed the battery level only when PiSugar's own power manager
(`pisugar-server`, from PiSugar's pisugar-power-manager-rs) was installed and
running; neither test board had it. Nothing protected the SD card when the
battery ran empty, the power button's soft shutdown did nothing, and after
*Shut down* a PiSugar kept the halted Pi powered until the battery was flat.
The bundled whisplay-daemon (unmodified) reads the battery through
`pisugar-server`'s socket and installs its PiSugar home-button hook there.
The owner asked for mFruit OS's own power management after reviewing
PiSugar's project. That project is GPL v3; mFruit OS is MIT.

## Decision

- **Host layer** `mfruitos/hosts/pisugar/` (layer E): drivers for PiSugar 3,
  PiSugar 2 (IP5209, 4 or 2 LEDs), PiSugar 2 Pro (IP5312) and the PiSugar 2
  SD3078 clock, written for mFruit OS from the boards' published register
  interface. No PiSugar code is copied. I2C uses the standard library
  (`i2c.py`), so python3-smbus is not needed. `base.Chip` is the formal
  interface the service uses, and `fake.py` provides register-level test
  doubles (ADR 0005: an interface comes with its real implementation and a
  double).
- **Platform service** `mfruitos/power/` (layer C) in its own process,
  `mfruit-power.service`. It runs as the mFruit user with the `i2c` group and
  `CAP_SYS_TIME`, which is used only to move the clock forward from the
  board's clock. It is the single owner of the board. It does not run inside
  the launcher, so a crashed or restarting UI cannot stop a low-battery
  shutdown.
  - **Safe shutdown**: below `safe_shutdown_level` % (default 5) while
    unplugged, a `safe_shutdown_delay` countdown (default 30 s) is announced.
    External power cancels it. At zero, `sudo -n systemctl poweroff` runs.
    A board that cannot sense external power (PiSugar 2 with four LEDs, or
    an unconfigured PiSugar 2) is judged charging from its voltage: a step
    up of 0.1 V, or three minutes of rising minute averages
    (`mfruitos/power/charging.py`; amended 2026-10-10 after sample-to-sample
    noise was reported as charging).
  - **Soft shutdown**: the PiSugar 3 power button can ask for this shutdown
    instead of cutting the power.
  - **Board settings and clock**: power on when plugged in, anti-mistouch,
    battery protection, a charging range on PiSugar 2, a wake alarm and the
    board clock.
  - **Button events**: board presses become events.
- **Sockets**: JSON lines on `state/power.sock` serve mFruit OS. PiSugar's
  text protocol on `/tmp/pisugar-server.sock` serves the unmodified daemon,
  apps' `mfruit_sdk.status` and existing scripts. Commands that cut power at
  once, change the I2C address or set web credentials are refused.
- **Power cut**: the root-owned hook `/usr/lib/systemd/system-shutdown/mfruit-power-off`
  (a copy of `scripts/mfruit-power-off`) switches the board off only on
  *poweroff*, after every filesystem is unmounted or read-only.
- **Launcher**: `PowerLink` follows the event stream, which drives the
  status bar, **Settings → Battery**, the low-battery countdown, the power
  menu and the double/long press actions. A single press stays
  whisplay-daemon's Home.
- **Installer**: installs the unit, the hook and `poweroff`/`reboot` in mFruit
  OS's sudoers rule. It stops and disables `pisugar-server` and
  `pisugar-poweroff`, and `uninstall.sh` enables them again. `--no-power`
  skips all of it. On the first start, settings found in
  `/etc/pisugar-server/config.json` are imported once (never the web login).

## Alternatives

- **Keep requiring PiSugar's server**: a Rust daemon from another vendor's
  package source, with a web/TCP server listening on all interfaces by
  default. It offers no safe-shutdown UI on the device and is not part of the
  offline install.
- **Port PiSugar's Rust code**: a derivative of GPL v3 code inside an MIT
  project. An independent implementation of the documented registers avoids
  that.
- **Run inside the launcher**: no extra process, but low-battery protection
  would depend on the UI process. The daemon and apps would also lose the
  battery whenever the launcher restarts.
- **The `pisugar_battery` kernel module**: gives a desktop battery icon only.
  It has no policies and must match every kernel.
- **Shut the board off from a unit `Before=poweroff.target`** (as PiSugar's
  pisugar-poweroff does): that runs while filesystems are still mounted. The
  system-shutdown hook runs after they are read-only.

## Consequences

The battery level, safe shutdown and the power cut work with mFruit OS
alone and from an offline install. One more Python process runs
(`mfruit-power`), and PiSugar boards with no taps wanted are read once a
second. A PiSugar 2 samples its button every 100 ms, but only while a
press action or hook is set. PiSugar's web UI and remote TCP/WebSocket API are
gone; the device's own screen and `mfruitctl power` replace them. PiSugar 3
firmware button thresholds (how long "long" is, and the hardware power-off
hold) are not known exactly. The long-press action therefore defaults to
*Nothing*, and soft shutdown stays as the board has it.

## Compatibility

Existing devices are unchanged until `scripts/install.sh` runs. After it
runs, the daemon, apps and scripts that read `/tmp/pisugar-server.sock` keep
working against mFruit power, which answers in PiSugar's format. A device
installed with `--no-power` keeps PiSugar's server, and the launcher falls
back to reading it as before. Settings in PiSugar's `config.json` are carried
over once. Tap hooks that ran as root under PiSugar's server now run as the
mFruit user.

## Validation

Tests: `tests/test_pisugar_drivers.py` (drivers against the fakes, including
the PiSugar 3 write protection with a negative control),
`tests/test_power.py` (policies, settings, PiSugar protocol, sockets; the
bundled daemon's own PiSugar client and the SDK reading the socket),
`tests/test_power_off_hook.py`, `tests/test_battery_ui.py` and the installer
checks in `tests/test_install_setup.py`, including `systemd-analyze` of the
unit. Device: NOT VERIFIED. The hardware checklist items P1–P8 in
[Validation](../../quality/VALIDATION.md#hardware-checklist--power-management)
need a board with a PiSugar 3 or 2
([record](../../quality/records/2026-10-10-power-management.md)).
