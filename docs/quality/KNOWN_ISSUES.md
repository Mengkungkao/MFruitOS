# Known issues and validation status

Status below reflects the latest handoff recorded on **2026-10-01**. Recheck
the current checkout and its tests before treating a status as current.

## Open

### Launch-window daemon-page regression

`test_press_during_launch_window_page_is_closed` is timing-sensitive. In a
full test run it did not always capture the expected `INTRUDER` event, although
the requested app opened. A targeted rerun passed. The trace indicates that a
second hold can begin while the daemon still reports MFruit OS in front; the
existing 0.2-second delay is not a reliable handoff barrier. No lifecycle fix
was recorded in the handoff.

Next: reproduce against the real daemon, synchronize on observed ownership
state, preserve the intruder-closure assertion, and add a negative control. Do
not mask the race by extending sleeps or weakening the test. See the
[launch lifecycle record](../LAUNCH_LIFECYCLE.md) and
[current handoff](../../CONTINUE.md).

### Full suite needs a clean rerun

The Oct 1 handoff records a 347-test full run with one failure and one error,
followed by focused passing fixes. The complete suite has not subsequently
been recorded as passing. Run one real-daemon suite at a time and report skips.
Successful Pi installation and the 39-screen render self-test are not a
substitute for the full suite.

## Physical checks

Button feel and gesture handling, physical USB/Bluetooth key routing and
hotplug, LED appearance, perceived audio/radio behavior and reboot appearance
must be marked verified only after someone observes them on the relevant
hardware. See the [hardware checklist](../HARDWARE_TESTS.md); older physical
checklists remain historical until new results are recorded.

## Reporting status

Use only these distinctions in documentation and release notes:

- **Implemented:** the behavior exists in this source revision.
- **Automated:** the named test ran and its result is recorded.
- **Device verified:** the behavior was observed on a named board/build.
- **Not verified:** the check was not run or required hardware/service was absent.
- **Planned:** design intent only; do not describe it as a supported feature.

[Testing guide](TESTING.md) · [Report template](REPORT_TEMPLATE.md) · [Quality index](README.md)
