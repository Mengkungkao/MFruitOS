# Validation

How to validate MFruit OS on a device, how to record the result, and what a
release needs. Automated test procedures are in [Testing](TESTING.md).

## Status language

Use exactly these terms ([Part I §20](../platform/DEVELOPMENT_RULES.md#20-quality-status-language)):
**IMPLEMENTED**, **AUTOMATED**, **DEVICE VERIFIED**, **NOT VERIFIED**,
**PLANNED**. Never convert one into another: a software key event,
screenshot, framebuffer capture or SSH health check is not a physical
observation.

## Hardware checklist — launch lifecycle and input

Run after any change to input, navigation or launching, on each board
(Raspberry Pi Zero 2 W, Orange Pi Zero 2W). Open a log view first:

```bash
tail -f ~/.whisplay-os/logs/launcher.log ~/.whisplay-os/logs/launch-gate.log \
  | grep --line-buffered -E "EVENT|GESTURE|LAUNCH|STATE|INTRUDER|DENIED|REFUSED|SESSION_END"
```

| # | Do | Expect | Log shows |
|---|---|---|---|
| 1 | On Home, tap 10 times quickly | selection moves, **nothing opens** | `GESTURE single_click`, no `LAUNCH_REQUEST` |
| 2 | Hold on an app for 2 s | at 0.7 s the card says **Release to open**; nothing opens while held | `EVENT PRESS`, no `LAUNCH_REQUEST` yet |
| 3 | Release | **exactly that app** opens | one `LAUNCH_REQUEST app=<it> source=home`, `STATE … -> RUNNING` |
| 4 | Leave the app (4× or its own exit) | back on Home, same app highlighted | `SESSION_END … outcome=exited` |
| 5 | Settings → Sounds → Volume (hold, release) | the Volume page opens **and stays open** | `LAUNCH_REQUEST app=whisplay-volume kind=page` |
| 6 | Open a slow app; while "Opening <App>" shows, hold ~1 s and release, twice | **nothing else happens**; the slow app opens (without the background wrapper: no other app starts, a daemon page may flash and is closed) | no new `LAUNCH_REQUEST`; without the wrapper `DENIED` / `INTRUDER` |
| 7 | Open an app that crashes | error screen with Retry / Logs / Back; launcher keeps working | `SESSION_END … outcome=failed` |
| 8 | Restart MFruit OS while an app is on screen | MFruit OS waits; after the app exits it shows Home | `EXTERNAL_SESSION`, then `SESSION_END` |
| 9 | Open an app and watch until it appears | MFruit OS's **Opening <App>** screen, never the daemon desktop; Wi-Fi keeps Settings until its own page appears | Diagnostics: *Hardware desktop: background* |
| 10 | Leave an app, then `pgrep -af <app>` over SSH | the process is gone within ~5 s | `APP_CLOSED app=… result=exited` (or `terminated`) |
| 11 | Set an app to *Keep running*, open and leave it | it keeps running; Home shows *Running* | no `APP_CLOSED` |

With a keyboard (USB, then Bluetooth) plugged in while MFruit OS runs
(`mfruitctl key …` exercises key handling but not keyboard reading):

| # | Do | Expect | Log shows |
|---|---|---|---|
| 12 | Plug in; press ↓ ↓ ↑ on Home | the selection moves at once; Diagnostics lists the keyboard | `keyboard connected: eventN`, `EVENT KEY down …` |
| 13 | Enter on an app | exactly that app opens, once | one `LAUNCH_REQUEST … source=home` |
| 14 | Inside an MFruit app: arrows / Enter / Esc | the app's list moves / opens / goes back; Esc on its first screen returns Home | `SESSION_END … outcome=exited` |
| 15 | Talk screen: hold Space, speak, release | records while held, sends on release | app log: listening / sent |
| 16 | Chatbot: type a question, Enter | the question is asked | chatbot log: `text_input` |
| 17 | Messenger on *Keep running*, leave it, type on Home | Home moves; nothing typed in Messenger | no Messenger log lines |
| 18 | Unplug while holding Space on a talk screen | recording stops and sends | `keyboard gone` |
| 19 | Plain Whisplay game (Jump Game, Flappy Bird): play with Space, leave with Esc | Space acts as the button; Esc returns Home | `KEY_BRIDGE app=… key=escape`, `SESSION_END … outcome=exited` |

Also: `ls ~/.whisplay-os/adopted/` lists gated daemon apps and
`grep launch_command ~/.whisplay-daemon/app/*.json` shows `mfruit-run` for each.

### 1.4.0 keyboard, Settings and light checks

- Typed keys never reach tty1; a held Enter across an app transition does not
  act in the next owner; USB hotplug and Bluetooth reconnection work.
- Developer → Daemon desktop releases the keyboard grab; returning takes it.
- Volume and Power pages accept forwarded arrows, Enter and Esc.
- Settings → Wi-Fi opens ConnectWifi directly; rapid taps move and wrap
  without exiting; holding **Back to Settings** ~1 s then releasing exits.
- RGB: white button feedback; Wi-Fi signal colour, blue while scanning or
  connecting, green/red results; Light switch and brightness apply; leaving
  Wi-Fi restores the launcher's LED state.
- Bluetooth: scan, pair a keyboard with the displayed code, confirm a numeric
  comparison, reject/cancel, disconnect/reconnect, forget.
- Boot shows only the logo; configuration errors remain visible afterwards.

## What a record contains

Every dated record in [records/](records/README.md) states
([Part I §21](../platform/DEVELOPMENT_RULES.md#21-quality-records)): date;
revision/commit and working-tree state; OS/platform; device; daemon or
dependency revision; commands; pass/fail totals; skipped tests; hardware tests
performed; unverified items; discovered issues. Keep credentials, private
messages and personal data out of records.

### Record template

```markdown
# <Feature or validation> — YYYY-MM-DD

## Scope
- Source revision and working-tree state:
- Device / OS / architecture:
- Python, Pillow, whisplay-daemon revision:

## Results
| Check | Command or procedure | Result (AUTOMATED / DEVICE VERIFIED / NOT VERIFIED) |
|---|---|---|

## Skipped and not verified
- Automated checks skipped (with reason):
- Physical checks not performed:

## Issues found
- <link to known issue or bug record>
```

## Release readiness

Before calling a version releasable, evaluate and record
([Part I §30](../platform/DEVELOPMENT_RULES.md#30-release-readiness)):

- [ ] Architecture and canonical docs current; known issues reviewed
- [ ] `scripts/check.sh` and CI green; full suite incl. real-daemon tests on the release revision
- [ ] Package lifecycle: install, launch, exit, update, failed update, rollback, uninstall with disposable data
- [ ] Installer: fresh install and rerun preserve apps and settings; uninstall restores the daemon
- [ ] System update and boot-guard rollback exercised
- [ ] Hardware checklist above on each target board, with NOT VERIFIED items listed
- [ ] Release notes state what was not tested
