# CONTINUE — where the work stands (2026-09-29)

Current request (from the user):

> update ai-chatbot, messenger, walkietalkie, cryptodashboard: write a claude
> rule. update the app projects following current MFruitOS UI and interface
> controller. Enable all app to use with keyboard via USB or Bluetooth.

Decisions the user made:

- **Gestures: "Hybrid".** Menus and lists in every app use MFruit OS's
  gestures exactly: tap next · 2× previous · hold (then release) open ·
  4× back. Hold-to-talk stays only on talk screens (Messenger chat,
  WalkieTalkie Start/Contacts/Talk/Range, the chatbot). The keys are the
  same everywhere: ↑/↓ move · Enter open · Esc back · Space held = talk.
- **Chatbot keyboard: "Type questions".** Typing, then Enter, sends a text
  question to the AI. Space held = talk. Esc = cancel/back.

Nothing is committed. Commit only when the user asks. All four app repos had
clean git trees before this work.

---

## Done

### MFruit App SDK — `mfruitos/sdk/` (the only source)

Apps get a vendored copy named `mfruit_sdk/` via
`scripts/sdk-sync.sh <app python root>`. Run it with `--check` to spot a
stale copy. The SDK uses relative imports only, and a test enforces that.

| Module | What it does |
|---|---|
| `keys.py` | `KeyReader` / `KeyDecoder`. Reads USB and Bluetooth keyboards from `/dev/input`, counting only devices with letter keys. Reports key down, repeat and up. Rescans for new keyboards every 2 s. When a keyboard disappears it sends "up" for held keys. A wake pipe lets `stop()` return promptly. |
| `gestures.py` | `ButtonGestures`, a threaded recogniser: `tap`, `double`, `triple`, `quad`, plus `hold_start` / `hold_end`. Events are delivered in order. Takes `clock=` and `threaded=False` for tests. |
| `input.py` | `InputController` and `Action(name, source, char, key, held)`. Action names: next, previous, select, back, extra (3×), talk_start, talk_end, char, erase, key. The app passes `talk=`, `typing=` and `active=` callables and an `on_armed` callback, and calls `reset()` on focus loss. A key only counts if it went down while the app was active. |
| `status.py` | `wifi_level()`, `read_battery()` (via the pisugar socket) and a `StatusMonitor` thread. |
| `daemon.py` | `own_escape_key(app_id)`: a partial `app.register` that sets `disable_esc_exit_key=True`. |
| `ui/` | `Canvas` (with `Canvas.over(draw)`), plus `status_bar(title, status, badge=, dot=, reserve=)` (returns the x of the reserved slot), `footer`, `menu_hints`, `draw_list` / `Row`, `toast`, `message`, `text_field`, `theme` (MFruit DARK/LIGHT and layout constants), `fonts` (Inter from MFruit OS, falling back to DejaVu; honours `MFRUIT_FONT_DIR`) and `rgb565`. |

Tests: `tests/test_sdk.py`.

### MFruit OS itself

- **Keyboard support in the launcher** (`launcher/runtime.py` `_on_key`,
  `KEY_ACTIONS`). ↑/← previous, ↓/→/Tab next, Enter select, Esc back,
  Home goes home.
  - Keys count only while MFruit OS owns the screen (`_output()`).
  - A key is ignored unless its down event arrived while MFruit OS owned
    the screen (tracked in `_keys_owned`, cleared on focus gained/lost).
  - A key press wakes a dark screen.
- **`register_os`** now sends `disable_esc_exit_key=True`
  (`app_manager/lifecycle.py`).
- **`mfruit-run`** exports `MFRUIT_HOME` and `MFRUIT_SESSION` to apps.
- **Tests:** `tests/test_runtime.py` gained `test_keyboard_navigation` and
  `test_keys_that_went_down_elsewhere_do_nothing`. The last full run was
  207 tests OK; that was before `Canvas.over` and `reserve`, whose SDK
  tests were added afterwards and pass.
- **New: `docs/APP_RULES.md`**, the Claude rule for MFruit apps. It is
  copied into each app as `.claude/rules/mfruit-os-app.md`.
- **New: `scripts/sdk-sync.sh`**.

