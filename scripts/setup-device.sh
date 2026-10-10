#!/usr/bin/env bash
# Read-only device preflight; explicitly opt into the existing installer.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE=check
MODE_SET=0
INSTALL_ARGS=()

usage() {
  cat <<'EOF'
Usage: bash scripts/setup-device.sh [--check]
       bash scripts/setup-device.sh --install [--dev] [--no-background-daemon] [--yes]

With no arguments or --check, verify prerequisites without installing files,
changing services, claiming the display, or installing system packages.
--install runs the same checks, then delegates to scripts/install.sh.
Run as the normal user that runs whisplay-daemon, not root.

Install options are forwarded unchanged to the existing installer:
  --dev                    run from this checkout
  --no-background-daemon   retain the daemon's own desktop between apps
  --yes                    installer noninteractive mode (sudo still needs authorization)

scripts/install.sh installs the mFruit OS Whisplay driver (docs/WHISPLAY_DRIVER.md)
when it is missing or out of date; --check only reports its state.
See docs/platform/INSTALLATION.md for prerequisites, manual setup, tests and recovery.
EOF
}

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
ok() { printf 'OK: %s\n' "$*"; }

for arg in "$@"; do
  case "$arg" in
    --check|--install)
      [ "$MODE_SET" = 0 ] || fail "choose only one of --check or --install"
      MODE="${arg#--}"
      MODE_SET=1
      ;;
    --dev|--no-background-daemon|--yes|-y) INSTALL_ARGS+=("$arg") ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $arg" ;;
  esac
done
[ "$MODE" = install ] || [ "${#INSTALL_ARGS[@]}" = 0 ] || fail "installer options require --install"

[ "$(uname -s)" = Linux ] || fail "mFruit OS requires Linux"
[ "$(id -u)" != 0 ] || fail "run as the whisplay-daemon user without sudo"
command -v python3 >/dev/null || fail "python3 is missing; install your distribution's Python 3.9+ package"
command -v systemctl >/dev/null || fail "systemd is required for device setup"
ok "$(uname -sm), user $(id -un)"
if [ -r /proc/device-tree/model ]; then
  ok "device: $(tr -d '\0' </proc/device-tree/model)"
fi

PYTHONDONTWRITEBYTECODE=1 python3 - "$SRC" <<'PY'
import sys

if sys.version_info < (3, 9):
    raise SystemExit("FAIL: Python 3.9 or newer is required")
try:
    import PIL
except ImportError:
    raise SystemExit("FAIL: Pillow is missing; on Debian/Ubuntu install python3-pil before continuing")
import re
_pil = re.match(r"(\d+)\.(\d+)", PIL.__version__)
if not _pil or (int(_pil.group(1)), int(_pil.group(2))) < (9, 0):
    raise SystemExit(f"FAIL: Pillow 9.0 or newer is required; this system has {PIL.__version__} "
                     "(Debian 11 / Raspberry Pi OS Bullseye are not supported)")

sys.path.insert(0, sys.argv[1])
from mfruitos import __version__
from mfruitos.apps.manifest import ManifestError, load_manifest

try:
    manifest = load_manifest(sys.argv[1])
except (ManifestError, OSError) as exc:
    raise SystemExit(f"FAIL: invalid mFruit OS checkout: {exc}")
if manifest.id != "mfruit-os" or manifest.type != "system" or manifest.version != __version__:
    raise SystemExit("FAIL: source version and system manifest disagree; use one complete checkout")
print(f"OK: Python {sys.version.split()[0]}, Pillow {PIL.__version__}, mFruit OS {__version__}")
PY

printf 'Whisplay driver:\n'
DRIVER_CHECK=0
bash "$SRC/drivers/whisplay/install.sh" --check | sed 's/^/  /' || DRIVER_CHECK=$?
[ "$DRIVER_CHECK" != 3 ] || fail "no supported Whisplay board detected (docs/WHISPLAY_DRIVER.md)"
[ "$DRIVER_CHECK" = 0 ] || ok "scripts/install.sh installs or updates the Whisplay driver (sudo; a reboot when buses or the sound card are new)"
printf 'Power management:\n'
if systemctl cat mfruit-power.service >/dev/null 2>&1; then
  if systemctl is-active --quiet mfruit-power.service; then
    ok "  mfruit-power.service is active (status: mfruitctl power)"
  else
    printf '  WARN: mfruit-power.service is installed but not active (journalctl -u mfruit-power -n 50)\n'
  fi
