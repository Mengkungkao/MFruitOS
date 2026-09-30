# Hello MFruit — MFruit OS app template

A minimal MFruit OS app package: a counter with MFruit OS's own controls
and look. It requires MFruit OS 1.4.0 or newer. Copy this folder to start a
new app, then validate the resulting package and its hardware behaviour.

| Button | Keyboard (USB or Bluetooth) | |
|---|---|---|
| tap | Down, Right, Tab | +1 |
| 2 clicks | Up, Left | −1 |
| hold, then release | Enter | reset |
| 4 clicks | Esc | leave the app |

It follows the MFruit OS app rules (`docs/APP_RULES.md` in the MFruit OS
repository; included here as `.claude/rules/mfruit-os-app.md`):
input through the SDK's `InputController`, MFruit OS's status bar and
footer hints, `exit_gesture: "none"` and `disable_esc_exit_key: true`.

```
whisplay-app-template/
├── manifest.json   required: id, name, version, entrypoint
├── run.sh          entrypoint started by MFruit OS
├── install.sh      runs on install and update (non-zero exit = abort + rollback)
├── update.sh       optional: data migration on upgrade/downgrade
├── uninstall.sh    optional: cleanup before removal
├── test.sh         optional: smoke test before activation
├── .claude/rules/mfruit-os-app.md   canonical development and release checklist
├── app/
│   ├── main.py
│   ├── whisplay_app.py   small whisplay-daemon client (copy it)
│   └── mfruit_sdk/       the MFruit App SDK, a copy: refresh it with
│                         MFruitOS/scripts/sdk-sync.sh <your app>/app
└── assets/icon.png
```

## Create your app

1. Copy this folder, including `.claude`, to your new repository.
2. Set a stable `id`, a display `name`, a semantic `version` and your own
   `repository` in `manifest.json`. Keep `min_os_version: "1.4.0"`,
   `exit_gesture: "none"` and `disable_esc_exit_key: true`.
3. Replace the counter content and its hints using the SDK. Keep the status
   bar, footer, focus checks and input controller. Match the standalone
   fallback id in `app/whisplay_app.py` to the manifest id; rename example
   labels and script log messages too.
4. Store user data in `WHISPLAY_OS_APP_DATA`. Adapt `install.sh` for your
   dependencies and `test.sh` for a fast import/render check that leaves the
   display and network alone. Make any data migrations reversible.
5. Refresh the vendored SDK and copied rules from the same MFruit OS checkout:

   ```bash
   ~/MFruitOS/scripts/sdk-sync.sh ./my-app/app
   cp ~/MFruitOS/docs/APP_RULES.md ./my-app/.claude/rules/mfruit-os-app.md
   python3 ~/MFruitOS/scripts/check-app.py ./my-app
   ```

Follow the included rules for input tests, screen previews, lifecycle
behaviour and the production checklist. A successful static check does not
replace those tests.

## Try it on a device

```bash
mfruitctl sideload ~/whisplay-app-template        # install from a folder
mfruitctl launch hello-whisplay
```

Use your new path and id after renaming the template. Confirm button and
keyboard navigation, return to Home, focus loss, and that data survives an
update and rollback. Inspect the app log for errors. Record checks that need
physical hardware and have not been completed.

## Publish it

1. Run the static package check, app tests, sideload and hardware checks on
   the final package. Keep caches, secrets and personal data out of the archive.
2. Push to GitHub and add the topic `whisplay-app` so MFruit OS can discover it.
3. Create a release whose tag matches the manifest version (`v1.1.0` ↔ `"1.1.0"`
   for this template before renaming).
   Optionally attach `<id>-<version>.tar.gz` and a `SHA256SUMS` file;
   otherwise the source archive of the tag is used.

See `APP_DEVELOPMENT.md` in the MFruit OS repository for the full specification.
