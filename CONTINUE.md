# CONTINUE — next-session handoff (updated 2026-09-30)

## Quick summary

This session paused with the keyboard-leak crash fix already implemented and validated. The remaining work is the Settings redesign, moving Connect WiFi into Settings, adding the Bluetooth screens, removing the noisy boot screen, cleanup of old app entries, and final deployment verification on the Orange Pi.

## The request

From the user, 2026-09-30:

> now let move connect wifi to setting, reaagrange setting to became like a
> iphone setting. update bluetooth connect setting UI and make it ease to use.
> when I try to use updater to update any app the app is crash. remove the
> startup/booting MFruitOS and infos. Leave only a logo with dark background.

Follow-ups the same day:
- "move it from app to setting": Connect WiFi leaves the Home app list and
  opens from Settings.
- "and remove the run test app too" (`whisplay-run-test`).
- "remove Hello Whisplay too" (`hello-whisplay`).

Then: "now update continue.md and pause working now", and "write me commit
messages". Messages were given for part 1 (MFruitOS, ConnectWifi and the four
apps) and for this file; `git log` in each repo shows what the user committed.
The unfinished list, Settings and Bluetooth files were held back. Nothing is
deployed.

## Current checkpoint

- Verified: the updater crash was caused by keyboard leakage to tty1; the fix is in code and the full suite passes.
- Remaining: the Settings rework, Connect WiFi migration, Bluetooth UI, logo-only boot screen, app cleanup, and final deploy + hardware verification.
- Priority order for next session: Settings → Connect WiFi → Bluetooth → boot screen → remove apps → deploy.

| Part | Status |
|---|---|
| 1. "Updater crash" | Root cause found. The fix is in code with tests. Docs and deploy remain. |
| 2. iPhone-style Settings | The list supports groups and icon tiles. The screens are not started. |
| 3. Connect WiFi into Settings | Not started |
| 4. Bluetooth UI | Back end drafted, not reviewed or tested. Screens not started. |
| 5. Logo-only boot screen | Not started |
| 6. Remove Run Test and Hello Whisplay | Method known. Not started. |
| 7. Deploy and verify on the Orange Pi | Waits for 1–6 |

The previous task (the apps converted to the MFruit App SDK; SDK 1.1.0;
MFruit OS 1.3.0) is committed. Details are in CHANGELOG 1.3.0 and in git.

---

## 1. The "updater crash": root cause and fix (done in code, not deployed)

**It was not the updater.** Evidence from the Orange Pi's journal:

```
sudo[2758]: orangepi : TTY=tty1 ; PWD=/home/orangepi ; USER=root ; COMMAND=/usr/bin/systemctl restart whisplay-os.service
```

The keyboard also drives tty1, where getty's autologin bash runs, so every key
pressed in MFruit OS reached that shell too:
1. ↑ recalled the history line `sudo -n systemctl restart whisplay-os.service`.
2. Enter ran it; sudoers allows it without a password.
3. MFruit OS restarted, and the app with it, which looked like the app
   crashing during an update.

**The fix:** while MFruit OS runs, it holds every keyboard exclusively
(`EVIOCGRAB`). It hands each key to whoever owns the screen, through a
*key hub*. Nothing else gets keys: not the console, not whisplay-daemon, not
stray readers.

**MFruit OS side:**
- `mfruitos/launcher/keyhub.py` (new):
  - `KeyHub` listens on `~/.whisplay-os/state/keys.sock` (mode 0600,
    `paths.keys_socket`).
  - One JSON line per message. App → hub: `{"app_id": …}`. Hub → app:
    `{"type":"keyboards","devices":[…]}` and
    `{"type":"key","kind","value","action","code"}`.
- `runtime.py`:
  - The keyboard reader is `KeyReader(grab=True, on_devices=keyhub.set_devices)`.
  - `_on_hardware_key` sends each key-down to the screen owner (MFruit OS,
    or `focus.target` in APP mode). That key's repeats and release go to
    the same owner.
  - Developer → Daemon desktop (`yield_to_desktop`) releases the grab, and
    `on_focus_gained` takes it again.
- `ctl_handlers.py`: `mfruitctl key …` goes through `_on_hardware_key` (down,
  then up), so it tests the same routing.

**SDK side:**
- `keys.py`: `KeyReader(grab=, app_id=, hub=, on_devices=)`.
  - With an app id and a reachable hub, it reads keys from the hub.
    Otherwise it reads `/dev/input` itself, and switches to the hub as soon
    as the hub appears.
  - `hub_socket_path()` tries `MFRUIT_KEYS_SOCKET`, then
    `$MFRUIT_HOME` / `$WHISPLAY_OS_HOME` / `~/.whisplay-os`, then
    `/home/*/.whisplay-os`.
