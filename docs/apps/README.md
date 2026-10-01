# App integration

MFruit OS runs apps through whisplay-daemon and provides a managed package,
launch and update path. The app remains responsible for its own features and
dependencies; MFruit OS owns registration, foreground lifecycle and package
activation.

## Choose a path

| I want to… | Start here |
|---|---|
| Create a new compatible app | [App development guide](../../APP_DEVELOPMENT.md) |
| Check input, screen, lifecycle and release requirements | [MFruit app rules](../APP_RULES.md) |
| Start from a working example | [Whisplay app template](../../templates/whisplay-app-template) |
| Install a local package or use app update/rollback | [App updates](../UPDATES.md) |
| Install or validate MFruit OS on a device | [Device setup](../DEVICE_SETUP.md) |

## Integration stages

1. **Run as an app:** use the daemon's shared framebuffer and event contract;
   do not take independent ownership of the display, button or keyboard.
2. **Adopt an existing app:** MFruit OS may launch an existing daemon app, but
   adoption alone does not make its clone a complete native package.
3. **Package natively:** add a root `manifest.json`, managed entrypoint,
   repeatable install/update hooks where needed, and a deterministic smoke test.
4. **Validate the artifact:** run `scripts/check-app.py`, sideload the exact
   folder/archive, and test launch, exit, update and rollback. Record physical
   checks separately from automated results.
5. **Publish:** make the release tag match the manifest version and include the
   complete runtime artifact and dependency instructions.

The app guide and rules are the contract. A manifest draft or passing unit
tests alone does not certify dependency installation, data migration, hardware
behavior or production readiness. Existing companion-app release gaps are
listed in [the app development guide](../../APP_DEVELOPMENT.md#existing-companion-release-gaps-2026-09-30).

[Documentation home](../README.md) · [OS development](../os/README.md) · [Quality](../quality/README.md)
