# 2026-10-13 — Settings → Wi-Fi shown twice

## Problem

On both test boards, Settings → Wi-Fi showed the right page (network,
address, *Choose a network…*, *Phone Setup*), but *Choose a network…* opened
the same settings again: the Wi-Fi app's own page with a status card,
*Choose a network*, *Hidden network*, *Phone setup* and *Back to Settings*.

## Evidence

| What | Observed |
|---|---|
| Boards before the change | Orange Pi Zero 2W: mFruit OS 1.5.3 (release), Wi-Fi app 1.1.0 (bundled, `source: local`, no repository). Pi Zero 2 W: mFruit OS 1.6.0 (release, system setup applied), Wi-Fi app 1.1.0 (same record) |
| Source | `WifiScreen.choose_network` launches `connectwifi`; `ConnectWifiApp` always started in `MODE_MENU`, the page in `screens._menu` |
| The app's *Phone setup* row | starts/stops `sugar-wifi-config.service` with `sudo systemctl`; mFruit OS's Phone Setup runs sugar-wifi-conf itself as the user (ADR 0013): two owners of one function |
| Why a fix in the app would not reach the boards | `provision.py` installs the bundled app only when none exists; a System update swaps only the OS code (`Installer._install`: "system updates only swap code") |
| Wi-Fi page after the app closed | `WifiScreen.on_show` runs only on push or when uncovered by a pop; the Wi-Fi app opens without an Opening screen (`services.launch_app`), so nothing was popped and the page kept the network read before the app opened |

## Root cause

The Wi-Fi app was written as a complete Wi-Fi manager. Since 2026-10-10
mFruit OS's own Settings → Wi-Fi page shows the connection and runs Phone
Setup, so the app's menu duplicated that page (and its Phone setup switch
duplicated the owner of Phone Setup).

## Fix (uncommitted)

- Wi-Fi app 1.2.0 (`bundled/connectwifi`, mirrored into `~/ConnectWifi`):
  started by mFruit OS (`MFRUIT_HOME`, set by `mfruit-run`) it opens on the
  network list; the first row *Back*, Esc, four clicks and a successful
  connection end the app, which returns to Settings → Wi-Fi; the trailing
  *Back to Settings* row is left out; the old BLE service is not queried.
  Run on its own it keeps its menu.
- `mfruitos/updater/bundled.py` + `ScreenServices.update_bundled_apps`: after
  start-up and on the update timer, an installed copy of a bundled app from a
  local package, older than the bundled version and not rolled back from it,
  is updated through the installer job (once per version, not while open,
  hidden/order flags untouched). `provision.py` shares the packaging.
- `Runtime.on_session_ended`: when an app opened without an Opening screen
  ends, the page it was opened from runs `on_show` again.
- mFruit OS 1.6.1 (manifest, `__version__`, CHANGELOG).

## Regression tests

| Test | Negative control |
|---|---|
| `~/ConnectWifi/tests/test_app.py` `test_from_settings_*` (5) | all 5 fail against the 1.1.0 app (`git show HEAD:bundled/...`), pass with 1.2.0 |
| `tests/test_bundled_wifi_app.py` (the bundle as packaged, in mFruit OS CI) | the chooser test fails with the 1.1.0 app (`git stash` of the app) |
| `tests/test_bundled_apps.py` due rules | the rolled-back case fails without the `previous_version` check |
| `tests/test_bundled_apps.py` launcher update | fails without the open-app check |
| `tests/test_bundled_apps.py` Wi-Fi page re-read | fails without the `on_show` call in `on_session_ended` |

## Validation

| Check | Result |
|---|---|
| `bash scripts/check.sh` (dev machine, Jetson, Python 3.12) | all checks passed; 750 tests OK |
| `python3 -m pytest tests` in `~/ConnectWifi` | 144 passed |
| Orange Pi: `scripts/deploy.sh --no-service`, launcher restarted | at start `Updating bundled connectwifi to 1.2.0`, installed in 0.2 s (previous 1.1.0 kept, `hidden` still true, *Update Wi-Fi — Done* screen); Settings → Wi-Fi → *Choose a network…* (keys sent with `mfruitctl key`) showed **Networks** directly (9 networks, Back first, no second Wi-Fi page); up, up, Enter on *Back* → the app exited (code 0) and Settings → Wi-Fi was on screen. **DEVICE VERIFIED** (app framebuffer and launcher screenshots) |
| Pi Zero | Wi-Fi app 1.2.0 installed with the same installer call the launcher makes (`bundled.install_request`, as the user, `hidden` kept); *Choose a network…* showed **Networks** (1 network); Esc → app exited (code 0), Settings → Wi-Fi on screen. **DEVICE VERIFIED** for the app; the launcher-side changes are not on this board |

## Board state left

- **Pi Zero:** mFruit OS **1.6.0 release** (the files-only install of the
  1.6.1 build was undone before it ever ran: `system/current` back to
  `1.6.0-4c8e02`, record rewritten with previous 1.4.0, the 1.6.1 build
  removed), Wi-Fi app 1.2.0 (previous 1.1.0). Reason: the build reports 1.6.1
  before that release exists; the board's system setup would have tried to
  download v1.6.1 within a minute, failed, and not tried again for 1.6.1.
  Backup: `~/mfruit-backups/20261013-112901-before-wifi-chooser/`.
- **Orange Pi:** mFruit OS `1.6.1-local20261013112924` (reports 1.6.1; system
  setup not installed there, so nothing tries to download it), Wi-Fi app 1.2.0.
  Software Update will not offer a 1.6.1 release (same version), only later
  ones. Backup: `~/mfruit-backups/20261013-112859-before-wifi-chooser/`.

## Not verified

- The physical button on either board (keys were sent with `mfruitctl key`).
- Joining a different network from the list on a board, and the Wi-Fi page
  showing it afterwards (automated only; joining would cut the SSH session).
- The bundled update arriving through a real System update to a 1.6.1
  release (only through the launcher starting the new code).
- Python 3.9 at run time (CI job; syntax check passed locally).
