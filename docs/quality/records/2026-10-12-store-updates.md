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

## Tests

| Test | Result |
|---|---|
| `tests/test_catalog_sync.py` (10) | PASS; negative controls (no checksum check, no manifest check, no owner filter, no OS check) each fail their test |
| `tests/test_build_release.py` (4): same files as install.sh, version agrees, archive clean and matches its checksum, installs as a system update with the device's Installer | PASS |
| `catalog-sync.py --dry-run` against GitHub | RadioConnect 0.5.0 → 0.6.0, AI Chatbot 1.0.2 → 1.1.0, both downloaded and verified (17 s); the dashboard (adopted) untouched |
| Orange Pi `mfruitctl check` after the 1.1.0 release | AI Chatbot: update to 1.1.0 offered; RadioConnect: latest 0.6.0 |
