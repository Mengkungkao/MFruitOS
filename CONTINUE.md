# CONTINUE — MFruit OS installer validation, 2026-10-01

## Latest checkpoint — Raspberry Pi installed, 2026-10-01

**Installation completed:** After `git pull`, the user ran
`bash scripts/install.sh` on the Raspberry Pi and supplied its successful log.
A read-only SSH check independently confirmed:

- `~/MFruitOS` is clean at commit `cfe8ac2` (installer/provisioning fixes,
  regression tests and validation documentation).
- Active build:
  `/home/jarvis/.whisplay-os/system/versions/1.4.0-local20260930185444`.
- Both `whisplay-os` and `whisplay-daemon` are active/running with
  `NRestarts=0`; launcher PID 6939, daemon PID 873.
- `mfruitctl status` responds successfully: version 1.4.0, Home/IDLE, connected
  with screen focus, nine apps and keyboard devices event0/event4.

The supplied installer log reports a passed self-test rendering 39 screens,
existing configuration kept, offline ConnectWifi provisioning completed with
existing apps/preferences preserved, service integration installed and the
launcher running. Its service start timestamp is `2026-09-30 18:55:23 BST`;
the session date above uses the user's Australia/Sydney timezone.

Installation is complete; do not rerun it merely because the earlier notes
say deployment is pending. The remaining launch-timing investigation and a
complete passing test-suite rerun are still pending. Successful installation
and the rendering self-test do not resolve that outstanding regression test.

Commit message for this handoff-only update:
`docs: record completed Raspberry Pi installation`.

The user supplied a working SSH target:

```powershell
ssh -i "$HOME\.ssh\id_ed25519_github" jarvis@192.168.0.33
```

At validation time, `raspberrypi` ran Linux aarch64, Python 3.13.5 / Pillow 11.1.0,
with a clean `~/MFruitOS` checkout at `2cc3ef5` before the user's later pull.
Before this installation, the verified active build was
`/home/jarvis/.whisplay-os/system/versions/1.4.0-local20260930171222`.
Both services were active with zero restarts (launcher PID 884, daemon 873),
Home/IDLE and eight registered apps. This target is separate from the older
Orange Pi checkpoint below.

Before the user's installation, changes were tested in an isolated copy without
deploying them:
`/home/jarvis/.mfruit-validation/installer-20261001T031928/source`.
All 205 initially transferred source files matched the recorded SHA-256
manifest. Two test files were subsequently refreshed for the follow-up below.
The first full run, including the real-daemon harness using `~/Whisplay`, ran
347 tests in 273 seconds with one failure and one error (`../full-tests.log`).

- **Fixed and passed:** `test_disable_app_persists_and_hides` incorrectly used
  the settings file's existence as its save-completion signal; boot had already
  created that file. It now waits for the queued save to finish.
- **Added and passed:**
  `test_files_only_first_install_and_rerun_preserve_provisioned_apps` runs the
  complete `install.sh --no-service` twice, using real bundled Wi-Fi/SDK files
  and isolated command doubles. It verifies initial starter selection and
  preservation of settings, Wi-Fi version/data, registrations, marker, backup
  and launch policy on rerun. These two tests passed in 21.165 seconds;
  evidence: `../followup-tests.log`.
- **Still unresolved:**
  `test_press_during_launch_window_page_is_closed` did not capture the expected
  INTRUDER event in the full run, although the requested slow app won. One
  targeted rerun passed. Its trace shows the second hold can start while the
  daemon still reports MFruit OS in front: the existing 0.2-second sleep is not
  a reliable handoff barrier. This is an investigation finding, not a completed
  fix. No launch-lifecycle source or test change has been made. Trace:
  `../page-intruder-original-daemon.log`.

Do not claim a full-suite pass yet. Only one real-daemon suite may run at a time.
Local evidence: `C:\Users\mengs\AppData\Local\Temp\mfruit-pi-validation-20261001T031928`.
Full/follow-up logs, the daemon trace and preview log were copied there.
The Pi rendered all 39 preview screens; both contact sheets were visually
inspected. At the end of that validation stage both live services retained their
original PIDs and zero restarts; no live services had been restarted and no test
process was found running. The user's subsequent installation and current
service state are recorded above. Preserve the Pi's installation and app data.

Live downloads of all three catalogue archives passed SHA-256 and entry-target
checks: BTC Dashboard 88,515 bytes; WalkieTalkie 269,487 bytes; Messenger 151,550
bytes. No downloaded code was executed. Evidence:
`C:\Users\mengs\AppData\Local\Temp\mfruitos-catalog-live-rk5i10a2\report.json`.
WalkieTalkie still needs system Codec2/ALSA; Messenger voice features need their
optional ASR/model or speech tools. Verified source pins do not certify hardware.

### Next actions

The pulled checkout and active build have now been checked as recorded above.
Before further changes, compare their source with the isolated validation copy
so tests target the intended revision. A complete runtime checksum comparison
has not been performed after this installation.

1. Reproduce and resolve the remaining daemon-page test using observed daemon
   state to synchronize the handoff. Preserve its assertion that an intruding
   page is closed and the requested app wins; do not mask it with longer sleeps.
2. Run the complete suite again from the isolated source. The four previously
   skipped catalogue tests ran successfully on Linux in the first full run.
3. A real catalogue-install smoke script and the verified archives were copied
   to the evidence directory but **not executed**. If continuing that check,
   `python3 ../catalogue-install-smoke.py ..` creates package-local environments
   under `../catalogue-home`, installs Python dependencies, and runs generated
   package self-tests without launching apps or registering with the live daemon.
