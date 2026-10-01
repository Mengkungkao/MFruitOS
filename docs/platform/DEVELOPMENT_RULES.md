# OS engineering rules and workflow

These are the canonical development rules for MFruit OS contributors and
coding agents. [Architecture](../ARCHITECTURE.md) describes the current code;
[Direction](DIRECTION.md) separates implemented capability from future work.
Follow [app integration](../apps/README.md) for independent app development.

## Ownership and boundaries

- Keep core logic hardware-independent when possible. Hardware access belongs
  behind the existing daemon client/host boundary; isolate new platform-specific
  work so it can move into a future adapter.
- On today's host, whisplay-daemon owns LCD, button, LED, backlight and focus.
  Use `mfruitos/daemon/client.py` for launcher requests. Do not add GPIO/SPI or
  direct framebuffer drivers to screens, package code or independent apps.
  The documented exception is `launcher/direct.py`, which displays recovery UI
  only when the daemon service is inactive or failed, never while it is starting.
- Do not edit the external Whisplay checkout to customize the platform. Extend
  `scripts/whisplay-daemon-mfruit.py` and test the wrapper against compatible
  real daemon source. Preserve normal daemon behavior when MFruit OS is absent
  or the user deliberately chooses Daemon desktop.
- The UI and CLI call the same service operations. Screens request actions;
  they do not own package installation, process creation or update policy.
- Reuse the current implementation and migrate gradually. Preserve working
  functionality and user state; do not perform a blind rewrite.

## Lifecycle, navigation and input invariants

1. **One launch authority.** All launch requests go through
   `ApplicationManager.request_launch(app_id, kind, source)`. It refuses rather
   than queues requests while a session exists. The host executes the request.
2. **Selection is separate from launching.** Moving a list selection, rendering,
   refreshing the registry, installing an app or checking updates must not
   launch an app. Only an explicit confirmation or configured autostart may
   request it. Newly installed apps have autostart disabled.
3. **Stable identity.** Use the immutable manifest ID, not menu position,
   display name, filename or PID. Every launch creates a new session ID;
   stale timers, process reports and cleanup must not affect a later session.
4. **One foreground session.** The implemented lifecycle is
   `IDLE → STARTING → RUNNING → STOPPING → IDLE`, with failure/exit outcomes
   recorded on the session. Registry enabled/installed flags are separate.
   Do not treat the broader state lists in old design notes as implemented enums.
5. **Consume the complete gesture before handoff.** A long press arms at the
   threshold, shows feedback, and selects on release. Never let an old press,
   release or repeat activate the next screen owner.
6. **Respect the launch gate.** Keep one-shot tickets, the launcher lock,
   background daemon desktop and intruder eviction. An unexpected foreground
   app during a pending launch must not be adopted as the requested app.
   Adopting an existing external foreground app while idle is a separate recovery
  path. See [launch lifecycle evidence](../LAUNCH_LIFECYCLE.md).
7. **Close apps after exit unless Keep running is set.** Allow the exit request
   and 3-second grace period, then stop the matching process group with SIGTERM,
   followed by SIGKILL after 2 seconds if needed. Use the matching session's
   `state/runs/<id>.json`, not a stale PID; log the result. Current ownership is
   `AppLifecycle` and `mfruit-run`, not a nonexistent `ProcessManager` class.
8. **Keep keyboard ownership coherent.** The launcher grabs keyboards through
   the SDK and routes keys through the hub. Each press, repeat and release stays
   with the press's original foreground owner. Apps pass their immutable ID to
   `InputController` and retain their own focus/stray-release checks. Direct
   evdev is a standalone fallback when the hub is unavailable.

Keep the navigation screen stack, focus state and application session explicit.
No event should produce duplicate actions or replay a queued launch later.
Do not hide a race with longer debounce windows or arbitrary sleeps: establish
the missing ownership or state condition and test it.

## UI, workers and resources

- Render from state: no app launches/stops, subprocesses, network requests,
  installs or persistent configuration changes inside drawing methods.
- Keep blocking work off the UI thread. Use `run_task` for lookups and
  `start_job` for install/update work; post results back to the event loop.
  Preserve serialized package jobs and the separate Bluetooth and cleanup lanes.
- Avoid multiple threads mutating foreground, registry or package state.
  Application lifecycle decisions belong to their single owner on the loop.
- Avoid continuous polling and unnecessary redraws, writes or animation. Use
  events, blocking readers and scheduled timers. The bounded launch monitor is
  an intentional exception because the daemon has no early-launch-failure event;
  retain its bounds and cancellation. Bounded cleanup checks are another
  purposeful exception, not a general polling pattern.
- Keep dependencies small. Prefer Python's standard library and Pillow; justify
  additions with target-device support, maintenance, RAM and startup costs.
- Log failures and recovery decisions. Catch specific exceptions where possible;
  a broad catch must have a documented boundary and must not silently hide an
  operational failure. An app failure must not crash unrelated apps or the launcher.

Use the shared [UI and code style](STYLE.md). Every screen should make its
location, selected action and way back clear.

