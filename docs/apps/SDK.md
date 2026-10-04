# MFruit App SDK

The SDK makes an app handle input and look like MFruit OS. Its source is
`mfruitos/sdk/` (MFruit OS uses it too); every app carries a copy named
`mfruit_sdk/` ([ADR 0003](../platform/ADR/0003-vendored-sdk-distribution.md)).
It needs Python 3.9+ and Pillow (UI only), imports only itself, the standard
library and Pillow, and uses relative imports so the copy works under its new
package name.

Current version: **1.4.0** (`SDK_VERSION` in `mfruitos/sdk/__init__.py`).

## Modules

| Module | Provides |
|---|---|
| `mfruit_sdk.input` | `InputController`: the button and USB/Bluetooth keyboards as MFruit OS actions |
| `mfruit_sdk.gestures` | `ButtonGestures`: tap, 2×, 3×, 4×, hold (used by `InputController`) |
| `mfruit_sdk.keys` | `KeyReader`, `KeyEvent`: keyboards via the key hub, or evdev standalone |
| `mfruit_sdk.ui` | `Canvas`, `status_bar`, `footer`, `menu_hints`, `draw_list`, `Row`, `toast`, `message`, `text_field`, `to_rgb565`, `DARK`, `LIGHT` |
| `mfruit_sdk.ui.theme` | geometry constants (`CONTENT_TOP`, `FOOTER_Y`, …) and colour tokens |
| `mfruit_sdk.status` | `StatusMonitor`, `read_status()`, `wifi_level()`, `read_battery()` |
| `mfruit_sdk.daemon` | `own_escape_key(app_id)`, `request(cmd, payload)` (Whisplay-specific) |
| `mfruit_sdk.background` | `get()`, `set(keep_running=, screen_bright=)`: this app's *Keep running* and *Keep screen bright* ([below](#keep-running-in-the-background-mfruit_sdkbackground)) |
| `mfruit_sdk.radio` | the shared LoRa radio store: `settings` (`load_radio`, `load_device`, `radio_dir`), `contacts.Contacts`, `keyring.Keyring`, `crypto` — keyring/crypto need `cryptography` |

## Controls

The same in every app and in the launcher ([App contract §1](APP_CONTRACT.md)):

| Action | Button | Keyboard |
|---|---|---|
| `next` | tap | Down, Right, Tab |
| `previous` | 2× | Up, Left |
| `select` | hold (700 ms), then **release** | Enter |
| `back` | 4× | Esc |
| `extra` | 3× | screen-specific letter |
| `talk_start` / `talk_end` (talk screens) | hold — talks while held | Space — talks while held |
| `char` / `erase` / `key` | — | printable characters, Backspace, Home/End/PageUp/PageDown/Delete |

## Using `InputController`

```python
from mfruit_sdk.input import BACK, NEXT, PREVIOUS, SELECT, InputController

controller = InputController(on_action, app_id=APP_ID,
                             active=lambda: board.foreground_ready,
                             on_armed=show_release_hint)
controller.attach(board)    # wires the daemon's button_pressed / button_released
controller.start()          # starts the keyboard reader

def on_action(action):      # called from the button or keyboard thread; keep it short
    if action.name == NEXT: ...
    elif action.name == SELECT: ...
    elif action.name == BACK: ...   # on the first screen: leave the app
```

- Pass the registered `app_id` (or inherit `WHISPLAY_APP_ID` from `mfruit-run`);
  the key hub routes keys by it.
- `active()` must be true only while the app owns the screen; keys that went
  down while it was false are ignored even if released later. Call
  `controller.reset()` when focus is revoked.
- Talk screens pass `talk=lambda: True` and `talk_press_ms=350`; a hold there
  talks, and 3× opens the selected item. Screens that take text pass
  `typing=` so Space types a space.
- Options: `click_window_ms=400`, `long_press_ms=700`, `debounce_ms=75`,
  `keyboard=True`, `clock`, `threaded=True` (tests use `threaded=False`, a fake
  clock and `keyboard=False`, see [Testing](TESTING.md)).

## Keyboard input and the key hub

While MFruit OS runs it holds every keyboard exclusively (`EVIOCGRAB`), so an
app cannot read `/dev/input` directly. The SDK's `KeyReader` connects to the
key hub at `~/.whisplay-os/state/keys.sock` (override: `MFRUIT_KEYS_SOCKET`;
otherwise resolved from `MFRUIT_HOME`/`WHISPLAY_OS_HOME`). Each press, repeat
and release goes to the app that owned the screen when the key went down.
Without a reachable hub (app running standalone) the SDK reads evdev itself,
finding keyboards through inotify without polling.

Apps that do not use the SDK cannot read the grabbed keyboards. For them
MFruit OS bridges the Whisplay keyboard convention through the daemon: **Esc**
closes the app unless it set `disable_esc_exit_key`, and **Space** reaches it
as its button (`button_pressed`/`button_released`). Other keys are not
delivered; use the SDK for full keyboard input.

Hub protocol (internal between the platform and the SDK; apps use the SDK):

```text
app -> hub   {"app_id": "<id>"}
hub -> app   {"type": "keyboards", "devices": ["event3"]}
             {"type": "key", "kind": "key", "value": "enter", "action": 1, "code": 28}
```

## Drawing

