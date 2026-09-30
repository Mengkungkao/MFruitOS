# CONTINUE — MFruit OS validation and app integration, 2026-09-30

## Current uncommitted work — app installer and first-install setup, 2026-10-01

The working tree now contains a new app-installation flow, first-install
provisioning, and a daemon startup handoff adjustment. No commits or pushes have
been made for these changes.

- Home now opens **App installer**; its curated catalogue installs
  checksum-pinned app snapshots, prepares package-local venv scripts and the
  current SDK, and leaves more-source discovery, local packages and updates
  available. Apps already on disk can be restored to the Apps menu without
  deleting their files or data.
- Installation provisions the bundled ConnectWifi package, a clean initial
  Apps menu and the two starter games where their daemon definitions exist.
  Settings tracks the curated app IDs so unrelated daemon apps remain disabled
  or out of the menu until explicitly added. Wi-Fi selection now uses
  ConnectWifi rather than the daemon's Wi-Fi page.
- The installer checks NetworkManager and Python venv support and grants the
  target user the listed NetworkManager actions through a polkit rule. The
  daemon wrapper treats MFruit OS as active for up to 30 seconds at startup to
  avoid briefly exposing the daemon UI before the launcher acquires its lock.
- Pending files: `config/catalog.json`, `config/default.json`,
  `bundled/connectwifi/`, `mfruitos/provision.py`,
  `mfruitos/updater/catalog.py`, and changes in the registry, launcher screens
  and services, settings, updater, installer script and daemon wrapper.
- At handoff, `git diff --check` passes. Focused tests for catalogue
  verification, first-install provisioning, clean-menu behavior, polkit setup
  and daemon startup grace have not been run or added yet. Run the relevant
  suite and full tests before deploying; inspect the installer changes because
  they add system packages and a persistent polkit rule.

Suggested commit messages for this pending work:

- `feat: add checksum-pinned app installer catalogue`
- `feat: provision ConnectWifi and a curated first-run app menu`
- `fix: keep daemon UI hidden during launcher startup`
- `docs: record app installer work and remaining validation`

## Current Settings and updater checkpoint

The Settings spacing and package-management follow-up is deployed at
`/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930105821`.
Backup: `/home/orangepi/.mfruit-deploy-backups/settings-updater-20260930T105808Z`. All **296 MFruit OS tests passed locally and on
Orange Pi**; 39 screens rendered. Live native-app install → update → downgrade →
failed-update recovery → rollback → uninstall passed, preserving the fixture's data.
The temporary app was removed and both services are healthy with the original
seven apps. All 118 deployed runtime/asset/script/template files match this source.

Settings now uses uniform rows. Install apps through **Settings → Apps → Install
app**, including local packages in `~/.whisplay-os/inbox/`. System update offers
rollback to the previous saved local build. Git updates recognize nested checkouts
and preserve rollback history; failed activation restores install metadata too.

Remote distribution remains a separate condition: MFruit OS has no published
releases/tags, ConnectWifi/Messenger are copied folders without Git metadata, and
chatbot/WalkieTalkie contain protected local edits. Do not overwrite these edits or
claim every companion is a native release package. No commits or pushes were made
for this follow-up. See [the update guide](docs/UPDATES.md) and
[validation evidence](docs/VALIDATION_SETTINGS_2026-09-30.md).

## Earlier validation and Git integration checkpoint

User request: continue this handoff, validate everything, and test on
`orangepi@192.168.1.122`. The user chose automated checks now and will do
physical hardware checks afterward.

