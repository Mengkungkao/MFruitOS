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
  settings writes are atomic; installs never overwrite the running version.
- **Every screen answers:** where am I, what is selected, what happens when I
  press, how do I go back.

## Development setup

```bash
python3 -m unittest discover -s tests          # ~140 tests, no hardware needed
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
3. Add or update tests — every fixed bug gets a regression test.
4. Test on hardware when the change touches the display, button, LED, audio
   or the daemon, and say in the PR what was and was not verified on hardware.
5. Update the docs and `CHANGELOG.md` when behaviour changes.

Commit messages: `feat: …`, `fix: …`, `test: …`, `docs: …`.

## Code style

Python 3.9+ compatible (the Orange Pi image ships 3.10), type hints where they
help, small functions, specific exceptions (no bare `except: pass`), and
logging instead of prints. Match the surrounding code.
