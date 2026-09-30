# CONTINUE — where the work stands (2026-09-30)

The request (from the user, 2026-09-29):

> update ai-chatbot, messenger, walkietalkie, cryptodashboard: write a claude
> rule. update the app projects following current MFruitOS UI and interface
> controller. Enable all app to use with keyboard via USB or Bluetooth

Decisions the user made:

- **Gestures: "Hybrid".** Menus and lists in every app use MFruit OS's
  gestures exactly: tap next · 2× previous · hold (then release) open ·
  4× back. Hold-to-talk stays only on talk screens.
- **Keys** are the same everywhere: ↑/↓ move · Enter open · Esc back ·
  Space held = talk.
- **Chatbot keyboard: "Type questions".** Enter sends a typed question,
  Space held talks, Esc cancels or goes back.

**Status: the code is done in all five repos, and tests pass locally.**
What remains is hardware: both boards have been unreachable ("No route to
host") since the morning of 2026-09-30. Nothing from today is committed; the
user commits.

---

## What is done

### MFruit OS (`~/MFruitOS`), now 1.3.0 — 222 tests pass

**MFruit App SDK 1.1.0, `mfruitos/sdk/` (the only source).** Apps carry a copy named
`mfruit_sdk/`, made with `scripts/sdk-sync.sh <dir>`; `--check` reports a
stale copy.

| Module | What it does |
|---|---|
| `keys.py` | Keyboard reader: letter-key devices only, key down/repeat/up, held keys released when a keyboard goes away. It watches `/dev/input` with **inotify**, so a keyboard plugged in later is found at once and nothing polls while idle; without inotify it rescans every 2 s. |
| `gestures.py` | Button recogniser. Its worker sleeps until a button edge arrives (no idle wakeups). `hold_after` sets a hold threshold per press. |
| `input.py` | `InputController` and `Action`. It maps button and keyboard to next / previous / select / back / extra, plus talk_start / talk_end, char, erase and key. It takes `talk=`, `typing=`, `active=`, `on_armed=`, `talk_press_ms=` (talking can start sooner than a menu hold arms) and `reset()`. A key only counts if it went down while the app owned the screen. |
| `status.py` | WiFi and battery (`StatusMonitor`). |
| `daemon.py` | `own_escape_key(app_id)`. |
| `ui/` | `Canvas` (with `.over(draw)`), `status_bar(title, status, badge=, dot=, reserve=, title_sizes=)`, `footer`, `menu_hints`, `draw_list` / `Row`, `toast`, `message`, `text_field`, `theme`, `fonts` and `rgb565`. Fonts: Inter from MFruit OS (also found in a `~/MFruitOS` checkout), else DejaVu; `MFRUIT_FONT_DIR` overrides. |

**Launcher:**
- Keyboard control: arrows move, Enter opens, Esc goes back, Home goes to
  Home; only keys owned by MFruit OS count.
- MFruit OS registers with `disable_esc_exit_key`.
- `mfruit-run` exports `MFRUIT_HOME` and `MFRUIT_SESSION` to apps.
- Diagnostics has a *Keyboard* row, and `mfruitctl status` lists
  `keyboards`. `mfruitctl key down|up|left|right|tab|enter|escape|home`
  types a key through the real keyboard path (`Runtime._on_key`), so the
  launcher's key handling can be checked on a board without a keyboard.

**Docs:**
- `docs/APP_RULES.md` is the Claude rule; each app has a copy at
  `.claude/rules/mfruit-os-app.md`.
- APP_DEVELOPMENT.md has a new "MFruit App SDK" section.
- README: keyboard, controls table, layout.
- CHANGELOG: 1.3.0.
- CLAUDE.md: §15 "Keyboards and apps"; §23 on ending an app remotely.
- `docs/ARCHITECTURE.md`: a "Keyboards and the MFruit App SDK" section, and
  the `mfruit-keys` thread.
- `docs/HARDWARE_TESTS.md`: keyboard steps 12–18.

**Esc claim order (all apps and the template).** `own_escape_key` is called
right after `app.register` and **before** taking the screen. Every
registration makes whisplay-daemon draw its desktop straight to the LCD, and
without the background drop-in (not yet installed on the boards) that
flashed over an app that already had the screen. This is written into
APP_RULES.md §2 and into the SDK docstring.

**Other:**
- **App template** (`templates/whisplay-app-template`, 1.1.0): a correct
  MFruit app. It uses the SDK controller and chrome, sets `exit_gesture`
  "none" and `disable_esc_exit_key`, and its `test.sh` imports the app.
  `tests/test_template.py` covers it.
- `contrib/manifests/*`: drafts set `disable_esc_exit_key: true`.
- `.gitignore` added (`__pycache__/`, `*.pyc`). Compiled files the user
  already committed are still tracked. To untrack them:
  `git rm -r --cached -q $(git ls-files '*.pyc')`.

### ~/whisplay-crypto-dashboard — DONE (82 tests)

- **Controls:** tap/↓ next page · 2×/↑ previous · hold/Enter = the page's
  action (timeframe on Bitcoin, refresh elsewhere) · 3×/R refresh · 4×/Esc
  exit · T, H, 1–5.
- **Look:** MFruit status bar (page name, data light, WiFi, battery), plus
  footer hints and toasts.
- Committed by the user; today's SDK re-sync is not committed.

### ~/WalkieTalkie — DONE (578 tests)

- The navigation table is in MFruit actions. Talk screens (Start, Paired,
  Talk, Range test): hold or Space talks; there 3× and Enter open the row.
  Editors take actions, and typed digits are accepted.
- Status bar with the LoRa signal in a reserved slot; short page names that
  are tested to fit.
- **Hold thresholds (today):** talk after 350 ms (`input.hold_ms`); a menu
  hold arms after MFruit OS's 700 ms (new `input.long_press_ms`). Before
  this, menus opened after 350 ms.
- **Verified on the Orange Pi** (2026-09-29):
  - all tests pass on the device;
  - launched through MFruit OS and drew the new look;
  - Esc is claimed (`disable_esc_exit_key: true`);
  - exited cleanly (`APP_CLOSED result=exited`).
  - Not verified there: the physical button and a keyboard.
- Committed by the user; today's changes (split thresholds, SDK re-sync,
  README) are not committed.