- `input.py`: `InputController(app_id=)` falls back to `WHISPLAY_APP_ID`.
- `scripts/mfruit-run` exports `WHISPLAY_APP_ID`, `MFRUIT_HOME` and
  `MFRUIT_SESSION` to every app.

**Apps:**
- Each app passes its id:
  - dashboard: `app.board.APP_ID`;
  - WalkieTalkie and Messenger: `board_module.APP_ID`;
  - chatbot: `whisplay_client.DEFAULT_APP_ID`;
  - template: `self.app.app_id`.
- The SDK copies are re-synced in all of them.
- `~/ConnectWifi`:
  - It has a vendored `mfruit_sdk/` (new, untracked).
  - `connectwifi/keyboard.py` has `SdkKeyboardReader` (app id `connectwifi`),
    used by `app.py`'s `main()`.
  - Its tests: 129 passed, 1 skipped.

**Tests:**
- `tests/test_sdk.py`: `KeyHubTests`, `GrabTests`.
- `tests/test_runtime.py`: `test_keys_go_to_whoever_owns_the_screen`,
  `test_the_keyboards_are_held_exclusively`.
- **The full suite passes: 230 tests, 2026-09-30.**

**Still to do for this part:**
- Bump `SDK_VERSION` to 1.2.0 (`mfruitos/sdk/__init__.py`). Re-sync every
  copy, including `~/ConnectWifi`.
- Docs:
  - CHANGELOG: a new version, 1.4.0.
  - CLAUDE.md §6: a new root-cause row. Keys reached the tty1 shell; the
    guard is the exclusive grab and the key hub.
  - CLAUDE.md §15: while MFruit OS runs, keys come through the hub.
  - `docs/LAUNCH_LIFECYCLE.md`.
  - `docs/ARCHITECTURE.md`: the key hub and its protocol.
  - `docs/APP_RULES.md`, plus each app's `.claude/rules/mfruit-os-app.md`
    copy. Apps read keys through the SDK with their app id; an app that
    reads `/dev/input` itself gets nothing while MFruit OS runs.
  - APP_DEVELOPMENT.md and README.
  - `docs/HARDWARE_TESTS.md`, new steps:
    - typed keys do not reach tty1;
    - keys reach the foreground app;
    - Daemon desktop releases the grab.
- **Ask the user**, because these need their sudo or touch their files:
  - turn off tty1 autologin;
  - remove the `systemctl restart whisplay-os.service` lines from the
    Orange Pi's `~/.bash_history`.

  The grab only protects while MFruit OS runs. It does not cover Daemon
  desktop mode or a stopped service.

## 2. iPhone-style Settings (in progress)

**Done** (backwards compatible; the suite passes; no screen uses it yet):
- `mfruitos/launcher/ui/components.py`:
  - `section(title="")` makes a group heading when given a title, and a gap
    when not.
  - `selectable(item)`.
  - `Item.tile = (r, g, b)` draws the item's icon in white on a rounded tile
    of that colour.
  - Separators are drawn only between selectable rows, indented past a tile.
- `mfruitos/launcher/ui/screens/base.py`: `ListScreen` skips sections when it
  moves (`_step`) and never lands on one (`current_items`).

**To do**, in `mfruitos/launcher/ui/screens/settings.py`. Today
`SettingsScreen` (line 35) has Applications, Display, Button, LED, Audio,
Network, System, Developer, About.
- The new layout is five groups, each row with an icon tile:
  1. Wi-Fi (value: network name), Bluetooth (value: On / Off / device)
  2. Display & Brightness, Sounds, Button, Light
  3. General
  4. Apps, Developer
  5. Back
- A new `WifiScreen` shows:
  - the network and IP address;
  - whether the internet is reachable;
  - **Choose a network…** (opens Connect WiFi; see §3);
  - Check internet.
- A new `GeneralScreen` holds About, Software Update, System info,
  Diagnostics, Power and Restart launcher. Today these are spread over
  `SystemScreen` (line 225) and `AboutScreen` (line 311).
- `NetworkScreen` (line 199) goes away.
- The icons already exist in `mfruitos/launcher/ui/icons.py`: wifi, bluetooth,
  display, audio, button, led, system, info, apps, developer, power,
  diagnostics, updater.
- After every screen change:
  - update the self-test / `preview.py` and the screen tests;
  - look at a rendered PNG.

## 3. Connect WiFi moves into Settings (to do)

- **Hide it from Home.** Add a "settings apps" list to the registry and
  exclude it from `launcher_entries()` (`mfruitos/apps/registry.py:318`).
  - The list starts with `connectwifi`. Check the board for other WiFi-setup
    app ids.
  - It stays launchable, and stays listed in Settings → Apps.
