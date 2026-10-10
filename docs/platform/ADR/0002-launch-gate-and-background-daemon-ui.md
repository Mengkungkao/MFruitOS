# ADR 0002 — Launch gate tickets and the daemon UI in the background

Status: Accepted in 1.1.0 (gate) and 1.2.0 (background UI); recorded
retroactively 2026-10-02.

## Context

whisplay-daemon's own desktop is a second launcher. While an app mFruit OS
launched is starting, no app owns the screen, so the physical button belongs to
the daemon desktop, which can start another app or open a page (RC2), and the
daemon has a single pending-launch slot (RC3). The external Whisplay checkout
must not be edited.

## Decision

1. Register every managed or adopted app with `mfruit-run <id>`. While mFruit OS
   holds `state/launcher.lock`, `mfruit-run` starts an app only with a one-shot
   ticket mFruit OS writes just before its own `app.launch`; other starts are
   denied and logged.
2. Close any page or app that takes the screen during a pending launch
   (intruder eviction).
3. Start the unmodified daemon through `scripts/whisplay-daemon-mfruit.py`, which
   patches five methods so the daemon desktop draws nothing and ignores the
   button while mFruit OS runs (opt-out: `--no-background-daemon`).

## Alternatives

- **Modify whisplay-daemon** — rejected: it is an external project.
- **Longer delays around the handoff** — rejected by the rules; does not remove
  the second launcher.
- **Keep mFruit OS foreground during launches** — impossible: the daemon refuses
  `app.launch` while another app is foreground.

## Consequences

Exactly the requested app starts; a press during start-up does nothing with
the wrapper, and at worst flashes a page without it. Adopted apps' original
registrations must be saved and restored on uninstall. The wrapper depends on
daemon method names and must be tested against real daemon source.

## Compatibility

Without mFruit OS running, the gate is open and the daemon behaves as before.
Uninstall restores original registrations and the daemon desktop.

## Validation

`tests/test_launch_lifecycle.py` (real daemon, without the wrapper) and
`tests/test_background_ui.py` (real daemon with the wrapper, plus a negative
control). Physical checks: [Validation](../../quality/VALIDATION.md).
