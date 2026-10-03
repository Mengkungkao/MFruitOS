# ADR 0005 — Incremental host boundary extraction

Status: Accepted 2026-10-02. Implementation PLANNED.

## Context

Only `ApplicationManager.Host` is a formal host interface. Focus, frame
output, input, LED, backlight, battery and process stop call concrete Whisplay
classes from several modules ([Host API](../HOST_API.md)). MFruit OS cannot run
on another host or a MockHost, and contract tests run only against
whisplay-daemon.

## Decision

Extract host boundaries one at a time in the order of
[Part I §25](../DEVELOPMENT_RULES.md#25-current-whisplay-migration-strategy):
formalize interfaces around existing behavior, put daemon transport behind a
`WhisplayHost`, then focus, input, display, indicators/power, then a MockHost
and shared contract tests. Each step:

- keeps the Whisplay path working and its real-daemon tests passing;
- introduces an interface only with at least the Whisplay implementation and a
  test double;
- moves code only when the step needs it (no tree reshuffle for its own sake);
- records remaining coupling in [Architecture](../ARCHITECTURE.md).

## Alternatives

- **Rewrite around a host abstraction** — rejected: risks the verified launch
  lifecycle and violates Part I §1.
- **Build a MockHost first** — rejected: without formal interfaces the mock
  would copy Whisplay internals and drift.

## Consequences

Progress is slower but every step is shippable and reversible. Temporary
duplication between old call sites and new interfaces is allowed while a step
is in progress and must be documented.

## Compatibility

No app-visible change is intended. Apps keep the whisplay-daemon integration
contract until an App API step says otherwise, with migration notes.

## Validation

Per step: the existing real-daemon suite, new interface contract tests, and —
from step 8 — the same contract tests passing against WhisplayHost and
MockHost.