- **Open it from Settings.** Settings → Wi-Fi → Choose a network… calls
  `ApplicationManager.launch("connectwifi")`, the only launch authority
  (§9).
  - If Connect WiFi is not installed, fall back to the daemon's `whisplay-wifi`
    page (`SYSTEM_PAGES`, registry.py:32).
- Leaving Connect WiFi should return to Settings → Wi-Fi, not to Home. Check how
  the runtime picks the screen after an app exits.

## 4. Bluetooth UI (back end drafted, screens to do)

**The back end:** `mfruitos/system/bluetooth.py` (new). **Nothing imports it
yet. It is not linted and has no tests.**
- `Bluetooth` provides:
  - `available()`, `powered()`, `set_powered()`;
  - `devices()`, returning `BtDevice` objects (address, name, paired,
    connected, trusted, icon → kind, rssi);
  - `search(seconds)`;
  - `pair()` (pair, trust, connect), `connect()`, `disconnect()`, `forget()`.
- It drives BlueZ over D-Bus; `python3-dbus` and `gi` are both on the
  Orange Pi.
- Without them it falls back to `bluetoothctl` (version 5.64 on the Orange Pi).
  That version has no `devices Paired`, so the fallback uses `devices` plus
  `info`.
- A pairing agent (`KeyboardDisplay`) reports passkeys and confirmation
  requests through `on_prompt(Prompt)`. `answer(accept)` answers a
  confirmation.

**Review it before wiring it in:**
- `_interface()` opens a private system bus on every call and never closes
  it. Keep one bus per `Bluetooth` instead.
- `RequestConfirmation` blocks the agent's GLib loop while it waits, up to
  30 s. That is acceptable only because the loop serves nothing else.
- whisplay-daemon has its own pairing agent (`bluetooth_pairing_agent.py` in
  the Whisplay checkout), and ours calls `RequestDefaultAgent`. On the board,
  check that:
  - the two agents do not fight;
  - the service user is allowed to call `org.bluez` (D-Bus policy).
- Write `tests/test_bluetooth.py`: `parse_info`, `named`, the sort order, and
  the `bluetoothctl` paths with a fake `run`.

**The screens:**
- `BluetoothScreen`:
  - an On/Off toggle;
  - **My devices**: paired devices, with name, kind and Connected / Not
    connected;
  - **Other devices**: named devices found while searching. The search starts
    when the screen opens and shows "Searching…".
  - Every call runs through `os.run_task`, because the calls block.
- `BtDeviceScreen`: Connect / Disconnect, and Forget This Device (asks for
  confirmation).
- **Pairing dialog.** It shows one of:
  - the passkey to type ("Type 123456 on the keyboard, then press Enter");
  - a Yes/No confirmation, for numeric comparison.

  `Prompt("done")` closes it.
- Settings → Bluetooth opens these screens instead of the daemon's
  `whisplay-bluetooth` page.

## 5. Logo-only boot screen (to do)

- `mfruitos/launcher/ui/screens/boot.py` (65 lines) draws the start-up steps
  and the info. `runtime.py` drives it: `BootScreen(...)` and `set_step(...)`,
  around lines 118–150.
- It should draw only the MFruit OS logo on a dark background.
- Keep the step tracking for the log. A failed step must still reach the user,
  for example as a message screen.
- Check `preview.py` and the tests that expect the step list.

## 6. Remove Run Test and Hello Whisplay (to do, on the Orange Pi)

- **`hello-whisplay`** is an MFruit package (`~/.whisplay-os/apps/hello-whisplay`).
  Uninstall it through the package manager: `Installer.uninstall`, the same
  path as Settings → Apps → Uninstall (`screens/apps.py:152`).
- **`whisplay-run-test`** is a whisplay-daemon app that MFruit OS adopted. Its
  original is in `~/.whisplay-os/adopted/whisplay-run-test`. The daemon has no
  unregister command, so:
  1. Send `app.register` for it with `persist: false`; the daemon then deletes
     its registration file (`_save_app`).
  2. Delete the adopted copy.
  3. Restart whisplay-daemon; sudoers allows it.
- Consider a general "Remove" for daemon apps in Settings → Apps (a ctl
  command, the UI and a test).
- Check that nothing registers either app again at boot.

## 7. Deploy and verify (after 1–6)

