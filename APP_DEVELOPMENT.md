# Developing apps for MFruit OS

A MFruit OS app is a normal **whisplay-daemon foreground app** plus a
`manifest.json`. The daemon owns the hardware; your app draws into the
daemon's shared framebuffer and reacts to button events. MFruit OS installs,
launches, updates and removes it.

The [app integration index](docs/apps/README.md) routes app developers through
creation, adoption, packaging and validation. The fastest start is the template: copy
[`templates/whisplay-app-template`](templates/whisplay-app-template), change
the `id`, `name` and `repository`, and install it with
`mfruitctl sideload <folder>`.

This guide covers app packages and their managed runtime. The app behavior
contract is in [docs/APP_RULES.md](docs/APP_RULES.md); MFruit OS platform
architecture is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Package layout

```
my-app/
├── manifest.json     required
├── run.sh            entrypoint (any path; declared in the manifest)
├── install.sh        optional: runs on install and every update
├── update.sh         optional: runs after install.sh on upgrade/downgrade
├── uninstall.sh      optional: runs before removal
├── test.sh           optional smoke test (declared as "test")
├── app/…             your code
├── assets/icon.png   optional, square PNG
└── README.md
```

## manifest.json

```json
{
  "id": "weather",
  "name": "Weather",
  "version": "1.0.0",
  "description": "Weather information",
  "entrypoint": "run.sh",
  "icon": "assets/icon.png",
  "min_os_version": "1.4.0",
  "repository": "https://github.com/example/whisplay-weather",
  "exit_gesture": "none",
  "priority": 0,
  "env": {"WEATHER_UNITS": "metric"},
  "test": "test.sh",
  "persist": [".venv", "config.yaml"],
  "disable_esc_exit_key": true
}
```