## Packages, configuration and user data

- Keep package code, app data, configuration, cache, logs and temporary downloads
  separate. Never install over the active version.
- Preserve the update stages: check, download, verify, backup, install, test,
  activate. On failed installation restore the previous code/data as supported
  by the installer. Manual rollback does not promise to reverse all data migrations.
- Validate IDs, manifests, minimum OS version, entrypoint containment, archive
  contents and integrity metadata before activation. Use HTTPS and existing
  verifier/path helpers. Platform and dependency compatibility must be checked
  by the integration/release workflow; do not claim a generic architecture or
  permissions validator that does not exist.
- Use `updater/rollback.safe_rmtree` for managed Python deletion paths and verify
  containment in shell tooling. A package must not write arbitrary system files.
  Uninstall/data removal must follow the visible retention/removal choice.
- Write settings atomically. Preserve malformed input as evidence, log the error
  and load safe defaults; never silently overwrite the only copy of user settings.
- Disabling an app is not uninstalling it. Retain its files and data, hide it from
  normal launching, and allow re-enabling through Settings.
- Treat downloads as untrusted. Package checks reduce risk but do not sandbox a
  running app; never present future capability permissions as current enforcement.

## Local development

Use a full checkout with Python 3.9+ and Pillow. Linux/WSL is needed for the
Linux process, socket, shell and daemon integration paths. A Windows IDE can
edit the repository; Windows-only results are not Linux/device certification.
The commands below run from the repository root in a Linux shell:

```bash
python3 -m mfruitos --help
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --self-test
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --preview /tmp/mfruit-preview
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Self-test imports modules and renders screens offline; preview writes PNGs.
Neither is an interactive headless launcher or physical hardware test.
Real-daemon tests need a compatible Whisplay source tree; see
[Testing](../quality/TESTING.md) for `WHISPLAY_SRC`, skipped coverage and test
selection. **Never run two real-daemon suites at once:** they share fake-app
cleanup. The full suite is not currently recorded as green; consult
[Known issues](../quality/KNOWN_ISSUES.md) before reporting a baseline pass.

For a live launcher use [Device setup](../DEVICE_SETUP.md). Stop its systemd
service before starting `python3 -m mfruitos --debug`, keep the daemon running,
then restore the service when finished. Use `--home` for an isolated runtime
data directory, but do not assume it isolates hardware or the real daemon.

The SDK source of truth is `mfruitos/sdk/`. Change it here, run its tests, then
sync vendored `mfruit_sdk` copies with `scripts/sdk-sync.sh`; `--check` detects
stale copies. SDK modules use relative imports, support Python 3.9 and need
only Pillow for UI. Idle input must block rather than poll. Deploy compatible
launcher, wrapper and keyboard-app SDK versions together.

## Change workflow

1. Read the current handoff, known issues and relevant source/tests. Identify
   the owning component and preserve unrelated local edits.
2. For a bug, reproduce it, capture logs/state/process evidence, separate the
   observation from a proposed explanation, then identify the actual cause.
3. Make the smallest coherent change. Keep refactors and unrelated features in
   separate changes. A future architecture goal is not authorization to remove
   working behavior.
4. Add a meaningful regression for a bug fix and relevant contract tests for new
   behavior. For daemon-dependent fixes test real daemon behavior, including a
   negative control that fails without the guard. Do not weaken an assertion to
   obtain a passing result.
5. Run focused checks, then the broader checks appropriate to the change.
   Repeat timing-sensitive suites before declaring them stable. Report failures
   and skips; do not substitute a self-test or targeted pass for a full-suite pass.
6. For hardware changes, record each board's display/button/keyboard/LED/audio/
   power checks as verified or not verified using the
  [hardware checklist](../HARDWARE_TESTS.md).
7. Update the canonical behavior/architecture/app contract as appropriate,
   `CHANGELOG.md` for user-visible changes, the quality record for evidence and
   `CONTINUE.md` for the next handoff. Do not duplicate the entire evidence log
   across guides.

Use focused commit messages such as `feat: ...`, `fix: ...`, `test: ...` and
`docs: ...`. A useful review explains the concrete problem, behavior after the
change, validation and remaining limits.

## Definition of done

A code change is complete when its behavior is implemented, errors are handled,
useful state changes are logged, relevant unit/integration/regression checks
pass and the affected documentation is current. Core behavior should be tested
without physical hardware; platform-specific behavior also needs host tests.
Record any unverified hardware path explicitly. Documentation-only changes need
source/command/link review; they do not require new runtime tests.

Stress goals for lifecycle work include 100 navigation events, 100 confirmations,
50 launches, 20 crashes, 10 daemon reconnects and 10 failed installs/updates.
After each scenario verify valid registry/configuration, a live launcher, no
orphan process, no duplicate foreground app and coherent lifecycle state. These
are validation targets, not a claim that an automated stress suite already
implements every count. Full hardware independence is a roadmap milestone, not
a completed property to tick for today's Whisplay runtime.

[OS development](README.md) · [App integration](../apps/README.md) · [Quality](../quality/README.md)
