# MFruit OS — Claude Development Rules

## 1. Project Mission

You are developing **MFruit OS**, a lightweight embedded application operating environment for the **PiSugar Whisplay Display HAT** running primarily on **Raspberry Pi Zero 2W**.

MFruit OS sits **on top of the existing Whisplay Daemon**.

The architecture must remain:

```text
┌──────────────────────────────┐
│        MFruit OS           │
│                              │
│ Launcher                     │
│ Settings                     │
│ App Manager                  │
│ Updater                      │
│ Diagnostics                  │
└──────────────┬───────────────┘
               │
               │ Daemon API
               ▼
┌──────────────────────────────┐
│      MFruit Daemon         │
│                              │
│ LCD / Framebuffer             │
│ Button                        │
│ RGB LED                       │
│ Backlight                     │
│ Audio / Foreground Apps       │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      Whisplay Hardware       │
└──────────────────────────────┘
```

**Never bypass the daemon for functionality already provided by it unless there is a documented technical reason and the change is explicitly justified.**

---

# 2. Golden Rules

## Rule 1 — Inspect Before Changing

Before modifying code:

1. Inspect the existing project structure.
2. Read the relevant source files.
3. Understand how the existing Whisplay Daemon works.
4. Understand how the application currently communicates with the daemon.
5. Determine whether the requested functionality already exists.
6. Reuse existing mechanisms whenever possible.

Do not immediately rewrite working code.

Do not make assumptions about APIs.

Do not invent daemon endpoints.

Do not assume an API behaves like a different version of the project.

---

# 3. Protect Existing Functionality

MFruit OS must not unnecessarily break:

* `whisplay-daemon`
* framebuffer access
* button handling
* LED control
* backlight control
* audio
* application registration
* foreground application management
* existing Whisplay applications

Before modifying daemon-related code, identify:

```text
Who owns the hardware?
Who owns the framebuffer?
Who owns the button?
Who controls foreground applications?
What process is responsible for each operation?
```

The answer should normally remain:

```text
Whisplay Daemon → hardware ownership
MFruit OS     → application management and UI
Applications    → their own functionality
```

---

# 4. Development Workflow

Every feature must follow this workflow:

```text
Understand
   ↓
Inspect
   ↓
Plan
   ↓
Implement
   ↓
Test
   ↓
Debug
   ↓
Fix
   ↓
Regression Test
   ↓
Document
```

Do not skip testing simply because the code change is small.

---

# 5. Before Coding

Before implementing a feature, identify:

### Requirement

What exact behaviour is required?

### Existing implementation

Does something similar already exist?

### Dependencies

What existing modules are affected?

### Hardware impact

Does the change affect:

* LCD
* button
* LED
* audio
* network
* filesystem
* daemon
* systemd

### Failure modes

What can go wrong?

### Recovery

How does the application recover?

For complex changes, first write a short implementation plan in the working notes before editing multiple files.

---

# 6. Small Changes First

Prefer small, isolated changes.

Bad:

```text
Rewrite launcher
Rewrite daemon client
Rewrite settings
Rewrite updater
Rewrite application manager
```

Good:

```text
Add app registry
↓
Test
↓
Add launcher integration
↓
Test
↓
Add settings integration
↓
Test
```

Do not combine unrelated refactoring with feature development.

---

# 7. Architecture Rules

Keep modules separated by responsibility.

Recommended boundaries:

```text
launcher/
    UI and navigation

app_manager/
    application discovery
    registration
    enable/disable
    lifecycle

updater/
    GitHub
    versioning
    download
    install
    rollback

daemon/
    communication with Whisplay Daemon

system/
    diagnostics
    system information
    configuration

ui/
    rendering
    screens
    components
```

Avoid giant files.

Avoid placing business logic inside UI rendering code.

Avoid placing GitHub/network logic directly inside button handlers.

Avoid hard-coded application definitions.

---

# 8. Raspberry Pi Zero 2 W Constraints

Treat the Raspberry Pi Zero 2 W as a resource-constrained embedded device.

Every implementation should consider:

* CPU usage
* RAM usage
* storage writes
* startup time
* network usage
* battery usage
* display redraw frequency
* background processes

Avoid unnecessary:

* polling loops
* high-frequency timers
* threads
* subprocesses
* network requests
* filesystem writes
* animations
* heavy dependencies

Prefer:

```text
event-driven
cached
lazy-loaded
low-frequency
asynchronous where useful
```

Do not introduce a large framework just to solve a small problem.

---