| Field | Required | Rules |
|---|---|---|
| `id` | yes | 1–48 chars: lowercase letters, digits, `-`, `_`. Must be stable forever — it is the daemon `app_id` your code uses. Reserved: `mfruit-os`, `whisplay-wifi`, `whisplay-bluetooth`, `whisplay-volume`, `whisplay-system`. |
| `name` | yes | up to 40 chars, shown in the launcher |
| `version` | yes | [semantic version](https://semver.org) (`1.2.3`, `1.2.3-beta.1`) |
| `entrypoint` | yes | relative path inside the package; no `..`, no absolute paths, only `A-Za-z0-9._/-` |
| `description` | no | up to 160 chars |
| `icon` | no | relative path to a PNG; a coloured tile with initials is used otherwise |
| `min_os_version` | no | installation is refused on older MFruit OS versions; apps using the current SDK contract declare `1.4.0` or newer |
| `repository` | no | `https://github.com/owner/repo`; if present it must match the repository the package is downloaded from |
| `exit_gesture` | no | parser accepts `quad_click` (legacy default), `long_press` or `none`; MFruit apps explicitly use `none` because the SDK implements back |
| `priority` | no | integer; ordering hint (the user's own order wins) |
| `env` | no | extra environment variables (string values) |
| `test` | no | script run after installation, before activation; non-zero = rollback |
| `persist` | no | paths copied from the previous version into the new one on update (the user's copy replaces the packaged file) — for a venv or user-edited config |
| `disable_esc_exit_key` | no | `true` to stop an external keyboard's Esc key from closing the app. MFruit apps set it: Esc is their "back" (see [The MFruit App SDK](#the-mfruit-app-sdk)) |
| `background` | no | `true` if the app must keep running after the user leaves it (e.g. it receives messages). Default `false`: leaving an app closes it completely. Users can change it per app (*Keep running*). |

A manifest that fails validation is rejected as a whole; nothing is installed.

## Runtime contract

MFruit OS registers your app with the daemon (`app.register`, `persist: true`)
with the launch command `~/.whisplay-os/bin/mfruit-run <id>`. When launched:

- the working directory is the active version folder (`…/apps/<id>/current`);
- environment: `WHISPLAY_APP_ID=<id>`, `WHISPLAY_OS_APP_DIR` (code, read-only
  in spirit — it is replaced on update), `WHISPLAY_OS_APP_DATA` (persistent
  data, kept across updates and snapshotted before each update), plus your
  manifest `env`;
- stdout/stderr go to `~/.whisplay-os/logs/<id>.log`; the exit code is
  recorded, and a crash within 10 s shows *Application failed to start* with
  Retry / Logs / Back.

Your app must follow the Whisplay daemon integration contract
([APP_INTEGRATION.md](https://github.com/PiSugar/Whisplay/blob/main/APP_INTEGRATION.md)):

1. subscribe to events (`events.subscribe` with your `app_id`);
2. `app.focus.acquire`, then `framebuffer.acquire`, and `mmap` the buffer;
3. draw 240×280 RGB565 (big-endian) frames into it;
4. on `app_exit_requested`: stop work, `app.focus.release`, exit quickly
   (the daemon force-releases the screen after 1.5 s);
5. on `app_focus_revoked`: stop drawing; the buffer is gone.

Do **not** call `app.register` with a `launch_command` yourself — that would
replace the MFruit OS wrapper (MFruit OS re-adopts the app on its next scan).
Registering without one is harmless.

Apps must not start other apps through the daemon (`app.launch`): while MFruit
OS runs, every app start needs a one-shot ticket that only MFruit OS issues,
so such a start is denied and logged in `~/.whisplay-os/logs/launch-gate.log`.
`templates/whisplay-app-template/app/whisplay_app.py` is a small client
that does all of this; copy it.

When the user leaves your app (four quick clicks by default), MFruit OS takes
the screen back automatically, and — unless your app is marked `background` —
makes sure it has exited: after 3 seconds its process group receives SIGTERM,
then SIGKILL. Exit promptly on `app_exit_requested`.

Draw your first frame as soon as you can: until then the user sees MFruit OS's
"Opening <your app>" screen. Apps that set `exit_gesture: "none"` must
release focus themselves when the user asks to leave.

## The MFruit App SDK

Every MFruit OS app should handle and look like MFruit OS itself. The MFruit
App SDK makes that the easy path: the source is `mfruitos/sdk/` in this
repository, and an app carries a copy named `mfruit_sdk` beside its code:

```bash
~/MFruitOS/scripts/sdk-sync.sh <dir where "import mfruit_sdk" must work>
~/MFruitOS/scripts/sdk-sync.sh <that dir> --check    # exit 1 if the copy is stale
```

Never edit the copy; change `mfruitos/sdk/` (with its tests in
`tests/test_sdk.py`) and sync again. It needs Python 3.9+ and Pillow (UI
only).

| Module | What it gives you |
|---|---|
| `mfruit_sdk.input` | `InputController`: the button and any USB or Bluetooth keyboard, as MFruit OS actions |
| `mfruit_sdk.keys` | the keyboard reader underneath (found on plug-in via inotify, no polling) |
| `mfruit_sdk.ui` | `Canvas`, `status_bar`, `footer`, `draw_list` / `Row`, `toast`, `message`, `text_field`, the MFruit theme and fonts (Inter from MFruit OS, DejaVu elsewhere), `to_rgb565` |
| `mfruit_sdk.status` | WiFi level and battery for the status bar (`StatusMonitor`) |
| `mfruit_sdk.daemon` | `own_escape_key(app_id)`: make Esc the app's key — call it after registering and before taking the screen (a registration makes the daemon redraw its desktop) |

The controls, the same in every app and in the launcher:

| Action | Button | Keyboard |
|---|---|---|
| next | tap | Down, Right, Tab |
| previous | 2× | Up, Left |
| select | hold (0.7 s), then **release** | Enter |
| back | 4× | Esc |
| extra | 3× | a letter |
| talk (talk screens) | hold — talks while held | Space — talks while held |

```python
from mfruit_sdk.input import BACK, NEXT, SELECT, InputController

controller = InputController(on_action, app_id=APP_ID,
                             active=lambda: board.foreground_ready,
                             on_armed=show_release_hint)
controller.attach(board)          # the daemon's button_pressed / button_released
controller.start()                # and every keyboard on the board
...
def on_action(action):
    if action.name == NEXT: ...
    elif action.name == SELECT: ...
    elif action.name == BACK: ...   # from the first screen: leave the app
```

Keys only count while the app has the screen (`active`), and only keys that
went down while it did. MFruit OS holds keyboards exclusively and routes keys
through its hub to the foreground app. Pass the registered `APP_ID` or inherit
`WHISPLAY_APP_ID` from `mfruit-run`; standalone SDK readers fall back to evdev
when the hub is unavailable.
Call `controller.reset()` when focus is revoked. Talk screens pass
`talk=lambda: True` (and `talk_press_ms=350` so the first word is kept);
screens that take text pass `typing=`, which turns Space into a space.

The rules MFruit apps follow — controls, registration, screen layout,
tests — are in [docs/APP_RULES.md](docs/APP_RULES.md); copy them into your
app as `.claude/rules/mfruit-os-app.md`. The template app uses all of the
above.

## Lifecycle scripts

All scripts run as the normal user, with no terminal, from the new version's
folder, with these variables: `WHISPLAY_APP_ID`, `WHISPLAY_OS_VERSION`,
`WHISPLAY_OS_APP_DIR`, `WHISPLAY_OS_APP_DATA`, `WHISPLAY_OS_PREVIOUS_VERSION`
(empty on first install). Output goes to the app log.

| Script | When | On failure |
|---|---|---|
| `install.sh` | every install, update, downgrade and reinstall, before activation (timeout 15 min) | install aborted, previous version kept, data restored |
| `update.sh` | after `install.sh`, only when a previous version exists | same as above |
| `test` script | after installation, before activation (timeout 2 min) | same as above |
| `uninstall.sh` | before the app folder is deleted (timeout 2 min) | logged, removal continues |

Uninstall removes the managed app directory, including its `data/` directory.
Back up any user data that must survive removal before uninstalling. The
`uninstall.sh` hook runs before deletion and is for cleaning up resources the
app created outside its managed directory.

Scripts must not need `sudo` interactively. If your app needs system packages,
check for them in `install.sh` and fail with a clear message.

Keep Python dependencies in a virtualenv inside `$WHISPLAY_OS_APP_DATA` (see
the template's `install.sh`), or list `.venv` in `persist`, so updates don't
rebuild it. Building wheels on a Pi Zero 2 W is slow; prefer
`--system-site-packages` with apt-provided Pillow. Use the SDK's `to_rgb565`
for frame conversion; it needs no NumPy dependency.

## How updates are installed

```
CHECK → DOWNLOAD → VERIFY → BACKUP → INSTALL → TEST → ACTIVATE
```

- The new version is extracted to its own folder
  `apps/<id>/versions/<version>-<random>/`; the running version is never
  touched.
- Archives are checked for path traversal, absolute paths, escaping symlinks
  and device files; set-uid bits and group/world write permissions are removed.
- Activation is an atomic swap of the `current` symlink. On any failure the
  previous version stays active and app data is restored from its snapshot.
- The previous version is kept for one-step *Roll back*; older versions are
  pruned (`updater.keep_versions`, default 2).

## Publishing on GitHub

1. Push the package to a public GitHub repository and add the topic
   **`whisplay-app`** (this is how *Updater → Install app → Discover* finds it).
2. Create a **release** whose tag is the manifest version: tag `v1.2.0` ↔
   `"version": "1.2.0"`. The installer refuses a release whose manifest
   version does not match its tag.
3. Optionally attach a package archive named `<id>-<version>.tar.gz` (or
   `.zip`) plus a checksum: GitHub's asset digest, a `SHA256SUMS` file, or
   `<asset>.sha256`. With a checksum the install is verified; without an
   asset, the tag's source archive is used and integrity relies on HTTPS.
   Set `updater.require_checksum` to refuse unverified installs.

Only semantic-version tags count as versions; the newest commit is not treated
as a release. Repositories without releases can still be installed by `git
clone` and registered with the daemon; MFruit OS then offers commit-tracking
updates for them.

## Testing locally

```bash
python3 ~/MFruitOS/scripts/check-app.py ./my-app  # static package/rules/SDK checks
~/MFruitOS/scripts/sdk-sync.sh ./my-app/app --check
mfruitctl sideload ./my-app        # full install pipeline from a folder or archive
mfruitctl launch my-app
tail -f ~/.whisplay-os/logs/my-app.log
mfruitctl screenshot /tmp/s.png    # what MFruit OS itself is drawing
```

Use the creation, development, production and integration checklists in
[docs/APP_RULES.md](docs/APP_RULES.md) before publishing. Static checks and
unit tests do not confirm physical button, keyboard, audio, radio or LED
behaviour. Record each hardware check separately, including checks not run.

An app adopted from the daemon registry can run inside MFruit OS without
being a complete native release package. A manifest drafted under
`contrib/manifests/` does not install missing dependencies, build an app, or
provide its smoke test. Test the actual release artifact through sideload,
update and rollback before calling it ready for native distribution.

### Existing companion release gaps (2026-09-30)

These describe the current local companion checkouts, not a requirement to
reinstall working clone-based apps. Continue using their board-specific
setup instructions and daemon adoption until the native migration is tested.

| App | Work still required before native release sign-off |
|---|---|
| Connect WiFi | Native manifest and install-time smoke hook are absent; adapt its standalone setup/registration flow for managed installation. |
| WalkieTalkie | Add a native manifest and smoke hook. Keep radio/codec/system setup separate from repeatable package hooks; preserve managed registration. |
| Messenger | A native manifest exists, but lacks a minimum OS version and smoke hook. Persist or relocate downloaded `models/`, migrate data into the managed data contract, and replace assumptions about a sibling `WalkieTalkie/config.yaml` before testing updates and rollback. |
| Crypto dashboard | Add a native manifest and smoke hook; adapt the standalone installer, which can install system packages and write daemon registration directly, for a noninteractive managed lifecycle. Account for existing external configuration/data. |
| AI Chatbot | Add the native package manifest and a reproducible Node build/install plus smoke hook, or publish a complete built release artifact. Preserve model/configuration/data paths. Its existing Node button logic still relies on daemon `quad_click` exit; see the explicit compatibility exception in the app rules. |

Shared SDK/UI checks and runtime fixes are separate from these release
requirements. A passing app test suite does not prove that a new package can
install dependencies, preserve models/messages, or reverse a data migration.

## SDK 1.2.0 keyboard migration

Pass the stable app id to InputController(app_id=APP_ID). The SDK uses MFruit
OS's key hub while available and direct evdev input when running standalone.
Do not open /dev/input yourself: the platform grabs keyboards exclusively.
Synchronize SDK copies and deploy keyboard apps together with MFruit OS 1.4.0.
The key hub protocol and ownership rules are in docs/ARCHITECTURE.md.
