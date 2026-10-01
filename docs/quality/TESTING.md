# Testing and validation

Run commands from the MFruit OS repository root unless noted. Use Linux for
shell, process, socket, permission and real-daemon integration behavior. A
Windows-only run can validate portable code, but it is not Linux or device
certification.

## Local checks

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --help
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --self-test
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --preview /tmp/mfruit-preview
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Self-test imports the application and renders screens without taking hardware
focus. Preview writes frames for visual review. Neither is an interactive
headless launcher or a physical test.

## Focused and integration checks

Run the narrowest relevant test first, then the full suite for shared lifecycle,
input, package or installer changes. Tests that rely on daemon semantics use
the real-daemon harness under `tests/real_daemon/`. Set `WHISPLAY_SRC` when the
compatible Whisplay checkout is not in a default test location.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_application_manager.py
PYTHONDONTWRITEBYTECODE=1 WHISPLAY_SRC=/path/to/Whisplay python3 -m unittest discover -s tests -v
```

Use the actual test module relevant to the change. Never run two real-daemon
test runs simultaneously: they share fake-app cleanup. For timing-sensitive
regressions, repeat the focused test and retain the negative control that proves
the test fails when the guard is removed. Do not claim a full-suite pass from a
focused run; list skips and unavailable dependencies.

## App package checks

From the repository root, check the exact package directory before testing it
on a device:

```bash
python3 scripts/check-app.py templates/whisplay-app-template
bash scripts/sdk-sync.sh /path/to/app --check
```

Then sideload and test the actual package through install, launch, exit, update,
failed smoke-test rollback and removal using disposable data. Static checks do
not run package hooks or certify app behavior. Follow the [app integration
guide](../apps/README.md) and [device setup guide](../DEVICE_SETUP.md).

## Hardware validation

Use [the hardware checklist](../HARDWARE_TESTS.md) on each target board. Record
button, keyboard, display, LED, audio and radio checks separately. A software
key event, screenshot, framebuffer capture or SSH health check cannot stand in
for a physical observation.

## Record results

Use the [quality report template](REPORT_TEMPLATE.md). Include revision,
platform/runtime versions, exact commands, totals, skips, logs and outstanding
manual checks. Keep the active investigation in [known issues](KNOWN_ISSUES.md)
and use dated reports for completed evidence.

[Quality index](README.md) · [OS development workflow](../os/DEVELOPMENT.md)
