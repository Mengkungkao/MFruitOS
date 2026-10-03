# Update, rollback and uninstall

How MFruit OS changes an installed app's version and what it guarantees when
something fails. Updating MFruit OS itself is in
[platform installation](../platform/INSTALLATION.md#updating-mfruit-os).

Where to find it on the device: manage apps under **Settings → Apps → app**
(Updates, Versions, Roll back, Uninstall); **App installer → Updates** checks
every channel. CLI: `mfruitctl check`, `mfruitctl install`, `mfruitctl sideload`.

## The pipeline

```text
CHECK → DOWNLOAD → VERIFY → BACKUP → INSTALL → TEST → ACTIVATE
```

| Step | What happens |
|---|---|
| Check | HTTPS URL required; at least 50 MB free |
| Download | up to `updater.max_download_mb`; SHA-256 computed while downloading |
| Verify | checksum compared when published (required if `updater.require_checksum`); archive extracted with path, link, special-file and size checks into a work directory; manifest validated; app ID, repository and release version must match the request |
| Backup | the current version directory is the code backup and is never touched; app `data/` is snapshotted to `backups/data-<version>/` |
| Install | package moved to `versions/<version>-<random>/`; `persist` paths copied from the previous version; `install.sh` then `update.sh` run |
| Test | manifest re-validated; entrypoint present; `test` hook run |
| Activate | atomic swap of the `current` symlink; install record written; daemon registration refreshed |

On any failure after Backup: the previous version stays (or becomes again)
active, the data snapshot is restored if hooks had run, the half-installed
version is deleted, and the progress screen says *Previous version restored*.
A failed first install removes the partial app. Older versions beyond
`updater.keep_versions` (default 2) are pruned after success.

## Release channel (native packages)

**Versions** lists releases; choosing one updates, downgrades or reinstalls.
**Roll back** switches to the saved previous installation without network.
Stop a running app before changing its version. The updater refuses
incompatible manifests and mismatched IDs, versions or repositories.

## Apps installed as Git checkouts

For an app whose folder is inside a Git repository (including nested app
folders and worktrees), the updater fast-forwards a clean branch to
`origin/<branch>`, byte-compiles changed Python files (a syntax error aborts
the update), and saves the previous commit for **Roll back**. Local edits and
diverged branches are never discarded; they require manual reconciliation.
Git updates do not install new dependencies or build assets; follow the app's
own instructions when a commit needs that. Folders copied without Git
metadata cannot use this channel.

## Uninstall

*Settings → Apps → app → Uninstall* (after a confirmation that lists what is
deleted) runs `uninstall.sh`, then deletes the managed app directory —
**including `data/`** — and its log and run record. Back up data that must
survive removal first. Disabling an app instead keeps everything.

## What rollback does not do

- It does not reverse data migrations an `update.sh` performed; only the
  snapshot taken before the failed install is restored automatically.
- It does not undo changes an app made outside its managed directory.
- It does not roll back dependencies installed into a persisted `.venv`.

## Testing updates

Before a release, exercise with disposable data: clean install, reinstall,
update, a deliberately failing smoke test (expect rollback), manual rollback
and removal; confirm intended data survives updates and nothing is left
running ([Testing](TESTING.md#package-lifecycle)). Automated coverage:
`tests/test_installer.py`, `tests/test_update_flows.py`,
`tests/test_catalog.py`.