# 9. UI Development Rules

The UI must remain:

* minimal
* readable
* responsive
* consistent
* usable with one physical button

Every new screen must answer:

```text
Where am I?
What is selected?
What happens when I press?
How do I go back?
```

Do not create screens that require touchscreen interaction.

Do not depend on tiny text.

Do not add unnecessary animations.

Keep redraws efficient.

Avoid blocking the UI thread.

---

# 10. Button Interaction Testing

Every change affecting navigation must test:

```text
single click
double click
long press
quad click
```

where supported by the current daemon implementation.

Verify:

* correct selection
* correct launch behaviour
* correct back behaviour
* no accidental double execution
* no stuck state
* no event duplication

Never implement a competing button event system without understanding the daemon's existing event handling.

---

# 11. Daemon Communication

All daemon communication should go through one controlled client abstraction.

Do not duplicate socket communication code throughout the project.

Example:

```text
WhisplayDaemonClient
    ├── register_app()
    ├── list_apps()
    ├── launch_app()
    ├── acquire_focus()
    ├── release_focus()
    ├── request_exit()
    ├── set_backlight()
    ├── set_led()
    └── subscribe_events()
```

Handle:

* connection failure
* socket unavailable
* malformed response
* timeout
* daemon restart
* stale connection
* unexpected event

The OS launcher should not crash because the daemon temporarily disappears.

---

# 12. Error Handling

Errors must be handled deliberately.

Never use:

```python
except:
    pass
```

unless there is a very specific and documented reason.

Prefer:

```python
try:
    ...
except SpecificError as exc:
    logger.error("...", exc_info=exc)
    recover()
```

Every user-facing failure should provide a useful state.

Example:

```text
Updater

Unable to reach GitHub.

Internet connection unavailable.

[ Retry ]
[ Back ]
```

Do not expose raw Python tracebacks on the normal UI.

Always log the detailed error.

---

# 13. Logging Rules

Use structured, useful logs.

Recommended levels:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Example:

```text
INFO     Launcher started
INFO     Connected to Whisplay daemon
INFO     Discovered 6 applications
INFO     Launching bitcoin
WARNING  GitHub request timed out
ERROR    Failed to install version 2.1.0
```

Logs should contain enough information to reproduce failures.

Avoid logging secrets, tokens or passwords.

---

# 14. Configuration

Do not hard-code user configuration.

Use a dedicated configuration layer.

Configuration must support:

* enabled applications
* app order
* brightness
* timeout
* theme
* button mappings
* updater settings
* developer mode

Validate configuration on startup.

If configuration is invalid:

```text
1. Log the error
2. Preserve the broken file
3. Fall back to safe defaults
4. Continue startup
```

Never silently destroy user configuration.

---

# 15. App Registry Rules

The application registry must be the source of truth for installed applications.

An app should have metadata such as:

```json
{
  "id": "example",
  "name": "Example",
  "version": "1.0.0",
  "enabled": true,
  "entrypoint": "run.sh",
  "repository": "https://github.com/example/repository"
}
```

Validate every manifest before loading it.

Reject:

* missing required fields
* invalid versions
* invalid paths
* duplicate application IDs
* unsafe installation locations

A broken app manifest must not prevent other applications from loading.

---

# 16. Updater Rules

The updater is a critical system component.

Never perform:

```text
download → overwrite current installation
```

without a recovery path.

Preferred sequence:

```text
Check
 ↓
Download temporary files
 ↓
Validate
 ↓
Backup current version
 ↓
Install new version
 ↓
Validate installation
 ↓
Activate
```

If installation fails:

```text
Restore previous version
 ↓
Verify rollback
 ↓
Report failure
```

Never delete the previous working version until the new version has been successfully validated.

---

# 17. GitHub Integration

Treat GitHub as an external dependency.

Always handle:

* no Internet
* DNS failure
* GitHub unavailable
* rate limits
* HTTP errors
* invalid repository
* missing release
* malformed metadata
* incomplete download
* invalid archive

Cache update information where practical.

Do not assume GitHub is always available.

Do not repeatedly query GitHub in a tight loop.

Use timeouts.

---

# 18. Version Handling

Use semantic version comparison where applicable.

Never compare versions as plain strings.

Incorrect:

```python
"10.0.0" < "2.0.0"
```

Use a dedicated version parser/comparison mechanism.

Support:

```text
install
upgrade
downgrade
reinstall
rollback
```

Keep OS versioning independent from app versioning.

---

# 19. Security Rules for App Installation

