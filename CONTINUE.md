# CONTINUE — next-session handoff (updated 2026-09-30)

## Current checkpoint

MFruit OS **1.4.0 is deployed and running on the Orange Pi** at
`orangepi@192.168.0.130`. The Settings redesign, Wi-Fi migration, Bluetooth
screens, logo-only boot, keyboard hub, and requested app removals are done.
The remaining work is physical hardware verification, especially keyboard
isolation from tty1 and real Bluetooth pairing.

The previous handoff was stale: commit `f5fe300` already contained Settings,
Wi-Fi, Bluetooth, boot, SDK 1.2.0 and their documentation. This session
reviewed that implementation, fixed Bluetooth lifecycle failures, tested it,
and deployed the coordinated OS/app update. A live smoke test then exposed
a chatbot startup delay, which was fixed and verified. No git commits were created.

## User request being continued

- Move Connect WiFi from Home into Settings and arrange Settings like iPhone Settings.
- Improve Bluetooth connection settings and usability.
- Fix the apparent app crash when using the updater.
- Show only a logo on a dark background during startup.
- Remove Run Test (`whisplay-run-test`) and Hello Whisplay (`hello-whisplay`).
- Continue work, update this handoff before finishing, and provide commit messages.

## Completed this session

### Bluetooth fixes (uncommitted locally, deployed)

- Reuse an agent startup already in progress rather than starting another
  D-Bus agent thread after a slow startup times out.
- Refuse agent startup after close; wake waiting callers when opening the
  agent bus fails; release the agent loop when BlueZ releases the agent.
- Report failed bluetoothctl discovery instead of claiming search completed.
- Preserve successful pair/connect/disconnect/forget operations when a
  subsequent status lookup fails.
- Ignore pairing prompts queued by an earlier operation and prevent a late
  Forget completion from popping an unrelated screen.
- Added backend and UI lifecycle regressions in `tests/test_bluetooth.py`
  and the new `tests/test_bluetooth_screens.py`.

### SDK and documentation

- ConnectWifi's functional SDK already matched; updated its version marker
  and `VENDORED` from 1.1.0 to **1.2.0**, and added its canonical
  `.claude/rules/mfruit-os-app.md` copy.
- Messenger, WalkieTalkie and the dashboard already had matching SDK/rules.
- The local chatbot checkout initially lacked the migration, then changed
  externally to clean commit `68273da` while this session was running. Its
  SDK 1.2.0 and keyboard migration were checked and tested before deployment.
  This agent did not change the chatbot checkout or its git history.
- Updated CHANGELOG and `docs/HARDWARE_TESTS.md`, including current menu names
  and the verified-versus-unverified hardware checkpoint.

### Chatbot startup fix (uncommitted locally, deployed)

- Live launch initially timed out before the Python UI claimed the screen.
  The launcher recorded `outcome=headless` after its 9.5-second pending window
  and terminated the app; Node had started normally with no Python traceback.
- An import-only probe caught `python/utils.py` loading optional OpenCV for
  camera resizing before the display could start. Deferred that import until
  `convertCameraFrameToRGB565` needs it, caching either the module or its absence.
  Existing OpenCV and Pillow fallback conversion behavior is preserved.
- Added three tests in `python/test/test_image_utils.py`: a fresh interpreter
  forbids OpenCV during display utility imports, plus conversion/cache tests
  for both OpenCV and Pillow paths.
- Board UI import time dropped from **4.345 s to 2.078 s**. A subsequent live
  chatbot launch succeeded and Escape returned through the key hub to Home.
  The original utility file is backed up in `chatbot-startup/utils.py` beneath
  the deployment backup listed below. No timeout was extended.

## Deployment details

- Host/user confirmed: **orangepi@192.168.0.130**.
- Active OS installation:
  `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930043441`.
- Prior OS installation:
  `/home/orangepi/.whisplay-os/system/versions/1.3.0-local20260929235902`.
- Backups of replaced source files, compiled chatbot files, removed apps,
  original registrations and settings:
  `/home/orangepi/.mfruit-deploy-backups/20260930-043440/`.
- Source checkouts updated: `~/MFruitOS`, `~/ConnectWifi`, `~/Messenger`,
  `~/WalkieTalkie`, `~/ai-chatbot` (excluding its Whisplay checkout).
- Reviewed rsync checksum dry runs before deployment. Preserved each app's
  device configuration, venv/models, chatbot `.env`, data, dependencies and
  plugins. Old WalkieTalkie `app/input/` and Messenger button/keys bytecode
  leftovers were moved into the backup.
- Compiled chatbot in staging with the existing Node 20.20.2 and node_modules;
  only `core/chat-flow/states.js` and `device/display.js` differed in dist.
  Deployed the compiled result without rerunning the build's registration
  hook, so the existing launch-gate registration stayed intact.
- Ran MFruitOS `scripts/install.sh --yes --no-service`; its self-test passed.
  Restarted whisplay-daemon and whisplay-os using existing narrow sudoers rules.
  The daemon background drop-in was already installed; no systemd unit edits
  or new sudo configuration were necessary.
- Uninstalled Hello Whisplay using `Installer.uninstall`, after backing up
  its entire app directory (including data). Removed both apps' persisted
  daemon registrations with `persist: false`, removed their OS metadata,
  and moved Run Test's adopted registration into the backup.
- Both entries remained absent after the daemon restart. The daemon only
  loads the user's persisted registrations at startup. Its install script
  can seed Run Test again if Whisplay itself is reinstalled; do not edit
  Whisplay source to prevent that.
- Dashboard was not installed or deployed. The Raspberry Pi was not changed.

## Verification completed

