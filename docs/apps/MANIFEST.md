# Manifest specification

Every native package has a `manifest.json` at its root. It is validated by
`mfruitos/apps/manifest.py` before anything is installed and again after
installation; a manifest that fails validation is rejected as a whole and
nothing is installed. This document describes that validator.

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
  "disable_esc_exit_key": true,
  "priority": 0,
  "env": {"WEATHER_UNITS": "metric"},
  "test": "test.sh",
  "persist": [".venv", "config.yaml"],
  "background": false
}
```

## Fields

| Field | Required | Default | Validation | Meaning |
|---|---|---|---|---|
| `id` | yes | — | `[a-z0-9][a-z0-9_-]{0,47}`; not reserved (below). `app_id` is accepted as an alias | Permanent identity: daemon `app_id`, data directory, settings key. Never change it. |
| `name` | yes | — | non-empty, ≤40 characters | Name shown in the launcher |
| `version` | yes | — | semantic version (`1.2.3`, `1.2.3-beta.1`), ≤64 characters | Package version; must match the release tag when installed from GitHub |
| `entrypoint` | yes | — | safe relative path (≤200, `A-Za-z0-9._/-`, no `..`, no leading `/` or `~`); must be a file inside the package | What `mfruit-run` executes |
| `description` | no | `""` | ≤160 characters | Subtitle in the launcher |
| `icon` | no | `""` | safe relative path to a PNG | Launcher icon; a missing file is dropped silently and initials are shown |
| `min_os_version` | no | `""` | semantic version | Installation refused on an older MFruit OS. Apps using SDK 1.2.0 declare `1.4.0` or newer |
| `repository` | no | `""` | `https://github.com/owner/repo` or `owner/repo`; `http://` refused; normalized | Must match the repository the package is downloaded from |
| `branch` | no | `""` | ≤100 characters | Recorded in the install record; informational |
| `exit_gesture` | no | `quad_click` | `quad_click`, `long_press`, `none` | Daemon exit gesture. MFruit apps use `none` because the SDK implements Back |
| `disable_esc_exit_key` | no | false | boolean | Stops the daemon closing the app on Esc. MFruit apps set `true` (Esc is their Back) |
| `priority` | no | 0 | integer −1000…999 | Ordering hint; the user's own order wins |
| `env` | no | `{}` | keys `[A-Za-z_][A-Za-z0-9_]{0,63}`, string values ≤1024 | Extra environment variables at launch |
| `test` | no | `""` | safe relative path; must be a file in the package | Smoke test run after installation, before activation; non-zero exit rolls back |
| `persist` | no | `[]` | list of safe relative paths — **checked during installation only**: unsafe entries are skipped with a warning | Paths copied from the previous version into the new one on update (a venv, a user-edited config) |
| `background` | no | false | boolean | Keep running after the user leaves (e.g. receives messages); users can override per app (*Keep running*) |
| `type` | no | `app` | `app` or `system`; only `mfruit-os` may be `system` | Package type; `system` is MFruit OS itself |

Reserved IDs: `mfruit-os`, `whisplay-wifi`, `whisplay-bluetooth`,
`whisplay-volume`, `whisplay-system`, `settings`, `updater`, `system`.

Size limit: 64 KiB. The file must be UTF-8 JSON with an object at the top
level.

## Additional requirements for native MFruit apps

`scripts/check-app.py` enforces the [app contract](APP_CONTRACT.md) on top of
the validator: `type` is `app`, `exit_gesture` is `none`,
`disable_esc_exit_key` is `true`, a `test` hook is declared, a declared icon
exists, hooks are executable with a shebang and LF endings, and the vendored
SDK and contract copy match MFruit OS. The only documented exception is the
existing AI chatbot's daemon `quad_click` exit (contract §1).

## Compatibility rules

- **Unknown fields** are ignored by the validator (they stay available in the
  raw manifest) and do not fail installation on older MFruit OS versions.
  Do not rely on an unknown field having any effect.
- **There is no manifest schema version.** Compatibility is expressed with
  `min_os_version`: a manifest that needs a newer OS behavior declares the
  OS version that introduced it.
- **Defaults never change silently.** Changing a default (for example
  `exit_gesture`) is a compatibility change for every installed app.

## Adding or changing a field

Follow [Part I §9](../platform/DEVELOPMENT_RULES.md#9-app-integration-contract):
define the use case and owner, the validation, the behavior on older MFruit OS
versions, add tests in `tests/test_manifest.py`, and update this document and
the [app contract](APP_CONTRACT.md) if apps must act on it. A field that
changes how the launcher treats an app needs an [ADR](../platform/ADR/README.md).
