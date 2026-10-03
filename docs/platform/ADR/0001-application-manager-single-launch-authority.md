# ADR 0001 — ApplicationManager is the single launch authority

Status: Accepted in 1.1.0 (2026-09-29); recorded retroactively 2026-10-02.

## Context

In 1.0.0 several sources could start apps: the Home screen, autostart, the
control socket and a stale *Retry*. Overlapping launches started the wrong app
or several apps (RC4), and the launcher "followed" whatever took the screen,
which hid other defects (RC5). See [Lifecycle](../LIFECYCLE.md#root-cause-history).

## Decision

`mfruitos/core/application_manager.py` owns every launch session. It allows one
session at a time, refuses (never queues) requests while busy, gives every
session an ID, drops host reports for other sessions (`STALE_EVENT`) and logs
each transition on `mfruitos.lifecycle`. It knows nothing about Whisplay; the
host implements `start`/`stop` and reports back.

## Alternatives

- **Queue requests** — rejected: a queued launch can fire long after the user
  stopped wanting it.
- **Let the UI call the daemon directly** — rejected: no single place to enforce
  single flight or attribute failures.
- **Follow the foreground app** — rejected: masks wrong launches (RC5).

## Consequences

One place to reason about launches; launches are testable without hardware;
a refused request is visible in the log with its source. The UI must check
`apps.busy` and handle refusals.

## Compatibility

No app-visible change. Apps started outside MFruit OS while it is idle are
adopted as `external` sessions.

## Validation

`tests/test_application_manager.py` (host-independent) and the real-daemon
suite `tests/test_launch_lifecycle.py` (`test_duplicate_launch_is_prevented`,
`test_stale_event_is_ignored`).
