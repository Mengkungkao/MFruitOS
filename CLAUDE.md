# MFruit OS — Development, Testing, Debugging & Architecture Rules

## 1. Project Mission

You are developing **MFruit OS**, a lightweight, modular, hardware-independent application platform designed primarily for small Linux-based devices.

MFruit OS is an **application operating environment**, not a hardware-specific application.

Its primary hardware target is currently the **PiSugar Whisplay Display HAT**, but Whisplay is only one supported hardware platform.

The core MFruit OS must not depend on the Whisplay repository, Whisplay daemon, or any other external hardware-specific framework.

The architecture must be:

```text
┌──────────────────────────────────────────────┐
│                 MFruit OS                   │
│                                              │
│  Home / Launcher                             │
│  Settings                                    │
│  App Manager                                 │
│  Package Manager                             │
│  Updater                                     │
│  Diagnostics                                 │
│  Notifications                               │
│  System Information                          │
│                                              │
├──────────────────────────────────────────────┤
│                MFruit CORE                  │
│                                              │
│  Navigation State Machine                   │
│  Input/Event Manager                         │
│  Application Registry                        │
│  Application Lifecycle                       │
│  Process Manager                             │
│  Package Engine                              │
│  Update Engine                               │
│  Configuration                               │
│  Storage                                     │
│  Logging                                     │
│  Event Bus                                   │
│                                              │
├──────────────────────────────────────────────┤
│            HARDWARE ABSTRACTION              │
│                                              │
│  Display Adapter                             │
│  Input Adapter                               │
│  LED Adapter                                 │
│  Audio Adapter                               │
│  Power Adapter                               │
│                                              │
├──────────────────────────────────────────────┤
│              LINUX / OS LAYER                │
└──────────────────────────────────────────────┘
```

The core principle is:

```text
MFruit Core
    ≠
Hardware
    ≠
Application
    ≠
UI
```

Each layer must have clear ownership.

---

# 2. Project Identity

The official project name is:

**MFruit OS**

Do not call the core project:

* Whisplay OS
* Whisplay Shell
* Whisplay Platform
* Whisplay App OS

Whisplay is only a supported hardware adapter.

Examples:

```text
MFruit OS
MFruit OS Launcher
MFruit OS Package Manager
MFruit OS Updater
MFruit OS App
MFruit OS Hardware Adapter
```

Whisplay-specific components may use names such as:

```text
WhisplayDisplayAdapter
WhisplayInputAdapter
WhisplayAudioAdapter
WhisplayLEDAdapter
```

These belong under the hardware abstraction layer.

---

# 3. Fundamental Architecture

Applications communicate with the MFruit OS platform rather than directly accessing hardware.

Correct:

```text
Application
     ↓
MFruit App API
     ↓
MFruit Core
     ↓
Hardware Adapter
     ↓
Hardware
```

Incorrect:

```text
Application
     ↓
GPIO / framebuffer / Whisplay daemon
     ↓
Hardware
```

Application developers should not need to know whether the device is using:

* Whisplay
* another LCD
* terminal mode
* desktop Linux
* another embedded display
* another input device

---

# 4. Standalone Requirement

MFruit OS must be independently buildable and runnable.

The project must not require:

```text
PiSugar/Whisplay GitHub repository
Whisplay source tree
Whisplay daemon source code
Whisplay-specific Python modules
Whisplay-specific repository layout
```

to run the MFruit OS core.

Whisplay integration must exist only as an adapter.

The following should remain possible:

```bash
mf-os --headless
```

or equivalent development mode.

The exact command may differ, but the principle is mandatory.

The core must work without physical hardware.

---

# 5. Existing Project Must Be Preserved

Do not throw away the current implementation.

First inspect the existing code and identify:

```text
working functionality
reusable modules
hardware-specific code
architectural problems
duplicated responsibilities
launching bugs
process lifecycle problems
navigation bugs
```

Migrate useful functionality gradually.

Do not perform a blind rewrite.

Do not delete working functionality simply because it is currently implemented in the wrong place.

## Current state of the migration (MFruit OS 1.1.0)

Already hardware-independent and tested without hardware:

```text
mfruitos/core/application_manager.py   launch authority, sessions, lifecycle log
mfruitos/apps/                         manifest validation, registry
mfruitos/updater/                      GitHub, versions, verifier, installer, rollback
mfruitos/system/settings.py            configuration
```