4. Before any further deployment, inspect/back up the Pi's current build, registrations,
   settings and app data; compare runtime files and preserve local edits. The
   older Orange Pi deployment instructions are historical, not Pi backup paths.

Commands on the Pi (run the full suite only when no other daemon test is active):

```bash
cd ~/.mfruit-validation/installer-20261001T031928/source
PYTHONDONTWRITEBYTECODE=1 WHISPLAY_SRC=/home/jarvis/Whisplay python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --preview ../preview-final
```

### Earlier commit messages for the validation changes

No commits, pushes or deployments were performed by the assistant. The user
subsequently pulled and installed commit `cfe8ac2`, which includes these changes.
The suggestions below are retained as history; inspect Git before reusing them.
Keep the user's `MFruitOS.code-workspace` separate. Combined message:

```text
fix: preserve app setup state and harden installer validation

Preserve existing apps and preferences during repeat provisioning, validate
catalogue entry targets, and improve installer and daemon startup recovery.
Add provisioning, catalogue, navigation and settings-save regression coverage.

Record Raspberry Pi validation: catalogue pins and 39 previews passed; the
first-install/reinstall and settings-save follow-ups passed. The daemon-page
launch-window test still needs investigation before a full-suite pass.
```

For separate commits, group the corresponding code/tests and split installer
hunks where necessary:

```text
fix: preserve existing apps and preferences during provisioning
fix: validate catalogue entrypoints and generated package scripts
fix: harden installer prerequisites and daemon startup recovery
test: cover installer navigation and synchronize settings saves
docs: record Raspberry Pi validation and remaining launch test
```

## Earlier checkpoint — installer validation on Windows, 2026-10-01

The Windows-only limitations and pending checks below describe the earlier
checkpoint. The Raspberry Pi results and next actions above supersede them.

The previous installer work is committed at `1f9798e`, despite the older
handoff calling it uncommitted. This session continues its validation. The
fixes below are working-tree changes; no commits, pushes or deployments have
been made by this session. Keep the user's untracked `MFruitOS.code-workspace`.

- First-install provisioning now has an explicit `--first-install` mode and a
  completion marker. Repeated setup preserves existing apps, Wi-Fi packages,
  settings, app order, autostart preferences and launch policy. Only available,
  valid starter game definitions enter the initial menu.
- Clean-menu filtering keeps daemon system pages launchable. Forgetting an
  app removes its curated-menu ID as well as its other settings.
- Catalogue preparation checks the actual Python entry target before changing
  the package, reports unknown IDs clearly, uses guarded SDK removal, and
  writes UTF-8/LF launch scripts.
- Installer prerequisite/polkit checks and startup-grace regressions pass in
  isolated tests. The startup grace ends after the launcher lock is seen;
  uninstall removes the MFruit NetworkManager polkit rule. Missing venv support
  fails before files are installed, including in `--no-service` mode.
- Seven standalone installer navigation tests pass, covering confirmation,
  saved-app restoration, failure guards and ConnectWifi routing. Existing
  navigation tests are updated for the Home App installer and ConnectWifi-only
  Wi-Fi flow. Eight synthetic UI frames were rendered in dark/light themes and
  visually inspected; this is not a device or full-launcher preview check.

Validation environment: Windows Python 3.12.14 is available at
`C:\Users\mengs\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.
Use `PYTHONDONTWRITEBYTECODE=1`. WSL is not installed. Full discovery was
attempted, but Linux imports (`fcntl`), POSIX permissions, shell paths and
symlink privileges prevent a meaningful full-suite pass on this host. Keep
Linux-only tests pending; do not remove these checks or stub the platform to
claim a pass. The final focused run completed **66 tests: 62 passed, 4 skipped**
(catalogue POSIX shell/symlink/activation/rollback tests). This covers catalogue
validation, provisioning with mocked package execution, settings, clean-menu
registry behavior, screen services, navigation, startup probes and installer
command doubles. The polkit checks exercise rule generation; they do not test a
live polkit service. Log: `focused-final.log`. Temporary evidence is in
`C:\Users\mengs\AppData\Local\Temp\mfruit-validation-20261001\`.
Python 3.9 grammar checks passed for 127 source/test files; `bash -n` passed
for the changed install/uninstall scripts, and `git diff --check` passed.

SSH to `orangepi@192.168.1.122` timed out with an 8-second connection timeout.
The board's current address/availability is awaiting the user. No live-device
state was changed. Once reachable, run the complete suite including the real
daemon, provisioning/package activation and rollback checks, and preview on
Linux before deploying. Preserve board settings, protected app edits and data;
follow the earlier backup/checksum instructions below. Physical checks remain
with the user. The last deployed build recorded below has not been refreshed
or verified by this session.

Remaining checks include downloading all three pinned catalogue archives and
confirming their SHA-256 hashes against `config/catalog.json`; fixture checksum
tests passed, but live source downloads were not completed. Run the bundled
ConnectWifi install on Linux and confirm first-install/reinstall behavior
through the complete shell installer. Full Linux command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 -m mfruitos --preview /tmp/mfruit-installer-preview
```

Suggested commit message for this validation follow-up:

```text
fix: preserve app setup state and validate installer handoffs

Keep repeat provisioning from resetting apps and preferences, preserve system
page access, validate catalogue entry targets, and end startup grace after
launcher handoff. Add installer, catalogue, menu and provisioning regressions
and document the remaining Linux/device validation.
```

## Previous checkpoint — app installer and first-install setup, 2026-10-01

This work added an app-installation flow, first-install provisioning, and a
daemon startup handoff adjustment. It was subsequently committed at `1f9798e`.
The notes below describe its original handoff, before the validation above.

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
