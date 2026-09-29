# Hello Whisplay — MFruit OS app template

A minimal, complete Whisplay app package: tap to count, hold to reset, four
quick taps to exit. Copy this folder to start a new app.

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
│   └── whisplay_app.py   standalone whisplay-daemon client (copy it)
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
