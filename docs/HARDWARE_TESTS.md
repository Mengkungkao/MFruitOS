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
| 5 | Settings → Audio → Volume (hold, release) | the Volume page opens **and stays open** | `LAUNCH_REQUEST app=whisplay-volume kind=page` |
| 6 | Open a slow app (e.g. WalkieTalkie); while "Opening <App>" is on screen, hold the button ~1 s and release, twice | **nothing else happens**; the slow app opens (without the background wrapper: no other app starts, a daemon page may flash and is closed) | no new `LAUNCH_REQUEST`; without the wrapper `DENIED …` / `INTRUDER …` |
| 7 | Open an app that crashes (or stop its folder) | error screen with Retry / Logs / Back; launcher keeps working | `SESSION_END … outcome=failed` |
| 8 | Restart MFruit OS while an app is on screen | MFruit OS waits; after the app exits it shows Home | `EXTERNAL_SESSION`, then `SESSION_END` |
| 9 | Open any app and watch the screen until it appears | only MFruit OS's **Opening <App>** screen, never the daemon's list or "Opening app…" | Diagnostics: *Whisplay UI: background* |
| 10 | Leave an app, then check `pgrep -af <app>` over SSH | the app's process is gone within ~5 s | `APP_CLOSED app=… result=exited` (or `terminated`) |
| 11 | Set the app to *Keep running* (Settings → Applications → app), open and leave it | it keeps running; Home shows *Running* | no `APP_CLOSED` line |

With a keyboard (USB, then Bluetooth), plugged in while MFruit OS runs.
(`mfruitctl key down|up|enter|escape` exercises MFruit OS's own key handling
without a keyboard, but not the reading of one.)

| # | Do | Expect | Log shows |
|---|---|---|---|
| 12 | Plug the keyboard in; press ↓ ↓ ↑ on Home | the selection moves at once (no restart needed); Settings → System → Diagnostics lists it under *Keyboard* | `keyboard connected: eventN`, `EVENT KEY down …` |
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
