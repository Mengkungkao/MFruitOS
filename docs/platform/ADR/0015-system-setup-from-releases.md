# ADR 0015: The system setup follows System updates, from the official release

Status: Accepted 2026-10-12 (owner's request: devices must update without a
computer, also what needs root). IMPLEMENTED and AUTOMATED in 1.6.0; device
results are in the [record](../../quality/records/2026-10-12-system-setup.md).

## Context

`scripts/install.sh` sets up two kinds of things. The code goes into the
user's folder (`~/.whisplay-os/system/versions/…`); a *System update* from the
Fruit Store replaces it ([ADR 0014](0014-releases-and-catalogue-follow.md)).
The **system setup** is root's: the systemd units of the launcher and the
power service, the daemon drop-in, the sudoers and polkit rules, the
power-off shutdown hook, the `i2c-dev` module list, the Whisplay driver and
the packages mFruit OS needs. A System update cannot change any of it: it
runs as the user.

So a device's system setup was whatever its last `sudo bash
scripts/install.sh` wrote. On 2026-10-12 both boards had system setups from
before 1.5 (their later installs were files-only), missing at least the
Wi-Fi permission for polkit 0.105 (Orange Pi, Ubuntu 22.04), the
existing-groups-only units and the driver's newer sound card build; and
nothing told anyone which device lacked what.

Constraints: the code in the user's folder is writable by every program the
user runs (apps included), so root must never run it or take instructions
from it; a device must not need its owner's password for routine updates;
and a device must say what is missing when it cannot fix it itself.

## Decision

- **`scripts/install.sh` stays the one owner of the system setup**, with two
  more modes. `--check-system` builds every root-owned file as the installer
  would and compares it with the device (read-only, no root needed; with
  sudo it also reads the files only root may read), plus enabled units,
  replaced PiSugar services, packages and the driver (`drivers/whisplay/install.sh
  --check`). `--system-only` applies only the system setup for the version
  installed; it installs only files that differ and restarts only services
  whose units changed. Run as root it needs `--user NAME`, and then it never
  runs the user's Python: files root installs are rendered by
  `/usr/bin/python3`, everything else of the user's runs as the user.
- **`mfruit-system-apply.service` (root, oneshot) applies the system setup
  of the running version from its official release.** `install.sh`
  installs `/usr/local/lib/mfruit-os/mfruit-system-apply` (a root-owned copy
  of `scripts/mfruit-system-apply`), the unit, and
  `/etc/mfruit-os/system.conf`: the user, their mFruit OS folder, the Python
  their services run, the repository (`https://github.com/OWNER/NAME` from
  the installed manifest) and the installer options. The service reads only
  the **version number** from the user's files (as the user; a regular file,
  no link, at most 64 KiB), downloads that version's
  `mfruit-os-<version>.tar.gz` and its `.sha256` from the repository's
  release over HTTPS, checks the checksum, unpacks only plain files and
  folders into a folder only root can write, checks the package's manifest
  (id, system type, version) and runs its `scripts/install.sh --system-only`
  as root with a clean environment. Releases before 1.6.0 are refused.
- **One sudoers rule** lets the launcher start it: `systemctl start
  mfruit-system-apply.service`, which takes no arguments.
- **The launcher starts it once per version**: after a System update is
  confirmed healthy (or a minute after any other start, such as a roll back),
  never while an app is open or another install job runs. *Settings → General
  → Software Update* shows **System setup** (*Up to date*, *Needed*, *Failed*,
  *Not downloaded*, or *Needs a computer* where the service is not installed)
  with **Apply system setup** and, when the driver needs it, **Restart to
  finish setup**. `mfruitctl system-setup [check|apply]` does the same over SSH.
- The status, `/var/lib/mfruit-os/system-setup.json` (0644), says which
  version's system setup was applied, what changed, whether a reboot is due,
  or why it failed; the log is next to it.

## Alternatives

- **A sudoers rule for the user's own `install.sh`.** Every program the user
  runs could then edit that script and run it as root. Rejected.
- **The launcher writes the root files itself through narrow sudo rules** (one
  per file). Each rule is a general root write (the content comes from the
  user's files); the same objection. Rejected.
- **Root takes the code the launcher already downloaded and verified** (in
  `~/.whisplay-os/system/versions/`). That folder is the user's; it can change
  between the check and the use. Rejected: root downloads its own copy.
- **Root trusts the checksum the user's updater recorded.** The record is the
  user's too. Rejected; the published `.sha256` is fetched by root.
- **Keep it manual, and say in release notes when `sudo bash
  scripts/install.sh` is needed.** That is how the boards fell behind
  ([ADR 0014](0014-releases-and-catalogue-follow.md)). Rejected.

## Consequences

- After the one-time setup of 1.6, a System update brings its system setup
  too, without a computer or password. A board installed earlier needs that
  once: `bash ~/.whisplay-os/system/current/scripts/install.sh --system-only`
  (the screen says so under *System setup*).
- Root trusts what the repository named at installation publishes as a
  release (HTTPS to GitHub). The SHA-256 protects against a broken download,
  not against the repository's owner; it is the same trust a System update
  already has, now also for root. A program running as the user can only ask
  root to apply an official release's system setup of a version it chooses
  (1.6.0 or later); it cannot choose what runs.
- The installers, now also run by root unattended, touch the user's home
  only as the user (`~/.whisplay-daemon`, the list of replaced PiSugar
  services), so a link there cannot redirect a root-owned write.
- A system setup that changes the launcher's unit restarts the launcher; a
  changed daemon drop-in or driver restarts the daemon (running apps close).
  This happens right after a System update, which restarts the launcher
  anyway, or when the user chooses **Apply system setup**.
- About 2 MB more download per System update (root's own copy).

## Compatibility

Devices on 1.5.x or earlier have no service: a System update to 1.6.0 shows
*System setup: Needs a computer* until the one-time command runs. Nothing
else changes for them. `install.sh` without the new options behaves as
before (it also records the system setup and installs the service).
`--system-only` does not copy files, prompt, or install apps; it refuses
`--no-service`, `--dev` and `--app`.

## Validation

`tests/test_system_setup.py` (install.sh's helpers in both modes, the whole
installer in check mode without sudo and in system mode as root with command
doubles, the service's input checks, checksum, extraction and end-to-end run
with a fake GitHub, the launcher's status, trigger, screen rows and
`mfruitctl`), `tests/test_install_setup.py`,
`tests/test_whisplay_driver_install.py`, with negative controls; the
fresh-install rehearsal (`tests/fresh_install/verify.sh`: check, drift,
repair as root); device runs in the
[record](../../quality/records/2026-10-12-system-setup.md).
