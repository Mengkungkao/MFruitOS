# Packaging

How to lay out a native package so mFruit OS can install, update, roll back and
remove it without manual steps. Field rules are in [Manifest](MANIFEST.md);
behavior rules in the [App contract](APP_CONTRACT.md) §7.

## Layout

```text
my-app/
├── manifest.json                    required, at the root
├── run.sh                           entrypoint (any safe relative path declared in the manifest)
├── install.sh                       optional: runs on install, reinstall, update and downgrade
├── update.sh                        optional: runs after install.sh when a previous version exists
├── uninstall.sh                     optional: runs before removal
├── test.sh                          smoke test, declared as "test"
├── app/…                            your code, including the vendored mfruit_sdk/
├── assets/icon.png                  optional square PNG
├── .claude/rules/mfruit-os-app.md   byte-identical copy of the app contract
└── README.md
```

Shell entrypoints and hooks use LF endings, a shebang and the executable bit.
End `run.sh` with `exec` so signals and the exit status reach mFruit OS.

## Lifecycle hooks

Hooks run as the normal user with no terminal (stdin is `/dev/null`), from the
**new** version's folder, with an allowlisted environment plus:
`WHISPLAY_APP_ID`, `WHISPLAY_OS_VERSION`, `WHISPLAY_OS_APP_DIR` (the new
version folder), `WHISPLAY_OS_APP_DATA`, `WHISPLAY_OS_PREVIOUS_VERSION` (empty on
first install). Output goes to `~/.whisplay-os/logs/<id>.log`.

| Hook | When | Timeout | On failure |
|---|---|---|---|
| `install.sh` | every install, reinstall, update and downgrade, before activation | 15 min | install aborted, previous version kept, data snapshot restored |
| `update.sh` | after `install.sh`, only when a previous version exists | 15 min | same |
| `test` hook | after installation, before activation | 2 min | same |
| `uninstall.sh` | before the app folder is deleted | 2 min | logged; removal continues |

Hooks must be repeatable: running `install.sh` twice leaves the same result.
The smoke test imports the app and checks essential local behavior; it must not
claim the display, send messages, transmit radio audio or need network
credentials, and it exits non-zero on failure.

## Dependencies

- Python packages: a venv inside `$WHISPLAY_OS_APP_DATA` (the template's
  `install.sh` shows how), or a `.venv` in the package listed in `persist` so
  updates do not rebuild it. On a Pi Zero 2 W prefer `--system-site-packages`
  with apt-provided Pillow; building wheels is slow.
- System packages: check for them in `install.sh` and fail with a clear message
  naming the package. Never require an interactive `sudo`.
- Frame conversion needs no NumPy (`to_rgb565`).
- Apps installed from the curated catalogue get generated venv scripts from
  their catalogue entry ([Installation](INSTALLATION.md#curated-catalogue)).

## Data

Code in the version folder is replaced on every update; treat it as
read-only. Everything users create or configure lives in
`$WHISPLAY_OS_APP_DATA`, which survives updates and is snapshotted before
hooks run. `persist` copies listed paths (for example a user-edited config
file) from the previous version into the new one; the user's copy replaces the
packaged default. Uninstall deletes the managed app directory **including
`data/`**; `uninstall.sh` cleans up anything the app created outside it.

## Release contents

Include the entrypoint, required assets, built runtime output (for example a
Node app's `dist/`), the vendored SDK and the contract copy. Exclude
`__pycache__`, bytecode, test caches, logs, live `.env` files and personal
runtime data; `check-app.py` rejects them. A source-only archive is incomplete
if `install.sh` does not build it.

## Preflight

```bash
python3 ~/MFruitOS/scripts/check-app.py <exact package directory>
```

Read-only: validates the manifest with the running OS version, the contract
settings, hooks, the SDK copy, the contract copy and common packaging
artifacts. It does not run any code and does not certify behavior or hardware
support ([Testing](TESTING.md)).
