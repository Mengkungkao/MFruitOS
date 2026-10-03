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

Hardware drivers and whisplay-daemon must already be installed and running.
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

[ "$(uname -s)" = Linux ] || fail "MFruit OS requires Linux"
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

sys.path.insert(0, sys.argv[1])
from mfruitos import __version__
from mfruitos.apps.manifest import ManifestError, load_manifest

try:
    manifest = load_manifest(sys.argv[1])
except (ManifestError, OSError) as exc:
    raise SystemExit(f"FAIL: invalid MFruit OS checkout: {exc}")
if manifest.id != "mfruit-os" or manifest.type != "system" or manifest.version != __version__:
    raise SystemExit("FAIL: source version and system manifest disagree; use one complete checkout")
print(f"OK: Python {sys.version.split()[0]}, Pillow {PIL.__version__}, MFruit OS {__version__}")
PY

systemctl cat whisplay-daemon.service >/dev/null 2>&1 || fail "install whisplay-daemon.service using the driver instructions for your board"
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
