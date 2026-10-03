# Troubleshooting

Symptoms, where to look and what to do. Reading the launch log is explained in
[Lifecycle](../platform/LIFECYCLE.md#reading-the-lifecycle-log); installation
steps are in [Installation](../platform/INSTALLATION.md).

## First commands

```bash
systemctl status whisplay-os.service whisplay-daemon.service --no-pager
journalctl -u whisplay-os.service -u whisplay-daemon.service -n 150 --no-pager
mfruitctl status                       # launcher state, session, keyboards
tail -n 100 ~/.whisplay-os/logs/launcher.log
tail -n 100 ~/.whisplay-os/logs/updater.log
tail -n 100 ~/.whisplay-os/logs/launch-gate.log
tail -n 100 ~/.whisplay-os/logs/<app-id>.log
mfruitctl screenshot /tmp/screen.png   # what MFruit OS is drawing (not an app's frame)
```

Daemon-managed apps that are not MFruit OS packages may log to
`~/.whisplay-daemon/daemon-app.log` or their own log instead.

## Symptoms

| Symptom | Check / do |
|---|---|
| The daemon's "Opening app…" or desktop still appears | Rerun `install.sh` (adds the daemon drop-in). *Settings → General → Diagnostics* shows *Hardware desktop: background* when active. |
| The hardware desktop shows instead of MFruit OS | `systemctl status whisplay-os`; pick **MFruit OS** on the hardware desktop. *Developer → Daemon desktop* switches there on purpose. |
| "Hardware service unavailable" | The daemon is stopped or failed: `journalctl -u whisplay-daemon -n 50`. *Retry* waits for it; *Restart daemon* restarts it (sudoers rule). |
| "Application failed to start" | *Logs* on that screen, or the app log. Check the app's dependencies before reinstalling. |
| A different app than selected opened, or two apps | Find the `LAUNCH_REQUEST` and its `source` in `launcher.log`; `DENIED` lines in `launch-gate.log` and `INTRUDER` lines show starts MFruit OS blocked. Report with the [bug template](BUG_TEMPLATE.md). |
| `LAUNCH_REFUSED_BY_DAEMON` | The line records who held the screen; usually another app was still closing. Retry. |
| Keys do nothing in an app | SDK apps need SDK 1.2.0 (key hub) and must pass their `app_id`. Apps without the SDK get only Esc (exit) and Space (button) through the keyboard bridge; after updating MFruit OS, restart whisplay-daemon once so the wrapper has `mfruit.app.key`. `mfruitctl status` lists grabbed keyboards. |
| App installer shows **Repair** | The app is registered but its folder is missing; Repair reinstalls it from the catalogue and keeps its settings. |
| Typed keys reach the console | Should not happen while MFruit OS runs (keyboards are grabbed); check Daemon desktop mode, then report. |
| Updater says "Internet unavailable" | Check the network; the check retries after 10 minutes. |
| "GitHub rate limit reached" | Anonymous access allows 60 requests/hour per IP; set `updater.github_token` ([Configuration](../platform/CONFIGURATION.md)). |
| Settings reset to defaults | A corrupt `settings.json` is kept as `settings.json.broken-<date>` and logged; fix or delete it. |
| Button feels slow | Single clicks wait for the double-click window (300 ms). Lower *Settings → Button → Click speed*, or set double/triple click to *Nothing*. |
| A system update rolled back by itself | The new version failed to start three times; `boot-guard` restored the previous one. See the journal for the failure. |
| `dnsmasq.service` fails on the Orange Pi | Port 53 is held by the DNS stub at 127.0.0.53; unrelated to MFruit OS. Wi-Fi still works. |

## Running the launcher interactively

```bash
sudo systemctl stop whisplay-os.service
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --debug   # from the checkout; Ctrl-C to stop
sudo systemctl start whisplay-os.service
```

Keep whisplay-daemon running; never run two launchers at once.

## Recovery

- Broken app: *Settings → Apps → app → Roll back*, or uninstall and reinstall.
- Broken MFruit OS version: the boot guard rolls back automatically; manual
  steps are in [Installation](../platform/INSTALLATION.md#manual-rollback-of-a-checkout-installation).
- Remove MFruit OS but keep data: `bash scripts/uninstall.sh`.
