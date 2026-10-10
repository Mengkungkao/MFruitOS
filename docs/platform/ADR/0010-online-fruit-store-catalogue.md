# ADR 0010: The Fruit Store list is downloaded, the bundled list is the fallback

## Context

The Fruit Store listed only `config/catalog.json` from the installed mFruit OS
version. A new app (or a new pinned version of a listed one) reached a device
only with an OS update; on 2026-10-05 a freshly installed OS could not offer an
app that was being prepared for the Store.

## Decision

- The Fruit Store downloads `config/catalog.json` from the default branch
  (`HEAD`) of `system.repository`, the repository system updates already come
  from, when it is opened and `mfruitctl catalog` lists (at most every
  5 minutes; `updater.online_catalog`, default on).
- A usable download is kept in `<home>/cache/catalog.json` and replaces the
  bundled list, including removals. Offline, on a failed download or with a
  corrupt stored copy, the last good list (or the bundled one) is used.
- Every entry, bundled or downloaded, is validated on load
  (`catalog.check_entry`): id, name, GitHub HTTPS archive URL, full commit
  `ref`, SHA-256, native/adopted fields, known `requires`, optional
  `min_os_version`. Entries this OS version cannot use are left out and
  logged, so the online list can grow without breaking older devices.
- Installation is unchanged: the archive must match the entry's SHA-256, and
  the installer re-reads the entry it verifies against.

## Alternatives

- **Separate store repository:** cleaner ownership of app releases, but a new
  trust root and a repository to create; the setting can move to a URL later.
- **GitHub topic search only** (*More sources*): already exists, but lists
  unreviewed repositories without pins and needs native release packages.
- **Union of bundled and online lists:** an app could never be removed from
  the Store online.

## Consequences

Adding an app to the Store is a commit to `config/catalog.json` on the default
branch; devices see it the next time the Store is opened. The online list is
trusted as much as `system.repository` (whoever can push there can already
publish OS updates); the per-entry pin still protects the downloaded archive.
An unreleased entry on the default branch is live, so entries must be complete
and verified when committed.

## Compatibility

Devices on mFruit OS 1.4.0 without this change keep their bundled list. The
file format is unchanged (a JSON list); `min_os_version` is a new optional
entry field. Turning `updater.online_catalog` off removes the downloaded copy.

## Validation

`tests/test_catalog.py` (`OnlineCatalogTests`: replacement, removal, filtering,
failed download, corrupt copy, reuse window, service source and switch,
installing an app only in the downloaded list) and
`tests/test_app_installer_screen.py` (background refresh on opening the Store).
Device check on the Pi Zero 2 W: [record](../../quality/records/2026-10-05-online-catalogue.md).
