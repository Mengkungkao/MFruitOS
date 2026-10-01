# Git integration — 2026-09-30

The six repositories now combine the validated device/source work with all 13
incoming origin/main commits using normal two-parent merges. Neither history
was rewritten. The source review compared every incoming changed file with the
combined tree; identical files and reviewed differences are recorded in
`/home/meng/mfruit-integration-backups/20260930T103112Z/upstream-audit.json`.

## Preserved upstream changes

### MFruitOS

Incoming origin/main: `69423af`.

- `69423af` fix: open Wi-Fi directly from Settings and add button LED feedbac
- `17714ee` fix: harden Bluetooth pairing and device operation recovery
- `57d6d17` update continue for next tasks
- `f5fe300` feat: align MFruit OS app lifecycle and input contracts

### ConnectWifi

Incoming origin/main: `82abbed`.
Merge commit: `0f1edf6`.

- `82abbed` feat: unify Wi-Fi settings UI and require explicit Back selection
- `33a0d7e` chore: sync MFruit App SDK 1.2.0 and app rules

### WalkieTalkie

Incoming origin/main: `58af425`.
Merge commit: `a99c4bd`.

- `58af425` fix: make Status explicit and add hold-to-select Back navigation
- `b25e098` feat: align WalkieTalkie with MFruit OS app controls and lifecycle

### Messenger

Incoming origin/main: `43e06e7`.
Merge commit: `6d46d15`.

- `43e06e7` feat: describe Messenger as Radio Message in MFruit OS
- `527d775` feat: align Messenger with MFruit OS app input and lifecycle rules

### ai-chatbot

Incoming origin/main: `4620648`.
Merge commit: `7df8249`.

- `4620648` fix: defer OpenCV import until camera conversion
- `68273da` feat: align ai-chatbot with MFruit OS app input and lifecycle model

### whisplay-crypto-dashboard

Incoming origin/main: `42e4e2c`.
Merge commit: `d67a661`.

- `42e4e2c` feat: align crypto dashboard with MFruit OS app behavior

## Resolution decisions

- MFruit OS keeps upstream direct Settings → Wi-Fi launch, button LED feedback,
  Bluetooth recovery, lifecycle contracts and SDK changes. The additional
  pending-pair cancellation/shutdown guards and their regression tests remain.
- ConnectWifi keeps upstream Wi-Fi screens, network flows, LED feedback and
  explicit Back rows. Its old bespoke button timing is superseded by the
  validated shared InputController: tap next, double previous, 700 ms hold/release
  select and four clicks/Esc back. Focus gating and managed registration remain.
- WalkieTalkie retains upstream explicit Status and hold-to-select Back navigation,
  with the additional dark-screen wake-without-recording guard.
- Messenger retains the upstream Radio Message manifest and SDK. Chatbot retains
  upstream lazy OpenCV import and its regression test unchanged.
- Updated app rules and installation/validation documentation are kept. Incoming
  keyboard compatibility sections were incorporated into chatbot/dashboard READMEs.
- Removed an automatically duplicated, stale architecture paragraph that claimed
  Wi-Fi returns to a Wi-Fi page; the current behavior returns to Settings.

The merged runtime files are byte-for-byte identical to the validated local
checkpoint in every repository. The reconciliation adds documentation and Git
ancestry; the deployed runtime already contains the combined implementation.

## Post-resolution verification

All 1,304 local Python tests passed: MFruit OS 284, ConnectWifi 137, WalkieTalkie
637, Messenger 147, dashboard 86 and chatbot 13. MFruit OS rendered 37 screens.
SDK synchronization, native template package preflight, whitespace and unresolved
conflict checks passed.

Orange Pi SSH health checks show Home/IDLE, keyboard event3, both services active,
launcher PID 24012 and zero restarts. The isolated chatbot Node build and
interrupted-reply regression passed there. No production restart or redeployment
was needed for these documentation/history changes. The prior full device test
run and deployment are recorded in [the validation report](VALIDATION_2026-09-30.md).

Post-merge logs: `/tmp/mfruit-merge-*-tests.log` and
`/tmp/mfruit-merge-device-check.log`. Physical button, keyboard, Bluetooth pairing,
LED, audio and RF checks remain for the user. These automated results do not
certify native production packaging for all adopted apps.

## Recovery and publishing

Pre-merge Git bundles, binary working patches, untracked-file archives and
original/checkpoint commit IDs are saved under:

`/home/meng/mfruit-integration-backups/20260930T103112Z`

Every merge preserves both the validated checkpoint and fetched origin/main as
ancestors. Final merge hashes and ancestry/clean-tree results are recorded in
`merge-results.json` and `final-verification.json` in that backup directory.
This integration session issued no push commands. During final verification,
WalkieTalkie, Messenger, chatbot and dashboard origin/main tracking refs advanced
to their new merge commits with `update by push` reflog entries from concurrent
activity. MFruitOS and ConnectWifi were still two commits ahead at the merge
checkpoint. A subsequent MFruitOS documentation commit records this observation.
