# Roadmap

Where MFruit OS is going, in dependency order, with acceptance criteria
instead of dates. Every item is **PLANNED** until its evidence is recorded in
[quality records](../quality/records/README.md). Current behavior is in
[Architecture](ARCHITECTURE.md); the rules for getting there are in
[Development rules](DEVELOPMENT_RULES.md).

## Goals

| Goal | What success looks like |
|---|---|
| Easy to use | The selected item is visible, opens once, Back is predictable, failures offer recovery — with one button or a keyboard. |
| Easy to develop | Each responsibility has one owner; offline tests, previews and CI give fast feedback; one canonical document per contract. |
| Feasible to integrate | A new app goes from the template to install, launch, update and rollback without launcher changes. |
| Reliable on small boards | Fits a Raspberry Pi Zero 2 W; idle input and rendering do not busy-loop; heavy work never freezes navigation. |
| Portable over time | Lifecycle, registry and packages stay host-independent; Whisplay becomes one host among others. |

## Current capability and target

| Area | Implemented now (1.4.0) | Direction |
|---|---|---|
| Launcher and settings | Pillow UI, screen stack, button gestures, keyboard hub, settings, diagnostics | Same user model on every host |
| Application lifecycle | Host-independent `ApplicationManager`; `ForegroundManager` performs the Whisplay handoff | Keep semantics; extract host responsibilities behind tested interfaces |
| Processes | daemon starts apps via `mfruit-run`; `AppLifecycle` does tickets, registration, run records, stop | A process service only when a second host needs it |
| Packages and updates | manifest, registry, GitHub releases, catalogue, sideload, versions, rollback, boot guard | Same services for GUI and CLI; explicit platform/dependency compatibility per host |
| Hardware independence | offline unit/integration tests, `--preview`, `--self-test` | MockHost and contract tests shared with WhisplayHost |
| App API | vendored SDK 1.2.0 (input, status, UI) | Host-independent API; lifecycle and data-path helpers; no breaking changes for installed apps |
| Quality | 348 automated tests incl. real-daemon contract tests; CI without hardware | Recorded device validation per release |
| Permissions | package validation only; no sandbox | Capabilities only with enforcement and tests |

## Phases

| Phase | Work | Acceptance criteria | Status |
|---|---|---|---|
| 1. Reliable baseline | Resolve the launch-window test using observed state; CI; full suite green | Regression fails with its guard removed; repeated runs stable; full suite recorded with skips disclosed; CI runs on every change | Test fixed and stable on a dev machine (2026-10-02); full-suite and CI evidence in [records](../quality/records/README.md); a Pi rerun is NOT VERIFIED |
| 2. Repeatable integration | Template + one app contract; sideload safety; release packaging; install/update/rollback with disposable data | A clean checkout becomes an installable app without launcher edits; lifecycle results recorded; `check-app.py` and SDK sync pass for released apps | In progress |
| 3. Host boundaries | Steps 1–6 of [Part I §25](DEVELOPMENT_RULES.md#25-current-whisplay-migration-strategy), see [Host API](HOST_API.md#planned-host-interfaces) and [ADR 0005](ADR/0005-incremental-host-boundary-extraction.md) | Whisplay regressions intact; core contract tests run without a Whisplay checkout; temporary coupling documented | PLANNED |
| 4. Offline host | MockHost (step 7), then shared contract tests (step 8), documented recovery/diagnostic commands | Navigate, launch a fake app, stop it, inspect failure, change settings and exercise disposable package operations without a daemon or HAT | PLANNED |
| 5. Broader hardware and app services | Second adapter; notifications/permissions only when an app needs them | Second host passes shared contract tests and its own physical checklist; any permission claim has enforcement tests | PLANNED |

## Backlog from the 2026-10-02 review

Ordered by [Part I §34](DEVELOPMENT_RULES.md#34-priority-order). Each item is
also listed in [known issues](../quality/KNOWN_ISSUES.md) until fixed.

1. ~~Sideloaded folders bypass archive checks~~ — fixed 2026-10-02
   (`copy_package_dir`).
2. **Hard-coded `connectwifi` in launcher and registry logic** (§33). Needs a
   reviewed contract, e.g. a manifest or catalogue field declaring that an app
   belongs to Settings and keeps the Settings stack instead of an Opening
   screen — designed per [Part I §9](DEVELOPMENT_RULES.md#9-app-integration-contract)
   with an ADR. *Owner: registry/manifest.*
3. **Duplicated launcher and SDK code** — gestures, theme, fonts, RGB565,
   Wi-Fi/battery reads. Converge on the SDK modules where behavior is
   identical, with SDK compatibility checks. *Owner: SDK.*
4. **Manifest gaps** — validate `persist` at load time; document `branch` and
   the `app_id` alias; decide whether unknown fields warn. *Owner: manifest.*
5. ~~Dead settings~~ — removed 2026-10-02 (old files still load).
6. **`launcher/runtime.py` size** — move key routing and fallback handling
   behind the host boundaries as phase 3 proceeds; no standalone refactor.

## Decision rules

1. Lifecycle, navigation and input correctness before major features.
2. Reuse an existing service, SDK component or standard-library facility
   before adding a parallel one or a heavy dependency.
3. App-specific behavior stays in the app; a shared service needs a clear
   owner, callers and failure behavior.
4. Every design note separates required, implemented and verified behavior;
   proposals say **PLANNED**.
5. Significant architectural changes get an [ADR](ADR/README.md).
