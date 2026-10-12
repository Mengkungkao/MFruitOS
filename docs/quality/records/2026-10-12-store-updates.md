# 2026-10-12 — New software from the Fruit Store, without a computer

## Problem

The owner: devices running mFruit OS must get new software, and updates,
from the Fruit Store alone. The Orange Pi Zero 2W had AI Chatbot 1.0.2 and
was not offered 1.1.0.

## Evidence (before)

| What | Observed |
|---|---|
| Orange Pi `cache/updates.json` (check 09:28) | AI Chatbot: `release` channel, latest 1.0.2 (releases 1.0.2, 1.0.1, 1.0.0); RadioConnect 0.6.0: "No releases or version tags"; mFruit OS: "No releases or version tags" |
| ai-chatbot | commit 2b57d48 (1.1.0) pushed, no tag `v1.1.0`, so no release |
| RadioConnect, MFruitOS | no releases or tags ever; the Fruit Store pinned RadioConnect 0.5.0 by commit |
| `config/catalog.json` | AI Chatbot pinned to 1.0.2, RadioConnect to 0.5.0 |

The device side worked (release check, checksum, install, test, activate,
roll back); releases depended on manual steps that had been skipped.

## Fix ([ADR 0014](../../platform/ADR/0014-releases-and-catalogue-follow.md))

- `release.yml` in ai-chatbot, RadioConnect and MFruitOS: a new manifest
  version on main is tested, packaged with its SHA-256 and published.
- `scripts/catalog-sync.py` + `catalog-sync.yml` (hourly): pins of the owner's
  native apps follow their releases after verification.
- mFruit OS 1.5.0 (the CHANGELOG already had a 1.4.0 dated 2026-09-30):
  `scripts/build-release.sh` builds `mfruit-os-<version>.tar.gz`.

## Releases (GitHub Actions)

| Release | Run | Result |
|---|---|---|
| ai-chatbot v1.1.0 | first run failed: the release tests lacked numpy (`test_image_utils.py`); fixed in 1d6f256 | published 22:43 UTC, 92 MB asset, digest `df495d0d…` |
| RadioConnect v0.6.0 | first run | published 22:42 UTC, `aa533136…` = its SHA256SUMS |
| MFruitOS v1.5.0 | first run (check.sh, build, publish) | published 22:55 UTC, `mfruit-os-1.5.0.tar.gz` 1.6 MB |
| Catalogue sync (on its first push) | committed `064ba7f` as `mfruit-catalog-sync`: RadioConnect 0.5.0 → 0.6.0, AI Chatbot 1.0.2 → 1.1.0 | the pins and SHA-256s match the releases |
| MFruitOS v1.5.1 (Store row fix) | published by the workflow ~5 min after the version bump was pushed | no tag pushed by hand |
| MFruitOS v1.5.2 (rate-limit retry) | same | published 10:29 local |
| MFruitOS v1.5.3 (offers follow the installed version) | same | published 10:39 local |
| Catalogue sync, hourly schedule | ran by itself at 23:31 UTC | success, no pin to move |

The release monitoring here used up GitHub's 60 unauthenticated API calls an
hour for the home network's address (shared with the boards); see 1.5.2.

## Found and fixed on the way

| Finding | Fix |
|---|---|
| The Store list is fetched from `raw.githubusercontent.com`, cached by its CDN for 300 s (`cache-control: max-age=300`): the Orange Pi fetched the old pins a minute after the sync commit | none: documented (the list moves hourly; a few minutes more is minor) |
| The Store row said "Installed" for AI Chatbot beside "Update apps · 1 available": it compared only with the list's pin (still 1.0.2) | 1.5.1: the row takes the newer of the pin and the app's newest release (test fails without it) |
| A device check refused by GitHub's rate limit counted as done: the next check came 12 h later | 1.5.2: due a minute after the limit resets, kept across restarts (2 of 3 tests fail without it) |
| After the update to 1.5.1, System update showed Current 1.5.1, Latest 1.5.1 and still "Update now" (cached check made on 1.4.0) | 1.5.3: the service matches its cached OS entry to the running version at start; the System update screen and an app's Store page offer only a newer version than the installed one (4 tests; each half fails without its fix) |
| AI Chatbot's package is 92 MB; devices refuse downloads over `updater.max_download_mb` (100) | the chatbot build and mFruit OS's build refuse a package over the limit; the sync never pins one (test) |

