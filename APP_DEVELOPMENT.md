# Developing apps for MFruit OS

A MFruit OS app is a normal **whisplay-daemon foreground app** plus a
`manifest.json`. The daemon owns the hardware; your app draws into the
daemon's shared framebuffer and reacts to button events. MFruit OS installs,
launches, updates and removes it.

The fastest start is the template: copy
[`templates/whisplay-app-template`](templates/whisplay-app-template), change
the `id`, `name` and `repository`, and install it with
`mfruitctl sideload <folder>`.

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
  "min_os_version": "1.0.0",
  "repository": "https://github.com/example/whisplay-weather",
  "exit_gesture": "quad_click",
  "priority": 0,
  "env": {"WEATHER_UNITS": "metric"},
  "test": "test.sh",
  "persist": [".venv", "config.yaml"],
  "disable_esc_exit_key": false
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
| `min_os_version` | no | installation is refused on older MFruit OS versions |
| `repository` | no | `https://github.com/owner/repo`; if present it must match the repository the package is downloaded from |
| `exit_gesture` | no | `quad_click` (default), `long_press` or `none` — passed to the daemon |
| `priority` | no | integer; ordering hint (the user's own order wins) |
| `env` | no | extra environment variables (string values) |
| `test` | no | script run after installation, before activation; non-zero = rollback |
| `persist` | no | paths copied from the previous version into the new one on update (the user's copy replaces the packaged file) — for a venv or user-edited config |
| `disable_esc_exit_key` | no | `true` to stop an external keyboard's Esc key from closing the app |
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
`templates/whisplay-app-template/app/whisplay_app.py` is a small
dependency-free client that does all of this; copy it.

When the user leaves your app (four quick clicks by default), MFruit OS takes
the screen back automatically, and — unless your app is marked `background` —
makes sure it has exited: after 3 seconds its process group receives SIGTERM,
then SIGKILL. Exit promptly on `app_exit_requested`.

Draw your first frame as soon as you can: until then the user sees MFruit OS's
"Opening <your app>" screen. Apps that set `exit_gesture: "none"` must
release focus themselves when the user asks to leave.

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

Scripts must not need `sudo` interactively. If your app needs system packages,
check for them in `install.sh` and fail with a clear message.

Keep Python dependencies in a virtualenv inside `$WHISPLAY_OS_APP_DATA` (see
the template's `install.sh`), or list `.venv` in `persist`, so updates don't
rebuild it. Building wheels on a Pi Zero 2 W is slow; prefer
`--system-site-packages` with apt-provided Pillow/numpy.

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
mfruitctl sideload ./my-app        # full install pipeline from a folder or archive
mfruitctl launch my-app
tail -f ~/.whisplay-os/logs/my-app.log
mfruitctl screenshot /tmp/s.png    # what MFruit OS itself is drawing
```
