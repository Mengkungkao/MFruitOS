# MFruit OS validation — 2026-09-30

## Follow-up validation, cleanup and app standards

This section supersedes the original checkpoint below. The user expanded the
scope to cleanup, MFruit OS software/UI consistency, app development/production
rules and manual installation/testing/debugging on other devices.

| Suite | Local | Orange Pi final staged source |
|---|---:|---:|
| MFruit OS, including real daemon | 284 passed | 284 passed |
| ConnectWifi, including ShellCheck | 137 passed | 137 passed |
| WalkieTalkie | 637 passed | 637 passed |
| Messenger | 147 passed | 147 passed |
| Crypto dashboard | 86 passed | 86 passed |
| Chatbot keyboard/images/startup | 13 passed | 13 passed |
| **Python total** | **1,304** | **1,304** |

Chatbot TypeScript compilation and its interrupted-reply Node regression passed
in an isolated Orange Pi staging directory using the existing Node 20.20.2
dependencies. A negative control disabled the reply generation guard: the test
reported an incomplete reply and returned exit 1, then the compiled file was
restored. This validates that the test now fails correctly instead of always
returning success. No AI request or audio transmission was sent.

The dashboard is not installed as a production app on this board. Its first
staged test attempt lacked `requests`; pure-Python wheels were isolated under
`~/.mfruit-validation/python-deps`, then all 86 tests passed. No system packages
or production dependencies were removed or replaced. Board test fixtures
occasionally log failed attempts to grab event3 because the production launcher
already owns the real keyboard; the production service remained healthy.

### Corrected behaviour

- Wi-Fi now uses SDK InputController for both keyboard and button gestures,
  including previous/back, 700 ms hold/release, focus gating and held-key
  handover. Removed the obsolete evdev reader and redundant key adapter;
  explicit Back rows and first-frame behaviour remain. Ten sample documentation
  screens were refreshed, using mock network details.
- ConnectWifi, WalkieTalkie, Messenger and dashboard preserve the managed
  mfruit-run registration. Standalone launches still register their own entry.
- Dark-screen holds wake both radio apps without recording. Regressions failed
  before the fix. Messenger's empty `/` command no longer stops terminal input.
- Chatbot startup finds its own directory, including paths containing spaces.
  `npm test` now compiles and runs a regression with meaningful exit status.
- SDK/rules copies match the canonical source; ordinary UI text uses sentence
  case while abbreviations, ticker symbols and content accents are retained.
- MFruit test fixtures close parent log handles, process pipes, framebuffer
  attachments and socket readers; no fixture ResourceWarnings in final local run.

### Cleanup and deliverables

The reviewed cleanup removed 59 remaining cache directories, 350 files and
4,990,269 bytes. SDK refresh had already cleared two more audited cache
directories. All 95 tracked bytecode files (94 MFruit OS, one chatbot) are now
unstaged deletions. Chatbot has root ignore rules for future caches. Removed
unused Python imports/assignments, dashboard's unused NumPy installer dependency
and the redundant npm crypto package/lock entry. Kept assets, vendored SDKs,
models, environments, configuration, user data and board backups.

- [App rules](APP_RULES.md): creation, shared UI/input/lifecycle, development,
  native packaging, release and integration checklists; synced into six templates/apps.
- [App development](../APP_DEVELOPMENT.md): corrected manifest example and
  explicit native-release gaps in existing adopted companions. Chatbot's
  daemon-owned four-click exit remains a documented compatibility exception.
- [Device guide](DEVICE_SETUP.md): manual SSH copy, prerequisites, backup,
  install, checks, hardware validation, logs, debugging, rollback and uninstall.
- `scripts/setup-device.sh`: checks by default, explicit `--install` delegates
  to the existing installer. Eight tests cover mutation-free checks, failed
  prerequisites, argument forwarding and installing documentation. Its read-only
  check passed against the running Orange Pi's Python 3.10.12/Pillow 9.0.1/daemon.