`Canvas` wraps a 240×280 Pillow image with the MFruit theme and fonts (Inter
from MFruit OS, DejaVu elsewhere; `MFRUIT_FONT_DIR` adds a directory).
`status_bar(canvas, page_name, status)` draws the page name and Wi-Fi/battery;
`draw_list(canvas, rows, selected)` draws `Row` lists; `footer(canvas,
menu_hints(...))` draws hints; `to_rgb565(image)` converts a frame for the
daemon framebuffer without NumPy. Layout rules: [UI guidelines](UI_GUIDELINES.md).

## Status

`StatusMonitor(interval=10.0, on_change=...)`, once `start()`ed, refreshes
Wi-Fi level and battery on its own thread and calls `on_change(status)` when
they change; render code reads the cached value with `monitor.sample()`.

## Daemon helper

`own_escape_key(app_id)` re-registers only `disable_esc_exit_key: true` for the
app. Call it right after registering and **before taking the screen**: every
`app.register` makes whisplay-daemon redraw its desktop. This module is
Whisplay-specific and will move behind a host-neutral API in a later SDK
([Roadmap](../platform/ROADMAP.md)).

## The shared radio (`mfruit_sdk.radio`)

Radio apps share one module, frequency, identity and contact list
([ADR 0007](../platform/ADR/0007-shared-radio-capability.md)). Read the
provisioned settings with `settings.load_radio()` (None until
`setup-radio.sh` has run — show "Radio not set up" instead of guessing);
take this radio's Device ID from `settings.load_device(legacy_address=...)`;
keep keys in `keyring.Keyring()` (pass `legacy_path=` once to adopt an app's
older `keys.json`) and names in `contacts.Contacts()`. Encrypt with
`crypto.seal`/`open_sealed` (WalkieTalkie's header) or
`crypto.seal_with`/`open_with` (any header: a 4-byte per-packet context plus
authenticated header bytes). Never copy `keys.json` between devices.

## Keep running in the background (`mfruit_sdk.background`)

An app that must keep working after the user leaves it (receiving radio
messages, for example) can offer its own switch for MFruit OS's per-app
*Keep running* and *Keep screen bright* ([ADR 0009](../platform/ADR/0009-app-background-request.md)):

```python
from mfruit_sdk import background

state = background.get()          # State(keep_running, screen_bright), or None
background.set(keep_running=True, screen_bright=True)
```

With *Keep running*, leaving the app must **release the screen and stay
quiet** instead of exiting ([app contract](APP_CONTRACT.md)); MFruit OS hands
the screen back when the user opens the app from Home. With *Keep screen
bright*, MFruit OS holds the backlight at 100% while the app runs in the
background: ask for it only when the hardware needs it (a LoRa HAT whose M0 is
the backlight pin, [KI-11](../quality/KNOWN_ISSUES.md#ki-11-radio-deaf-while-the-screen-is-dimmed-stock-lora-hat-jumpers)),
and say on screen that the display stays lit. `None` means MFruit OS is not
running or is older than SDK 1.4.0: show the switch as unavailable. The user
sees and can change both in Settings > Apps; read `get()` again before acting
on them. This is a convenience contract on the user's own control socket, not
a permission.

## Vendoring and drift checks

```bash
~/MFruitOS/scripts/sdk-sync.sh <dir where "import mfruit_sdk" must work>          # copy
~/MFruitOS/scripts/sdk-sync.sh <dir where "import mfruit_sdk" must work> --check  # exit 1 if stale
```

Never edit the copy; change `mfruitos/sdk/`, run `tests/test_sdk.py`, bump
`SDK_VERSION` when behavior changes, then sync each app. `sdk-sync.sh` writes a
`VENDORED` note with the version. `scripts/check-app.py` also compares every
`mfruit_sdk/` in a package with the platform copy.

## Versions and compatibility

| SDK | Shipped with | Change | Compatibility |
|---|---|---|---|
| 1.1.0 | MFruit OS 1.3.0 | first release: input controller, keyboard reader, chrome, status | apps read keyboards directly |
| 1.2.0 | MFruit OS 1.4.0 | keys through the launcher's key hub; exclusive grab | **requires MFruit OS 1.4.0** for keyboard input while the launcher runs; older direct-input apps receive no keys under 1.4.0. Deploy the OS and keyboard apps together |
| 1.3.0 | MFruit OS 1.4 (unreleased) | adds `radio` (shared radio store, pairing keys, crypto) | additive: apps on 1.2.0 keep working; `check-app.py` reports their copies as stale until synced. `radio.keyring`/`crypto` need `cryptography` |
| 1.4.0 | MFruit OS 1.4 (unreleased, 2026-10-04) | adds `background` (an app's own *Keep running* / *Keep screen bright*, control command `app.background`) | additive: apps on 1.3.0 keep working; with an MFruit OS that lacks `app.background`, `get()`/`set()` return None. Affected: RadioConnect 0.5.0 (uses it), the template (synced). Tests: `tests/test_background_screen.py` |

Every SDK change records: the version, a compatibility statement, the sync and
check procedure above, the affected apps and the regression tests
([Part I §13](../platform/DEVELOPMENT_RULES.md#13-sdk-distribution)). Apps
vendoring the SDK today: ConnectWifi (bundled), the template, Messenger,
WalkieTalkie, the crypto dashboard and the AI chatbot's Python process.
