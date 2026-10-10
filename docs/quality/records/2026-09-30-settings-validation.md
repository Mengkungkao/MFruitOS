# Settings and package validation — 2026-09-30

Deployed build: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930105821`.
Previous build: `/home/orangepi/.whisplay-os/system/versions/1.4.0-local20260930101701`.
Recovery archive and installer log: `/home/orangepi/.mfruit-deploy-backups/settings-updater-20260930T105808Z`.

## Changes

- Standard list rows are 46 pixels high, with and without subtitles. Empty group
  spacers are removed from Settings, General and the Wi-Fi fallback screen.
- Settings → Apps now opens app installation directly. The shared local-package
  screen uses the existing `~/.whisplay-os/inbox`, with explicit confirmation.
- Offline checks retain access to app management. Empty release lists explain
  the missing tags/releases and offer Retry; failed checks no longer claim that
  everything is up to date.
- Git tracking recognizes nested folders and worktrees. No-op and failed updates
  retain the previous successful rollback commit.
- Failed package activation restores both the current symlink and install record.
  Failed manual rollback restores the version and metadata it started with.
- Running apps cannot be updated or rolled back through these actions. Successful
  installs/updates refresh cached versions before refreshing the registry.
- Local OS installation records its previous build. The System update screen
  exposes saved-build rollback, which arms the boot guard before restarting.

## Results

All **296 mFruit OS tests passed locally and on Orange Pi**, including the real
hardware-daemon integration harness. The self-test rendered **39 screens**.
Seven targeted negative controls failed against the original implementation.
Python static checks, Python 3.9 compatibility and shell syntax passed. ShellCheck
reports the install script's pre-existing unused ASSUME_YES warning and its
existing command-chain/listing suggestions; the new metadata block adds none.

On the live launcher, a temporary native app was installed through Settings:

1. Install 1.0.0.
2. Update to 1.1.0.
3. Downgrade to 1.0.0.
4. Attempt 2.0.0 with a deliberately failing test and a hook that changes data:
   activation is rejected, 1.0.0 stays active and the original data is restored.
5. Select saved-version rollback in the app's Updates screen: 1.1.0 is restored.
6. Uninstall the temporary app through its normal menu and remove its inbox fixtures.

The first live harness attempt assumed Home on a completed progress dialog went
straight to Home; it closes the dialog first. The harness was corrected to follow
that existing behavior, then the remaining sequence passed. Evidence retains both
attempts. The temporary app's cached daemon registration was cleared by a controlled
daemon/launcher restart. The original seven apps remain, both services are active,
keyboard event3 is attached, launcher PID 38867 has zero automatic restarts, and
no temporary package remains. A hash check confirms all 118 runtime/asset/script/
template files match the local source in both the device checkout and active build.
System rollback/boot-guard behavior was tested in isolated installs; the live system
screen and saved previous-build record were checked without downgrading production.

## Distribution conditions still requiring release or checkout work

A fresh live GitHub/Git check completed. mFruit OS has no semantic releases/tags;
ConnectWifi and Messenger have no Git checkout metadata; chatbot and WalkieTalkie
have local modifications and are correctly protected from automatic updates.
The chatbot's nested checkout is now detected. The three Whisplay example apps'
shared repository is detected and is up to date. Native package workflows are
verified; this does not make copied companion folders into native release packages.
No release/tag was published and no local app edits were discarded.

## Evidence and next steps

Device logs: `~/.mfruit-validation/settings-update-final-tests.log` and
`~/.mfruit-validation/settings-live.log`. Screenshots:
`~/.mfruit-validation/settings-live/`. Local evidence is copied under
`/home/meng/mfruit-validation/settings-updater-20260930/`.

Follow [the install/update/downgrade guide](../../apps/UPDATE_ROLLBACK.md). Physical button and keyboard
use, LED colours, pairing, real audio and RF still require manual checks. Changes
in this follow-up are not committed or pushed by this session.