Latest validated build: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930101701`.
Backup: `/home/orangepi/.mfruit-deploy-backups/cleanup-20260930101701/` (MFruit source, 29 companion files,
previous version and deployment metadata). Previous build:
`/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930093556`.

Git integration follow-up: all 13 incoming origin/main commits across six repos
are preserved in normal merge commits alongside the validated fixes. All 1,304
local Python tests and the Orange Pi chatbot build/regression passed again;
SSH health checks remain healthy. Runtime files match the deployed validated
checkpoint, so no redeployment was needed. This integration session issued no
push commands. Concurrent push activity updated the WalkieTalkie, Messenger,
chatbot and dashboard tracking refs to their merge commits; MFruitOS and
ConnectWifi remain two commits ahead of the fetched origin/main at this checkpoint.
See [the integration record](docs/INTEGRATION_2026-09-30.md) for upstream commit
inventory, resolution decisions, app merge hashes and recovery backups.

Follow-up user requests: validate and remove unnecessary files; align software
and UI with MFruit OS; create app creation/development/production rules; supply
a manual install, test and debug workflow for other devices.

- Read [docs/DEVICE_SETUP.md](docs/DEVICE_SETUP.md) for manual setup. Run
  `bash scripts/setup-device.sh --check` first, then `--install` explicitly.
  Whisplay drivers and its daemon must already work on the target board.
- [docs/APP_RULES.md](docs/APP_RULES.md) is the canonical app rule list, synced
  to the template and all five companion projects. Native package preflight:
  `python3 scripts/check-app.py <clean-package-directory>`.
- Latest automated results: **1,304 Python tests passed locally and on the
  Orange Pi**: MFruit OS 284, ConnectWifi 137, WalkieTalkie 637, Messenger 147,
  dashboard 86, chatbot 13. Chatbot Node build/interrupted-reply regression
  also passes; disabling its generation guard makes the check fail with exit 1.
- Cleanup removed 59 remaining cache directories (350 files, 4,990,269 bytes),
  including the removal of all 95 tracked bytecode files; SDK refresh had
  already removed two additional cache directories. New chatbot ignore rules
  prevent recurrence. Configuration, models, dependencies and user data kept.
- ConnectWifi now uses the shared InputController: tap next, double previous,
  700 ms hold/release selects, four clicks/Esc back; explicit Back rows remain.
  Removed both the old evdev reader and its redundant SDK key adapter.
- Managed launches preserve mfruit-run registration in ConnectWifi and the
  radio/dashboard apps. Dark radio-screen holds wake without recording.
  Messenger accepts `/` without killing terminal input. Chatbot starts from
  any working directory; npm test now compiles and returns failures correctly.
- Removed unused imports/assignments, dashboard's unused NumPy installation
  and redundant npm crypto dependency; standardized ordinary UI wording.
- MFruit test fixtures now close files, pipes and framebuffers explicitly.
- A Logi K250 keyboard is now attached as event3. Launcher input ownership and
  an EBUSY result for a second EVIOCGRAB were confirmed over SSH. Physical
  typing, hotplug, pairing, button, LED, audio and RF checks remain manual.
- Existing companions run as adopted apps. Native production package gaps
  are documented in APP_DEVELOPMENT.md; do not claim all release packages
  are production-certified. Chatbot retains its documented daemon-owned 4× exit.

Post-deployment live checks passed: Wi-Fi launch/scan/return/repeated keys,
Bluetooth discovery and agent shutdown, all three adopted app launch/exits,
and updater check plus 100 navigation keys. Home/IDLE afterward; both services
active, launcher PID 24012, NRestarts 0. All four companion registrations retain
mfruit-run. Installed device and template preflights passed; no new launcher
journal warnings. Live evidence: `~/.mfruit-validation/live-cleanup-check.log`.

See [the validation record](docs/VALIDATION_2026-09-30.md) for the latest live
checks, deployment details and evidence. The historical recovery below explains
why this working tree contains substantial changes relative to its Git base.

The local checkout was behind the board: local MFruit OS was 1.3.0 at
`a874398`, while the board already had 1.4.0 and later Wi-Fi, navigation and
branding changes. Recovered and reviewed the board source instead of deploying
the stale local checkout. During that initial recovery, no staging, commits,
pushes or tags were performed; the later local merges are described above.

Original board source: `/tmp/mfruit-board-snapshot`. Companion snapshots:
`/tmp/mfruit-app-validation/`; recovered-file inventory:
`/tmp/mfruit-companion-recovered.json`. Device configuration, secrets, models,
user data and radio addresses were preserved.

## Recovered implementation

- MFruit OS 1.4.0: grouped Settings, native Bluetooth discovery/device/pairing
  screens, General settings, logo-only dark boot and MFruit branding.
- Settings → Wi-Fi opens ConnectWifi directly without a loading screen and
  returns to Settings. ConnectWifi stays out of Home but remains manageable
  under Settings → Apps. Run Test and Hello Whisplay are already removed.
- SDK 1.2.0: exclusive keyboard capture and foreground key hub, including
  forwarding to internal daemon pages. SDK and app rules are synchronized
  across ConnectWifi, WalkieTalkie, Messenger, chatbot and dashboard.
- ConnectWifi 1.1.0: MFruit styling, status/IP, network/password/hidden-network
  flows, explicit Back selection, faster first frame and useful LED feedback.
- WalkieTalkie: explicit Status menu and Back choices; partial four-click exit
  no longer opens Status, held Back does not record, leaving Pair ends pairing.
- Messenger: manifest and README description **Radio Message**.
- Chatbot: deferred optional OpenCV import and startup regression coverage.

## Fixes made during validation

1. Recovered shell helpers contained CRLF endings: nine launch-gate tests failed
   on both Linux hosts. Normalize source to LF, preserve executable bits and
   add `.gitattributes` to keep scripts runnable across Windows checkouts.
2. Bluetooth shutdown closed its query bus before cancellation and could leave
   pairing waiting 62 seconds. Cancellation now uses the captured agent
   connection/path, wakes the worker immediately and prevents queued Pair calls
   after shutdown. Two regression tests were demonstrated failing before the fix.
3. Refresh boot and Settings documentation screenshots.

## Original validation checkpoint (superseded by results above)

See [the full validation record](docs/VALIDATION_2026-09-30.md) for results,
deployment/backup paths and limitations.

- MFruit OS final suite: **266 passed locally and on Orange Pi**, including
  the real daemon.
- Companion checks: **1,004 passed** — ConnectWifi 137, WalkieTalkie 632,
  Messenger 141, dashboard 82, chatbot 12. The initially skipped ShellCheck
  check was rerun successfully using a binary under `/tmp`.
- Chatbot TypeScript `tsc --noEmit` passed on the Orange Pi.
- 37 screens rendered on both hosts. Preview and live framebuffers inspected.
- Runtime pyflakes, Python 3.9 compatibility, shell syntax, SDK equality and
  Git whitespace checks passed. Fixture ResourceWarnings were addressed in the follow-up.
- Isolated Orange Pi installer/update/rollback tests passed.
- Live checks: Wi-Fi launch/scan/return and repeated keys; Bluetooth discovery
  and agent registration/shutdown; Messenger, WalkieTalkie and chatbot
  launch/exit; daemon Volume keyboard return; updater check with 100 keys.
  The launcher stayed alive without an unexpected service restart.
- Existing production apps were not updated from upstream. Unreleased changes
  on the board are preserved.

Evidence: local `/tmp/mfruit-validation-final.log`,
`/tmp/mfruit-validation-preview/`, `/tmp/mfruit-live-captures/`;
board `~/.mfruit-validation/final-tests.log`,
`~/.mfruit-validation/live-after-deploy.log`, `/tmp/mfruit-live-validation/`,
`/tmp/mfruit-validation-deployment.json`.
Temporary files may disappear on reboot.

A device reboot during the first final-suite attempt cleared `/tmp`; this
validation issued no reboot command and the cause is unconfirmed. The launcher
recovered; the full suite was rerun with persistent output and passed before
deployment. See the validation record for details.

## Physical checks the user will do next

Follow `docs/HARDWARE_TESTS.md`; do not infer these from virtual keys:

1. USB/Bluetooth keyboard routing, hotplug, held-key handover, no tty1 leakage,
   grab release/reacquisition in Daemon desktop. A real keyboard is now attached; physical routing still needs observation.
2. Actual Bluetooth passkey/numeric comparison, rejection/cancellation,
   reconnect/disconnect and forget. No peripheral was paired or forgotten.
3. Physical button feel, RGB colours, and an observed reboot/logo.
4. Updater use with a physical keyboard. Automated install/rollback and live
   update checking passed; production app updates were not applied.
5. Real LoRa/audio exchange remains unverified. The prior handoff noted
   WalkieTalkie `/dev/gpiomem` diagnostics; this session was not a radio repair
   task and sent no message, voice recording or chatbot question.

Existing board issue: `dnsmasq.service` fails because port 53 is occupied
by the DNS stub at `127.0.0.53`. Wi-Fi networking and scans work; no DNS
configuration was changed.

Do not change tty1 autologin or shell history as part of these fixes. Raspberry
Pi rollout and dashboard installation on Orange Pi need new user intent.
Headless/hardware abstraction and Messenger timezone changes remain deferred.
Tracked bytecode cleanup is complete in the local checkouts.

## Useful commands

```bash
cd ~/MFruitOS
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 -m mfruitos --preview /tmp/mfruit-preview
ssh orangepi@192.168.1.122 '~/.whisplay-os/bin/mfruitctl status'
ssh orangepi@192.168.1.122 '~/.whisplay-os/bin/mfruitctl key down'
ssh orangepi@192.168.1.122 'cd ~/ai-chatbot/whisplay-ai-chatbot && ~/.nvm/versions/node/v20.20.2/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false'
```

Noninteractive SSH does not put Node on PATH. Do not run two real-daemon suites
concurrently on the same machine. `mfruitctl screenshot` renders the launcher
router, not an external app: decode its existing
`/tmp/whisplay-fb-<id>-*.bin` with `from_rgb565(raw, 240, 280)`.
Do not acquire a new framebuffer for screenshots. Keep private conversation
screenshots in temporary storage. Before deploying, compare checksums and
preserve board configuration/data.

## Suggested commit messages

The local histories differ from the old Windows handoff. Inspect `git diff`
and `git log` here when staging; no commits were created for you.

- MFruitOS feature recovery:
  `feat: add grouped Settings, Bluetooth pairing and integrated Wi-Fi`
- MFruitOS validation fixes:
  `fix: cancel pairing on shutdown and preserve Linux script line endings`
- MFruitOS documentation:
  `docs: record Orange Pi validation and remaining physical checks`
- ConnectWifi:
  `feat: unify Wi-Fi settings and require explicit Back selection`
- WalkieTalkie:
  `fix: make Status explicit and add safe Back navigation`
- Messenger:
  `feat: show Radio Message metadata and sync MFruit SDK 1.2.0`
- Chatbot:
  `fix: defer OpenCV loading and sync MFruit SDK 1.2.0`
- Dashboard:
  `chore: sync MFruit SDK 1.2.0 and app rules`