### ~/Messenger — code DONE today (141 tests); not deployed

- **Input** goes through `InputController`; `controls/button.py`,
  `controls/keys.py` and `tests/test_keys.py` are removed.
  - **Chat (a talk screen):** hold or Space talks · tap/↑ older · ↓ newer
    · 2×, Tab or Enter → quick replies (2× on a failed message resends it)
    · 3× read aloud · 4×/Esc leave · letters compose, Enter sends, Esc
    cancels typing.
  - **Quick replies (an MFruit list):** tap/↓ next · 2×/↑ previous ·
    hold (release)/Enter send · 4×/Esc back.
  - Thresholds: talk after 350 ms (`input.hold_ms`); the list hold after
    700 ms (new `input.long_press_ms`).
- **Screen:**
  - MFruit status bar: the other radio's name, which shrinks rather than
    being cut, then WiFi and battery.
  - The footer shows hints, or a coloured pill while listening, sending or
    on an error.
  - The reply list is an SDK list.
  - Only whole bubbles are drawn below the status bar.
  - The typing cursor is drawn, because Inter has no "▏".
- **Tests:** new `tests/test_controls.py` drives the app's own controller
  with a fake clock. Chat, display and end-to-end tests are ported.
- **Other:** new `tools/preview.py`; README (with an update entry in the
  repo's own format), CLAUDE.md, rule, `docs/screen.png`, and Messenger's
  own CONTINUE.md step 2 are updated.

### ~/ai-chatbot — code DONE today; not deployed

- **Python:**
  - New `python/keyboard_input.py` (`KeyboardQuestions`): typed questions
    (Enter asks once the bot is idle, otherwise the text is kept); Space
    held sends `button_pressed` / `button_released`; Esc clears the
    question or leaves the app; Enter / Esc answer an approval prompt.
    Tests: `python/test/test_keyboard_input.py` (9).
  - `chatbot-ui.py`: MFruit status bar (the state as page name —
    Ready / Listening / Thinking / Answering… — then the chatbot's own
    icons, WiFi and battery). Footer hints while idle, and an MFruit text
    field while typing. It reads `text_input_enabled` from Node, claims Esc,
    resets input on focus loss, and `send_to_all_clients` iterates a copy.
  - The header is 14 px taller (129 → 143).
- **Node:** `src/device/display.ts` routes `text_input` →
  `handleTextInputEvent` and `approval_answer` → `onApprovalAnswer`;
  `states.ts` answers approvals from it. Type-checked in a scratch copy
  (`yarn install --ignore-scripts`, `tsc --noEmit`). The only error was a
  pre-existing one in `gemini.ts`, which I didn't touch.
- **The button stays in Node.** Its gestures already match MFruit OS's
  talk screens; this exception is written into APP_RULES.md.
- **Docs:** AGENTS.md ("MFruit OS app"), README (controls table), root
  CLAUDE.md, and `.claude/rules/mfruit-os-app.md` at the repo root.
- `battery_icon.py` / `wifi_icon.py` are now unused, but kept to stay close
  to upstream PiSugar.

---

## Next steps

1. **Wait for the boards, then deploy and verify.** Check with
   `ssh -o ConnectTimeout=6 orangepi@192.168.0.130 true` (and
   `jarvis@192.168.0.33`).
   - **Before every deploy:** do an rsync dry run with the deploy script's
     excludes, to confirm the device tree differs only by this work (it
     matched for WalkieTalkie).
   - **MFruit OS 1.3.0:** `scripts/deploy.sh orangepi@192.168.0.130
     --no-service`, then `sudo -n systemctl restart whisplay-os.service`.
     Check `mfruitctl status` shows version 1.3.0, and that a
     `mfruit-os.json` registration has `disable_esc_exit_key: true`. Then
     `mfruitctl key down` / `key enter` / `key escape`: Home should move,
     open and go back.
   - **WalkieTalkie:** `./deploy.sh orangepi@192.168.0.130`, then remove any
     leftover empty `app/input/` on the device (rsync keeps directories
     that hold `__pycache__`). Then `rm -rf app/input`.
   - **Messenger:** `./deploy.sh orangepi@192.168.0.130`, then
     `rm -rf controls/__pycache__/button* controls/__pycache__/keys*`.
     Run `python3 -m pytest -q` on the device.
   - **Chatbot:** copy the tree to the device, **then `bash build.sh`**. Node
     runs the compiled `dist/`, so without a build the new
     `text_input` / `approval_answer` events are ignored.
   - **Verify each app:**
     - `~/.whisplay-os/bin/mfruitctl launch <id>`;
     - grab `/tmp/whisplay-fb-<id>-*.bin` (convert with
       `mfruitos.launcher.ui.rgb565.from_rgb565`) and look at it;
     - check the app log for errors;
     - end the app with the daemon's `app.exit.request` (e.g.
       `python3 -c "from mfruit_sdk.daemon import request; request('app.exit.request', {'app_id': '<id>'})"`
       from the app dir), then check for `APP_CLOSED` in
       `~/.whisplay-os/logs/launcher.log`.
     - App ids: `whisplay-crypto-dashboard` (not registered on the Orange
       Pi; ask before installing it), `whisplay-lora-walkie`,
       `whisplay-lora-messenger`, `whisplay-ai-chatbot`.
   - **The physical button and a real keyboard need the user**: none is
     attached, and `/dev/uinput` is root-only. Use `docs/HARDWARE_TESTS.md`
     steps 12–18 and report each as verified or *not verified*.
