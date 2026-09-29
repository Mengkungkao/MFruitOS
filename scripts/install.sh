#!/usr/bin/env bash
# MFruit OS installer.
#
#   bash scripts/install.sh              install (or upgrade) and start the service
#   bash scripts/install.sh --no-service install files only (no systemd changes)
#   bash scripts/install.sh --dev        run straight from this checkout (development)
#   bash scripts/install.sh --yes        do not ask questions
#   bash scripts/install.sh --no-background-daemon
#                                        keep whisplay-daemon's own user interface
#
# Run as your normal user (the one whisplay-daemon runs as). sudo is only
# used for the systemd unit, an optional narrow sudoers rule and the
# /usr/local/bin/mfruitctl link.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
TARGET_UID="$(id -u "$TARGET_USER")"
OS_HOME="${WHISPLAY_OS_HOME:-$TARGET_HOME/.whisplay-os}"
SERVICE=whisplay-os.service
DAEMON_SERVICE=whisplay-daemon.service
SOCKET=/tmp/whisplay-daemon.sock

INSTALL_SERVICE=1
BACKGROUND_DAEMON=1
DEV=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --no-service) INSTALL_SERVICE=0 ;;
    --no-background-daemon) BACKGROUND_DAEMON=0 ;;
    --dev) DEV=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }
fail() { printf '    \033[0;31mxx\033[0m  %s\n' "$*"; exit 1; }
as_user() { if [ "$(id -un)" = "$TARGET_USER" ]; then "$@"; else sudo -u "$TARGET_USER" "$@"; fi; }

if [ "$TARGET_USER" = "root" ]; then
  fail "run this as your normal user (the whisplay-daemon user), not root"
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/mfruitos/__init__.py")"
say "MFruit OS $VERSION for user $TARGET_USER"

# ------------------------------------------------------------------ checks
say "Checking system"
[ "$(uname -s)" = "Linux" ] || fail "MFruit OS needs Linux"
ok "$(uname -sm)"
if [ -r /proc/device-tree/model ]; then ok "device: $(tr -d '\0' </proc/device-tree/model)"; fi
command -v systemctl >/dev/null || { [ "$INSTALL_SERVICE" = 0 ] || fail "systemd is required (or use --no-service)"; }

PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || fail "python3 not found"
"$PYTHON" - <<'PY' || fail "Python 3.9 or newer is required"
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY
ok "$("$PYTHON" --version)"

if ! "$PYTHON" -c "import PIL" 2>/dev/null; then
  warn "Pillow missing; installing python3-pil"
  sudo apt-get install -y python3-pil || fail "could not install Pillow"
fi
ok "Pillow $("$PYTHON" -c 'import PIL; print(PIL.__version__)')"
command -v git >/dev/null && ok "git (updates for git-installed apps)" || warn "git not found: git-tracked app updates disabled"
command -v aplay >/dev/null && ok "aplay (speaker test)" || warn "aplay not found: speaker test disabled"

say "Checking Whisplay"
WHISPLAY_ROOT=""
if command -v systemctl >/dev/null && systemctl cat "$DAEMON_SERVICE" >/dev/null 2>&1; then
  WHISPLAY_ROOT="$(systemctl show -p WorkingDirectory "$DAEMON_SERVICE" | cut -d= -f2)"
  ok "$DAEMON_SERVICE installed ($(systemctl is-active "$DAEMON_SERVICE" || true))"
else
  warn "$DAEMON_SERVICE not found. Install Whisplay first: https://github.com/PiSugar/Whisplay"
fi
[ -n "$WHISPLAY_ROOT" ] || WHISPLAY_ROOT="$TARGET_HOME/Whisplay"
if [ -f "$WHISPLAY_ROOT/runtime/whisplay.py" ]; then ok "Whisplay runtime at $WHISPLAY_ROOT"
else warn "Whisplay runtime not found (daemon-down fallback display disabled)"; fi
if [ -S "$SOCKET" ]; then ok "daemon socket $SOCKET"; else warn "daemon socket not present yet"; fi

# ------------------------------------------------------------------ files
say "Installing files to $OS_HOME"
as_user mkdir -p "$OS_HOME"/{config,apps,cache,logs,system/versions,bin,inbox}
as_user mkdir -p -m 700 "$OS_HOME/state" "$OS_HOME/state/runs"