Still Whisplay-bound and to be moved behind adapters (Milestone 2):

```text
mfruitos/launcher/focus.py        screen hand-over through whisplay-daemon (the Whisplay host)
mfruitos/daemon/                  whisplay-daemon client, events, framebuffer
mfruitos/launcher/runtime.py      wires the daemon directly
mfruitos/system/hardware.py       backlight / LED through the daemon
mfruitos/launcher/direct.py       fallback display via WhisplayBoard
```

Move these one at a time, keeping every test green, rather than rewriting.

---

# 6. Launch Lifecycle Bugs — Root Causes and Guards

The 1.0.0 system opened wrong apps, opened several apps, closed daemon pages
instantly and let old input reach new apps. These were **architecture and
state-management problems**, found with evidence (device logs and the real
daemon code) and fixed in 1.1.0. Full record: `docs/LAUNCH_LIFECYCLE.md`.

| # | Root cause | Guard that must stay in place |
|---|---|---|
| RC1 | A hold fired while the button was still down; the release reached the next screen owner (the daemon's desktop launched *its* selection, daemon pages took it as "select", apps got a stray release). | A hold arms at the threshold and **fires on release** (§16). |
| RC2 | While an app starts up, no app owns the screen and whisplay-daemon's own desktop handles the button — a second launcher. | Daemon UI in the background (§23); launch tickets in `mfruit-run`; intruders closed. |
| RC3 | The daemon has a single pending-launch slot; a second launch blocks the first app. | Single flight in the ApplicationManager; nothing else may launch. |
| RC4 | No single-flight rule: autostart, control socket and Retry could overlap. | ApplicationManager refuses (never queues) requests while a session exists. |
| RC5 | A "follow whatever took the screen" patch masked RC1. | A foreign app during a launch is an intruder, never adopted as intended. |

Rules learned:

* Do not hide such problems with arbitrary sleeps or random delays.
* Find the actual root cause from evidence before changing code; a plausible
  explanation that was not verified (the 1.0.0 "hand-off" theory) is not a root cause.
* A test double that does not model the real component's behaviour hides bugs:
  lifecycle tests must run against the real whisplay-daemon code (§38).

---

# 7. Deterministic Navigation

The navigation system must be an explicit state machine.

Example:

```text
HOME
  ↓
SELECTING
  ↓
SELECTED
  ↓
LAUNCH_REQUESTED
  ↓
STARTING_APP
  ↓
APP_RUNNING
  ↓
STOPPING_APP
  ↓
HOME
```

A normal navigation event must not directly execute an application.

Correct:

```text
Input
 ↓
Navigation Controller
 ↓
UI State
 ↓
Confirmed Action
 ↓
Application Manager
 ↓
Process Manager
```

Incorrect:

```text
Button Press
 ↓
launch_app()
```

---

# 8. Selection Is Not Launching

The selected application and running application are separate states.

Example:

```text
Selected App:
weather

Running App:
music
```

must be valid platform state during navigation.

Moving the selection must never launch the newly selected application.

Only an explicit confirmation action may request a launch.

A UI redraw must never cause a launch.

An app list refresh must never cause a launch.

An app installation event must never cause a launch.

An updater event must never cause a launch.

---

# 9. One Authoritative Application Manager

Only `ApplicationManager` may request application launches.

No other component may directly launch applications.

Use a single authoritative interface such as:

```python
ApplicationManager.launch(app_id)
```

The following must never independently launch an app:

```text
UI Renderer
Launcher Screen
Settings
Updater
Event Handler
App Registry
GitHub Client
Hardware Adapter
```

They may request an action through the proper service.

---

# 10. Stable Application IDs

Every application must have an immutable unique ID.

Example:

```json
{
  "id": "bitcoin",
  "name": "Bitcoin"
}
```

Application IDs must not depend on:

```text
screen position
list index
display name
PID
filename
menu position
```

An app's name may change.

Its ID must remain stable.

---

# 11. Application Lifecycle

Every application must have explicit lifecycle states:

```text
INSTALLED
DISABLED
READY
STARTING
RUNNING
STOPPING
STOPPED
FAILED
UPDATING
```

Only valid transitions are allowed.

Example:

```text
READY
 ↓
STARTING
 ↓
RUNNING
 ↓
STOPPING
 ↓
READY
```

Invalid transitions must be rejected and logged.

Never allow uncontrolled repeated transitions such as:

```text
STARTING
STARTING
STARTING
STARTING
```

---

# 12. Single Foreground Application

MFruit OS must maintain one authoritative foreground application.

At any point:

```text
0 or 1 foreground application
```

The launcher is foreground when no app is running.

Never allow accidental parallel foreground applications.

If multi-instance applications are added in the future, they must explicitly declare support for multiple instances.

---

# 13. Process Manager

Create a dedicated `ProcessManager`.

Responsibilities:

```text
start()
stop()
terminate()
restart()
is_running()
get_status()
get_pid()
```

No application should be launched using unmanaged `subprocess` calls scattered throughout the project.

Every process must belong to a known application and session.

Track:

```text
app_id
pid
session_id
start_time
state
exit_code
```

## Exit policy

When the user leaves an application it must be **closed completely**:

```text
app leaves the screen
      ↓
exit request (the app should quit by itself)
      ↓
grace period (3 s)
      ↓
SIGTERM to the app's process group → 2 s → SIGKILL
```

Only apps marked **Keep running** (per-app setting; a manifest may default it
with `"background": true`) are left running. Log the result
(`APP_CLOSED app=… result=exited|terminated|killed`).

On the Whisplay platform the daemon starts the process through the
`mfruit-run` gate, which records `pid`, `session` and `exit_code` in
`~/.whisplay-os/state/runs/<id>.json`; only a record with the ending
session's id may be used.

---

# 14. Application Session IDs

Every launch creates a unique session ID.

Example:

```text
app_id: bitcoin
pid: 1842
session_id: 48c2d0...
```

A process event must be matched against both:

```text
app_id
session_id
```

Do not rely on PID alone.

This prevents stale process events from affecting a newly launched application.

---

# 15. Input Architecture

There must be one authoritative input pipeline:

```text
Physical Input
      ↓
Input Adapter
      ↓
Input Manager
      ↓
Normalized Event
      ↓
Event Bus
      ↓
Navigation Controller
```

Applications must not independently read the physical button or input hardware unless they are explicitly given permission to do so.

The platform owns global navigation input.

## Keyboards and apps (1.3.0)

* whisplay-daemon hands keys only to its own pages (and closes an external app
  on Esc unless it registers `disable_esc_exit_key`). So MFruit OS and every
  MFruit app read USB / Bluetooth keyboards themselves, through
  `mfruitos/sdk/keys.py`. Nobody grabs the device: **every process sees every
  key**. The guard is ownership: a reader acts only while its program owns the
  screen, and only on keys whose press it saw while it did (the key-up of the
  Esc that closed an app, or the repeat of the Enter that opened one, must not
  act in the next owner — the keyboard form of RC1).
* Apps get the platform's controls through the MFruit App SDK
  (`mfruitos/sdk/`, vendored as `mfruit_sdk` by `scripts/sdk-sync.sh`):
  `InputController` is the one interpreter of the button and keyboard in an
  app. The contract apps follow is `docs/APP_RULES.md` (also each app's
  `.claude/rules/mfruit-os-app.md`). Change the SDK only here, with
  `tests/test_sdk.py`, then re-sync every app (`--check` finds stale copies).
* SDK modules use relative imports only (tested), run on Python 3.9 and need
  only Pillow (UI). Nothing in the SDK may poll while idle: the button worker
  sleeps until an edge, the keyboard reader waits on inotify.

---

# 16. Input Events

Normalize hardware-specific events.

For example:

```json
{
  "type": "CLICK",
  "timestamp": 123456789,
  "sequence_id": 42
}
```

Possible events:

```text
CLICK
DOUBLE_CLICK
LONG_PRESS
BACK
SYSTEM
```

The final event definitions should be based on actual platform requirements.

A long press is **armed** when the threshold is reached (show feedback such as
"Release to open") and **fires on release**. An input gesture must be fully
consumed by its current owner before the screen changes owner; otherwise the
rest of the gesture (the release) is delivered to the next owner.

Every event must have:

```text
type
timestamp
sequence_id
```

where practical.

---

# 17. Exactly-Once Event Processing

A single physical event must not produce multiple application actions.

Prevent:

```text
duplicate click processing
event replay
stale events
multiple subscribers launching the same app
queued actions executing after state changes
```

Do not solve this only through increasing debounce delays.

Implement event ownership and state validation.

---

# 18. Renderer Must Be Side-Effect Free

UI rendering may:

```text
read state
draw state
refresh display
```

UI rendering must not:

```text
launch applications
stop processes
modify app registry
execute shell commands
install software
change system configuration
```

Correct:

```text
State
 ↓
Renderer
 ↓
Display
```

Incorrect:

```text
Renderer
 ↓
launch_app()
```

---

## Screen layout conventions

```text
┌────────────────────────────┐
│ Apps              ᯤ  ▭ 82% │   status bar: page name left, WiFi strength + battery right
│ ┌────────────────────────┐ │
│ │ [MS] Messenger          │ │   selected item: card with icon and status line
│ │      Running            │ │
│ └────────────────────────┘ │
│  [WT] WalkieTalkie          │
│  ─────────────────────────  │
│  tap next  hold open  2× prev │ footer: gestures for this screen
└────────────────────────────┘
```

* The page name lives in the status bar; screens do not draw a second title row.
* No product name or clock in the status bar.
* Long titles belong in the content as a heading; the bar gets a short label
  ("Confirm", "Update").
* Scroll lists in whole rows; never leave a half-cut row under the status bar.
* Starting an app shows MFruit OS's own "Opening <App>" screen, drawn before
  the screen is handed over and kept up until the app draws its first frame.

---

# 19. Application Registry

The application registry belongs to MFruit OS.

Example:

```text
data/
├── apps/
├── registry.json
├── config/
├── cache/
├── updates/
├── backups/
├── logs/
└── temporary/
```

Every app must have metadata.

Example:

```json
{
  "schema_version": 1,
  "id": "weather",
  "name": "Weather",
  "version": "1.2.0",
  "enabled": true,
  "entrypoint": "run.sh",
  "repository": "https://github.com/example/weather",
  "minimum_platform_version": "1.0.0"
}
```

A broken app manifest must not prevent other applications from loading.

---

# 20. App Enable / Disable

Disabling an application does not uninstall it.

Example:

```text
Installed: YES
Enabled: NO
```

Disabled applications:

* remain installed
* retain configuration
* do not appear in the normal launcher
* cannot be launched
* can be re-enabled through Settings

---

# 21. Autostart

Applications must never autostart by default.

Default:

```text
autostart = false
```

Only explicitly configured applications may autostart.

Autostart must not be triggered accidentally by:

* refresh
* reboot state
* app installation
* app update
* launcher redraw
* GitHub check
* registry reload

---

# 22. Hardware Abstraction

Create generic interfaces:

```python
class DisplayAdapter:
    def initialize(self): ...
    def render(self, frame): ...
    def clear(self): ...


class InputAdapter:
    def initialize(self): ...
    def read_events(self): ...


class LEDAdapter:
    def set_state(self, state): ...


class AudioAdapter:
    def play(self, audio): ...


class PowerAdapter:
    def get_status(self): ...
```

The exact API may evolve, but ownership must remain clear.

---

# 23. Whisplay Adapter

Whisplay is one hardware implementation.

Example:

```text
hardware/
├── base/
├── whisplay/
├── framebuffer/
├── terminal/
└── mock/
```

The Whisplay adapter may communicate with the existing Whisplay daemon where needed.

However:

```text
MFruit Core must not depend on Whisplay
```

Only:

```text
Whisplay Adapter → Whisplay interface
```

may know about Whisplay-specific implementation details.

## Whisplay platform as built (1.1.0)

* **whisplay-daemon is a background hardware service.** It owns the LCD,
  button, LED, backlight and app focus. MFruit OS is the only user interface.
* **The daemon's own UI runs in the background.** `scripts/whisplay-daemon-mfruit.py`
  starts the unmodified daemon (systemd drop-in
  `whisplay-daemon.service.d/mfruit-os.conf`, written by `install.sh`). While
  MFruit OS runs it stops the daemon drawing its desktop / "Opening app…" modal,
  ignores the button when no app owns the screen, and shows the last owner's
  final frame on hand-over. When MFruit OS is not running, or the user picks
  Developer → "Daemon desktop", the daemon behaves normally. Never edit the
  Whisplay checkout itself; extend the wrapper instead.
* **Launch gate.** Every app the daemon can start is registered with
  `~/.whisplay-os/bin/mfruit-run <id>` (MFruit packages, and daemon apps MFruit
  OS *adopts*; originals in `~/.whisplay-os/adopted/`, restored by `uninstall.sh`).
  While MFruit OS holds `state/launcher.lock`, `mfruit-run` starts an app only
  with the one-shot ticket MFruit OS writes before its own `app.launch`.
* **Daemon facts the design depends on** (verified in `whisplay_daemon.py`):
  `app.launch` is refused while another app is foreground; there is one pending
  launch slot; `desktop_entered` / `screen_locked` go only to global
  subscribers; daemon pages open synchronously without a launch command; its
  monitor loop can turn a hold into a tap. See `docs/ARCHITECTURE.md`.
* **Ending an app remotely:** `mfruitctl summon` does nothing while an app
  session is active (it only takes the screen back from the daemon desktop).
  Send the daemon `app.exit.request` for the app instead — the same path as
  Settings → *Stop app*.

---

# 24. Mock Hardware

Provide mock hardware adapters for development.

Examples:

```text
MockDisplay
MockInput
MockLED
MockAudio
MockPower
```

This allows the entire core to be tested without the Whisplay HAT.

---

# 25. Terminal / Headless Mode

Provide a headless development mode.

Example:

```bash
mf-os --headless
```

It should support:

```text
navigation testing
application testing
settings
app registry
package installation
updater
diagnostics
process management
```

This mode is important for CI/CD and debugging.

---

# 26. Package Manager

MFruit OS must have a platform-independent package manager.

Conceptual API:

```text
install(package)
uninstall(app_id)
update(app_id)
downgrade(app_id, version)
reinstall(app_id)
rollback(app_id)
```

The UI and CLI must use the same package manager.

Do not duplicate package logic in the UI.

---

# 27. App Ecosystem

Apps should behave like applications in a small operating system.

Users should be able to:

```text
Browse
Install
Launch
Disable
Enable
Update
Downgrade
Reinstall
Rollback
Uninstall
```

Applications are independent of the core OS.

---

# 28. GitHub Integration

GitHub is the first software distribution mechanism.

Support:

```text
Repositories
Releases
Tags
Release Assets
Version metadata
Checksums
```

Do not hard-code the updater around one repository.

Use a generic application manifest.

Correct architecture:

```text
GitHub
 ↓
Release Resolver
 ↓
Package Validator
 ↓
Package Manager
 ↓
Application Registry
```

---

# 29. Updater

The Updater must safely support:

```text
Update
Downgrade
Rollback
Reinstall
New app installation
```

Do not overwrite the currently working application immediately.

Use:

```text
Check
 ↓
Download temporary package
 ↓
Validate
 ↓
Verify
 ↓
Backup
 ↓
Install
 ↓
Validate installation
 ↓
Activate
```

If anything fails:

```text
Rollback
 ↓
Verify previous version
```

---

# 30. Versioned Application Storage

Where practical, maintain versioned application installations:

```text
apps/
└── bitcoin/
    ├── versions/
    │   ├── 1.0.0/
    │   ├── 1.1.0/
    │   └── 1.2.0/
    └── current
```

The current version can point to the active version.

This makes downgrade and rollback safer.

---

# 31. Security

Never blindly execute downloaded applications.

Validate:

* application ID
* package structure
* manifest
* version
* package path
* archive contents
* architecture
* minimum MFruit OS version

Use HTTPS.

Prevent path traversal.

Restrict application installation locations.

Never allow an app package to overwrite arbitrary system files.

---

# 32. Application Permissions

Design the platform so applications can eventually declare permissions.

Example:

```json
{
  "permissions": [
    "display",
    "network",
    "audio"
  ]
}
```

Potential permissions:

```text
display
input
audio
network
camera
filesystem
system_info
notifications
hardware
```

Full enforcement can be introduced incrementally.

---

# 33. Application Data Separation

Separate:

```text
Application binary
Application configuration
Application user data
Cache
Logs
Temporary update files
```

Uninstalling an app should not automatically destroy user data unless explicitly requested.

---

# 34. Safe Mode

Provide:

```bash
mf-os --safe-mode
```

Safe mode should:

* disable third-party applications
* disable autostart
* start core launcher
* allow application disabling
* allow rollback
* provide diagnostics

A broken third-party application must never be able to permanently prevent MFruit OS from starting.

---

# 35. Diagnostics

Provide:

```bash
mf-os doctor
```

Check:

```text
Core configuration
App registry
Manifest validity
Running processes
Filesystem
Storage
Display adapter
Input adapter
Network
GitHub connectivity
```

Also provide:

```bash
mf-os status
mf-os apps
mf-os logs
```

---

# 36. Runtime Status

`mf-os status` should expose enough information to diagnose application launch issues.

Example:

```text
MFruit OS       1.0.0

Mode:
Whisplay

Screen:
HOME

Selected App:
bitcoin

Foreground App:
bitcoin

App State:
RUNNING

PID:
1842

Session:
48c2d0...

Pending Action:
NONE
```

---

# 37. Debug Logging

In developer/debug mode, log:

```text
timestamp
event
current screen
selected app
requested app
foreground app
session ID
PID
state transition
```

Example:

```text
18:41:10 EVENT CLICK
18:41:10 SELECTED weather

18:41:12 EVENT LONG_PRESS
18:41:12 LAUNCH_REQUEST weather

18:41:12 STATE weather READY -> STARTING
18:41:12 PROCESS_STARTED pid=1421 session=abc123
18:41:13 STATE weather STARTING -> RUNNING
```

Invalid events should explain why they were ignored.

Example:

```text
18:41:15 LAUNCH_REQUEST weather
18:41:15 IGNORE: application already RUNNING
```

---

# 38. Testing

Testing must cover:

## Unit Tests

```text
navigation
event handling
version comparison
manifest validation
configuration
registry
path validation
state transitions
```

## Integration Tests

```text
launcher ↔ core
package manager ↔ registry
updater ↔ package manager
process manager ↔ application manager
hardware adapter ↔ core
```

## Real-daemon tests

Anything that depends on whisplay-daemon behaviour is tested against the
**real daemon code** (`tests/real_daemon/`: the daemon from a Whisplay checkout,
a simulated board with injectable button presses, fake apps with realistic
start-up times). Rules:

* Prove each fix with a **negative control**: the test must fail without the
  fix (e.g. `test_background_ui.py` fails against the unmodified daemon).
* Repeat timing-sensitive suites several times before calling them stable.
* Never run two real-daemon test runs at the same time (they share fake-app
  cleanup).

## Hardware Tests

When applicable:

```text
display
button
LED
audio
power
```

Physical-button checks are listed in `docs/HARDWARE_TESTS.md`; report each
step as verified or *not verified* per board.

---

# 39. Mandatory Regression Tests

These exist and must keep passing (`tests/test_launch_lifecycle.py`,
`tests/test_background_ui.py`, `tests/test_application_manager.py`,
`tests/test_gestures.py`). Add to them; do not weaken them.

### Wrong Application

```text
Select A
Move to B
Confirm
```

Expected:

```text
Only B launches
```

### Duplicate Launch

```text
Confirm A multiple times rapidly
```

Expected:

```text
One A process
```

### Selection Without Launch

```text
Move through menu
```

Expected:

```text
No application starts
```

### Stale Event

```text
Run A
Exit A
Select B
```

Expected:

```text
A's previous events cannot start A
```

### Process Crash

```text
Start A
Force crash
```

Expected:

```text
Launcher survives
A becomes FAILED
User can retry
```

### Rapid Input

Send many events rapidly.

Expected:

```text
No application storm
No invalid state
No duplicate process
```

### Press During App Start-up

```text
Open A (slow start)
Hold the button while A starts
```

Expected:

```text
Nothing else starts, no daemon UI appears, A opens
```

### App Closed After Exit

```text
Open A
Leave A (A releases the screen but keeps running)
```

Expected:

```text
A's process is stopped, unless A is marked Keep running
```

---

# 40. Stress Testing

Test:

```text
100 navigation events
100 confirmation events
50 application launches
20 application crashes
10 daemon reconnects
10 failed installations
10 failed updates
```

After each test verify:

```text
registry valid
configuration valid
launcher alive
no orphan processes
no duplicate active app
valid lifecycle state
```

---

# 41. Debugging Method

When a bug occurs:

```text
Reproduce
 ↓
Capture evidence
 ↓
Inspect event sequence
 ↓
Inspect state
 ↓
Inspect process state
 ↓
Identify root cause
 ↓
Implement smallest correct fix
 ↓
Add regression test
 ↓
Run relevant tests
 ↓
Run broader tests
```

Never randomly modify code.

Do not patch a race condition with arbitrary sleeps unless the actual design explicitly requires timing control.

---

# 42. Error Handling

Never use broad silent exception handling such as:

```python
except:
    pass
```

unless it is explicitly justified and documented.

Errors must:

```text
be logged
be classified
have recovery where possible
not crash unrelated components
```

The core launcher must survive application failures.

---

# 43. Concurrency

Minimize concurrency.

Background workers may be used for:

```text
network
GitHub
downloads
package installation
system monitoring
```

Only one system component should own application lifecycle mutations.

Avoid multiple threads modifying:

```text
app state
foreground app
registry
package state
```

at the same time without a controlled mechanism.

---

# 44. Configuration

Keep configuration separate from application binaries.

Validate configuration at startup.

If invalid:

```text
preserve original file
log error
load safe defaults
continue operation
```

Never silently overwrite user configuration.

---

# 45. Performance

MFruit OS should run well on:

* Raspberry Pi Zero 2 W
* Raspberry Pi 4
* Raspberry Pi 5
* similar Linux SBCs

Avoid unnecessary:

* polling
* filesystem writes
* heavy dependencies
* large frameworks
* browser engines
* excessive animations
* constant screen redraws

The system should remain responsive and lightweight.

---

# 46. Dependency Rules

Before adding a dependency, determine:

```text
Is it necessary?
Can the standard library solve it?
Does it support target hardware?
What is the RAM cost?
What is the startup cost?
Is it maintained?
```

Do not introduce large frameworks to solve small problems.

---

# 47. CLI and GUI Must Share the Same Core

The GUI must not implement its own business logic.

Correct:

```text
GUI
 ↓
MFruit Services
 ↓
Core
```

and:

```text
CLI
 ↓
MFruit Services
 ↓
Core
```

For example:

```text
GUI Update
CLI Update
```

must both call the same update engine.

---

# 48. Documentation

Update documentation whenever architecture or behaviour changes.

Maintain:

```text
README.md
INSTALL.md
APP_DEVELOPMENT.md
CHANGELOG.md
ARCHITECTURE.md
```

Document:

* installation
* architecture
* application format
* package system
* updater
* rollback
* hardware adapters
* development mode
* debugging
* troubleshooting

---

# 49. Git Workflow

Use focused commits.

Examples:

```text
feat: add MFruit app registry
fix: prevent duplicate application launch
feat: add hardware abstraction
feat: add GitHub package resolver
fix: restore previous app after crash
test: add navigation regression tests
```

Do not mix unrelated features and refactoring into one commit.

---

# 50. Refactoring Priority

Prioritise stability in this order:

```text
1. Application lifecycle
2. Navigation state machine
3. Input/event system
4. Process manager
5. Application registry
6. Hardware abstraction
7. Package manager
8. Updater
9. UI refinement
10. Additional features
```

Do not add major ecosystem features while application launching remains unstable.

---

# 51. Definition of Done

A feature is complete only when:

```text
✓ Implemented
✓ Unit tested
✓ Integration tested where relevant
✓ Regression tested
✓ Error handled
✓ Logged appropriately
✓ Works in headless/mock mode
✓ Works without Whisplay
✓ Works with Whisplay adapter when applicable
✓ Documentation updated
```

Never claim hardware verification unless hardware was actually tested.

---

# 52. Final Architectural Principle

MFruit OS must always follow:

```text
                    MFruit OS
                        │
             ┌──────────┼──────────┐
             ▼          ▼          ▼
            UI       Services     Apps
             │          │          │
             └──────────┼──────────┘
                        ▼
                    MFruit Core
                        │
               Hardware Abstraction
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      Whisplay      Terminal       Other HW
```

The core platform must not know or care which hardware adapter is being used.

Applications must not know or care which hardware adapter is being used.

The UI must display state, not secretly control state.

The process manager owns processes.

The application manager owns application lifecycle.

The package manager owns application installation.

The updater owns software updates.

The hardware adapter owns hardware.

No component should silently perform another component's responsibilities.

---

# 53. Final Development Rule

Before making a change, ask:

> Can this be implemented entirely inside MFruit Core?

If yes, keep it hardware-independent.

If hardware access is required, ask:

> Can this functionality be exposed through a generic adapter interface?

If yes, add it to the hardware abstraction layer.

If not, document why.

The goal is to make MFruit OS a **real standalone application platform**, with Whisplay being simply one supported device.

The final architecture should allow:

```text
MFruit OS
   +
Whisplay Adapter
```

today, while also allowing:

```text
MFruit OS
   +
Future Hardware Adapter
```

without rewriting the operating system.
