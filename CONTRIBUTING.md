# Contributing to mFruit OS

mFruit OS targets a 512 MB Raspberry Pi Zero 2 W with one button, so every
change is judged by whether it stays light, deterministic, recoverable and
usable with a single button. The binding rules are in
[docs/platform/DEVELOPMENT_RULES.md](docs/platform/DEVELOPMENT_RULES.md);
this page is the quick start.

## From clone to submitted change

1. **Clone and install prerequisites** (Linux, Python 3.9+, Pillow):

   ```bash
   git clone https://github.com/Mengkungkao/MFruitOS.git && cd MFruitOS
   sudo apt-get install python3 python3-pil git   # or: pip install Pillow
   ```

   The real-daemon contract tests use the Whisplay daemon bundled in
   `drivers/whisplay` ([Whisplay driver](docs/WHISPLAY_DRIVER.md)); nothing
   else needs cloning.

2. **Run the checks:** `bash scripts/check.sh` (the same as CI;
   [Testing](docs/quality/TESTING.md)).
3. **Preview the UI:** `python3 -m mfruitos --preview /tmp/mfruit-preview`
   writes every screen as PNG.
4. **Understand the architecture:** [Architecture](docs/platform/ARCHITECTURE.md),
   [Lifecycle](docs/platform/LIFECYCLE.md), [Host API](docs/platform/HOST_API.md).
5. **Make a focused change:** read [CONTINUE.md](CONTINUE.md) and
   [known issues](docs/quality/KNOWN_ISSUES.md); find the owner; keep
   refactors separate from features; add a regression test with a negative
   control for every fix ([Regression policy](docs/quality/REGRESSION_POLICY.md)).
6. **Validate:** `bash scripts/check.sh`; real-daemon tests for daemon
   semantics; device checks for display, button, keyboard, LED, audio or
   lifecycle changes, reported as verified or not verified
   ([Validation](docs/quality/VALIDATION.md)).
7. **Submit:** update the canonical doc, `CHANGELOG.md` for user-visible
   changes and a dated record for evidence. Commit messages: `feat: …`,
   `fix: …`, `test: …`, `docs: …`, `ci: …`. Describe the problem, the behavior
   after the change, the validation performed and what was not verified.

To try a change on a device: [Installation](docs/platform/INSTALLATION.md)
(copy to a candidate directory, `setup-device.sh --check`, install, verify).

## Ground rules (short form)

- whisplay-daemon owns the hardware today; talk to it only through
  `mfruitos/daemon/` (the recovery display in `launcher/direct.py` is the one
  documented exception).
- Only `ApplicationManager` launches apps; selection and rendering never do.
- No polling where events exist, no blocking work on the UI thread, no sleeps
  to hide races.
- Standard library and Pillow; justify any new dependency.
- Never destroy user state: atomic settings writes, `safe_rmtree`, no install
  over the running version, destructive actions confirmed.
- Every screen answers: where am I, what is selected, what happens on
  confirm, how do I go back.

## Code style

Python 3.9-compatible, type hints where they clarify, small functions,
specific exceptions, module loggers; match the surrounding code
([Style guide](docs/platform/STYLE_GUIDE.md)).
