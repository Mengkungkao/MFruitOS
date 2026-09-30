# Hello MFruit — MFruit OS app template

A minimal, complete MFruit OS app package: a counter with MFruit OS's own
controls and look. Copy this folder to start a new app.

| Button | Keyboard (USB or Bluetooth) | |
|---|---|---|
| tap | Down, Right, Tab | +1 |
| 2 clicks | Up, Left | −1 |
| hold, then release | Enter | reset |
| 4 clicks | Esc | leave the app |

It follows the MFruit OS app rules (`docs/APP_RULES.md` in the MFruit OS
repository; copy it into your app as `.claude/rules/mfruit-os-app.md`):
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
├── app/
│   ├── main.py
│   ├── whisplay_app.py   small whisplay-daemon client (copy it)
│   └── mfruit_sdk/       the MFruit App SDK, a copy: refresh it with
│                         MFruitOS/scripts/sdk-sync.sh <your app>/app
└── assets/icon.png
```

## Try it on a device

```bash
mfruitctl sideload ~/whisplay-app-template        # install from a folder
```

## Publish it

1. Change `id`, `name` and `repository` in `manifest.json`.
2. Push to GitHub and add the topic `whisplay-app` so MFruit OS can discover it.
3. Create a release whose tag matches the manifest version (`v1.0.0` ↔ `"1.0.0"`).
   Optionally attach `hello-whisplay-1.0.0.tar.gz` and a `SHA256SUMS` file;
   otherwise the source archive of the tag is used.

See `APP_DEVELOPMENT.md` in the MFruit OS repository for the full specification.