| Check | Result |
|---|---|
| MFruitOS Linux unittest suite, including real-daemon harness | 260 passed in 161.787 s |
| MFruitOS self-test / preview | 37 screens rendered |
| ConnectWifi pytest | 129 passed, 1 skipped |
| Messenger pytest | 141 passed |
| WalkieTalkie pytest | 578 passed |
| Chatbot keyboard and camera/startup pytest | 12 passed |
| Chatbot TypeScript compilation | Passed |
| Bluetooth files Python 3.9 grammar | Passed |
| Git diff whitespace checks | Passed |

- Both systemd services active; OS status reports **1.4.0**, connected daemon,
  seven installed apps, and no attached keyboards.
- Live control-socket keys opened Settings and Wi-Fi, launched Connect WiFi,
  and exited it through the actual key hub back to **Settings → Wi-Fi**.
- Messenger, WalkieTalkie and chatbot each launched on the real board and
  exited through key-hub Escape. Chatbot passed after the startup fix above.
- Home entries verified: Messenger, WalkieTalkie, AI Chatbot, Settings, Updater.
  Connect WiFi remains in Settings → Apps; Run Test and Hello Whisplay are gone.
- Bluetooth UI opened and completed discovery. D-Bus queries, discovery,
  temporary pairing-agent registration, and agent shutdown succeeded as
  `orangepi` while whisplay-daemon was running. No devices were paired or removed.
- Inspected live Home/Settings/Wi-Fi/Bluetooth screenshots and offscreen
  boot/passkey previews. Boot has only the centred logo on the dark background.
- Final runtime state: HomeScreen, session IDLE, daemon connected, OS 1.4.0.
- Test staging/logs/previews on the board: `/tmp/mfruit-session-20260930/`
  (temporary; removed by reboot). Full suite log: `tests.log`; app logs:
  `ConnectWifi-tests.log`, `Messenger-tests.log`, `WalkieTalkie-tests.log`.
  Preview PNGs: `previews/`; live PNGs: `device-screens/`.

## What remains

1. **Physical USB and Bluetooth keyboard tests** in `docs/HARDWARE_TESTS.md`:
   keys reach the foreground app, no keys reach tty1, held-key handover,
   hotplug/reconnection, and Daemon desktop releases/reacquires the grab.
   Virtual keys verify routing, not EVIOCGRAB on physical hardware.
2. **Actual Bluetooth pairing**: passkey entry, numeric confirmation,
   rejection/cancellation, reconnect/disconnect and forgetting, including
   coexistence with the daemon's agent during a real pairing transaction.
3. Physical button checks and an observed reboot/boot-logo check. The prior
   physical checklist steps 9–18 remain unverified unless the user reports
   running them. Audio/radio transmissions were not tested this session.
4. A real updater operation while using the physical keyboard. The original
   crash was keys leaking to tty1's autologin shell, where Up + Enter ran an
   old `systemctl restart whisplay-os.service` history line. The exclusive
   EVIOCGRAB/key-hub fix is now deployed, with matching SDKs in the apps.
5. User-assisted hardening if desired: turn off tty1 autologin and remove
   those restart lines from the board's bash history. This touches their
   shell/service configuration; ask before doing it. Neither was changed.
6. Raspberry Pi rollout remains unperformed; check reachability and device
   differences first. Dashboard installation still requires user intent.

Deferred: M2+ hardware abstraction/headless work, tracked .pyc cleanup,
Messenger board timezone setup. Do not expand into these before completing
or recording the physical verification above.

## Repository status and commit messages (checked 2026-09-30)

Only MFruitOS, ConnectWifi and ai-chatbot have uncommitted work. The other
three app repositories are clean; their latest relevant work is already
committed. Suggested subjects below are for the pending changes unless marked
already committed.

- **MFruitOS — pending**, split by concern:
  - Bluetooth source/tests and CHANGELOG:
    `fix: harden Bluetooth pairing and device operation recovery`
  - This handoff and `docs/HARDWARE_TESTS.md`:
    `docs: record 1.4.0 deployment and remaining hardware checks`
- **ConnectWifi — pending**, SDK version markers and new app rules:
  `chore: sync MFruit App SDK 1.2.0 and app rules`
- **ai-chatbot — pending**, deferred OpenCV import and regression tests:
  `fix: defer OpenCV import until camera conversion`
- **Messenger — clean; already committed**:
  `feat: align Messenger with MFruit OS app input and lifecycle rules`
- **whisplay-crypto-dashboard — clean; already committed**:
  `feat: align crypto dashboard with MFruit OS app behavior`
- **WalkieTalkie — clean; already committed**:
  `feat: align WalkieTalkie with MFruit OS app controls and lifecycle`

The earlier Settings, boot and keyboard-hub work is already committed; do not
recreate it. No commits were created for this deployment session.

## Working environment and commands

The current workstation is Windows PowerShell; WSL is not installed and local
Python lacks Pillow. Tests ran on Linux in the isolated Orange Pi staging
copy. Source files use CRLF locally, so normalize text to LF in deployment
archives; keep executable modes from git. Do not send Windows shell scripts
with CRLF directly to bash. Avoid shipping local scratch/dependency folders.

```bash
ssh orangepi@192.168.0.130
~/.whisplay-os/bin/mfruitctl status
~/.whisplay-os/bin/mfruitctl apps
~/.whisplay-os/bin/mfruitctl key down
~/.whisplay-os/bin/mfruitctl key enter
~/.whisplay-os/bin/mfruitctl key escape
cd ~/MFruitOS && python3 -m unittest discover -s tests
python3 -m mfruitos --preview /tmp/mfruit-previews
```

Never run two real-daemon suites concurrently. Coordinate live navigation
checks with the user so automated input does not race their button presses.
