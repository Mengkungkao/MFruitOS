# Changelog

All notable changes to MFruit OS are documented here. Versions follow
[Semantic Versioning](https://semver.org/). App versions are independent of
the OS version.

## [1.0.0] - 2026-09-29

First release.

### Core OS
- Runs as a whisplay-daemon foreground app (`mfruit-os`); the daemon keeps
  ownership of LCD, backlight, LED, button and app lifecycle.
- Boot screen with real startup steps; Home launcher with status bar (clock,
  WiFi, PiSugar battery), app cards and status badges.
- Single-button navigation: tap = next, double = previous, hold = select,
  four clicks = back. All gestures configurable; configurations that would
  make *select* unreachable are refused.
- Screen auto-dim and timeout, dark and light themes.
- Daemon pages (WiFi, Bluetooth, Volume, Power) surfaced in Settings when the
  running daemon provides them.
- Automatic recovery: re-takes the screen after apps exit, crash or are
  revoked; survives daemon restarts and screen locks.
- Fallback display when whisplay-daemon is stopped, with Retry / Restart
  daemon / Diagnostics.

### App management
- Registry merging OS-managed packages, daemon-registered apps and daemon pages.
- Enable, disable, hide, reorder, default app, autostart, stop, force stop,
  per-app logs, uninstall.
- `mfruit-run` wrapper records exit codes; failed launches show
  "Application failed to start" with Retry / Logs / Back.

### Updater
- GitHub Releases (and semver tags) as the distribution source, ETag-cached.
- Safe pipeline: check, download, verify, backup, install, test, activate;
  automatic rollback on failure; the running version is never overwritten.
- Upgrade, downgrade, reinstall, rollback, install from GitHub, discovery by
  topic, local sideload.
- SHA-256 verification from GitHub asset digests or `SHA256SUMS` files.
- Commit tracking for existing apps installed as git checkouts.
- System self-update with a boot guard that rolls back a version that fails
  to start three times.

### Tooling
- `install.sh`, `uninstall.sh`, `update.sh`, `deploy.sh`, systemd unit with
  watchdog, `mfruitctl` command-line control.
- App template (`templates/whisplay-app-template`), documentation, unit and
  integration tests (fake daemon, end-to-end runtime).
