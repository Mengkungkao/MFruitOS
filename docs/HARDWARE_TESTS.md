# Hardware test procedure — launch lifecycle

Run after any change to input, navigation or launching, on each board
(Raspberry Pi Zero 2 W, Orange Pi Zero 2W). Automated tests drive the real
daemon code with a simulated button; these steps cover the physical button.

Before starting, open a log view over SSH:

```bash
tail -f ~/.whisplay-os/logs/launcher.log ~/.whisplay-os/logs/launch-gate.log \
  | grep --line-buffered -E "EVENT|GESTURE|LAUNCH|STATE|INTRUDER|DENIED|REFUSED|SESSION_END"
```

| # | Do | Expect | Log shows |
|---|---|---|---|
| 1 | On Home, tap 10 times quickly | selection moves, **nothing opens** | `GESTURE single_click`, no `LAUNCH_REQUEST` |
| 2 | Hold on an app and keep holding 2 s | at 0.7 s the card says **Release to open**; nothing opens while held | `EVENT PRESS`, no `LAUNCH_REQUEST` yet |
| 3 | Release | **exactly that app** opens | one `LAUNCH_REQUEST app=<it> source=home`, `STATE … -> RUNNING` |
| 4 | Leave the app (four quick clicks, or the app's own exit) | back on MFruit OS Home, same app highlighted | `SESSION_END … outcome=exited` |
| 5 | Settings → Sounds → Volume (hold, release) | the Volume page opens **and stays open** | `LAUNCH_REQUEST app=whisplay-volume kind=page` |
| 6 | Open a slow app (e.g. WalkieTalkie); while "Opening <App>" is on screen, hold the button ~1 s and release, twice | **nothing else happens**; the slow app opens (without the background wrapper: no other app starts, a daemon page may flash and is closed) | no new `LAUNCH_REQUEST`; without the wrapper `DENIED …` / `INTRUDER …` |
| 7 | Open an app that crashes (or stop its folder) | error screen with Retry / Logs / Back; launcher keeps working | `SESSION_END … outcome=failed` |
| 8 | Restart MFruit OS while an app is on screen | MFruit OS waits; after the app exits it shows Home | `EXTERNAL_SESSION`, then `SESSION_END` |
| 9 | Open an app and watch the screen until it appears | MFruit OS's **Opening <App>** screen, never the daemon desktop; Wi-Fi retains Settings until its own page appears, with no loading screen | Diagnostics: *Hardware desktop: background* |
| 10 | Leave an app, then check `pgrep -af <app>` over SSH | the app's process is gone within ~5 s | `APP_CLOSED app=… result=exited` (or `terminated`) |
| 11 | Set the app to *Keep running* (Settings → Apps → app), open and leave it | it keeps running; Home shows *Running* | no `APP_CLOSED` line |

With a keyboard (USB, then Bluetooth), plugged in while MFruit OS runs.
(`mfruitctl key down|up|enter|escape` exercises MFruit OS's own key handling
without a keyboard, but not the reading of one.)

| # | Do | Expect | Log shows |
|---|---|---|---|
| 12 | Plug the keyboard in; press ↓ ↓ ↑ on Home | the selection moves at once (no restart needed); Settings → General → Diagnostics lists it under *Keyboard* | `keyboard connected: eventN`, `EVENT KEY down …` |
| 13 | Enter on an app | exactly that app opens, once | one `LAUNCH_REQUEST … source=home` |
| 14 | Inside an MFruit app (dashboard, WalkieTalkie, Messenger, chatbot): arrows / Enter / Esc | the app's own list moves / opens / goes back; Esc on its first screen leaves it, back to Home with nothing else opening | `SESSION_END … outcome=exited` |
| 15 | WalkieTalkie or Messenger on a talk screen: hold Space, speak, let go | it records while Space is held and sends on release | the app's log: listening / sent |
| 16 | Chatbot: type a question, Enter | the question is asked; the answer appears | chatbot log: `text_input` |
| 17 | Set Messenger to *Keep running*, leave it, type on Home | Home moves; nothing is typed or sent in Messenger | no Messenger log lines for the keys |
| 18 | Unplug the keyboard while holding Space in a talk screen | recording stops and sends (the held key is released) | `keyboard gone` |

Also check once: `ls ~/.whisplay-os/adopted/` lists the daemon apps MFruit OS
gates, and `grep launch_command ~/.whisplay-daemon/app/*.json` shows
`mfruit-run` for each.

Record the date, board and result of each step in the pull request or
CHANGELOG entry. A step that could not be run is reported as *not verified*.

## 1.4.0 keyboard and Settings checks

- Physical keyboard: type navigation and text in each foreground app; confirm
  tty1 receives none of it. Not yet physically verified.
- Hold Enter across an app transition: no repeat or release acts in the next
  owner. Test USB hotplug and Bluetooth keyboard reconnection.
- Developer > Daemon desktop releases the grab; returning to MFruit OS takes it.
- Volume and Power pages accept forwarded arrows, Enter and Esc.
- Settings > Wi-Fi opens the unified Wi-Fi manager directly, without a loading
  screen; closing it returns to Settings. Tap rapidly through Wi-Fi and
  Networks: selection moves and wraps without exiting. Hold the bottom
  **Back to Settings** row for one second, then release to exit.
- RGB: white button feedback, signal colour while Wi-Fi is idle, blue activity
  while scanning/connecting, green/red results; Light switch and brightness
  apply. Leaving Wi-Fi must restore the launcher's LED state.
- Bluetooth: scan, pair a keyboard using the displayed code, confirm a numeric
  comparison, reject/cancel pairing, disconnect/reconnect and forget.
- Boot displays only the logo; configuration errors remain visible afterward.

## Orange Pi checkpoint — 2026-09-30

Latest Wi-Fi/RGB follow-up (active OS `1.4.0-local20260930054411`):

- ConnectWifi 1.1.0: 136 tests passed, 1 skipped. MFruitOS focused launch,
  Settings, runtime, gesture and hardware checks: 46 tests passed. The install
  self-test rendered 37 screens. Earlier full-suite results below predate this
  follow-up and were not rerun in full.
- A private instance of the real daemon with simulated GPIO accepted 24 rapid
  hub taps and 28 network-list taps without exiting. All three Back routes
  acted only on a 1.12-second hold. No real network changes were performed.
- Live key-hub navigation verified direct Wi-Fi opening, no `LoadingScreen`,
  12 repeated hub moves without losing focus, and both bottom Back rows
  returning to Settings. Inspected the actual ConnectWifi RGB565 framebuffer.
- Both services active; left on Settings with an idle app session. Physical
  LED appearance and hand-operated buttons still need observation.

Earlier deployment checks:

Deployed MFruit OS 1.4.0 and the matching SDK 1.2.0 apps to
`orangepi@192.168.0.130`. Both systemd services are active.

- Automated Linux suite: 260 tests passed, including the real-daemon harness;
  self-test rendered 37 screens. Connect WiFi: 129 passed, 1 skipped;
  Messenger: 141 passed; WalkieTalkie: 578 passed; chatbot keyboard/startup: 12 passed.
  Chatbot TypeScript compiled successfully with the existing dependencies.
- Live control-socket keys opened Settings and Wi-Fi, launched Connect WiFi,
  and exited it through the key hub back to Wi-Fi. Bluetooth opened and
  completed discovery. Live screenshots were inspected.
- Messenger, WalkieTalkie and chatbot launched on the board and returned via
  key-hub Escape. The chatbot initially missed the launch deadline; deferring
  its optional OpenCV import reduced UI import time from 4.345 s to 2.078 s,
  and its subsequent live launch succeeded without changing the timeout.
- BlueZ queries, discovery, and registration/shutdown of our connection's
  pairing agent succeeded as `orangepi` while the daemon was running.
- Home excludes Connect WiFi; it remains in Settings → Apps. Hello Whisplay
  and Run Test were removed and remained absent after the daemon restart.
- Physical USB/Bluetooth keyboard input, tty1 isolation, physical button
  gestures, actual pairing/confirmation/cancellation, and grab release in
  Daemon desktop mode remain **not verified on hardware**. No keyboards were
  attached during these checks. Boot appearance was verified in a rendered
  preview, not observed during a physical reboot.
