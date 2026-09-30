# CONTINUE — next-session handoff (updated 2026-09-30)

## Current checkpoint

MFruit OS **1.4.0** and ConnectWifi **1.1.0** are deployed on
**orangepi@192.168.0.130**. The Wi-Fi merge, useful RGB feedback, accidental
tap-to-exit fix and removal of the Connect WiFi loading screen are complete.
WalkieTalkie's explicit Status menu item and hold-to-select Back choices are
also implemented and deployed. MFruit OS branding cleanup and Messenger's
**Radio Message** subtitle are now deployed too. Final live check left **HomeScreen**, app session
**IDLE**, daemon connected, both services active. No commits were created.

Handoff finalized: implementation and deployment are complete for the requests
above. Copy-ready commit messages are recorded below for all four repositories.
Only the explicitly listed physical hardware checks remain unverified.

Latest user requests:

- Blend Settings' MFruit UI with Connect WiFi's connection functionality.
- Make the Whisplay RGB LED useful for button control, signal and notifications.
- Moving down to the bottom must not return to Settings automatically. Use an
  explicit Back row and a hold to select it.
- Remove the Connect WiFi loading screen.
- WalkieTalkie: four presses intended to exit sometimes open Status. Make
  Status a menu selection and add explicit Back choices to selection screens.
- Remove Whisplay branding from visible MFruit OS labels, especially the
  Messenger subtitle (use Radio Message), without disrupting the project.
- Continue autonomously; update this file and generate commit messages.

## Implemented and deployed

### MFruit OS naming and Messenger description

- Messenger now supplies its description through its own `manifest.json`:
  **Radio Message**. This uses the existing contributed manifest (version
  1.0.0), with its original app ID, entrypoint and integration flags. The
  contributed copy has the same description. No release/tag was published.
- Home's generic fallback is **MFruit OS app**. Diagnostics use **Hardware
  service** and **Hardware desktop**; fallback errors, CLI help, package
  errors, project description and template display name use MFruit OS or
  neutral wording. Template display name is Hello MFruit; its ID is unchanged.
- Prominent README branding, matching installation/hardware notes, and Home
  and Diagnostics screenshots updated. Actual third-party hardware names and
  compatibility documentation remain where they identify a dependency.
- Deliberately preserved app IDs, daemon commands, module/class names,
  environment variables, discovery topic, service/socket/storage paths and
  launch behavior. No hardware migration or runtime API rename was attempted.
- Validation: **264 MFruit OS tests passed**, including the real-daemon launch
  suites; **37 screens rendered**. AST comparison with the previous installed
  OS confirmed that all ten modified Python files differ only in text literals.
  The Messenger manifest validated and matched its contributed copy.
- Live check: exact Radio Message subtitle inspected, Messenger launched using
  its existing ID and Escape restored Home. A registry reload after app exit
  retained the description. Both services active; session IDLE; no message sent.