### ~/whisplay-crypto-dashboard — DONE (82 tests pass)

- Vendored `mfruit_sdk/`; added `.claude/rules/mfruit-os-app.md` and
  `CLAUDE.md`.
- **Controls** now go through `InputController` → `DashboardApp.handle_action`:

  | Button | Keyboard | Action |
  |---|---|---|
  | tap | ↓ / → / Tab | next page |
  | 2× | ↑ / ← | previous page |
  | hold, release | Enter | the page's action: timeframe on the Bitcoin page, refresh elsewhere |
  | 3× | R | refresh |
  | 4× | Esc | exit |
  | | T | next timeframe |
  | | H / Home | Bitcoin page |
  | | 1–5 | jump to page |

  The page action is set by `Screen.select_label`.
- **Chrome:** new `app/ui/frame.py`. The status bar shows the page name, a
  data light, WiFi and battery; the footer shows hints; toasts come from
  the SDK. The screens were re-laid-out to fit y 40–248.
- `theme.py` now uses the MFruit palette and fonts, keeping Bitcoin orange
  as the content accent.
- Registration: packaging JSON has `disable_esc_exit_key: true`, and the
  app calls `own_escape_key` at start.
- Removed `app/input/`, `tests/test_button.py` and `test_gesture_routing.py`.
  Added `tests/test_controls.py` and chrome/content-bounds tests in
  `test_rendering.py`.
- README updated. Preview with:

  ```
  MFRUIT_FONT_DIR=~/MFruitOS/assets/fonts python3 tools/preview.py --mock
  ```

### ~/WalkieTalkie — DONE (577 tests pass locally and on the Orange Pi)

- **`app/ui/navigation.py`** is rewritten around MFruit actions:
  - Tables for every screen, plus `CHAR_ACTIONS` (Home `s` = status,
    Talk `r` = replay, Inbox `p` = play, Range `p` = probe / `m` = mark).
  - `TALK_SCREENS` = Start, Contacts, Talk, Range. On those screens 3× and
    Enter open the selected row.
  - `hints()` returns `(gesture, label)` tuples, always keeps "4×" among
    the first three, and supports `armed=`.
  - 4× goes back; 4× on Home exits.
- **`main.py`:**
  - `InputController`, with `talk=` set to `can_talk(screen)` and
    `active=` set to `foregrounded`.
  - `_on_action` → `_dispatch`; editors go through `_editor_action`.
  - New `previous_*` handlers.
  - `input.reset()` is called on focus revoked.
  - `own_escape_key` is called at start; `StatusMonitor` supplies the WiFi
    level via `state.wifi_level`.
  - `battery_charging` added.
- **`editors.py`:**
  - Editors take actions: NEXT/PREVIOUS change the value, SELECT advances
    (Enter from the keyboard saves), BACK cancels.
  - Typing into the digit editor works, and Backspace steps back.
  - Choice editor: a typed letter jumps to a matching choice.
  - Confirm editor: y / n.
- **`screens.py`:**
  - MFruit status bar via `draw_header`, with LoRa signal bars in a
    reserved slot.
  - `draw_footer` uses the SDK footer, with the banner as a toast.
  - Menus use the SDK `draw_list`.
  - Selected rows use `theme.SELECTED`.
  - Short page names (`PAGE_TITLES`, `EDITOR_TITLES`: "Receive", "Clock",
    "Range", "Base") so they fit beside the signal meter, WiFi and a
    three-digit battery.
  - `editor_hints()`: tap change · hold next/save (or confirm) · 4× cancel
    (4× back on the confirm dialog, where "cancel" does not fit).
- **`theme.py`** uses the MFruit palette and fonts (mono stays DejaVu Mono).
- **`install.sh`** registers with `disable_esc_exit_key: True`.
- **Removed:** `app/input/`.
- **Tests:** added `tests/test_controls.py` (the real controller, driven by
  a fake clock). Ported `test_navigation`, `test_menu`,
  `test_settings_flow` (which now has `TAP`, `TWICE`, `HOLD`, `THRICE`,
  `QUAD`, `act()` and `play()`), `test_pairing`, `test_rangetest`,
  `test_background` and `test_screens`.
  - `test_screens` checks that page names and editor footers fit. These
    checks are skipped when Inter is not found, because the DejaVu
    fallback is wider.
  - Fixed a test-ordering leak: the settings-flow fixture patched
    `Settings.data_dir` on the class for good; it now uses `monkeypatch`.
