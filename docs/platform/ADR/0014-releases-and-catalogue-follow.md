# ADR 0014: Releases publish themselves; the Fruit Store follows verified releases

Status: Accepted 2026-10-12 (owner's request: devices must get new software
from the Fruit Store without a computer). IMPLEMENTED and AUTOMATED; device
results are in the [record](../../quality/records/2026-10-12-store-updates.md).

## Context

Devices already find updates on their own: an installed app is checked
against its repository's GitHub releases (the `release` channel), mFruit OS
against `system.repository`'s releases (*System update*), and the Fruit Store
list is downloaded from `config/catalog.json` on the default branch
([ADR 0010](0010-online-fruit-store-catalogue.md)), each entry pinned to one
archive by URL and SHA-256.

The publishing side was manual and was skipped: AI Chatbot 1.1.0 was committed
but never tagged, so no device could see it; RadioConnect and mFruit OS had
never published a release, so neither could be updated from a device at all
("No releases or version tags"); and every new version also needed a hand
edit of the catalogue pin.

## Decision

- **Releases publish themselves.** In mFruit OS, AI Chatbot and RadioConnect,
  `.github/workflows/release.yml` publishes `v<version>` whenever
  `manifest.json` carries a version that has no release: tests first, then the
  package (`<id>-<version>….tar.gz` with its SHA-256), from the pushed commit.
  Bumping the version and pushing is the release.
- **The catalogue follows verified releases of the owner's apps.**
  `scripts/catalog-sync.py` (hourly, `.github/workflows/catalog-sync.yml`)
  moves a native entry whose repository belongs to the same GitHub owner as
  mFruit OS to its newest release, only after downloading the package and
  checking its SHA-256 against the published one, its manifest id and version,
  and that it needs no newer mFruit OS than the list's; the result must pass
  the devices' own entry checks. It commits the list to the default branch.
- Entries from other owners, and adopted (non-native) entries, stay pinned by
  hand through a reviewed change, as before.

## Alternatives

- **Devices follow "latest release" directly, no pins.** No sync job, but every
  device would trust whatever a repository publishes, with no single place
  that checked it, and fresh installs could not be reproduced. Rejected.
- **The app repositories push the pin to mFruit OS.** Needs a cross-repository
  token in every app repository. Rejected: the hourly job needs only this
  repository's own token.
- **Keep it manual, with a checklist.** It had already been skipped. Rejected.

## Consequences

- A new version reaches devices within about an hour of the version bump
  (installed apps: at their next update check; the Store list: the next time
  the Store opens after the sync).
- Trust for the owner's apps moves from a hand review of each pin to the
  release workflow's tests plus the sync's checks. A compromised app
  repository of the owner could publish a bad version; the device still
  verifies the checksum and runs the package's test before activation, and
  keeps the previous version for roll back.
- The catalogue's history gains commits by `mfruit-catalog-sync`.
- A *System update* from the Store replaces mFruit OS's code only. Changes to
  what `scripts/install.sh` sets up as root (services, sudoers, polkit, the
  shutdown hook) still need `sudo bash scripts/install.sh` on the device; the
  release notes must say when a version needs it.

## Compatibility

No device-side change: devices running 1.4 already use the release channel,
*System update* and the online list. Existing pins stay valid. An app
release that needs a newer mFruit OS than the list's is not pinned (older
devices would drop the entry); it is still offered to devices new enough to
install it through the release channel.

## Validation

`tests/test_catalog_sync.py` (checksum, manifest, OS version, owner, no-op,
write), with negative controls; `tests/test_build_release.py` (the system
package holds what `install.sh` installs and installs as a system update);
the first runs on GitHub and an update from the Fruit Store on a device
([record](../../quality/records/2026-10-12-store-updates.md)).
