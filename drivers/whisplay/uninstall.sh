#!/usr/bin/env bash
# Remove the mFruit OS Whisplay driver.
#
#   sudo bash drivers/whisplay/uninstall.sh           stop and remove whisplay-daemon
#                                                     and the driver files
#   sudo bash drivers/whisplay/uninstall.sh --audio   also remove the sound card
#                                                     module, overlay and ALSA config
#
# App registrations and daemon settings (~/.whisplay-daemon) are kept. The
# LCD and button stop working until a driver is installed again.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER_DIR="${MFRUIT_WHISPLAY_DIR:-/usr/local/share/whisplay}"
SERVICE=whisplay-daemon.service
UNIT_PATH="/etc/systemd/system/$SERVICE"
AUDIO=0
[ "${1:-}" = "--audio" ] && AUDIO=1
[ "${EUID:-$(id -u)}" -eq 0 ] || { echo "Run as root: sudo bash $0" >&2; exit 1; }

if grep -qsF "# Installed by mFruit OS (drivers/whisplay/install.sh)." "$UNIT_PATH"; then
  systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
  rm -f "$UNIT_PATH" "/etc/systemd/system/$SERVICE.d/20-cubie-a7z-audio.conf"
  systemctl daemon-reload
  echo "[+] $SERVICE removed"
else
  echo "[!] $SERVICE was not installed by mFruit OS; left alone" >&2
fi
if [ -f "$DRIVER_DIR/MFRUIT_DRIVER" ]; then
  rm -rf -- "$DRIVER_DIR" "$DRIVER_DIR.previous"
  echo "[+] driver files removed from $DRIVER_DIR"
fi
rm -f /etc/sudoers.d/whisplay-daemon-power /etc/udev/rules.d/60-whisplay-orangepi.rules
if [ "$AUDIO" = 1 ]; then
  bash "$HERE/audio/whisplay-soundcard/scripts/uninstall.sh"
fi
echo "Daemon settings and app registrations in ~/.whisplay-daemon were kept."
echo "Saved earlier daemon units (if any): /var/backups/mfruitos/"