- **New `tools/preview.py`:** renders every screen and state to PNG.
- **Docs:**
  - README: controls table, a keyboard section, pairing, settings, range
    test, architecture and testing sections.
  - CLAUDE.md: a project section at the top that points to the rule.
  - `.claude/rules/mfruit-os-app.md` added.
- **Hardware, Orange Pi Zero 2W** (deployed with `./deploy.sh
  orangepi@192.168.0.130`; the device tree had matched local HEAD before
  deploying):
  - 577 tests pass on the device (Python 3.10, Pillow 9.0.1, Inter found).
  - `mfruitctl launch whisplay-lora-walkie` opened it through the launch
    gate.
  - The framebuffer shows the new MFruit look.
  - Radio and audio came up with no errors.
  - The daemon registration now has `disable_esc_exit_key: true`.
  - `app.exit.request`: the app exited by itself, then `SESSION_END
    outcome=exited`, `APP_CLOSED result=exited`, and MFruit OS returned
    Home.
- **Not verified on hardware:** the physical button gestures (nobody at
  the device) and any keyboard (none attached; `/dev/uinput` is
  root-only). The Pi Zero 2 W at 192.168.0.33 was unreachable ("No route
  to host").
- **Note:** `mfruitctl summon` does nothing while an app session is
  active; it is only for taking the screen back from the daemon desktop.
  To end an app remotely, send the daemon `app.exit.request` (the same
  path as "Stop app"), e.g. from the app dir:
  `python3 -c "from mfruit_sdk.daemon import request; request('app.exit.request', {'app_id': '<id>'})"`.
- **SDK change during this step:** the font search now also tries
  `~/MFruitOS/assets/fonts` (a source checkout). Re-synced into the
  dashboard and WalkieTalkie.

## Next steps, in order

1. **Messenger** (`~/Messenger`; Python root is the repo root):
   - Run `sdk-sync.sh ~/Messenger`.
   - Replace `controls/button.py` + `controls/keys.py` with `InputController`:
     - `talk=` returns True on the chat screen while the picker is closed;
       `typing=` returns `compose is not None`.
     - **Chat screen:** hold / Space = talk; tap = older; 2× = quick
       replies (resend on a failed message); 3× = read aloud; 4× / Esc =
       leave. Letters compose a message; Enter sends it.
     - **Quick-reply picker (a list):** tap next · 2× previous · hold /
       Enter send · 4× / Esc close.
     - `controls/keyboard.py` (stdin over SSH) stays.
   - Restyle `display/whisplay.py` with the MFruit status bar (the chat
     title as the page name), footer hints and fonts.
   - Keep `_has_screen` gating; it is now `active=`.
   - Registration already has `disable_esc_exit_key` per install.sh; call
     `own_escape_key` as well.
   - Messenger may run in the background (manifest `background: true`), so
     it must ignore keys while not in the foreground.
   - Update tests (`tests/test_keys.py` and the gesture tests), README,
     CLAUDE.md and the rule copy.
   - Follow the WalkieTalkie pattern:
     - a `tests/test_controls.py` that drives the real controller with
       `threaded=False` and a fake clock;
     - title- and footer-fit tests, skipped without Inter;
     - a `tools/preview.py`;
     - check the device tree with an rsync dry run before `./deploy.sh`;
     - verify on the Orange Pi with `mfruitctl launch <id>`, a framebuffer
       grab (`/tmp/whisplay-fb-<id>-*.bin`), then `app.exit.request`.
2. **AI chatbot** (`~/ai-chatbot/whisplay-ai-chatbot`; Python root is
   `python/`):
   - Run `sdk-sync.sh ~/ai-chatbot/whisplay-ai-chatbot/python`.
   - The Node side (`src/device/display.ts`) counts button clicks itself.
     Leave the button path alone and add keyboard input in
     `python/chatbot-ui.py`, using `InputController(keyboard only,
     talk=lambda: True, typing=lambda: bool(buffer))`:
     - Space down / up → send `{"event": "button_pressed"}` /
       `{"event": "button_released"}` to the Node clients.
     - chars / Backspace → edit a compose buffer shown on screen (SDK
       `text_field`).
     - Enter → send `{"event": "text_input", "text": ...}`.
     - Esc → clear the buffer if there is one; otherwise cancel if busy;
       otherwise exit the app.
   - In `display.ts`, handle `json.event === "text_input"` by calling the
     existing `handleTextInputEvent(text)`. `ChatFlow`'s sleep state
     already accepts text through `onTextInput`.
   - Esc: call `own_escape_key("whisplay-ai-chatbot")` and implement Esc
     in-app. Also update `~/.whisplay-daemon/app/whisplay-ai-chatbot.json`
     through its install script.
   - Restyle the header (`render_header`) to the MFruit status bar if that
     can be done safely. It is a 1300-line file with face animation, so
     keep the change surgical.
   - AGENTS.md is that repo's agent doc: add the rule pointer there and in
     a new CLAUDE.md.
3. **MFruit OS docs:**
   - APP_DEVELOPMENT.md: add an "MFruit App SDK" section and a keyboard
     section.
   - README: mention keyboard support.
   - CHANGELOG: add 1.3.0 (SDK, launcher keyboard, Esc registration,
     `MFRUIT_HOME` export). Bump the version in `mfruitos/__init__.py` and
     `manifest.json`.
   - CLAUDE.md: SDK location, the app rules, keyboard ownership rules.
   - docs/HARDWARE_TESTS.md: keyboard steps (navigate Home with a keyboard;
     Esc in an app goes back, not out; typing in app A does nothing in
     background app B).
   - Update the templates/whisplay-app-template to use the SDK.
4. **Deploy and verify on hardware:**
   - Orange Pi `orangepi@192.168.0.130`: `scripts/deploy.sh <host>
     --no-service`, then `sudo -n systemctl restart whisplay-os.service`.
   - Pi `jarvis@192.168.0.33` was unreachable at the last check.
   - The apps deploy with their own `deploy.sh`. WalkieTalkie is already
     deployed and verified on the Orange Pi.
   - The crypto dashboard is not registered on the Orange Pi (it is not in
     `~/.whisplay-daemon/app/`), so deploying it there needs its
     `install.sh`. Ask the user before installing a new app on a board.
   - MFruit OS on the Orange Pi is still 1.2.0: the launcher keyboard and
     Esc registration are not deployed yet.
   - No keyboard is attached to either board, and `/dev/uinput` is
     root-only, so keyboard hardware tests need the user to plug one in.
     Say so in the report rather than claiming it verified.
5. **Final report to the user**, per milestone format:
   - root cause / what changed
   - files changed
   - tests added and passing per repo
   - hardware tests done and not done
   - known issues

## Open items from before

- The user still has to run `bash ~/MFruitOS/scripts/install.sh` on both
  boards (it needs their sudo password). That installs the whisplay-daemon
  background drop-in and the Pi's service.
- Hardware checklist steps 9–11 in `docs/HARDWARE_TESTS.md` are not yet
  verified.
- Milestones M2+ (core/hardware separation, mock/headless) are deferred.
- The MFruitOS directory is not a git repo in this environment. The user
  may want a `.gitignore` for `__pycache__`.

## Useful commands

```bash
cd ~/MFruitOS && python3 -m unittest discover -s tests          # ~210 tests, ~2 min
python3 -m unittest discover -s tests -p "test_sdk.py"          # SDK only
scripts/sdk-sync.sh ~/WalkieTalkie                              # re-vendor after SDK edits
cd ~/WalkieTalkie && python3 -m pytest -q                       # 577 tests, ~1 min
python3 tools/preview.py --out /tmp/walkie-preview              # every screen to PNG
cd ~/whisplay-crypto-dashboard && python3 -m pytest -q
PF=/tmp/claude-1000/-home-meng-MFruitOS/*/scratchpad/venv/bin/pyflakes   # pyflakes lives here
```

After any SDK change: rerun `tests/test_sdk.py`, then `sdk-sync.sh` into
every app that has a `mfruit_sdk/`, then rerun each app's tests.
