# ADR 0003 — Vendored SDK distribution with drift checks

Status: Accepted in 1.3.0 (2026-09-30); recorded retroactively 2026-10-02.

## Context

Every app must handle input and look like MFruit OS. Apps run on boards
without a package index and must keep working when MFruit OS is not installed;
they cannot import the platform.

## Decision

The SDK source is `mfruitos/sdk/` (used by MFruit OS itself). Apps carry a copy
named `mfruit_sdk/`, created by `scripts/sdk-sync.sh`, with a `VENDORED` note
naming the SDK version. SDK modules use relative imports, the standard library
and Pillow only. `sdk-sync.sh --check` and `scripts/check-app.py` detect drift.
The app contract is distributed the same way (byte-identical copy at
`.claude/rules/mfruit-os-app.md`).

## Alternatives

- **pip package** — deferred: needs a package index or wheel distribution on
  every board and a release process; possible later with a migration path.
- **Import from the installed OS** — rejected: apps must run standalone and
  across OS versions.

## Consequences

Apps are self-contained and reproducible; an SDK change means syncing and
redeploying every app that needs it. Any SDK file change, even a docstring,
makes existing copies report drift, so SDK edits are batched with a version
bump.

## Compatibility

SDK 1.2.0 requires MFruit OS 1.4.0's key hub for keyboard input while the
launcher runs, and falls back to direct evdev standalone. Deploy the OS and
keyboard apps together ([SDK](../../apps/SDK.md#versions-and-compatibility)).

## Validation

`tests/test_sdk.py`, `tests/test_template.py`, `tests/test_check_app.py`; CI
runs `sdk-sync.sh --check` and `check-app.py` on the template.
