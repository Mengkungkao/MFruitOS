# 2026-10-03 — Fruit Store: uninstall, delete, reset

| | |
|---|---|
| Revision | working tree on top of `06fb70e` (uncommitted Fruit Store changes) |
| Device | Raspberry Pi Zero 2 W, `jarvis@192.168.0.33`; Whisplay upstream `1066486` |
| Request | WiFi Config appeared on the menu; add uninstall and delete (two functions, two confirmations); App installer becomes the Fruit Store (install, update, roll back, reset, uninstall, delete) |

## WiFi Config: what it was

- `~/.whisplay-daemon/app/whisplay-wifi-config.json` was written on 2026-09-30
  (an earlier Whisplay checkout registered its example `wifi_config_app.py`);
  mFruit OS adopted it the same day (`launcher.log`: `ADOPTED app=whisplay-wifi-config`).
  It has been on the menu since then.
- The fresh upstream clone (`1066486`) no longer has `example/wifi_config_app.py`,
  so opening it failed (`exit_code=2`, "The app exited before it opened a screen").
- The registry only checked that the working folder existed, so it was shown
  as installed. It now reports **App files missing (wifi_config_app.py)**.

## Changes

- Installer: `uninstall(keep_data=True)` keeps `data/` + `backups/` with
  `uninstalled.json`; `delete_data`; `reset_data`; a failed reinstall over kept
  data restores it (negative control: without the guard the data file is gone).
- Registry: `leftovers()`; "(removed)" daemon ghosts hidden; missing-script check.
- Daemon wrapper: `mfruit.app.unregister`; lifecycle falls back to the old
  re-register trick on a plain daemon.
- Services `uninstall_app` / `delete_app_data` / `reset_app` (jobs lane);
  Fruit Store screens (`store.py`); Settings › Apps uninstall uses the same
  questions; `mfruitctl uninstall|delete|reset|rollback`.
- The Fruit Store lists every app on the device except settings apps; the
  hard-coded app IDs it used to hide are gone.

## Commands and results

| Check | Result |
|---|---|
| `bash scripts/check.sh` | all steps ok; 422 tests |
| `tests/test_daemon_unregister.py` with `WHISPLAY_SRC` = upstream `1066486` | 3 OK |
| Preview (`--preview`) | 41 screens; Fruit Store, app page and the uninstall question checked as PNG |
| Pi: install, restart daemon + launcher (no job running) | wrapper lists `handle_command`, `_send_data`, `_send_data_bytes` |
| Pi: Fruit Store → WiFi Config → Uninstall → Uninstall → Delete data (driven with `mfruitctl key`, screenshots at each step) | daemon registration file removed and the app gone from `app.list`; second question shown; then adoption record removed; `~/Whisplay/example` untouched; WiFi Config no longer in `mfruitctl apps` |

## Not verified

- With the physical button or a real keyboard (simulated keys only).
- Uninstall, delete and reset of an OS-managed app on the device (automated only).
- A plain daemon on a device (`--no-background-daemon`): fallback tested only
  against the real daemon code in the test harness.
- Orange Pi.

## Found on the way

- The first on-device run of the questions showed long texts cut off with "…";
  they were shortened and rechecked in the preview.
- After Delete data the app's page stayed open with only Back; it now closes.

## Follow-up: RadioConnect lifecycle on two devices (same day)

RadioConnect 0.2.0, built with its `tools/build-release.sh`, was sideloaded as
a release archive.

| Check | Result |
|---|---|
| Pi: update 0.1.0 → 0.2.0, data kept | ok |
| Pi: `mfruitctl rollback` | **first refused but reported "started"**: the app had exited on its own and the registry still said running (refresh before the process was gone). Fixed (refresh after every close; ctl reports refusal); then ok |
| Pi: failed update (0.2.1 whose `test.sh` exits 1) | rolled back, data restored, 0.2.0 still active |
| Pi: reset, uninstall (data kept), reinstall (data back), uninstall + delete (nothing left; shared radio store kept), fresh install | ok |
| Pi: sideload while RadioConnect was open | **found: the first update went over the open app** (0.1.0 kept running from its old folder). Fixed: refused with "RadioConnect is open; close it, then install again" (verified after deploy) |
| Orange Pi: update 0.1.0 → 0.2.0 | ok |
| Both: mFruit OS deployed from `~/MFruitOS-candidate`, `install.sh --no-service`, launcher restart (no job running) | ok; check.sh 425 tests before deploying |
