# Getting started

From template to a running app on a device. Rules are in the
[app contract](APP_CONTRACT.md); this guide is the path through them.

## 1. Copy the template

```bash
cp -r ~/MFruitOS/templates/whisplay-app-template ~/my-app
cd ~/my-app
```

The template is a complete mFruit app: SDK input and chrome, a counter that
persists in the data directory, lifecycle hooks, a smoke test and the app
contract in `.claude/rules/mfruit-os-app.md`.

## 2. Choose a stable app ID

Edit `manifest.json`: set `id`, `name`, `version`, `description` and
`repository` ([Manifest](MANIFEST.md)). The ID is permanent: it is the
daemon `app_id`, the data directory name and the key for user settings.
Use the same ID in `InputController(app_id=...)` (or inherit
`WHISPLAY_APP_ID` from `mfruit-run`).

## 3. Build with the SDK

Keep the vendored `app/mfruit_sdk/`; never edit it. Read input through
`InputController`, draw with `mfruit_sdk.ui` and read status through
`StatusMonitor` ([SDK](SDK.md), [UI guidelines](UI_GUIDELINES.md)). Separate
state, actions and drawing so a smoke test can import and render without
taking the screen.

## 4. Store data in the right place

Code lives in `WHISPLAY_OS_APP_DIR` (replaced on every update). Everything
the user creates or configures lives in `WHISPLAY_OS_APP_DATA` (kept across
updates, snapshotted before each update). Never commit credentials; ship a
`.env.example` with placeholders.

## 5. Add dependencies

Python packages go into a venv inside the data directory (see the template's
`install.sh`) or a `.venv` listed in `persist`. System packages are checked in
`install.sh` with a clear error, never installed with an interactive `sudo`
([Packaging](PACKAGING.md#dependencies)).

## 6. Test locally

```bash
bash test.sh                                   # the smoke test the installer runs
python3 ~/MFruitOS/scripts/check-app.py .      # static package/contract/SDK preflight
~/MFruitOS/scripts/sdk-sync.sh app --check     # SDK copy is current
```

Controls and rendering tests drive the real `InputController` with a fake
clock ([Testing](TESTING.md)).

## 7. Sideload and run on a device

```bash
mfruitctl sideload ~/my-app        # full install pipeline from a folder or archive
mfruitctl jobs                     # wait for the install job to finish
mfruitctl launch my-app
tail -f ~/.whisplay-os/logs/my-app.log
```

Check the first frame, the status bar and footer, the controls with the button
and a keyboard, leaving the app (4× or Esc on the first screen) and that data
persists across a relaunch.

## 8. Package, release, update, roll back

Follow [Packaging](PACKAGING.md), then [Publishing](PUBLISHING.md). Exercise
update and rollback with disposable data before a release
([Update and rollback](UPDATE_ROLLBACK.md)).