if [ "$DEV" = 1 ]; then
  CODE_DIR="$SRC"
  warn "development mode: running from $SRC"
else
  STAMP="$(date +%Y%m%d%H%M%S)"
  CODE_DIR="$OS_HOME/system/versions/$VERSION-local$STAMP"
  as_user mkdir -p "$CODE_DIR"
  ITEMS=()
  for item in mfruitos assets config scripts templates manifest.json LICENSE README.md \
      APP_DEVELOPMENT.md INSTALL.md CHANGELOG.md CONTRIBUTING.md; do
    [ -e "$SRC/$item" ] && ITEMS+=("$item")
  done
  (cd "$SRC" && tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' -cf - "${ITEMS[@]}") \
    | as_user tar -xf - -C "$CODE_DIR"
  ok "code: $CODE_DIR"
fi
PREVIOUS="$(readlink -f "$OS_HOME/system/current" 2>/dev/null || true)"
as_user ln -sfn "$CODE_DIR" "$OS_HOME/system/current.tmp"
as_user mv -T "$OS_HOME/system/current.tmp" "$OS_HOME/system/current"
ok "active version -> $(readlink "$OS_HOME/system/current")"

if [ ! -f "$OS_HOME/config/settings.json" ]; then
  as_user cp "$SRC/config/default.json" "$OS_HOME/config/settings.json"
  ok "default configuration created"
else
  ok "existing configuration kept"
fi

as_user install -m 0755 "$SRC/scripts/boot-guard.sh" "$OS_HOME/bin/boot-guard.sh"
as_user install -m 0755 "$SRC/scripts/whisplay-daemon-mfruit.py" "$OS_HOME/bin/whisplay-daemon-mfruit.py"
sed "s|@MFRUIT_HOME@|$OS_HOME|" "$SRC/scripts/mfruit-run" | as_user tee "$OS_HOME/bin/mfruit-run" >/dev/null
as_user chmod 0755 "$OS_HOME/bin/mfruit-run"
sed "s|@MFRUIT_ROOT@|$OS_HOME/system/current|" "$SRC/scripts/mfruitctl" | as_user tee "$OS_HOME/bin/mfruitctl" >/dev/null
as_user chmod 0755 "$OS_HOME/bin/mfruitctl"
ok "helpers in $OS_HOME/bin"

say "Self-test"
if as_user env PYTHONPATH="$OS_HOME/system/current" "$PYTHON" -m mfruitos --self-test; then
  ok "self-test passed"
else
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$CODE_DIR" ]; then
    as_user ln -sfn "$PREVIOUS" "$OS_HOME/system/current"
    fail "self-test failed; previous version restored"
  fi
  fail "self-test failed"
fi

# Keep the two most recent local installs (the updater manages its own).
if [ "$DEV" = 0 ]; then
  ls -1dt "$OS_HOME"/system/versions/*-local* 2>/dev/null | tail -n +3 | while read -r old; do
    [ "$(readlink -f "$old")" = "$(readlink -f "$OS_HOME/system/current")" ] && continue
    [ "$(readlink -f "$old")" = "$PREVIOUS" ] && continue
    case "$old" in "$OS_HOME"/system/versions/*) as_user rm -rf -- "$old" ;; esac
  done
fi

if [ "$INSTALL_SERVICE" = 0 ]; then
  say "Done (no service installed). Start manually with:"
  echo "    PYTHONPATH=$OS_HOME/system/current python3 -m mfruitos"
  exit 0
fi

# ------------------------------------------------------------------ system
say "Installing $SERVICE"
sudo ln -sfn "$OS_HOME/bin/mfruitctl" /usr/local/bin/mfruitctl && ok "/usr/local/bin/mfruitctl"

GROUPS_LIST=""
for g in audio video gpio spi input; do getent group "$g" >/dev/null && GROUPS_LIST="$GROUPS_LIST $g"; done

SUDOERS_TMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TMP"' EXIT
SYSTEMCTL="$(command -v systemctl)"
printf '%s ALL=(root) NOPASSWD: %s restart %s, %s restart %s\n' \
  "$TARGET_USER" "$SYSTEMCTL" "$DAEMON_SERVICE" "$SYSTEMCTL" "$SERVICE" > "$SUDOERS_TMP"
if sudo visudo -cf "$SUDOERS_TMP" >/dev/null; then
  sudo install -o root -g root -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/whisplay-os
  ok "sudoers: only 'systemctl restart' of the daemon and launcher"
fi

sudo tee /etc/systemd/system/$SERVICE >/dev/null <<EOF
[Unit]
Description=MFruit OS - app launcher for Whisplay
Documentation=https://github.com/Mengkungkao/MFruitOS
After=$DAEMON_SERVICE
Wants=$DAEMON_SERVICE
StartLimitIntervalSec=0

[Service]
Type=notify
NotifyAccess=main
User=$TARGET_USER
Group=$TARGET_GROUP
SupplementaryGroups=$GROUPS_LIST
Environment=HOME=$TARGET_HOME
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$OS_HOME/system/current
Environment=XDG_RUNTIME_DIR=/run/user/$TARGET_UID
WorkingDirectory=$OS_HOME/system/current
ExecStartPre=/bin/sh $OS_HOME/bin/boot-guard.sh
ExecStart=$PYTHON -m mfruitos
# If the launcher dies while it owns the screen, ask the daemon to take it back.
ExecStopPost=/bin/sh $OS_HOME/bin/mfruitctl release
Restart=always
RestartSec=3
WatchdogSec=60
TimeoutStartSec=90
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemd-analyze verify /etc/systemd/system/$SERVICE 2>&1 | grep -v "^$" | sed 's/^/    /' || true

DROPIN_DIR="/etc/systemd/system/$DAEMON_SERVICE.d"
if [ "$BACKGROUND_DAEMON" = 1 ] && [ -f "$WHISPLAY_ROOT/daemon/whisplay_daemon.py" ]; then
  say "Running whisplay-daemon's user interface in the background"
  sudo mkdir -p "$DROPIN_DIR"
  DROPIN_TMP="$(mktemp)"
  cat > "$DROPIN_TMP" <<DROPIN
# Installed by MFruit OS. While MFruit OS runs, whisplay-daemon does not draw
# its own desktop and ignores the button when no app owns the screen; the
# hardware, apps and daemon pages are unchanged. Delete this file and run
# "systemctl daemon-reload && systemctl restart whisplay-daemon" to undo.
[Service]
ExecStart=
ExecStart=$PYTHON $OS_HOME/bin/whisplay-daemon-mfruit.py --whisplay $WHISPLAY_ROOT --lock $OS_HOME/state/launcher.lock
DROPIN
  if ! sudo cmp -s "$DROPIN_TMP" "$DROPIN_DIR/mfruit-os.conf"; then
    sudo install -m 0644 "$DROPIN_TMP" "$DROPIN_DIR/mfruit-os.conf"
    RESTART_DAEMON=1
  fi
  rm -f "$DROPIN_TMP"
  ok "$DROPIN_DIR/mfruit-os.conf"
elif [ -f "$DROPIN_DIR/mfruit-os.conf" ]; then
  sudo rm -f "$DROPIN_DIR/mfruit-os.conf"
  ok "whisplay-daemon user interface left in the foreground"
  RESTART_DAEMON=1
fi
sudo systemctl daemon-reload
if [ "${RESTART_DAEMON:-0}" = 1 ]; then
  warn "restarting whisplay-daemon (running apps are closed)"
  sudo systemctl restart "$DAEMON_SERVICE"
fi
sudo systemctl enable "$SERVICE" >/dev/null 2>&1
sudo systemctl restart "$SERVICE"
sleep 4
if systemctl is-active --quiet "$SERVICE"; then
  ok "$SERVICE is running"
else
  warn "$SERVICE is not running; see: journalctl -u $SERVICE -n 50"
fi
systemctl status "$SERVICE" --no-pager -n 5 || true

say "MFruit OS $VERSION installed"
echo "    status:  systemctl status whisplay-os"
echo "    logs:    journalctl -u whisplay-os -f    (or $OS_HOME/logs/)"
echo "    control: mfruitctl help"