2. **Hand the user commit messages** for today's changes, one per repo, in
   each repo's style.

## Open items from before

- The user still has to run `bash ~/MFruitOS/scripts/install.sh` on both
  boards (it needs their sudo password). That installs the whisplay-daemon
  background drop-in and the Pi's service.
- Hardware checklist steps 9–11 are not yet verified.
- Milestones M2+ (core/hardware separation, mock/headless) are deferred.
- Messenger's own CONTINUE.md: set both boards' timezone (needs sudo).

## Useful commands

```bash
cd ~/MFruitOS && python3 -m unittest discover -s tests              # 222 tests, ~2 min
python3 -m unittest discover -s tests -p "test_sdk.py"              # SDK only
for d in ~/whisplay-crypto-dashboard ~/WalkieTalkie ~/Messenger \
         ~/ai-chatbot/whisplay-ai-chatbot/python \
         ~/MFruitOS/templates/whisplay-app-template/app; do
  ~/MFruitOS/scripts/sdk-sync.sh $d; done                           # after any SDK change
cd ~/WalkieTalkie && python3 -m pytest -q                           # 578 tests, ~1 min
cd ~/Messenger && python3 -m pytest -q                              # 141 tests
cd ~/whisplay-crypto-dashboard && python3 -m pytest -q              # 82 tests
cd ~/ai-chatbot/whisplay-ai-chatbot/python && python3 -m pytest -q test/test_keyboard_input.py
python3 tools/preview.py            # WalkieTalkie, Messenger, dashboard: screens to PNG
```

`pyflakes` and `vermin` (Python 3.9 compatibility check) are installed in
the session scratchpad venv; recreate them with
`python3 -m venv <dir> && <dir>/bin/pip install pyflakes vermin`.