- Active OS: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930060547`.
  Backup: `/home/orangepi/.mfruit-deploy-backups/branding-20260930-060547/`.
  Previous OS retained; only the OS service was restarted. Messenger config,
  models, environment and app data were not replaced.
- Staging: `/tmp/mfruit-branding-20260930/{MFruitOS,Messenger}`; previews:
  `/tmp/mfruit-branding-preview/`; live helper: `/tmp/live_branding_check.py`;
  screenshot: `/tmp/mfruit-branding-home-verified.png`.
- Test output included ResourceWarnings from existing test fixtures and
  intentionally simulated failures; final unittest result was OK (264 tests).

### WalkieTalkie navigation follow-up

- Removed Home's three-click Status shortcut. Three accepted clicks during an
  attempted four-click exit now do nothing. Status is a normal Home menu row;
  keyboard S still opens it. Four-click/Escape Back shortcuts remain available.
- Home now lists Start, Receive, Pair devices, Settings, Status, Range test,
  **Back to MFruit OS**. Start and Settings also have bottom Back rows.
- Paired devices, Receive, Pair and Status have a persistent bottom Back
  choice. Tap moves/wraps selection; holding for 700 ms and releasing selects
  Back (Enter also works). Empty lists and Status stay open while tapping.
- Back on Start/Paired disables push-to-talk and microphone pre-roll. Stable
  Back flags keep incoming messages/radio discoveries from replacing Back
  while it is held. Pair starts on Back while searching; tap to select a found
  radio. Leaving Pair ends pairing immediately.
- Footers follow the same Back-aware action table as input. Notifications
  appear above pinned Back; all Status details still fit above it.
- README and 25-state preview generator updated. No SDK or board configuration
  changes; the deployed click window remains 700 ms.
- Validation: **632 passed** in the complete isolated Linux pytest suite;
  focused navigation/rendering run **257 passed**. Real InputController tests
  cover four-click exit with 80–520 ms gaps, partial exits, Back release timing,
  no microphone use on Back, and incoming messages/beacons during held Back.
- Live keyboard checks: explicit Status entry, taps staying on Status, Back
  through Settings/Start/empty Receive and Home exit. Actual app RGB565 frames
  inspected. No voice recording, playback, new pairing or range probing was
  requested during these checks. Physical button feel remains unverified.
- Deployment: changed files only in `/home/orangepi/WalkieTalkie`; production
  source matched the local Git baseline before replacement. Existing device
  config/data preserved; no service restart or package installation needed.
- Backup: `/home/orangepi/.mfruit-deploy-backups/walkie-nav-20260930-055657/`.
  Staging: `/tmp/mfruit-walkie-nav-20260930/WalkieTalkie`.
  Preview: `/tmp/walkie-nav-preview/`. Live helper: `/tmp/live_walkie_nav.py`;
  framebuffer captures: `/tmp/walkie-live-*.png`.
- Live Status reports `cannot read /dev/gpiomem` under hardware mode. This
  radio diagnostic was not investigated in this
  navigation task; do not infer that a real radio/audio exchange was verified.

### Unified Wi-Fi

- Settings → Wi-Fi launches ConnectWifi directly through ApplicationManager.
  The small old WifiScreen remains only as a fallback if no network manager is
  available. Closing the integrated app returns to Settings.
- ConnectWifi uses the vendored MFruit SDK's status bar, fonts, list rows,
  password field, footer, battery/Wi-Fi indicators and RGB565 renderer.
- Wi-Fi hub: connection/SSID/IP card, Choose a network, Hidden network,
  Phone setup, Back to Settings. Choosing Phone setup displays its name and
  key on separate lines in the card so the key is readable.
- Preserved cached/real scans, saved-profile joining, hidden SSID entry,
  password retries, failed-new-profile cleanup and BLE service control.
- Removed NumPy from the app renderer/install requirements. Version 1.1.0.
- Updated README and the generated UI contact sheet in ConnectWifi/docs.

### Navigation correction

- Cause of unexpected return: ConnectWifi registered the daemon's
  `quad_click` exit gesture while also treating every tap as Next. A burst of
  navigation taps therefore closed the app.
- `connectwifi/board.py` now registers `exit_gesture: none`. Tap only moves and
  wraps. Hold for one second and release selects. Unmatched releases are
  ignored; hold-ready feedback appears only after the threshold.
- Both Wi-Fi and Networks have a bottom **Back to Settings** row. The existing
  top Back on Networks returns to the Wi-Fi hub. Only selecting Back acts;
  highlighting or passing it does not leave. Keyboard Enter/Escape still work.
- Removed all four-tap exit hints from ConnectWifi. Footers say tap next /
  hold select, or hold back on a Back row.

### Launch and RGB

- `ScreenServices.launch_app` skips LoadingScreen for `connectwifi` only.
  Settings stays visible until the app draws; all launch guards, tickets,
  errors and other apps' loading screens are retained.
- ConnectWifi draws its real page before the blocking startup probe/status
  work, which now runs on its worker. Startup work remains busy/guarded.
- MFruit OS and ConnectWifi acknowledge a held button in white. ConnectWifi
  displays weak/usable/strong signal as amber/blue/green, disconnected as red,
  blue activity while scanning/connecting, and green/red connection results.
  It reads the existing MFruit Light switch and brightness at launch.
- DaemonBoard's RGB commands hold the focus lock and require a live token, so
  cleanup after focus revocation cannot turn off the next owner's LED.

## Verification for this checkpoint

| Check | Result |
|---|---|
| ConnectWifi full pytest in isolated Linux staging | 136 passed, 1 skipped |
| MFruitOS full suite after branding cleanup | 264 passed |
| WalkieTalkie full suite after navigation changes | 632 passed |
| Messenger metadata and live launch/exit | Manifest valid; Radio Message visible before and after launch |
| Earlier MFruitOS focused Wi-Fi checks | 46 passed |
| Deployed MFruit OS self-test | 37 screens rendered |
| Real whisplay-daemon with simulated GPIO/private socket | 24 rapid hub taps + 28 network taps retained focus; Back rows acted only on 1.12 s holds |
| Live Wi-Fi launch | No LoadingScreen; daemon registration exit_gesture=none |
| Live key hub | 12 repeated hub moves retained focus; hub and network bottom Back both restored Settings |
| UI inspection | Rendered screens and actual live ConnectWifi framebuffer inspected |
| Git diff whitespace | Passed |

The private real-daemon smoke used fake nmcli results, 69 release events and
five holds, with zero real network commands. Live navigation scanned but did
not join another network, alter credentials or toggle BLE. On this board,
nmcli reports the active network's cached signal as 0%; that is displayed as
reported, while the status icon/LED use the SDK's /proc signal reading.

Not verified physically: hand-operated button feel, visible RGB colours,
USB/Bluetooth keyboard capture/isolation, real Bluetooth pairing and reboot.
The Wi-Fi checkpoint initially reran the focused 46 tests. The later branding
checkpoint above ran the complete MFruit OS suite: 264 passed.

## Deployment and evidence

- Active OS:
  `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930060547`
- Previous OS:
  `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930054411`
- Wi-Fi checkpoint backup of replaced source files and prior system path:
  `/home/orangepi/.mfruit-deploy-backups/wifi-fix-20260930-054411/`
- Current ConnectWifi source: `/home/orangepi/ConnectWifi`.
- Updated source checkouts: `~/MFruitOS` and `~/ConnectWifi`. Installed a new
  OS version, self-tested before switching the current symlink, restarted
  only `whisplay-os.service` through its existing narrow sudo permission.
  No new packages, sudo rules or systemd units were installed on the board.
- Staging/tests: `/tmp/mfruit-wifi-fix-20260930/{MFruitOS,ConnectWifi}`.
- Private daemon evidence: `/tmp/mfruit-realdaemon-tgyqjtie/daemon.log` and
  `/tmp/mfruit_wifi_button_smoke.py`. That daemon stopped cleanly.
- Live check script: `/tmp/live_wifi_fix.py`; actual app framebuffer captures:
  `/tmp/wifi-fix-hub-back.png`, `/tmp/wifi-fix-networks-back.png`.
- Previews: `/tmp/mfruit-preview/out/`; these are temporary and may disappear
  on reboot. Local screenshots/packing helpers are in `C:/Users/userk/.codex/tmp/`.
- A previous deployment created an inactive directory with a CR character in
  its name before LF normalization. The active/previous paths above are clean.
  No cleanup of old installed versions was performed in this follow-up.

## Repository state and copy-ready commit messages

At this checkpoint MFruitOS, ConnectWifi, WalkieTalkie and Messenger contain pending changes.
Earlier Bluetooth and SDK work is committed: MFruitOS `17714ee`, ConnectWifi
`33a0d7e`. Chatbot is clean at `4620648` (deferred OpenCV startup import).
Do not recreate those commits or report them as pending.

These messages are ready to copy; no staging, commits or pushes were performed.
MFruitOS has two separate change sets. Stage their matching code and documentation
hunks separately; the final handoff can accompany the last commit or use the
optional documentation commit below.

### MFruitOS — Wi-Fi launch and button feedback

```text
fix: open Wi-Fi directly from Settings and add button LED feedback

