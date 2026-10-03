# Known issues

Open problems with their status, evidence and next step. Status words follow
[Part I §20](../platform/DEVELOPMENT_RULES.md#20-quality-status-language).
Last reviewed **2026-10-02** against `f15afe5` plus that session's working
tree ([record](records/2026-10-02-baseline-and-launch-window.md)).

## Open

### KI-2 Application IDs special-cased in platform code

`connectwifi` is hard-coded in `launcher/services.py` (no Opening screen),
`apps/registry.py` (`SETTINGS_APPS`), `launcher/ui/screens/settings.py`,
`launcher/ui/screens/updater.py` and `provision.py`, contrary to Part I §33.
Behavior is correct today; the coupling blocks other Wi-Fi apps. Next: decide
[ADR 0006](../platform/ADR/0006-settings-provider-apps.md) (proposed
`settings_provider` manifest field), then migrate.

### KI-3 Duplicated launcher and SDK implementations

Gesture recognition, theme, fonts, RGB565 conversion and Wi-Fi/battery reads
exist in both `mfruitos/launcher/` / `mfruitos/system/` and `mfruitos/sdk/`.
Next: converge where behavior is identical, honoring SDK compatibility
([ADR 0003](../platform/ADR/0003-vendored-sdk-distribution.md)).

### KI-4 Manifest validation gaps

`persist` is validated only during installation (unsafe entries skipped with
a warning); `branch` and the `app_id` alias are accepted without being part of
the documented contract until 2026-10-02. Next: validate `persist` in
`validate_manifest` with a compatibility note ([Manifest](../apps/MANIFEST.md)).

### KI-7 Daemon desktop can turn a hold into a tap (external)

whisplay-daemon defect, documented as
[Host API fact 8](../platform/HOST_API.md#whisplay-daemon-facts-the-design-depends-on).
With the background wrapper installed (default) the desktop ignores the button
while MFruit OS runs, so users are not affected; tests no longer depend on it.
Report upstream if the desktop path matters to other users.

### KI-8 Adopted record left behind after a repair

Repairing a broken adopted app installs a managed package (which `mfruit-run`
prefers), but the saved original registration in `~/.whisplay-os/adopted/<id>/`
stays. Uninstalling MFruit OS restores that original, broken registration.
Next: retire the adopted record when a managed package replaces it, with a test.

### KI-9 Restarting the launcher interrupts a running install

The install pipeline runs on a worker thread; stopping or restarting
`whisplay-os.service` (or `mfruitctl restart`) during a job kills it, possibly
in the middle of its own rollback. Observed 2026-10-03 on the Pi: a catalogue
install was killed during its smoke test, leaving `apps/<id>/versions/<partial>`,
an empty `data/` and `apps/.work-*`; the registry then showed *Installation
incomplete*. No data was lost (fresh install) and the next install succeeded
after the residue was removed. Next: shutdown waits for or refuses to
interrupt the `jobs` lane (bounded), and start-up removes stale `.work-*`
directories and never-activated fresh installs with empty data. Until then:
check `mfruitctl jobs` before restarting.

### KI-10 Fruit Store tile shows the Settings description

On Home, the Fruit Store tile's subtitle reads "Apps, display, button, LED…":
`HomeScreen._subtitle` (`launcher/ui/screens/home.py`) gives every built-in
entry except the Updater the Settings text. Seen in a screenshot on the
Orange Pi, 2026-10-03. Cosmetic. Next: a subtitle for `os.installer`, with a
test.

## Physical checks outstanding

Button feel and gestures, physical USB/Bluetooth key routing and hotplug,
Bluetooth pairing flows, LED colours, audio/radio behavior and reboot
appearance of the current build are **NOT VERIFIED**; follow the
[hardware checklist](VALIDATION.md#hardware-checklist--launch-lifecycle-and-input).
On the Raspberry Pi, four daemon registrations (Messenger, WalkieTalkie,
crypto dashboard, AI chatbot) point to checkouts that do not exist there and
show as broken until those apps are installed.

## Resolved

| Issue | Resolution | Evidence |
|---|---|---|
| Launch-window daemon-page test intermittently failing (2026-10-01) | root cause: daemon hold→tap race (KI-7), not MFruit OS; test now synchronizes on observed state; deterministic variant added | 20/20 dev-machine and 10/10 Pi iterations; negative control fails ([record](records/2026-10-02-baseline-and-launch-window.md)) |
| KI-1 Sideloaded package folders skipped the archive safety checks: escaping symlinks were copied, no limits applied, set-uid bits kept | `copy_package_dir` applies the archive rules before copying and normalizes permissions | 4 installer + 2 verifier regression tests; all 4 installer tests failed before the fix (2026-10-02) |
| KI-6 Tests touched real input devices (test runtimes tried to grab the machine's keyboards) | `Runtime(input_dir=…)`; every test runtime uses an empty directory | `test_runtimes_under_test_never_open_real_keyboards` (2026-10-02) |
| KI-5 Settings with no effect (`system.home_title`; `display.clock_24h` and its Display toggle) | keys, toggle and the per-minute clock tick removed; old files still load | `test_removed_keys_in_an_old_file_load_cleanly_and_are_dropped` (2026-10-02) |
| Plain Whisplay apps (Jump Game, Flappy Bird) could not be played or left with a keyboard: MFruit OS 1.4.0 holds the keyboards, so their own `/dev/input` reader and the daemon's Esc got nothing (reported by the user, 2026-10-03) | keyboard bridge: Esc through the daemon's Esc handling, Space as the app's button (`mfruit.app.key`) | `test_keys_reach_an_app_that_does_not_use_the_key_hub` (real daemon; failed before the fix) |
| App installer showed broken catalogue apps (registered, folder missing) as *Installed* with no way to fix them | such rows show **Repair** and reinstall from the pinned catalogue source | `test_broken_catalogue_app_is_offered_for_repair_not_shown_installed` (failed before the fix) |
| Full suite not recorded as passing after 2026-10-01 | full suite rerun | 349/349 on the dev machine and on the Raspberry Pi, 0 skipped (same record) |