- `scripts/check-app.py`: ten tests cover valid/invalid native packages, SDK/rules
  parity, missing files, unwanted artifacts and proof that hooks are never run.
  The clean template passed. This static check is not hardware certification.

### Deployment

- Active MFruit OS: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930101701`.
- Retained previous: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930093556`.
- Backup: `/home/orangepi/.mfruit-deploy-backups/cleanup-20260930101701/`.
- Installed 29 reviewed companion source/documentation files with hashes checked
  and rollback copies retained. No production dashboard installation or extra
  device installation. Board caches/data/configuration were not cleaned.

The post-deployment live check passed Wi-Fi launch/scan/return and repeated
keys; Bluetooth discovery and agent startup/shutdown; Messenger, WalkieTalkie
and chatbot launch/exit; update checking with 100 navigation keys. All four
companion registrations still point through mfruit-run. Final state was Home,
IDLE and connected, both services active; launcher PID 24012, NRestarts 0.
There were no new launcher journal warnings. Installed device preflight and
native template preflight both passed. No unrequested reboot occurred in this
follow-up; the earlier unexplained reboot remains part of the original record.

### Follow-up evidence and manual work

- Local MFruit final suite: `/tmp/mfruit-final-mf-tests.log` (284 tests, 140.089 s).
- Board final suites: `~/.mfruit-validation/final-cleanup-*-tests.log`;
  copied to `/tmp/mfruit-board-final-logs/` locally. MFruit: 185.294 s.
- Node build/regression and negative control:
  `/tmp/mfruit-cleanup-chatbot-node-tests.log`,
  `/tmp/mfruit-cleanup-chatbot-negative-control.log`.
- Post-deployment live log: `~/.mfruit-validation/live-cleanup-check.log` on
  Orange Pi; local `/tmp/mfruit-live-cleanup-check.log` and
  `/tmp/mfruit-live-final-health.log`.
- Cleanup inventory: `/tmp/mfruit-cleanup-removed.json`; device preflight:
  `/tmp/mfruit-device-preflight.log`.
- Deployment metadata: `~/.mfruit-validation/cleanup-deployment.json` and
  the permanent backup; local `/tmp/mfruit-cleanup-deployment.json`.

A Logi K250 keyboard is now attached at event3; the launcher has its file open,
and a competing EVIOCGRAB returns EBUSY. This confirms exclusive ownership,
not observed physical key routing. The user still needs physical keyboard and
hotplug/held-key tests, Bluetooth pairing/rejection/reconnect/forget, button and
LED inspection, reboot appearance, and real audio/LoRa exchange. Existing native
app package gaps remain documented; no claim of full production certification.

## Original validation record


Target: Orange Pi Zero 2W, `orangepi@192.168.1.122`, Linux 6.1.31 aarch64,
Python 3.10. Local validation: Linux, Python 3.12.

The board was ahead of the local checkout. Its newer MFruit OS 1.4.0 and
companion source were recovered and reviewed before further changes.
Configuration, secrets, user data, Git histories and radio addresses were preserved.

## Automated results

| Check | Result |
|---|---|
| MFruit OS final local suite, including real daemon | 266 passed |
| MFruit OS final Orange Pi suite, including real daemon | 266 passed |
| ConnectWifi | 137 passed, including separately rerun ShellCheck |
| WalkieTalkie | 632 passed |
| Messenger | 141 passed |
| Dashboard | 82 passed |
| Chatbot keyboard/startup | 12 passed locally and on Orange Pi |
| Deployed chatbot TypeScript | `tsc --noEmit` passed |
| MFruit OS self-test | 37 screens, local and Orange Pi |
| Orange Pi targeted installer / Git updater | 23 / 6 passed |
| Orange Pi targeted Bluetooth / shell wrapper | 15 / 12 passed |
| Runtime pyflakes / Python 3.9 compatibility / shell syntax | Passed |
| SDK and app rules equality across companion apps | Passed |
| Git whitespace checks | Passed |

