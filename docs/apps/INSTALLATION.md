# Installing apps

The ways an app gets onto an MFruit OS device, and what each one does. All
native installs run through the same pipeline
([Update and rollback](UPDATE_ROLLBACK.md#the-pipeline)); afterwards the app is
registered with whisplay-daemon through `mfruit-run`, enabled, and **not** set
to autostart.

| Path | Start from | Result |
|---|---|---|
| Curated catalogue | *Home → Fruit Store*, or `mfruitctl catalog [<id>]` | checksum-pinned source snapshot, prepared as a managed package |
| Local package | `~/.whisplay-os/inbox/` → *Fruit Store → Local packages*, or `mfruitctl sideload <path>` | native package from an archive or folder |
| GitHub release | *Fruit Store → More sources*, or `mfruitctl install github.com/owner/repo` | native package from a release |
| Git checkout | an app cloned and registered by its own installer | adopted app with commit-tracking updates |
| Adopted daemon app | any app registered directly with whisplay-daemon | launchable through the gate; not a native package |

## Curated catalogue

`config/catalog.json` lists reviewed apps with a pinned commit (`ref`), the
archive `url`, its `sha256`, the Python `entry` and pip `dependencies`.
Installing one:

1. downloads the archive over HTTPS and refuses it unless the SHA-256 matches;
2. checks that the declared Python entry exists inside the package;
3. **replaces** the app's own `install.sh`, `update.sh`, `uninstall.sh`,
   `run.sh`, `test.sh` and `manifest.json` with generated ones: a package-local
   `.venv` with the listed dependencies, a `run.sh` that execs the entry, a
   compile-and-import smoke test, and a manifest with version `1.0.0`,
   `min_os_version` 1.4.0, `exit_gesture: none`, `disable_esc_exit_key: true`
   and `persist: [config.yaml, .env, models]`;
4. copies the current platform SDK into the package as `mfruit_sdk/`;
5. runs the normal pipeline (hooks, smoke test, activation).

A catalogue app that is registered but whose files are missing shows
**Repair**; it runs the same installation. From a shell, `mfruitctl catalog`
lists each entry as `available`, `installed` or `broken`, and
`mfruitctl catalog <id>` installs or repairs it (follow it with
`mfruitctl jobs`).

Entries with `requires: ["radio"]` (WalkieTalkie, Messenger) show **Needs
radio setup first** until the LoRa radio is set up
([radio setup](../platform/INSTALLATION.md#radio-setup-lora-apps)); they can
still be installed first. Apart from that, the catalogue does not configure hardware: a radio, Codec2 or audio setup that
an app needs is still the user's step. Apps already on disk but missing from
the menu can be restored with **Add** (files and data kept, autostart off).

## Local packages

Copy a `.tar.gz`, `.tgz`, `.tar` or `.zip` archive, or a package folder with
`manifest.json` at its root, into `~/.whisplay-os/inbox/`, then choose it in
*Fruit Store → Local packages*, or run `mfruitctl sideload /absolute/path`.
Installing a lower version downgrades the app; the same version reinstalls it.
Archives and folders go through the same safety checks
([Security](../platform/SECURITY.md#implemented-protections)).

## GitHub releases

A repository needs a root manifest and a semantic-version release or tag
whose version equals the manifest version ([Publishing](PUBLISHING.md)).
Discovery lists repositories with the topic in `updater.discovery_topic`
(default `whisplay-app`) and those in `updater.sources`.

## Git checkouts and adopted apps

An app installed by `git clone` and its own installer appears as a daemon app.
MFruit OS adopts it: the original daemon registration is saved in
`~/.whisplay-os/adopted/<id>/` and the app is re-registered with `mfruit-run`
so the launch gate applies; uninstalling MFruit OS restores the original. If
the app folder is inside a Git repository, MFruit OS offers commit-tracking
updates ([Update and rollback](UPDATE_ROLLBACK.md#apps-installed-as-git-checkouts)).
Adoption alone does not make an app a native package
([Migrating an existing app](MIGRATING_EXISTING_APP.md)).

## Where installed files go

```text
~/.whisplay-os/apps/<id>/current -> versions/<version>-<random>/
~/.whisplay-os/apps/<id>/data/        (WHISPLAY_OS_APP_DATA)
~/.whisplay-os/logs/<id>.log
```

Full layout: [Directory structure](../platform/DIRECTORY_STRUCTURE.md#data-on-a-device).
