# CONTINUE — current hand-off

Read this first, then [known issues](docs/quality/KNOWN_ISSUES.md). The rules
are in [docs/platform/DEVELOPMENT_RULES.md](docs/platform/DEVELOPMENT_RULES.md).
History: [docs/quality/records/](docs/quality/records/README.md) (the previous
hand-off is preserved verbatim in
[2026-10-01-handoff.md](docs/quality/records/2026-10-01-handoff.md)).

## Session 2026-10-02/03 — constitution, docs architecture, CI, fixes, Pi install

The user supplied the project constitution, target architecture and
documentation tree, then asked to continue for two hours and to install and
test on the Raspberry Pi. The user committed and pushed the first half
(`15fec1c`, `f15afe5`); everything below that is still uncommitted.

| # | Checkpoint | Status |
|---|---|---|
| 0 | Baseline full suite (dev machine) | AUTOMATED: 348/348, 0 skipped |
| 1 | Launch-window test root cause and fix | DONE: daemon hold→tap race (not MFruit OS); 20/20 dev + 10/10 Pi iterations; negative control fails |
| 2 | Docs restructure into `docs/platform`, `docs/apps`, `docs/quality`; constitution; ADRs; agent entry files | DONE (link check passes) |
| 3 | `scripts/check.sh`, `scripts/check-docs.py`, `.github/workflows/ci.yml` | DONE locally (check.sh green with pinned Whisplay `1066486`); CI NOT VERIFIED until pushed (Python 3.9 job never run: no 3.9 here) |
| 4 | KI-1 sideloaded-folder safety (`verifier.copy_package_dir`) + 6 regression tests (4 installer, 2 verifier) | DONE; all 4 installer tests failed before the fix |
| 5 | KI-6 test keyboard isolation; KI-5 dead settings removed; ADR 0006 proposed for KI-2 | DONE (KI-2 awaits the user's decision) |
| 6 | Pi: backup, full suite, install, live check — final tree | DONE: 357/357 on the Pi; active `1.4.0-local20261002153118`; live launch/exit OK |

| 7 | User report: games ignore the keyboard; installer shows broken apps as installed | DONE: keyboard bridge + Repair; Pi active `1.4.0-local20261002160133`, games verified with `mfruitctl key` ([record](docs/quality/records/2026-10-03-keyboard-bridge-and-repair.md)) |

| 8 | Repair the broken catalogue apps on the Pi | DONE: `mfruitctl catalog` added; dashboard, Messenger, WalkieTalkie installed and launch/exit OK. Incident: a launcher restart killed a running install (KI-9) — **always check `mfruitctl jobs` before restarting** |

Evidence: [2026-10-02 record](docs/quality/records/2026-10-02-baseline-and-launch-window.md).
Pi backup: `~/mfruit-backups/20261002-145215-before-docs-restructure/`; the
previous build `1.4.0-local20260930185444` stays in `system/versions/`.

## Radio work (resumed 2026-10-03) — radio capability + Messenger pairing/SOS (started 2026-10-03)

User decisions: one-time SSH `scripts/setup-radio.sh` (no passwordless root);
band **AU915**; Messenger scope **pairing + SOS** first; **pair once for both**
apps (shared identity/contacts).

| Step | Work | Status |
|---|---|---|
| R1 | `mfruitos/hosts/lora/` — SX126X provisioning (ported from WalkieTalkie), M0/M1 board lines, readiness check | DONE (8 tests) |
| R2 | `mfruitos/sdk/radio/` (SDK 1.3.0) — shared store `~/.whisplay-os/shared/radio/`: `radio.json` (setup), `device.json` (Device ID/name), `keys.json` (WalkieTalkie format), `contacts.json`; crypto moved from WalkieTalkie | DONE (SDK 1.3.0; 11 tests) |
| R3 | `scripts/setup-radio.sh` — packages (libcodec2, serial, cryptography), UART, serial console, getty, dialout, reboot, provision AU915 | DONE (bash -n; not yet run on a device) |
| R4 | catalogue `requires: ["radio"]`; App installer / `mfruitctl catalog` readiness | DONE (installer + CLI; tests) |
| R5 | docs: ADR 0007, Host API, SDK, Installation, Configuration, Security | DONE (ADR 0007 + docs) |
| M1 | Messenger: shared identity, pairing (4-digit code), encrypted text | DONE in Messenger repo (uncommitted): shared identity, pairing, encrypted text; 185 tests pass |
| M2 | Messenger: SOS broadcast until acknowledged, alarm, I'm OK | DONE in Messenger repo (uncommitted): SOS send/receive, alarm, I'm OK, countdown; screens checked as PNG |
| W1 | WalkieTalkie: use the shared store, migrating existing keys (keep old files) | DONE in WalkieTalkie repo (uncommitted): SDK 1.3.0, `app/store/shared_radio.py`, main.py uses shared ID/keys/contacts/radio.json; 643 tests pass (incl. ID/name changes shared) |
| F1 | User report: Messenger "Radio deaf: check M0/M1" | DONE: wrapper `park_dc_low` (LCD DC = radio M1); deployed to the Pi, mode pins 100% transparent at idle; apps' check tolerates frame blips (not deployed) ([record](docs/quality/records/2026-10-03-radio-deaf-dc-line.md)) |
| T1 | Launch-window test failed once in check.sh (hold turned tap moved the daemon selection to gamma) | DONE: re-select beta before each retry; 6/6 runs, check.sh green (401) |
| D1 | Pi: run setup-radio (needs the user's sudo password), deploy, test | PARTLY: new Messenger + WalkieTalkie sideloaded and start with the radio transparent (868 MHz, module as before); `setup-radio.sh` NOT run yet (user's sudo); no over-the-air test |

Facts: both apps carry their own SX126X driver and `provision_radio.py`;
Messenger read `../WalkieTalkie/config.yaml` (breaks under managed installs);
WalkieTalkie Device ID is assigned and stored, Messenger's is crc32(hostname).
Only one radio (the Pi) is reachable, so no over-the-air test between two radios.

## Fruit Store (started 2026-10-03, user request)

User: WiFi Config appeared on the menu (a Sep 30 daemon registration whose
Whisplay example `wifi_config_app.py` no longer exists); add uninstall and
delete (two functions, two confirmations) and turn the App installer into
the **Fruit Store** (install, update, roll back, reset, uninstall, delete).
Then: a new project merging Messenger and WalkieTalkie into one app.

| Step | Work | Status |
|---|---|---|
| S1 | Installer: `uninstall` keeps data (`uninstalled.json`), `delete_data`, `reset_data`; failed reinstall never deletes kept data | DONE (6 tests, negative control) |
| S2 | Registry: `leftovers()`, hide "(removed)" ghosts, daemon app with a missing script is broken | DONE (3 tests) |
| S3 | Wrapper `mfruit.app.unregister` + client + lifecycle fallback | DONE (3 real-daemon tests, local + upstream 1066486) |
| S4 | Services `uninstall_app`/`delete_app_data`/`reset_app`; Fruit Store screens (`store.py`); Settings > Apps uninstall uses the same flow; `mfruitctl uninstall/delete/reset/rollback` | DONE (9 store + ctl tests) |
| S5 | Docs, check.sh, deploy to Pi, uninstall WiFi Config there | DONE: check.sh 422 OK; WiFi Config uninstalled + data deleted on the Pi through the Fruit Store ([record](docs/quality/records/2026-10-03-fruit-store.md)) |
| P1 | New project **RadioConnect** (`/home/meng/RadioConnect`): Messenger + WalkieTalkie in one app (user: WalkieTalkie v3 + SOS protocol; keep the old apps) | R0, R1 (Chats), L1 (standalone lifecycle on both devices) DONE; Talk redesign, voice/text delivery ticks, pairing-loss fix and unpairing (0.3.2) on both devices, texts ✓✓ both ways; R2 SOS next — see RadioConnect/CONTINUE.md |

## Next steps (in order)

1. User decision: commit and push (CI then runs for the first time; check
   both jobs, especially Python 3.9).
2. User decision on [ADR 0006](docs/platform/ADR/0006-settings-provider-apps.md)
   (KI-2, `settings_provider` manifest field); implement if accepted.
3. Companion app repos must refresh `.claude/rules/mfruit-os-app.md` from
   `docs/apps/APP_CONTRACT.md` (their `check-app.py` reports a difference until
   then). Not done without the user's go-ahead.
4. Physical checks of the installed Pi build (hardware checklist, incl. item 19:
   games with a real keyboard). KI-8 adopted-record clean-up; KI-9 make
   shutdown safe during install jobs; AI Chatbot on the Pi needs a manual
   reinstall (not in the catalogue).
5. Backlog: KI-4 `persist` validation (compatibility change; decide strictness),
   KI-3 launcher/SDK duplication, then host extraction steps 1–2
   ([ADR 0005](docs/platform/ADR/0005-incremental-host-boundary-extraction.md)).

## Standing facts

- Deploy MFruit OS to a device from `~/MFruitOS-candidate` (tar), never over
  `~/MFruitOS`: on the Orange Pi that is the user's git clone. On the Pi,
  `~/MFruitOS` was overwritten by earlier deploys this session (no `.git` there).

- Raspberry Pi Zero 2 W: `ssh jarvis@192.168.0.33` (key-based); Whisplay at
  upstream `1066486`; sudoers allows `systemctl restart whisplay-os.service`
  and `whisplay-daemon.service`. Orange Pi not tested this session.
- `~/ai-chatbot/Whisplay` on the dev machine is a copy vendored in the
  ai-chatbot repository, not a Whisplay git checkout.
- Never run two real-daemon test suites at once (they share fake-app clean-up).
- Physical checks remain the user's ([Validation](docs/quality/VALIDATION.md)).

## Pause notes (radio work)

- **Nothing from the radio work is deployed to the Pi, committed, or pushed.**
  MFruitOS tree: `scripts/setup-radio.sh` never run on a device; full
  `check.sh` not rerun since the radio changes (only focused tests).
- **Messenger** (`~/Messenger`, uncommitted): SDK 1.3.0 synced; new
  `messaging/{security,pairing,emergency}.py`, `controls/menus.py`; 185 tests.
  Not run on a board; no two-radio over-the-air test yet; manifest/README/docs
  (docs/EMERGENCY.md) not written; SOS is received only while Messenger is the
  foreground app (platform has no background notifications: add to roadmap).
- **WalkieTalkie** (`~/WalkieTalkie`, uncommitted): W1 done 2026-10-03 —
  `app/store/shared_radio.py` + `main.py`; factory reset now also unpairs in
  Messenger (shared keys). W1b done: a Device ID or name changed in
  WalkieTalkie (Settings, or the pairing clash move) is written to the shared
  `device.json` (`shared_radio.save_identity`); 643 tests pass, negative
  control: the two ID-change tests fail without it.
- `check.sh` re-run after the radio work: green (401 tests). Still to do: README/INSTALL docs for
  Messenger; catalogue refs for Messenger/WalkieTalkie are pinned to old
  commits (update after the user commits+pushes them); AU915 legality is the
  user's responsibility to confirm.