Unique local checks: **1,270 passed**. Board runs repeat checks on the target
architecture. Existing fixtures emit ResourceWarnings; simulated failures also
intentionally appear in test output.

Nine shell wrapper tests failed before CRLF normalization, on both hosts.
LF normalization and `.gitattributes` address that issue. Two new Bluetooth
regressions cover shutdown cancellation and queued pairing after shutdown;
both failed before the fix.

## Live checks

- Wi-Fi opens from Settings, retains focus through repeated navigation, scans
  real networks and returns to Settings. No network was joined or removed.
- Bluetooth queries, discovery and agent registration/shutdown succeed while
  the daemon's agent is present. No peripheral was paired or forgotten.
- Messenger, WalkieTalkie and chatbot launch and return through key-hub
  Escape. Actual RGB565 framebuffers were captured and visually inspected.
- The daemon Volume page accepts forwarded Escape and returns focus.
- An update check and 100 navigation keys leave the launcher healthy.
  Original launcher PID 1184 and NRestarts 0 stayed unchanged throughout
  this smoke run. No production app was updated from upstream.
- Home excludes ConnectWifi, Hello Whisplay and Run Test. ConnectWifi remains
  manageable under Settings → Apps.
- Teardown left Home, session IDLE, daemon connected, both services active.

## Deployment

Deployed after the complete local and Orange Pi suites passed. The staged
package passed its 37-screen self-test before activation; only the MFruit OS
service was restarted. Existing daemon configuration and all older installed
versions were retained.

- Active: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930093556`.
- Previous: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930060547`.
- Backup: `/home/orangepi/.mfruit-deploy-backups/validation-20260930093556/`.
  Contains the original source archive, previous system path and deployment record.

The live smoke was repeated successfully against this installed build: Wi-Fi
scan/return, Bluetooth discovery/agent lifecycle, all three app launch/exit
checks and updater navigation passed. Final state: Home, session IDLE, daemon
connected; both services active. New launcher PID 6435 remained stable with
NRestarts 0; the service journal had no warnings after deployment.

One device reboot occurred around 09:32 UTC during the first final-suite attempt,
clearing `/tmp`. No reboot command was issued by this validation; its cause is
unconfirmed. The launcher recovered automatically. The full suite was rerun
with persistent output and passed all 266 tests in 162.264 seconds before
deployment. This does not establish the physical appearance of the reboot.

## Remaining physical checks

The user chose to perform these afterward: actual USB/Bluetooth input and tty1
isolation; hotplug and held-key handover; real pairing/confirmation/rejection;
button gestures and visible RGB colours; observed reboot/logo; physical-keyboard
updater use. No real keyboard was attached. Virtual keys do not prove EVIOCGRAB.

LoRa/audio exchange remains unverified. No radio message, recording or chatbot
question was sent. The pre-existing `dnsmasq.service` failure is a port-53
conflict with the DNS stub at `127.0.0.53`; Wi-Fi and scans passed and DNS
configuration was left unchanged.

## Evidence

- Local suite: `/tmp/mfruit-validation-final.log`.
- Local preview: `/tmp/mfruit-validation-preview/`.
- Device suite: `~/.mfruit-validation/final-tests.log` on Orange Pi; copied to
  `/tmp/mfruit-device-final-tests.log` on the workstation.
- Post-deployment smoke: `~/.mfruit-validation/live-after-deploy.log` and
  `/tmp/mfruit-live-validation/` on Orange Pi.
- Local live captures: `/tmp/mfruit-live-captures/`.
- Deployment: `/tmp/mfruit-validation-deployment.json` on Orange Pi, also
  saved in the permanent device backup.

Temporary files can disappear on reboot. Documentation screenshots are in
`docs/screenshots/`; private app conversation screenshots stay in `/tmp`.