else
  ok "  not installed yet; scripts/install.sh installs mfruit-power.service (--no-power skips it)"
fi
# Settings > Wi-Fi works through NetworkManager, outside a login session.
printf 'Wi-Fi:\n'
if ! command -v nmcli >/dev/null 2>&1; then
  ok "  NetworkManager not installed yet; scripts/install.sh installs it"
  if networkctl list 2>/dev/null | awk '$3 == "wlan" && $5 == "configured"' | grep -q .; then
    printf '  NOTE: systemd-networkd (netplan) runs Wi-Fi here; NetworkManager will not take it over by itself (docs/platform/INSTALLATION.md#ubuntu-server-wi-fi-and-netplan)\n'
  fi
else
  WIFI_UNMANAGED="$(nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null \
                    | awk -F: '$2 == "wifi" && $3 == "unmanaged" { printf "%s ", $1 }' || true)"
  if [ -n "$WIFI_UNMANAGED" ]; then
    printf '  WARN: NetworkManager does not manage %s, so Settings > Wi-Fi cannot change it (docs/platform/INSTALLATION.md#ubuntu-server-wi-fi-and-netplan)\n' "${WIFI_UNMANAGED% }"
  else
    ok "  NetworkManager manages Wi-Fi"
  fi
  NM_PERMS="$(timeout 20 systemd-run --user --pipe --wait --quiet \
              nmcli -t -f permission,value general permissions 2>/dev/null || true)"
  if [ -z "$NM_PERMS" ]; then
    ok "  could not ask NetworkManager from outside this session (no user systemd); skipped"
  elif echo "$NM_PERMS" | grep -qx 'org.freedesktop.NetworkManager.wifi.scan:yes' \
      && echo "$NM_PERMS" | grep -qx 'org.freedesktop.NetworkManager.network-control:yes'; then
    ok "  NetworkManager allows scans and joins outside a login session"
  else
    printf '  NOTE: NetworkManager refuses scans or joins outside a login session; scripts/install.sh adds the permission (polkit %s)\n' \
      "$(pkaction --version 2>/dev/null | awk '{ print $NF }' || echo '?')"
  fi
fi
if systemctl is-active --quiet pisugar-server.service 2>/dev/null; then
  printf "  NOTE: PiSugar's pisugar-server is running; scripts/install.sh stops and disables it\n"
fi
if ! systemctl cat whisplay-daemon.service >/dev/null 2>&1; then
  if [ "$MODE" = check ]; then
    printf 'Preflight passed (the driver is installed first). Install with: bash scripts/setup-device.sh --install\n'
    exit 0
  fi
  exec bash "$SRC/scripts/install.sh" "${INSTALL_ARGS[@]}"
fi
DAEMON_USER="$(systemctl show --property=User --value whisplay-daemon.service)"
[ "$DAEMON_USER" = "$(id -un)" ] || fail "whisplay-daemon runs as ${DAEMON_USER:-root}; log in as its configured non-root user"
systemctl is-active --quiet whisplay-daemon.service || fail "whisplay-daemon is not active; inspect journalctl -u whisplay-daemon -n 80"
WHISPLAY_ROOT="$(systemctl show --property=WorkingDirectory --value whisplay-daemon.service)"
[ -n "$WHISPLAY_ROOT" ] || WHISPLAY_ROOT="$HOME/Whisplay"
[ -r "$WHISPLAY_ROOT/daemon/whisplay_daemon.py" ] || fail "Whisplay daemon source is missing at $WHISPLAY_ROOT; check the service WorkingDirectory"
ok "whisplay-daemon.service is active as $DAEMON_USER ($WHISPLAY_ROOT)"

PYTHONDONTWRITEBYTECODE=1 python3 - "$SRC" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
from mfruitos.daemon.client import DaemonError, WhisplayDaemonClient

try:
    WhisplayDaemonClient().ping()
except DaemonError as exc:
    raise SystemExit(f"FAIL: daemon health.ping failed: {exc}")
print("OK: daemon health.ping at /tmp/whisplay-daemon.sock")
PY

if [ "$MODE" = check ]; then
  printf 'Preflight passed. Install with: bash scripts/setup-device.sh --install\n'
  exit 0
fi

command -v sudo >/dev/null || fail "sudo is required by the system installer"
printf 'Installing through scripts/install.sh; this updates launcher files and restarts services.\n'
exec bash "$SRC/scripts/install.sh" "${INSTALL_ARGS[@]}"
