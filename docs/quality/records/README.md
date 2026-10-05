# Validation and investigation records

Dated evidence. Each record describes the revision and devices it names; it
is **not** a statement about the current checkout
([Part I §21](../../platform/DEVELOPMENT_RULES.md#21-quality-records)). Current
open problems are in [known issues](../KNOWN_ISSUES.md); the record format is
in [Validation](../VALIDATION.md#what-a-record-contains).

Name new records `YYYY-MM-DD-topic.md` and add them to the top of this list.

| Date | Record | Scope |
|---|---|---|
| 2026-10-05 | [Radio auto-setup](2026-10-05-radio-autosetup.md) | Queued RadioConnect installed by the launcher on the Pi; next-boot radio service verified only with `systemd-analyze` |
| 2026-10-05 | [Online Fruit Store list](2026-10-05-online-catalogue.md) | Store list downloaded from GitHub, bundled fallback; Pi Zero 2 W check with a simulated online-only entry |
| 2026-10-04 | [Radio over the air](2026-10-04-radio-over-the-air.md) | Pi ↔ Orange Pi at 920 MHz: 100% delivery with the backlight at 100%, 0% when dimmed (radio M0 = backlight pin) |
| 2026-10-03 | [Bundled Whisplay driver and offline installation](2026-10-03-bundled-whisplay-driver.md) | Whisplay driver in `drivers/whisplay`, offline packs; dev machine and Orange Pi (no privileged step run) |
| 2026-10-03 | [Fruit Store](2026-10-03-fruit-store.md) | WiFi Config leftover explained; uninstall/delete/reset; Pi check |
| 2026-10-03 | [Radio deaf: LCD DC line](2026-10-03-radio-deaf-dc-line.md) | Messenger "Radio deaf: check M0/M1": root cause, daemon-wrapper fix, Pi check |
| 2026-10-03 | [Keyboard bridge and App installer repair](2026-10-03-keyboard-bridge-and-repair.md) | Jump/Flappy Bird keyboard play and exit; Repair for broken catalogue apps; Pi install |
| 2026-10-02 | [Baseline and launch-window investigation](2026-10-02-baseline-and-launch-window.md) | full suite on a dev machine and the Raspberry Pi; root cause and fix of the intermittent launch-window test; Pi install |
| 2026-10-01 | [Installer validation hand-off](2026-10-01-handoff.md) | previous `CONTINUE.md`, archived verbatim: Raspberry Pi install of `cfe8ac2`, installer validation |
| 2026-09-30 | [Orange Pi checkpoint](2026-09-30-orange-pi-checkpoint.md) | Wi-Fi/RGB follow-up and 1.4.0 deployment on the Orange Pi |
| 2026-09-30 | [Validation](2026-09-30-validation.md) | MFruit OS and companion apps, cleanup, app standards |
| 2026-09-30 | [Settings and package validation](2026-09-30-settings-validation.md) | Settings spacing, package update flows, live install/rollback |
| 2026-09-30 | [Git integration](2026-09-30-git-integration.md) | merging upstream commits across six repositories |