Launch ConnectWifi from Settings and keep Settings visible until its first
frame, removing the Connect WiFi loading screen. Preserve launch guards
and add white RGB feedback while the hardware button is held.

Add launch regression coverage and update the changelog and hardware notes.
Validated with 46 focused tests, the 37-screen self-test and live Wi-Fi
launch/return checks on Orange Pi.
```

### ConnectWifi

```text
feat: unify Wi-Fi settings UI and require explicit Back selection

Use MFruit SDK styling for Wi-Fi status, network selection, credentials
and phone setup. Draw the first page before startup probes and add RGB
feedback for signal, button holds, connection activity and results.

Disable the daemon's four-tap exit and add explicit Back to Settings rows.
Guard unmatched releases and LED writes after focus loss. Update tests,
documentation, previews and dependencies; bump the app to 1.1.0.

Validated with 136 passing tests (1 skipped), simulated GPIO through the
real daemon and live navigation checks on Orange Pi.
```

### WalkieTalkie

```text
fix: make Status explicit and add hold-to-select Back navigation

Move Status into the Home menu and remove its three-click shortcut so a
partial exit gesture cannot open it. Add Back choices to menus and lists,
including empty lists, while retaining the four-click Back shortcut.

Prevent Back holds from recording audio and preserve Back selection as
messages and radios arrive. Stop pairing immediately when leaving Pair,
keep notifications above Back and update footers, docs and previews.

