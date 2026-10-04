# 2026-10-05 — Online Fruit Store list

## Context

On a freshly installed OS the Fruit Store could only show the list shipped
with that OS version (`config/catalog.json`), so an app added to the Store
needed an OS update to appear (user report: ai-chatbot missing). Change:
[ADR 0010](../../platform/ADR/0010-online-fruit-store-catalogue.md).

## Revision

`86af314` plus uncommitted changes (online catalogue; the radio option of
`scripts/install.sh` from the same day).

## Automated

| Check | Result |
|---|---|
| `tests/test_catalog.py` `OnlineCatalogTests` (8 tests), `tests/test_app_installer_screen.py` background refresh | pass |
| Negative control: installer looking up the entry without the device home | `test_an_app_only_in_the_downloaded_list_installs_with_its_pin` fails ("Unknown catalogue app"), passes with the fix |
| `bash scripts/check.sh` unit/integration/real-daemon suite | 493 tests, OK |

## Device: Raspberry Pi Zero 2 W (`meng@192.168.0.33`, hostname pizero)

Debian 13 trixie, kernel 6.18.50+rpt-rpi-v8, Python 3.13.5, Pillow 11.1.0.
Candidate copied to `~/MFruitOS-candidate` (the user's `~/MFruitOS` clone not
touched), configuration backed up to `~/mfruit-backups/`, installed with
`install.sh --no-service --yes` (self-test OK, 41 screens) as
`1.4.0-local20261005103400`, launcher restarted.

| Step | Observed |
|---|---|
| `mfruitctl catalog` right after the restart | `source: bundled` (no download yet) |
| The same 3 s later | `source: online`; `cache/catalog.json` written; log "Fruit Store list updated from the online catalogue (2 apps)" |
| Simulated online-only entry `demo-new-app` and an entry with `min_os_version: 9.0.0` written into `cache/catalog.json` | `mfruitctl catalog` and the Fruit Store screen (screenshot) list *Demo New App — Download*; the 9.0.0 entry is left out and logged "needs MFruit OS 9.0.0 (running 1.4.0)" |
| Stored copy deleted, Fruit Store opened on the device | list downloaded from GitHub again: BTC Dashboard and RadioConnect only (screenshot) |

## Not verified

- A real new app published on the default branch reaching the device (nothing
  is pushed; the online list on GitHub currently equals the bundled one).
- Installing an app that exists only in the online list on the device
  (automated only, with a local archive).
- Offline behavior on the device (automated only).
- The physical button path to the Store (navigation used `mfruitctl`).
