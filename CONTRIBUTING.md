# Contributing to MFruit OS

Thanks for helping. MFruit OS targets a 512 MB Raspberry Pi Zero 2 W with one
button, so every change is judged by: does it stay light, robust and usable
with a single button? The detailed engineering rules are in
[CLAUDE.md](CLAUDE.md); the short version is below.

## Ground rules

- **The daemon owns the hardware.** Talk to whisplay-daemon only through
  `mfruitos/daemon/client.py`. Do not add GPIO/SPI access (the one documented
  exception is `launcher/direct.py`, used only while the daemon is stopped).
- **No new dependencies** without a strong reason. Standard library + Pillow.
- **No polling loops.** Use the event loop's timers and daemon events.
- **No blocking work on the UI thread.** Network, disk-heavy and subprocess
  work goes through `run_task` / `start_job`.
- **Never destroy user state.** Deletions go through `updater/rollback.safe_rmtree`;
- **Preserve user state by default.** Destructive actions require explicit
  confirmation; deletions go through `updater/rollback.safe_rmtree`, settings
  writes are atomic, and installs never overwrite the running version.
- **Every screen answers:** where am I, what is selected, what happens when I
  press, how do I go back.
- **Keep lifecycle authority centralized.** Selection does not launch; only an
  explicit action reaches the ApplicationManager, and rendering stays free of
  lifecycle and storage side effects.

## Development setup

```bash
python3 -m unittest discover -s tests          # full unit suite, no hardware needed
python3 -m mfruitos --preview /tmp/screens     # render every screen to PNG
python3 -m mfruitos --self-test                # what system updates run
```

Run the full launcher against a real daemon on a device:

```bash
scripts/deploy.sh pi@<device-ip>               # copy + install + restart service
ssh pi@<device-ip> mfruitctl status
```

`tests/fake_daemon.py` reproduces the whisplay-daemon semantics MFruit OS
relies on (focus refusal, pending launches, global-only desktop events…) so
integration tests run anywhere.

## Changes

1. Inspect the relevant code first; reuse what exists.
2. Keep changes small and focused; do not mix refactoring with features.
3. Reproduce bugs with evidence; do not mask timing or state defects with
    arbitrary sleeps.
4. Add or update tests — every fixed bug gets a regression test. Changes that
    depend on whisplay-daemon behavior need real-daemon coverage and a negative
    control; do not run real-daemon suites concurrently because they share
    cleanup state.
5. Test on hardware when the change touches the display, button, LED, audio
   or the daemon, and say in the PR what was and was not verified on hardware.
6. Update the docs and `CHANGELOG.md` when behaviour changes.

Commit messages: `feat: …`, `fix: …`, `test: …`, `docs: …`.

## Validation

The no-hardware unit and preview checks above are the baseline. Run the
relevant regression tests for the changed behavior, then the full suite when
practical. Report hardware checks as verified or not verified; automated tests
do not certify physical behavior.

## Code style

Python 3.9+ compatible (the Orange Pi image ships 3.10), type hints where they
help, small functions, specific exceptions (no bare `except: pass`), and
logging instead of prints. Match the surrounding code.