**The boards:**
- The Orange Pi (`orangepi@192.168.0.130`) was reachable on 2026-09-30. It runs
  MFruit OS 1.3.0 **without** the key hub.
  - Registered there: connectwifi, whisplay-ai-chatbot, whisplay-flappy-bird,
    whisplay-jump, whisplay-lora-messenger, whisplay-lora-walkie,
    whisplay-play-mp4, whisplay-run-test (all adopted), and hello-whisplay
    (MFruit package).
- The Pi (`jarvis@192.168.0.33`) is often unreachable.

**Deploy MFruit OS and every app that uses the keyboard together.** Once MFruit
OS grabs the keyboards, an app still on the old SDK copy (which reads
`/dev/input` itself) gets no keys at all.

- Before each deploy, do an rsync dry run with the deploy script's excludes.
  Confirm the device tree differs only by this work.
- Run each app's tests before deploying it.
- **MFruit OS:**
  1. `scripts/deploy.sh orangepi@192.168.0.130 --no-service`
  2. `sudo -n systemctl restart whisplay-os.service`
  3. `mfruitctl status` should show the new version and `keyboards`.
- **The apps:**
  - WalkieTalkie and Messenger: `./deploy.sh orangepi@192.168.0.130`. Then remove
    older leftovers: `app/input/` in WalkieTalkie, and
    `controls/__pycache__/button*` and `keys*` in Messenger.
  - ConnectWifi: its own deploy script.
  - Chatbot: copy the tree, then run `bash build.sh` on the device. Node runs
    the compiled `dist/`.
  - The dashboard is not installed on the Orange Pi. Ask before installing it.
- **Verify:**
  - `mfruitctl key down|enter|escape` moves, opens and goes back in the new
    Settings.
  - Settings → Wi-Fi → Choose a network… opens Connect WiFi, and leaving it
    returns to Settings.
  - The Bluetooth screens render and search.
  - Boot shows only the logo.
  - Home no longer lists Connect WiFi, Run Test or Hello Whisplay.
  - Take screenshots from `/tmp/whisplay-fb-<id>-*.bin` and convert them with
    `mfruitos.launcher.ui.rgb565.from_rgb565`.
- **These need the user:** a physical keyboard and the button. The key hub
  (keys reach the foreground app, nothing reaches tty1) is **not verified on
  hardware**.

## 8. At the end

- Update this file.
- Give the user commit messages for the rest, in each repo's style. The key hub
  fix already has its messages (2026-09-30): in MFruitOS,
  `fix: hold keyboards exclusively so keys cannot reach the console shell`;
  in each app, "Take keyboard keys from MFruit OS's key hub".
  - Still to commit: `ui/components.py` and `screens/base.py` (list groups
    and tiles), and `mfruitos/system/bluetooth.py`, together with the
    screens that use them.
  - Then the Settings, Bluetooth and boot work, and the SDK 1.2.0 bump with
    the docs.

## Open items from before

- Unless the user has done it since, they still need to run
  `bash ~/MFruitOS/scripts/install.sh` on both boards. It needs their sudo
  password, and installs the whisplay-daemon background drop-in.
- Hardware checklist steps 9–18 are not verified.
- Milestones M2+ (core/hardware separation, mock/headless) are deferred.
- Messenger's own CONTINUE.md: set both boards' timezone (needs sudo).
- Compiled `.pyc` files are still tracked in git. To untrack them:
  `git rm -r --cached -q $(git ls-files '*.pyc')`.

## Useful commands

```bash
cd ~/MFruitOS && python3 -m unittest discover -s tests              # 230 tests, ~2.5 min
python3 -m unittest discover -s tests -p "test_sdk.py"              # SDK and key hub
python3 -m unittest discover -s tests -p "test_runtime.py"          # key routing
for d in ~/whisplay-crypto-dashboard ~/WalkieTalkie ~/Messenger ~/ConnectWifi \
         ~/ai-chatbot/whisplay-ai-chatbot/python \
         ~/MFruitOS/templates/whisplay-app-template/app; do
  ~/MFruitOS/scripts/sdk-sync.sh $d; done                           # after any SDK change
cd ~/ConnectWifi && python3 -m pytest -q                            # 129 passed, 1 skipped
cd ~/WalkieTalkie && python3 -m pytest -q
cd ~/Messenger && python3 -m pytest -q
cd ~/whisplay-crypto-dashboard && python3 -m pytest -q
cd ~/ai-chatbot/whisplay-ai-chatbot/python && python3 -m pytest -q test/test_keyboard_input.py
ssh -o ConnectTimeout=6 orangepi@192.168.0.130 '~/.whisplay-os/bin/mfruitctl status'
```

`pyflakes` and `vermin` (the Python 3.9 compatibility check) live in a scratch
venv. Recreate them with
`python3 -m venv <dir> && <dir>/bin/pip install pyflakes vermin`.