Validated with 632 passing tests and live menu navigation on Orange Pi.
Physical button feel and real radio/audio exchanges remain unverified.
```

### MFruitOS — visible branding

```text
fix: use MFruit OS branding in visible labels and descriptions

Replace generic Whisplay app branding with MFruit OS and neutral hardware
labels across Home, diagnostics, errors, CLI help and the app template.
Set the contributed Messenger description to Radio Message and refresh
the project documentation and screenshots.

Preserve compatibility IDs, services, paths, APIs and launch behavior.
Validated with 264 tests, 37 rendered screens, a text-only Python change
audit and live Messenger launch/exit checks on Orange Pi.
```

### Messenger

```text
feat: describe Messenger as Radio Message in MFruit OS

Add the existing MFruit OS package manifest with Radio Message as the
app description and document the launcher label. Keep the existing app
ID, entrypoint and integration flags; no runtime code changes.

Validated the manifest and confirmed the subtitle survives app launch,
exit and registry reload on Orange Pi.
```

Optional separate MFruitOS handoff commit:

```text
docs: record navigation and branding deployments

Record completed changes, test results, device deployment and backup paths,
remaining physical checks and commit messages for the four repositories.
```

## Earlier work and remaining hardware checks

Already implemented/deployed: grouped Settings with coloured icons, Bluetooth
discovery/pairing/device screens and lifecycle fixes, logo-only boot, SDK
1.2.0 exclusive keyboard grab/key hub, Hello Whisplay and Run Test removal.
ConnectWifi is hidden from Home but remains in Settings → Apps for management.

Prior full app verification: Messenger 141 tests, WalkieTalkie 578 (now 632), chatbot
keyboard/startup 12 plus TypeScript build. Chatbot's optional OpenCV import was
deferred, reducing board UI import time from 4.345 s to 2.078 s. Prior backup:
`/home/orangepi/.mfruit-deploy-backups/20260930-043440/`.

Remaining checks in `docs/HARDWARE_TESTS.md`:

1. Physical USB and Bluetooth keyboards: foreground routing, no tty1 leakage,
   held-key handover, hotplug/reconnection, release/reacquire in Daemon desktop.
2. Actual Bluetooth passkey/numeric confirmation, rejection/cancellation,
   reconnect/disconnect/forget with the daemon's pairing agent present.
3. Physical button and RGB observations; observed reboot/logo behavior.
4. Real updater operation with a physical keyboard. The original updater crash
   was keyboard input leaking to tty1 and executing shell history; the SDK
   grab/key-hub fix is deployed. Virtual keys do not verify physical EVIOCGRAB.
5. Raspberry Pi rollout is unperformed; crypto dashboard is not installed on
   Orange Pi. Do not expand to those without user intent.

Deferred: headless/hardware abstraction work, tracked bytecode cleanup,
Messenger timezone configuration. Do not change tty1 autologin or shell
history as part of these fixes.

## Working environment

Windows PowerShell, no WSL; default local Python lacks Pillow/pytest. The
launcher agent installed Pillow only in `%TEMP%/mfruit-services-deps` for a
local narrow check. Main validation used Linux staging on Orange Pi.

Normalize source text to LF in deployment archives and preserve executable
modes. Avoid copying local scratch, venv, model or secret files. Keep existing
board configuration/app data. Do not run two real-daemon suites concurrently.
Coordinate live navigation with the user to avoid racing physical input.

`mfruitctl screenshot` renders the launcher's router, even when another app
owns the display; it is NOT a live screenshot of that app. For ConnectWifi,
read its current `/tmp/whisplay-fb-connectwifi-*.bin` file and decode RGB565
with the SDK; don't acquire focus or a new framebuffer just for a screenshot.

```bash
ssh orangepi@192.168.0.130
~/.whisplay-os/bin/mfruitctl status
~/.whisplay-os/bin/mfruitctl key down
~/.whisplay-os/bin/mfruitctl key enter
~/.whisplay-os/bin/mfruitctl key escape
python3 -m pytest -q /tmp/mfruit-wifi-fix-20260930/ConnectWifi/tests
PYTHONPATH=/tmp/mfruit-wifi-fix-20260930/MFruitOS:/tmp/mfruit-wifi-fix-20260930/MFruitOS/tests \
  python3 -m unittest test_screen_services test_settings_screens test_runtime test_gestures test_misc
```
