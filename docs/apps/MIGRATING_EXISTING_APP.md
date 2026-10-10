# Migrating an existing app

How an existing whisplay-daemon app becomes a native mFruit OS package, and
how to tell the stages apart. Until the full package lifecycle is validated,
call it an **adopted app**, not a native package
([Part I §12](../platform/DEVELOPMENT_RULES.md#12-app-integration-guide)).

## What mFruit OS does with an existing app today

Any app registered with whisplay-daemon (`~/.whisplay-daemon/app/<id>.json`) is
discovered and **adopted**: its original registration is saved in
`~/.whisplay-os/adopted/<id>/` and the app is re-registered with
`mfruit-run <id>`, so it starts only through mFruit OS's launch gate. With
mFruit OS stopped or uninstalled it launches exactly as before. If the app is
a Git checkout, commit-tracking updates are offered.

Adoption gives launching, exit handling and process clean-up. Because mFruit
OS holds the keyboards, an adopted app that reads `/dev/input` itself gets
only the keyboard bridge: Esc (the daemon's exit) and Space as its button
([SDK](SDK.md#keyboard-input-and-the-key-hub)); move it to the SDK for
other keys. It does not
give managed installation, dependency setup, data snapshots, smoke tests,
release updates or rollback of data.

## 1. Inventory the app

Write down, before changing anything:

| Question | Why it matters |
|---|---|
| Hardware access: does it open GPIO, SPI, `/dev/input` or the display itself? | mFruit OS and whisplay-daemon own these; the app must use the daemon and the SDK |
| Direct daemon calls: `app.register` with a launch command, `app.launch`, focus handling | registration belongs to mFruit OS; other apps are never launched |
| Configuration files and where they live | must move to the data directory or `persist` |
| Dependencies: Python, Node, system packages, models | must install noninteractively from `install.sh` or a release artifact |
| Data locations, including paths outside the checkout and sibling repositories | updates replace the code folder; only managed data is snapshotted |
| Lifecycle assumptions: exit gesture, Esc handling, background work, start-up time | the contract requires `exit_gesture: none`, SDK Back and a fast first frame |
| Update behavior today (git pull, manual copy) | determines whether release packaging or the Git channel is used meanwhile |

## 2. Adopt the contract

- Vendor the SDK (`sdk-sync.sh`) and move input to `InputController` and the
  chrome to `mfruit_sdk.ui` ([SDK](SDK.md), [UI guidelines](UI_GUIDELINES.md)).
- Stop replacing the managed registration: no `app.register` with a launch
  command at start-up or in hooks; call `own_escape_key(APP_ID)` instead.
- Copy the contract to `.claude/rules/mfruit-os-app.md`.

## 3. Package natively

- Add `manifest.json` with the app's **existing** daemon `app_id`, so user
  settings and adoption records carry over ([Manifest](MANIFEST.md)).
- Write a repeatable, noninteractive `install.sh`; keep one-time system or
  hardware setup (codecs, radio configuration) as a documented prerequisite
  that `install.sh` checks for.
- Move user data to `$WHISPLAY_OS_APP_DATA`, or list it in `persist`; migrate
  existing data explicitly in `update.sh` and test the migration.
- Add a smoke test and run `check-app.py` ([Packaging](PACKAGING.md)).

Draft manifests for the companion apps live in `contrib/manifests/`; a draft
does not install dependencies, build the app or provide a smoke test.

## 4. Validate and switch over

Run the [package lifecycle tests](TESTING.md#package-lifecycle) with
disposable data, then sideload the release on a device that already has the
adopted app: confirm settings, data and models survive and that nothing
runs twice. Record the result before calling the app native.

## Companion app status (recorded 2026-09-30)

This table describes the local companion checkouts at that date; recheck
before relying on it. Existing clone-based installs keep working through
adoption meanwhile.

| App | Work still required before native release sign-off |
|---|---|
| ConnectWifi | Bundled with mFruit OS and provisioned on install; native manifest for an independent release and an install-time smoke hook absent; adapt its standalone setup/registration for managed installation. |
| WalkieTalkie | Native manifest and smoke hook; keep radio/codec/system setup separate from repeatable hooks; preserve managed registration. |
| Messenger | Manifest exists but lacks a minimum OS version and smoke hook; persist or relocate downloaded `models/`; migrate data into the managed data contract; replace the assumption of a sibling `WalkieTalkie/config.yaml`. |
| Crypto dashboard | Native manifest and smoke hook; adapt the standalone installer (system packages, direct daemon registration) for a noninteractive managed lifecycle; account for external configuration and data. |
| AI chatbot | Native manifest plus a reproducible Node build/install and smoke hook, or a complete built release artifact; preserve model/configuration/data paths. Its Node button logic still relies on the daemon `quad_click` exit (contract §1 exception). |
