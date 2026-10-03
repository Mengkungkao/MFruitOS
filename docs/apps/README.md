# App development

For people building or integrating applications for MFruit OS. An app is
normally integrated **without changing MFruit OS**: it ships a manifest, uses
the MFruit App SDK and goes through the managed package pipeline. The app owns
its features, data and dependencies; MFruit OS owns registration, launching,
the foreground lifecycle and package activation.

## The app lifecycle and where each stage is documented

| Stage ([Part I §9](../platform/DEVELOPMENT_RULES.md#9-app-integration-contract)) | Document |
|---|---|
| CREATE | [Getting started](GETTING_STARTED.md) — template, app ID, first run |
| VALIDATE | [Manifest](MANIFEST.md), [App contract](APP_CONTRACT.md), `scripts/check-app.py` ([Testing](TESTING.md)) |
| PACKAGE | [Packaging](PACKAGING.md) — layout, hooks, dependencies, data |
| INSTALL | [Installation](INSTALLATION.md) — catalogue, local packages, GitHub, adopted apps |
| LAUNCH / RUN / EXIT | [App contract](APP_CONTRACT.md) §1–2, [SDK](SDK.md), [UI guidelines](UI_GUIDELINES.md), platform [lifecycle](../platform/LIFECYCLE.md) |
| UPDATE / ROLLBACK / UNINSTALL | [Update and rollback](UPDATE_ROLLBACK.md) |
| PUBLISH | [Publishing](PUBLISHING.md) |
| Existing apps | [Migrating an existing app](MIGRATING_EXISTING_APP.md) |

## Integration levels

1. **Adopted daemon app:** an app registered with whisplay-daemon runs inside
   MFruit OS through the launch gate. This alone does not make it a native
   package.
2. **Native package:** root `manifest.json`, managed entrypoint, repeatable
   hooks, a smoke test, the vendored SDK and the app contract.
3. **Validated release:** the exact artifact passed `check-app.py`, sideload,
   launch, exit, update, failed-update rollback and removal with disposable
   data, and device checks are recorded.

A manifest draft or passing unit tests do not certify dependency
installation, data migration, hardware behavior or production readiness.

[Documentation home](../README.md) · [Platform](../platform/README.md) · [Quality](../quality/README.md)