Never blindly trust downloaded application content.

Before installation:

* validate repository information
* validate manifest
* validate paths
* prevent path traversal
* use HTTPS
* restrict installation directory
* validate archive contents
* preserve backups
* log installation activity

Never allow an application package to write arbitrary files across the system.

Do not execute installation scripts without verifying they belong to the intended application package.

---

# 20. Filesystem Safety

Be extremely careful with:

```text
rm
shutil.rmtree
os.remove
subprocess
systemctl
sudo
```

Before deleting or replacing anything:

1. Resolve the absolute path.
2. Confirm it belongs to the intended application directory.
3. Ensure it does not point to `/`, `/home`, `/etc`, or another unrelated location.
4. Log the operation.

Never use dangerous recursive deletion with an unchecked path.

---

# 21. Systemd Rules

The launcher should run as a managed service.

Test:

```bash
systemctl status whisplay-os
journalctl -u whisplay-os
```

When modifying the service:

```text
validate service file
↓
reload systemd
↓
restart service
↓
check status
↓
check logs
```

Do not assume a successful `systemctl restart` means the application is actually functioning.

Check the process and logs afterward.

---

# 22. Testing Strategy

Use multiple testing layers.

## Unit Tests

Test isolated functions:

```text
version comparison
manifest validation
configuration
app discovery
GitHub parsing
path validation
```

## Integration Tests

Test:

```text
OS → daemon
OS → app registry
OS → updater
OS → GitHub
```

## Hardware Tests

Test on the real Whisplay HAT:

```text
LCD
button
LED
backlight
audio
```

## Failure Tests

Intentionally test:

```text
daemon unavailable
Internet unavailable
GitHub unavailable
bad app manifest
bad package
failed installation
failed application startup
corrupted configuration
full disk
missing executable
```

---

# 23. Test Before and After Fixes

When debugging a bug:

```text
1. Reproduce the bug
2. Capture logs
3. Identify the smallest failing component
4. Create or update a regression test
5. Implement the fix
6. Run the regression test
7. Run the related test suite
8. Run broader tests
```

A bug is not considered fixed until the original failure can no longer be reproduced.

---

# 24. Debugging Method

When a problem occurs, do not randomly modify code.

Use:

```text
Symptom
  ↓
Evidence
  ↓
Reproduction
  ↓
Isolation
  ↓
Root cause
  ↓
Minimal fix
  ↓
Regression test
```

Always distinguish:

```text
Symptom
Cause
Fix
```

Do not assume the first error message is the root cause.

Check logs, process state, daemon state, file permissions, environment variables and configuration.

---

# 25. Debugging Commands

Use appropriate commands such as:

```bash
systemctl status whisplay-daemon
systemctl status whisplay-os

journalctl -u whisplay-daemon
journalctl -u whisplay-os

ps aux
free -h
df -h
uptime
vcgencmd measure_temp

ls -la
find
grep
ss
curl
python3
```

For Python issues:

```bash
python3 -m py_compile <file>
python3 -m pytest
python3 -m unittest
```

Use the project's actual test framework if one already exists.

---

# 26. Never Hide Errors During Development

During development, prefer detailed diagnostics.

Do not change code simply to suppress:

```text
warnings
exceptions
tracebacks
connection failures
```

First understand the cause.

Only suppress an error when:

1. It is expected.
2. It is harmless.
3. It is documented.
4. The recovery behaviour is correct.

---

# 27. Regression Protection

Every fixed bug should produce one of:

```text
unit test
integration test
hardware test procedure
regression script
```

Maintain a regression suite for previously fixed issues.

Examples:

```text
test_daemon_disconnect
test_invalid_manifest
test_duplicate_app_id
test_failed_update_rollback
test_disabled_app_not_visible
test_version_downgrade
test_github_timeout
```

---

# 28. Dependency Rules

Before adding a dependency:

Ask:

```text
Do we actually need it?
Is there already a standard-library solution?
Does it work on Raspberry Pi Zero 2 W?
Does it significantly increase startup time or RAM?
Is it actively maintained?
```

Prefer lightweight dependencies.

Do not add dependencies simply for convenience.

---

# 29. Code Quality

Write simple code.

Prefer:

```python
clear_function()
```

over:

```python
one_huge_function()
```

Use:

* meaningful names
* type hints where helpful
* docstrings for public interfaces
* small functions
* clear error messages
* constants instead of magic numbers

Avoid clever abstractions that make embedded debugging harder.

---

# 30. Backward Compatibility

