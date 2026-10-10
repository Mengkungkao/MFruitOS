# Validation

How to validate mFruit OS on a device, how to record the result, and what a
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
| 8 | Restart mFruit OS while an app is on screen | mFruit OS waits; after the app exits it shows Home | `EXTERNAL_SESSION`, then `SESSION_END` |
| 9 | Open an app and watch until it appears | mFruit OS's **Opening <App>** screen, never the daemon desktop; Wi-Fi keeps Settings until its own page appears | Diagnostics: *Hardware desktop: background* |
| 10 | Leave an app, then `pgrep -af <app>` over SSH | the process is gone within ~5 s | `APP_CLOSED app=… result=exited` (or `terminated`) |
| 11 | Set an app to *Keep running*, open and leave it | it keeps running; Home shows *Running* | no `APP_CLOSED` |

With a keyboard (USB, then Bluetooth) plugged in while mFruit OS runs
(`mfruitctl key …` exercises key handling but not keyboard reading):

| # | Do | Expect | Log shows |
|---|---|---|---|
| 12 | Plug in; press ↓ ↓ ↑ on Home | the selection moves at once; Diagnostics lists the keyboard | `keyboard connected: eventN`, `EVENT KEY down …` |
| 13 | Enter on an app | exactly that app opens, once | one `LAUNCH_REQUEST … source=home` |
| 14 | Inside an mFruit app: arrows / Enter / Esc | the app's list moves / opens / goes back; Esc on its first screen returns Home | `SESSION_END … outcome=exited` |
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

### Whisplay driver (bundled since 2026-10-03)

For each board, once as a fresh install and once as a changeover from a
`~/Whisplay` installation ([Whisplay driver](../WHISPLAY_DRIVER.md)):

| # | Do | Expect |
|---|---|---|
| D1 | `bash scripts/install.sh`, reboot if asked | no prompt from the driver; `bash drivers/whisplay/install.sh --check` prints only `OK` lines |
| D2 | Changeover only: compare before/after | `~/Whisplay`, `~/.whisplay-daemon/settings.json` and `~/.whisplay-daemon/app/*.json` unchanged; old unit in `/var/backups/mfruitos/`; sound card not rebuilt |
| D3 | Power on | logo, then Home; colours, orientation and the rounded-corner margins as before |
| D4 | Diagnostics: display, button, LED, speaker tests | each passes; backlight dims and brightens from Settings → Display |
| D5 | `arecord -D whisplaysound -f S16_LE -r 48000 -c 2 -d 3 /tmp/mic.wav && aplay -D whisplaysound /tmp/mic.wav` | the recording plays back clearly |
| D6 | Open and leave an app that uses `whisplay_client` (BTC Dashboard, RadioConnect) | it draws and reacts to the button (it found `/usr/local/share/whisplay/runtime`) |
| D7 | Power page: Reboot; then Shut down | both work without a password prompt |
| D8 | `sudo bash drivers/whisplay/install.sh --rollback` after a second install | the previous copy runs; `--check` reports the version difference |

## Hardware checklist — power management

Needs a board with a PiSugar battery board ([ADR 0012](../platform/ADR/0012-own-power-management.md)).
None of these has been performed yet (**NOT VERIFIED**). Watch:

```bash
journalctl -u mfruit-power -f      # or ~/.whisplay-os/logs/power.log
mfruitctl power status --details   # in another shell
```

| # | Do | Expect |
|---|---|---|
| P1 | `mfruitctl power` | `present: true`, the right `model`, a plausible `voltage` (3.3–4.2 V) and `level`; the status bar shows the same percentage |
| P2 | Plug and unplug USB power | `plugged`/`charging` follow within about 2 s; the status bar bolt appears and goes |
| P3 | `mfruitctl power set safe_shutdown_level 30` on battery (above 30 %: use a lower level when the battery is low) | the Battery low countdown appears and the LED turns red; plugging in cancels it (*Power connected*); unplugged, at zero the device powers off and the board switches off (no LED, no power draw) |
| P4 | Settings → General → Power → Shut down | the device powers off and the PiSugar switches its output off after Linux halted (`mfruit-power-off` on the console) |
| P5 | Settings → Battery → Hold to shut down safely on, then hold the power button | a safe shutdown instead of an instant power cut |
| P6 | Set *Long press* to Power menu; long-press the board button | the power menu opens; note how long the press must be and whether the board cuts power on a longer hold |
| P7 | Settings → Battery → Wake up 2 minutes from now, every day; shut down | the device starts by itself at that time |
| P8 | Boot without network | the system clock is set from the board's clock (`power.log`: "System clock set from the battery board") |

## Hardware checklist — Wi-Fi from a phone

Needs a phone with the PiSugar app (or Chrome with Web Bluetooth:
pisugar.com/sugar-wifi-conf) near the board ([ADR 0013](../platform/ADR/0013-phone-wifi-setup.md)).
Watch `tail -f ~/.whisplay-os/logs/wifi-setup.log` and
`mfruitctl wifi-setup status`.

| # | Do | Expect |
|---|---|---|
| W1 | Settings → Wi-Fi → Phone Setup | *Starting*, then *Ready* within about 15 s; Device and Key shown |
| W2 | In the app, find the device by that name and open it | Status *Connected*; the app shows the Wi-Fi name, IP, model and the info items (mFruit OS version, battery, CPU temperature, memory, up time) |
| W3 | Set Wi-Fi with a wrong key | the screen says the phone used a wrong key; Wi-Fi unchanged |
| W4 | Set a Wi-Fi network with the right key | *Wi-Fi set*; the device joins it (Wi-Fi row shows it and its address); the password is not in `wifi-setup.log` |
| W5 | Leave the screen | the tool stops; `bluetoothctl show` has Pairable as before |
| W6 | Settings → Bluetooth while *Run it* is *Always* | the tool pauses (a keyboard can be paired) and resumes when Bluetooth settings close |

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
