#!/usr/bin/env bash
# mFruit OS uninstaller.
#
#   bash scripts/uninstall.sh          remove the service and launcher code,
#                                      keep apps, settings and logs
#   bash scripts/uninstall.sh --purge  also delete ~/.whisplay-os (apps, data, logs)
#
# whisplay-daemon and apps registered directly with it are never touched.
set -euo pipefail

TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
OS_HOME="${WHISPLAY_OS_HOME:-$TARGET_HOME/.whisplay-os}"
SERVICE=whisplay-os.service
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

say "Stopping $SERVICE"
if systemctl list-unit-files "$SERVICE" >/dev/null 2>&1; then
  sudo systemctl disable --now "$SERVICE" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/$SERVICE"
  sudo systemctl daemon-reload
fi
say "Removing power management"
if [ -f /etc/systemd/system/mfruit-power.service ]; then
  sudo systemctl disable --now mfruit-power.service 2>/dev/null || true
  sudo rm -f /etc/systemd/system/mfruit-power.service
  sudo systemctl daemon-reload
fi
sudo rm -f /usr/lib/systemd/system-shutdown/mfruit-power-off /lib/systemd/system-shutdown/mfruit-power-off
# The i2c-dev module stays loaded until the next boot (other I2C tools may use it).
sudo rm -f /etc/modules-load.d/mfruit-power.conf
# PiSugar's own services, if the installer had stopped them.
if [ -f "$OS_HOME/state/pisugar-services-disabled" ]; then
  while read -r unit; do
    case "$unit" in pisugar-server.service|pisugar-poweroff.service|sugar-wifi-config.service) ;; *) continue ;; esac
    if systemctl cat "$unit" >/dev/null 2>&1; then
      sudo systemctl enable "$unit" >/dev/null 2>&1 || true
      [ "$unit" = pisugar-poweroff.service ] || sudo systemctl start "$unit" 2>/dev/null || true
      echo "    $unit enabled again"
    fi
  done < "$OS_HOME/state/pisugar-services-disabled"
  rm -f "$OS_HOME/state/pisugar-services-disabled"
fi
sudo rm -f /etc/sudoers.d/whisplay-os /usr/local/bin/mfruitctl \
  /etc/polkit-1/rules.d/49-mfruit-wifi.rules \
  /etc/polkit-1/localauthority/50-local.d/49-mfruit-wifi.pkla
if [ -f /etc/systemd/system/mfruit-radio-setup.service ]; then
  # Left by scripts/setup-radio.sh when the radio settings were never written.
  sudo systemctl disable mfruit-radio-setup.service 2>/dev/null || true
  sudo rm -f /etc/systemd/system/mfruit-radio-setup.service
  sudo systemctl daemon-reload
fi
if [ -f /etc/systemd/system/whisplay-daemon.service.d/mfruit-os.conf ]; then
  say "Giving whisplay-daemon its own user interface back"
  sudo rm -f /etc/systemd/system/whisplay-daemon.service.d/mfruit-os.conf
  sudo rmdir /etc/systemd/system/whisplay-daemon.service.d 2>/dev/null || true
  sudo systemctl daemon-reload
  RESTART_DAEMON=1
fi

say "Removing mFruit OS from the daemon desktop"
PYTHONPATH="$OS_HOME/system/current" python3 - "$PURGE" "$OS_HOME" <<'PY' || true
import os, sys
purge, os_home = sys.argv[1] == "1", sys.argv[2]
try:
    from mfruitos.daemon.client import WhisplayDaemonClient, DaemonError
except ImportError:
    sys.exit(0)
client = WhisplayDaemonClient()
# Give adopted daemon apps their original launch commands back.
try:
    from mfruitos.launcher.app_manager.lifecycle import AppLifecycle
    from mfruitos.paths import resolve_paths
    restored = AppLifecycle(client, resolve_paths(os_home)).restore_adopted()
    print(f"    restored {restored} app registration(s) to their original launch commands")
except (ImportError, OSError) as exc:
    print(f"    could not restore adopted apps: {exc}")
ids = ["mfruit-os"]
if purge:
    apps_dir = os.path.join(os_home, "apps")
    if os.path.isdir(apps_dir):
        ids += [d for d in os.listdir(apps_dir) if not d.startswith(".")]
for app_id in ids:
    try:
        # persist=false makes the daemon delete its own JSON entry.
        client.register_app(app_id, f"{app_id} (removed)", launch_command="", persist=False,
                            priority=-1000)
        print(f"    unregistered {app_id}")
    except DaemonError as exc:
        print(f"    daemon not reachable for {app_id}: {exc}")
PY

if [ "$PURGE" = 1 ]; then
  case "$OS_HOME" in
    "$TARGET_HOME"/?*) say "Deleting $OS_HOME"; rm -rf -- "$OS_HOME" ;;
    *) echo "Refusing to delete unexpected path $OS_HOME" >&2; exit 1 ;;
  esac
else
  # Only where mFruit OS code is: a WHISPLAY_OS_HOME set to the home folder by
  # mistake must not lose ~/bin.
  if [ "${OS_HOME:-/}" != / ] && { [ -d "$OS_HOME/system/versions" ] || [ -L "$OS_HOME/system/current" ]; }; then
    rm -rf -- "${OS_HOME:?}/system" "${OS_HOME:?}/bin"
  else
    echo "    no mFruit OS code under $OS_HOME; nothing deleted there" >&2
  fi
  say "Kept apps, settings and logs in $OS_HOME (use --purge to delete them)"
fi
if [ "${RESTART_DAEMON:-0}" = 1 ]; then
  sudo systemctl restart whisplay-daemon.service
fi
say "mFruit OS removed. whisplay-daemon's own desktop is available again."
