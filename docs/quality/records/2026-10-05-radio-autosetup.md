# 2026-10-05 — Radio set up and RadioConnect installed by the installer

## Context

After `install.sh --radio` on a fresh Pi, the module settings (920 MHz) were
written only by a second, manual `setup-radio.sh` run after the reboot, and
RadioConnect had to be installed from the Fruit Store by hand. The user asked
for both to happen by themselves.

## Revision

`1ab275f` plus uncommitted changes:
`mfruitos/hosts/lora/__main__.py` (`boot-unit`), `scripts/setup-radio.sh`,
`scripts/install.sh`, `scripts/uninstall.sh`, `mfruitos/updater/autoinstall.py`,
`mfruitos/launcher/services.py`, `runtime.py`, `tasks.py`.

## Automated

| Check | Result |
|---|---|
| `tests/test_autoinstall.py` (14 tests: queue, requirement lookup, launcher job, offline wait, attempts, task lanes, boot unit) | pass |
| Negative control: `TaskLaneTests` with the previous `tasks.py` | fails (callbacks saw their own lane busy), passes with the change |
| `bash scripts/check.sh` | 507 tests, all checks passed |

## Device: Raspberry Pi Zero 2 W (`meng@192.168.0.33`, hostname pizero)

Debian 13 trixie, Python 3.13.5. Candidate installed with
`install.sh --no-service --yes` as `1.4.0-local20261005110644`. The radio had
been provisioned by hand earlier (AU915, 920 MHz, `ready: true`).

| Step | Observed |
|---|---|
| `python3 -m mfruitos.hosts.lora boot-unit …` on the Pi, `systemd-analyze verify` of the output | exit 0 |
| RadioConnect uninstalled (data kept; see KI-12 for the first attempt), queued with `python3 -m mfruitos.updater.autoinstall add --requires radio` (printed "RadioConnect"), launcher restarted | 11:27:28 "Installing queued app radioconnect (attempt 1 of 5)"; progress screen on the device (screenshot: Check … Test); 11:27:38 "Installed radioconnect 0.4.0 (previous -, verified=True)"; Done screen "RadioConnect installed" |
| Afterwards | `mfruitctl catalog`: radioconnect installed, no missing requirements; queue empty; data directory kept |
| Side effect of the test | Uninstall forgets per-app launcher settings, so RadioConnect's *Keep running* / *Keep screen bright* flags were reset |

## Not verified

- The next-boot service on a device: installing it needs sudo, so neither
  `setup-radio.sh` scheduling it nor provisioning at boot was run.
- A full fresh `install.sh --radio` (reboot, provisioning at boot, automatic
  RadioConnect install) end to end.
- Install while offline at boot, then later when the network comes up
  (automated only).

## Discovered

KI-12: Uninstall does not stop an app the launcher adopted after a restart.