Assume that existing Whisplay applications may depend on the current daemon behaviour.

Do not change public interfaces unnecessarily.

If an API change is required:

```text
1. Document it
2. Maintain compatibility where possible
3. Update affected applications
4. Add regression tests
```

---

# 31. No Destructive Refactoring Without Evidence

Do not rewrite an existing subsystem simply because another implementation looks cleaner.

Before a large refactor:

* identify the actual problem
* measure current behaviour
* document expected behaviour
* create regression tests
* refactor incrementally

Preserve working functionality.

---

# 32. Performance Testing

For important changes, check:

```text
CPU usage
RAM usage
startup time
idle behaviour
screen responsiveness
network usage
```

Watch for:

```text
CPU constantly > expected idle level
memory growth over time
rapid filesystem writes
repeated GitHub requests
display flickering
button lag
```

For long-running services, periodically test whether memory usage remains stable.

---

# 33. Hardware-First Validation

When functionality involves physical hardware, software-only testing is not sufficient.

For example:

```text
Button code
→ test simulated events
→ test daemon events
→ test physical button

Display code
→ test renderer
→ test daemon framebuffer
→ test actual LCD

LED code
→ test command generation
→ test daemon interface
→ test physical LED
```

Do not claim hardware functionality is working until it has been tested on the target hardware or clearly marked as unverified.

---

# 34. Offline Testing

The core OS must remain usable without Internet access.

Always test:

```text
boot without Internet
launch apps without Internet
open settings without Internet
disable apps without Internet
view installed versions without Internet
```

Only updater/GitHub functionality should depend on Internet connectivity.

---

# 35. Recovery Mode

Design the system so a broken application cannot permanently brick the launcher.

The launcher should still start when:

* an app fails
* an app manifest is invalid
* GitHub is unavailable
* an update fails
* one configuration entry is corrupt

A broken component should degrade independently.

---

# 36. Git Workflow

Keep commits focused.

Good:

```text
feat: add app registry
fix: handle daemon disconnect
feat: add GitHub release checker
fix: rollback failed installation
test: add manifest validation tests
```

Avoid:

```text
update everything
```

Do not mix:

```text
feature
refactor
formatting
dependency changes
```

into one unrelated commit.

---

# 37. Documentation Rule

Whenever behaviour changes, update the relevant documentation.

Important documents:

```text
README.md
INSTALL.md
APP_DEVELOPMENT.md
CHANGELOG.md
```

Document:

* installation
* configuration
* app format
* update behaviour
* rollback behaviour
* troubleshooting
* developer API

---

# 38. Definition of Done

A feature is **not done** simply because the code compiles.

A feature is done when:

```text
✓ Implemented
✓ Tested
✓ Error-handled
✓ Regression-tested
✓ Documented
✓ Verified on target hardware when required
```

For hardware-dependent functionality:

```text
Software test
+
Real hardware test
```

are both required.

---

# 39. Final Verification Before Declaring Success

Before telling the user that a change is complete, verify:

### Code

```text
No syntax errors
No obvious dead code
No accidental debug code
```

### Tests

```text
Relevant tests pass
Regression tests pass
```

### Runtime

```text
Daemon connects
Launcher starts
Apps appear
Navigation works
```

### Hardware

```text
LCD works
Button works
LED works
Backlight works
```

when applicable.

### Updater

```text
Update check works
Installation works
Rollback works
Offline mode works
```

when applicable.

### Service

```text
systemd service starts
systemd service restarts
logs are useful
```

---

# 40. Communication Style During Development

When reporting progress, be precise.

Use:

```text
Implemented:
App registry discovery

Tested:
6 application manifests

Result:
6/6 passed

Issue found:
One manifest accepted an unsafe relative path

Fix:
Added path validation

Regression:
test_manifest_path_security passed
```

Do not say:

```text
Everything should work now.
```

unless it has actually been tested.

Distinguish clearly between:

```text
Implemented
Tested
Verified on hardware
Not yet tested
Known limitation
```

---

# 41. Most Important Rule

**Do not guess. Inspect, reproduce, test, fix, and verify.**

When something fails:

```text
DO NOT:
randomly rewrite code

DO:
collect evidence
→ reproduce
→ isolate
→ identify root cause
→ make the smallest safe change
→ test
→ regression test
```

The primary goal is not to produce the most code.

The primary goal is to produce a **stable, maintainable, lightweight MFruit OS that remains reliable on Raspberry Pi Zero 2W, other Pi, Orange Pi and remains compatible with the Whisplay Daemon.**
