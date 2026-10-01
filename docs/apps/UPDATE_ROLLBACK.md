# Install, update and downgrade

Open **Home → App installer**. Manage installed apps under **Settings → Apps**,
or open **App installer → Updates** to check their update channels.

## Curated catalogue and saved apps

Select a catalogue app and confirm **Install** to download its pinned source
archive. MFruit OS verifies the SHA-256 checksum, prepares its package-local
Python environment and current SDK, and adds it to Apps after installation.
The catalogue describes hardware requirements; installing a package does not
configure or validate radio hardware or Codec2. These snapshots are separate
from the native release workflow below.

An app marked **On device** can be restored with **Add**. Its files and data
are kept, and restoration does not enable autostart. **Installed** opens app
management. More repositories are available through **More sources**.

## Local app packages

1. Copy a native MFruit OS app archive (`.tar.gz`, `.tgz`, `.tar`, `.zip`) or
   package folder containing `manifest.json` into `~/.whisplay-os/inbox/`.
2. Open **App installer → Local packages**, select the package and confirm.
3. Wait for the progress screen to finish. The installed app appears in Apps.

Installing an older package downgrades the app; installing the same version
reinstalls it. Code is installed into a new version directory, hooks and the
package test run before activation, and the previous code is retained. App data
stays in the app's `data/` directory. Failed hooks/tests restore the data snapshot.
Packages must follow [the app rules](APP_RULES.md); arbitrary source clones with
standalone, system-wide installers are not native packages.

CLI equivalent: `mfruitctl sideload /absolute/path/to/package.tar.gz`.

## GitHub releases

Use **App installer → More sources** for the configured sources/topic, or run
`mfruitctl install github.com/owner/repository`. A native app repository needs a
root manifest and a compatible semantic version release or tag. The manifest
version must match the selected release. Publishing a Git commit alone does not
create a downloadable version in this channel.

For installed native apps, open **Settings → Apps → app → Updates** (or select
it in Software Update). **Versions** selects a release to update, downgrade or
reinstall. **Roll back** switches to the saved previous installation, even
without internet. Stop a running app before changing its version.

The updater verifies checksums when supplied and honors the require-checksum
setting. It refuses incompatible manifests or mismatched app IDs, versions and
repositories. Keep secrets and mutable data out of release archives.

## Apps installed as Git checkouts

The updater recognizes the repository containing the app's working directory,
including a nested app folder and Git worktrees. It fast-forwards a clean branch,
checks changed Python files, and saves the previous commit for **Roll back**.
Repeated/no-op and failed updates keep the last successful rollback target.
Local edits and diverged branches require manual reconciliation; they are never
silently discarded by an update. Copied folders without Git metadata cannot use
this channel. Git updates do not install new dependencies or compile app assets;
follow the app's own instructions when a commit needs those steps.

## MFruit OS

Use **Settings → General → Software Update**. **Versions** selects
a published version; **Roll back** restores the saved local build and restarts
the launcher. Local `scripts/install.sh` installations now record the previous
build as well. Both system update and rollback arm the boot guard.

On the Orange Pi inspected on 2026-09-30, the cached GitHub check reports no
MFruit OS releases/version tags. ConnectWifi and Messenger are copied folders;
WalkieTalkie has local modifications. These are distribution/checkout conditions,
not permissions to overwrite local work. Publish compatible releases for version
selection, or reconcile an app's Git checkout before expecting remote updates.
The AI chatbot's nested checkout is now detected, but its local edits are still
protected.

Automated package tests cover install → update → downgrade → reinstall, failed
activation, rollback recovery, persistent data and system boot-guard markers.
They do not certify every companion app as a native release package.
