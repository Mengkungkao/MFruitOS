#!/usr/bin/env bash
# setup-app.sh -- one-time device setup for Fruit Store apps that need system
# packages (the catalogue's "system_packages", e.g. AI Chatbot), then the app.
#
#   bash setup-app.sh <app_id>...           install the missing packages (asks first)
#                                            and queue the apps for installation
#   bash setup-app.sh --check <app_id>...   report only; change nothing
#   bash setup-app.sh --yes <app_id>...     do not ask
#
# Run as your normal user. sudo is used only for the packages, through
# scripts/offline.sh (an offline pack when there is one, otherwise apt-get).
# The app itself is installed by the launcher, through the same job as the
# Fruit Store's Install, once its packages are present (updater/autoinstall.py).
# install.sh --app <app_id> runs this script. Documentation:
# docs/apps/INSTALLATION.md ("Curated catalogue").
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OS_HOME="${WHISPLAY_OS_HOME:-$HOME/.whisplay-os}"
CHECK_ONLY=0
ASSUME_YES=0
APPS=()
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) APPS+=("$arg") ;;
  esac
done
[ "${#APPS[@]}" -gt 0 ] || { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user, not root (sudo is used where needed)." >&2; exit 2; }

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }
bad()  { printf '    \033[0;31mfail\033[0m %s\n' "$*"; FAILED=1; }
ask() {
  [ "$CHECK_ONLY" = 1 ] && return 1
  [ "$ASSUME_YES" = 1 ] && return 0
  local reply; read -r -p "        $1 [y/N] " reply; [[ "$reply" =~ ^[Yy] ]]
}
PY() { PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"; }

FAILED=0
QUEUED=0
for app in "${APPS[@]}"; do
  # name, then the packages (validated catalogue entry: Debian names only).
  info="$(PY - "$app" "$OS_HOME" <<'PY'
import sys
from mfruitos.updater import catalog
try:
    item = catalog.get(sys.argv[1], sys.argv[2])
except catalog.CatalogError as exc:
    sys.exit(str(exc))
print(item["name"])
print(" ".join(catalog.system_packages(item)))
print(" ".join(catalog.missing_packages(catalog.system_packages(item))))
PY
)" || { bad "$app: not in the Fruit Store list"; continue; }
  name="$(sed -n 1p <<<"$info")"
  packages="$(sed -n 2p <<<"$info")"
  missing="$(sed -n 3p <<<"$info")"
  say "$name ($app)"
  if [ -z "$packages" ]; then
    ok "needs no system packages"
  elif [ -z "$missing" ]; then
    ok "installed: $packages"
  else
    warn "missing: $missing"
    # shellcheck disable=SC2086  # validated package names, one word each
    if ask "install them with sudo?"; then
      if sudo bash "$ROOT/scripts/offline.sh" install $missing; then
        ok "installed"
      else
        bad "could not install: $missing"
        continue
      fi
    else
      bad "install them first: sudo apt-get install $missing"
      continue
    fi
  fi
  [ "$CHECK_ONLY" = 0 ] || continue
  if PY -m mfruitos.updater.autoinstall add "$app" --home "$OS_HOME" >/dev/null; then
    ok "queued: the device installs $name by itself (progress on the screen)"
    QUEUED=1
  else
    bad "could not queue $app; install it from the Fruit Store"
  fi
done

# Ask a running launcher to look now instead of at its next 10-minute check.
if [ "$QUEUED" = 1 ] && systemctl is-active --quiet whisplay-os.service 2>/dev/null; then
  PY -m mfruitos.ctl check >/dev/null 2>&1 && ok "launcher asked to install now" \
    || warn "launcher not reachable; it installs at its next check"
fi
[ "$FAILED" = 0 ] || exit 1
