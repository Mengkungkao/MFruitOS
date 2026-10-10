# Publishing

How to release an app so mFruit OS can discover, install and update it.

## Release on GitHub

1. Push the package to a public GitHub repository with `manifest.json` at the
   root and add the topic **`whisplay-app`** (the default
   `updater.discovery_topic`; *Fruit Store → More sources → Discover* finds
   it).
2. Create a release whose tag is the manifest version: tag `v1.2.0` ↔
   `"version": "1.2.0"`. The installer refuses a release whose manifest version
   differs from its tag. Only semantic-version tags count as versions; the
   newest commit is not a release.
3. Prefer attaching a package archive named `<id>-<version>.tar.gz` (or
   `.zip`) with a checksum: GitHub's asset digest, a `SHA256SUMS` file, or
   `<asset>.sha256`. With a checksum the install is verified; without an asset
   the tag's source archive is used and integrity relies on HTTPS. Devices with
   `updater.require_checksum` refuse unverified releases.
4. Keep secrets and mutable data out of the archive ([Packaging](PACKAGING.md#release-contents)).

Pre-releases are offered only to devices with `updater.include_prereleases`.

## Before you publish

- `check-app.py` passes on the exact release contents.
- The package lifecycle and device checks in [Testing](TESTING.md) were run on
  this version.
- Release notes record the tested commit and version, target devices,
  automated results, manual results and remaining limitations; untested items
  are marked untested.

Do not describe an app as production-ready only because SDK parity or an
automated suite passes ([Part I §30](../platform/DEVELOPMENT_RULES.md#30-release-readiness)).

## The curated catalogue

The Fruit Store's curated list (`config/catalog.json` in mFruit OS) pins a
reviewed commit and its archive SHA-256. Adding or updating an entry is an
mFruit OS change: open a pull request with the new `ref`, `url`, `sha256`,
`entry` and `dependencies`, after the archive was downloaded and its checksum
and entry verified. Devices running mFruit OS with the online list see the
entry once it is on the default branch, the next time the Fruit Store opens,
without an OS update ([Installation](INSTALLATION.md#curated-catalogue)); so
commit an entry only when its pin is verified. Add `min_os_version` when the
app needs a newer mFruit OS than the devices may run. To ship a new version of
a native entry, change its `ref`, `url`, `sha256` and `version` together;
devices that have the app installed are offered the update.

An app that has to be built (AI Chatbot: TypeScript and `node_modules`) is
pinned as a **release asset** instead of a source snapshot: `url` is the
asset's download URL, `ref` the commit it was built from, `sha256` the
asset's digest; the archive holds one folder with the native package.
System packages the app needs go in `system_packages` (Debian names; installed
once by `scripts/setup-app.sh`, never by the Store); the app's own
`install.sh` checks them and names the command when one is missing. Catalogue installs replace the app's own hooks
([Installation](INSTALLATION.md#curated-catalogue)), so a catalogue entry is not
a substitute for a native release.
