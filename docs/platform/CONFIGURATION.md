# Configuration

mFruit OS has one persistent settings file, a small set of environment
variables and command-line options, and two read-only configuration files
shipped with the code. The schema in `mfruitos/system/settings.py` (`SCHEMA`)
is the single source of truth; this document describes it. Do not read or
write settings outside the `Settings` service
([Part I §15](DEVELOPMENT_RULES.md#15-configuration)).

## Settings file

Location: `~/.whisplay-os/config/settings.json` (under `WHISPLAY_OS_HOME`).
`config/default.json` is a generated reference copy of the defaults:

```bash
python3 -m mfruitos.system.settings --dump-defaults > config/default.json
```

### Loading, validation and recovery

- **Unreadable or invalid JSON:** the file is preserved as
  `settings.json.broken-<timestamp>`, the error is logged and shown after boot,
  and safe defaults are used. The user's only copy is never overwritten.
- **One invalid value:** that key falls back to its default; others load.
- **Button map lock-out:** a map without a `select` gesture, or without a
  gesture that moves the selection, is refused (on load the default gestures
  are restored; on set the change is rejected).
- **Unknown keys** are ignored on load and dropped on the next save.
- **Writes** are atomic (temporary file, `fsync`, rename) and debounced by
  1.5 s; a launch or shutdown flushes pending changes first.
- **Migration:** the file carries `"schema": 1`. No migration exists yet
  because no schema change has required one; a future change that renames or
  reinterprets a key must add a tested migration and keep old files loadable
  ([Part I §29](DEVELOPMENT_RULES.md#29-backward-compatibility)).

### Keys

| Key | Default | Accepted values | Effect |
|---|---|---|---|
| `display.brightness` | 80 | 5–100 | backlight level while mFruit OS is in front |
| `display.auto_dim` | true | bool | dim after `dim_after_sec` |
| `display.dim_after_sec` | 30 | 10, 15, 30, 60, 120 | idle time before dimming |
| `display.dim_level` | 15 | 1–60 | dimmed brightness |
| `display.screen_timeout_sec` | 120 | 0, 15, 30, 60, 120, 300, 600 | idle time before the backlight turns off (0 = never) |
| `display.theme` | `dark` | `dark`, `light` | launcher theme |
| `display.animation` | `minimal` | `minimal`, `off` | progress-screen animation |
| `button.single_click` | `next` | gesture action | action for a tap |
| `button.double_click` | `previous` | gesture action | action for 2× |
| `button.triple_click` | `none` | gesture action | action for 3× |
| `button.long_press` | `select` | gesture action | action for hold-then-release |
| `button.quad_click` | `back` | gesture action | action for 4× |
| `button.click_gap_ms` | 300 | 150–800 | multi-click window |
| `button.long_press_ms` | 700 | 400–2000 | hold threshold |
| `led.enabled` | true | bool | RGB LED on/off |
| `led.idle_color` / `running_color` / `update_color` / `error_color` | blue / green / orange / red | LED colour name | colour per platform state |
| `led.brightness` | 30 | 0–100 | LED brightness |
| `audio.device` | `""` | string ≤64 | ALSA device for the speaker test (empty = default) |
| `updater.auto_check` | true | bool | periodic update checks |
| `updater.check_interval_hours` | 12 | 1–168 | check interval |
| `updater.include_prereleases` | false | bool | offer pre-release versions |
| `updater.require_checksum` | false | bool | refuse downloads without a published SHA-256 |
| `updater.keep_versions` | 2 | 1–5 | installed versions kept per app |
| `updater.max_download_mb` | 100 | 5–1024 | download size limit |
| `updater.github_token` | `""` | string ≤200 | optional GitHub token (raises the API rate limit) |
| `updater.discovery_topic` | `whisplay-app` | string ≤50 | GitHub topic used by *Discover* |
| `updater.online_catalog` | true | bool | download the Fruit Store list from `system.repository` so new apps appear without an OS update ([ADR 0010](ADR/0010-online-fruit-store-catalogue.md)) |
| `updater.sources` | `[]` | list of GitHub repositories | extra repositories listed in *More sources* |
| `system.repository` | `https://github.com/Mengkungkao/MFruitOS` | GitHub repository or empty | where system updates come from |
| `system.show_system_pages_on_home` | false | bool | list daemon pages on Home |
| `developer.enabled` | false | bool | show the Developer settings section |
| `developer.debug_logging` | false | bool | debug-level logs |
| `daemon.socket_path` | `/tmp/whisplay-daemon.sock` | string ≤200 | hardware service socket |
| `daemon.fallback_direct_display` | true | bool | allow the recovery display when the daemon unit is down |
| `daemon.whisplay_root` | `""` | string ≤300 | Whisplay driver directory for the recovery display (empty = detect: the daemon's `WorkingDirectory`, `/usr/local/share/whisplay`, `~/Whisplay`, the bundled copy) |
| `apps.order` | `[]` | list of app IDs | user's Home order |
| `apps.clean_menu` | false | bool | show only `installed_ids` (plus system entries) on Home |
| `apps.installed_ids` | `[]` | list of app IDs | apps added to the curated menu |
| `apps.default_app` | `""` | app ID or empty | app selected first on Home |

Gesture actions: `next`, `previous`, `select`, `back`, `home`, `none`. LED
colours: `off`, `white`, `blue`, `cyan`, `green`, `yellow`, `orange`, `red`,
`purple`, `pink`.

### Wi-Fi from a phone

| Key | Default | Meaning |
|---|---|---|
| `wifi_setup.mode` | `screen` | when PiSugar's sugar-wifi-conf runs: `screen` (only while Settings → Wi-Fi → Phone Setup is open), `offline` (also whenever there is no network), `always` ([ADR 0013](ADR/0013-phone-wifi-setup.md)) |
| `wifi_setup.key` | `""` | the key phones must give (6–32 letters and digits); made on first use (8 characters) and shown on the screen — a secret |
| `wifi_setup.name` | `""` | its Bluetooth name; empty uses the controller's own name |

The tool's own config is generated as `state/sugar-wifi-conf.json` (mode
0600): information (mFruit OS version, battery, CPU temperature, memory, up
time) and commands (restart mFruit OS, reboot, shut down). A valid
`config/sugar-wifi-conf.json` in the same format (`info`: label of at most
20 bytes, command, interval; `commands`: label, command) replaces it; its
commands run as the mFruit user. The tool's log, with everything a phone
typed removed, is `logs/wifi-setup.log`.

### Removed keys

Keys from older versions are ignored when loaded (no error) and dropped on the
next save.

| Key | Removed | Why |
|---|---|---|
| `display.clock_24h` | after 1.4.0 (2026-10-02) | the 1.2.0 status bar no longer shows a clock; the Display toggle had no visible effect |
| `system.home_title` | after 1.4.0 (2026-10-02) | no title row since 1.2.0; nothing read it |

### Per-app flags

`applications.<app_id>` holds flags the user changed; a flag never set keeps
its default and stays distinguishable from an explicit choice.

| Flag | Default | Meaning |
|---|---|---|
| `enabled` | true | launchable; disabling keeps files and data |
| `hidden` | false | hidden from Home |
| `autostart` | false | launch once per boot; only one app may autostart |
| `background` | false | *Keep running* after the user leaves (overrides the manifest default) |
| `screen_bright` | false | *Keep screen bright*: while the app runs in the background, the backlight stays at 100% (no dimming or screen-off); set by the user or by the app through the SDK ([ADR 0009](ADR/0009-app-background-request.md)) |

### Secrets

`updater.github_token` and `wifi_setup.key` are stored in plain text in
`settings.json` (mode set by the user's umask). Never commit a settings file, paste a token into a test,
example or log, or include it in a validation record.

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `WHISPLAY_OS_HOME` | platform, `mfruit-run`, `boot-guard.sh`, SDK | mFruit OS data directory (default `~/.whisplay-os`) |
| `WHISPLAY_DAEMON_HOME` | platform | whisplay-daemon data directory (default `~/.whisplay-daemon`) |
| `MFRUIT_HOME`, `MFRUIT_SESSION` | SDK (set by `mfruit-run`) | data directory and launch session for the running app |
| `MFRUIT_KEYS_SOCKET` | SDK | override the key hub socket path |
| `MFRUIT_FONT_DIR` | SDK | extra font directory |
| `WHISPLAY_APP_ID`, `WHISPLAY_OS_APP_DIR`, `WHISPLAY_OS_APP_DATA`, `WHISPLAY_OS_VERSION`, `WHISPLAY_OS_PREVIOUS_VERSION` | apps and hooks | runtime contract ([App contract](../apps/APP_CONTRACT.md)) |
| `NOTIFY_SOCKET`, `WATCHDOG_USEC`, `WATCHDOG_PID` | launcher | systemd readiness and watchdog |

## Command line

`python3 -m mfruitos [--home DIR] [--socket PATH] [--debug] [--self-test]
[--preview DIR] [--version]`. `--self-test` imports every module and renders
every screen offscreen (the system update TEST step); `--preview` also writes
PNGs. `mfruitctl help` lists the control commands.

## Shared radio files

`~/.whisplay-os/shared/radio/` (mode 0700, files 0600), owned by the SDK's
`radio` module ([ADR 0007](ADR/0007-shared-radio-capability.md)):

| File | Written by | Content |
|---|---|---|
| `radio.json` | `setup-radio.sh` only | `frequency_mhz`, `air_speed`, `power_dbm`, `net_id`, `port`, `band`, `module`, `provisioned_at`, `schema` |
| `device.json` | radio apps (first use) | this radio's Device ID (`address`, 1–65534) and `name` |
| `keys.json` | radio apps | this radio's X25519 key and broadcast key, and each paired radio's keys — **secret** |
| `contacts.json` | radio apps | names of paired radios |

## Power settings

`~/.whisplay-os/config/power.json`, written only by the power service
(`mfruit-power.service`, [ADR 0012](ADR/0012-own-power-management.md)).
The launcher's Settings → Battery and `mfruitctl power set KEY VALUE` change
it through the service, which validates, applies to the board and saves
atomically. A broken file is kept as `power.json.broken-<timestamp>` and the
defaults are used; one invalid entry falls back alone. On the first start,
settings of PiSugar's own power manager (`/etc/pisugar-server/config.json`
and the model in `/etc/default/pisugar-server`) are imported once.

| Key | Default | Meaning |
|---|---|---|
| `model` | `auto` | `auto` (detect), `pisugar3`, `pisugar2-4led`, `pisugar2-2led`, `pisugar2-pro`, or `none` (power management off; the bus is not opened) |
| `i2c_bus` | 1 | I2C bus (`/dev/i2c-N`) |
| `i2c_address` | null | PiSugar 3 address when changed from 0x57 |
| `safe_shutdown_level` | 5 | power off below this charge (%) while unplugged; 0 = off; at most 30 |
| `safe_shutdown_delay` | 30 | countdown in seconds before that power-off (0–120); external power cancels it |
| `button_double`, `button_long` | `none` | board button action: `none`, `home`, `screen` (screen off/on), `power_menu`; a single press is whisplay-daemon's Home |
| `soft_poweroff`, `anti_mistouch`, `power_restore`, `battery_protect` | null | board settings (PiSugar 3; `power_restore` also PiSugar 2 with its clock); null = leave the board as it is |
| `charging_range` | null | `[start, stop]` % for boards that can switch charging (PiSugar 2 2-LED and Pro) |
| `full_charge_duration` | 300 | seconds to keep charging once the range's stop level is reached |
| `wake_time`, `wake_days` | null, 127 | wake alarm in local time `HH:MM` and weekday mask (bit 0 = Sunday); not with `power_restore` |
| `rtc_sync` | true | move the clock forward from the board's clock at boot when not synchronised; save the synchronised time to the board |
| `battery_curve` | null | your own `[[volts, percent], …]` (rising), replacing the board's curve |
| `compat_socket` | true | serve PiSugar's protocol on `/tmp/pisugar-server.sock` |
| `power_off_at_shutdown` | true | the shutdown hook switches the board off after a power-off |
| `tap_hooks` | off | `{single|double|long: {enabled, shell}}`, set by clients through PiSugar's protocol (`set_button_shell`); run as the mFruit user |

## Shipped configuration files

| File | Purpose |
|---|---|
| `config/default.json` | generated defaults reference (see above) |
| `config/catalog.json` | curated Fruit Store catalogue: per app `id`, `name`, `description`, `repository`, pinned `ref`, archive `url`, `sha256`, Python `entry`, `dependencies` and optional `requires` (device capabilities, e.g. `radio`), `min_os_version` and `system_packages` (Debian packages installed once by `scripts/setup-app.sh`); a native package instead has `"native": true` and its `version`. The same file on the default branch of `system.repository` is the online list ([App installation](../apps/INSTALLATION.md#curated-catalogue)) |
| `manifest.json` | mFruit OS's own system package manifest (`type: system`) |
