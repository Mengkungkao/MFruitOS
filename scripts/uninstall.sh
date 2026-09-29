#!/usr/bin/env bash
# MFruit OS uninstaller.
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
sudo rm -f /etc/sudoers.d/whisplay-os /usr/local/bin/mfruitctl

say "Removing MFruit OS from the daemon desktop"
PYTHONPATH="$OS_HOME/system/current" python3 - "$PURGE" "$OS_HOME" <<'PY' || true
import os, sys
purge, os_home = sys.argv[1] == "1", sys.argv[2]
try:
    from mfruitos.daemon.client import WhisplayDaemonClient, DaemonError
except ImportError:
    sys.exit(0)
client = WhisplayDaemonClient()
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
  rm -rf -- "$OS_HOME/system" "$OS_HOME/bin"
  say "Kept apps, settings and logs in $OS_HOME (use --purge to delete them)"
fi
say "MFruit OS removed. whisplay-daemon's own desktop is available again."