## Device: Orange Pi Zero 2W, from its screens (mfruitctl key + screenshots)

| Step | Result |
|---|---|
| Home before | update dot on AI Chatbot |
| Fruit Store | "Update apps · 1 available"; AI Chatbot row "Installed" (the row bug above, 1.5.0) |
| AI Chatbot page → **Update to 1.1.0** | Check, Download (92 MB), Verify, Backup, Install, Test, Activate in ~30 s; `verified=True`, `source github`, previous 1.0.2 kept; `.env` (616 lines) kept in the data folder; the app started (09:57) and was closed again |
| Settings → General → Software Update | showed the cached "No releases or version tags"; **Check now** → Latest 1.5.1 |
| **Update now** → Confirm | Check … Test (self-test), Activate at 10:24:23, `verified=True`; launcher back on 1.5.1 within seconds; "System update to 1.5.1 confirmed healthy" (boot guard, 10:24:46); previous 1.4.0 kept for roll back; the power service restarted itself and read the PiSugar 2 on bus 2 |
| System update again | Current 1.5.1, Latest 1.5.1, **"Update now" still offered** (finding above) |
| Check now → Latest 1.5.3 → Update now → Confirm | installed 10:40:54 (`verified=True`, previous 1.5.1), launcher on 1.5.3 in ~12 s, "confirmed healthy" 10:41:18 |
| System update after it | Current 1.5.3, Latest 1.5.3 (green), no "Update now": the 1.5.3 fix works on the device |

## Device: Raspberry Pi Zero 2 W

Its Fruit Store showed the new pins (RadioConnect 0.6.0, AI Chatbot 1.1.0,
both "Installed": it had them from sideloads). The OS update from its screens
was **NOT VERIFIED**: its Wi-Fi (known weak) dropped every SSH session
(timeouts, 50% ping loss) before the screens could be driven. It runs
`1.4.0-local20261010235737` and is offered 1.5.3 in Settings > General >
Software Update after *Check now*.

## Not verified

- An update on the Pi Zero (above), and over its weak Wi-Fi a 92 MB download.
- RadioConnect updated through the Store on a device (both boards already had
  0.6.0).
- Changes needing root after a Store system update (none in 1.5.x).


## Tests

| Test | Result |
|---|---|
| `tests/test_catalog_sync.py` (11) | PASS; negative controls (no checksum check, no manifest check, no owner filter, no OS check) each fail their test; a package over the download limit is not pinned |
| `tests/test_app_installer_screen.py` (row shows Update for a newer release) | PASS; fails without the 1.5.1 fix |
| `tests/test_update_rate_limit.py` (3) | PASS; 2 fail without the 1.5.2 fix |
| `tests/test_update_state.py` (4) | PASS; each half fails without its 1.5.3 fix |
| `scripts/check.sh` | All checks passed (713) |
| `tests/test_build_release.py` (4): same files as install.sh, version agrees, archive clean and matches its checksum, installs as a system update with the device's Installer | PASS |
| `catalog-sync.py --dry-run` against GitHub | RadioConnect 0.5.0 → 0.6.0, AI Chatbot 1.0.2 → 1.1.0, both downloaded and verified (17 s); the dashboard (adopted) untouched |
| Orange Pi `mfruitctl check` after the 1.1.0 release | AI Chatbot: update to 1.1.0 offered; RadioConnect: latest 0.6.0 |
