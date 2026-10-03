# Regression policy

Every confirmed bug fix gets a regression test when technically possible
([Part I §18](../platform/DEVELOPMENT_RULES.md#18-regression-policy)).

## What a regression test must show

1. **Negative control:** the test fails when the fix or guard is absent. Show
   it once — revert the fix locally or patch the guard out in a scratch run —
   and note the result in the bug record or validation record.
2. **Positive result:** the test passes with the fix.
3. **Stability:** timing-sensitive tests pass repeatedly (record the count).

## Rules

- **Never weaken a valid assertion** to obtain a green run. If an assertion
  depends on a precondition the test cannot guarantee, make the precondition
  explicit and observable; skip with a precise reason only when the behavior
  under test is covered deterministically elsewhere.
- **No sleeps as synchronization.** Wait on observable state (daemon
  foreground/pending state, session state, files written, log lines). Fixed
  sleeps are acceptable only to let unwanted effects show up *after* the
  synchronized point (for example "nothing else launched within 1 s").
- **Daemon semantics are tested against the real daemon** (`tests/real_daemon/`);
  the fake daemon is only for behavior it models faithfully.
- **Name the root cause.** A regression test references the defect it guards
  (for example RC1–RC6 in [Lifecycle](../platform/LIFECYCLE.md#root-cause-history)).
- A flaky test is a bug: investigate it with evidence and record it in
  [known issues](KNOWN_ISSUES.md) until fixed.

## Example: launch-window page test (2026-10-02)

The test failed in 25% of runs. A daemon trace showed the hold was recognized
as a tap by whisplay-daemon (not an MFruit OS fault). The fix synchronized on
the observed launch window, retried while the desktop selection stays on a
daemon page, and added a deterministic variant. Negative control: with
intruder eviction patched out, both tests fail; with it, 20/20 iterations pass
([record](records/2026-10-02-baseline-and-launch-window.md)).
