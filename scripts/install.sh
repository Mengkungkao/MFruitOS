#!/usr/bin/env bash
# mFruit OS installer.
#
#   bash scripts/install.sh              install (or upgrade) and start the service
#   bash scripts/install.sh --no-service install files only (no systemd changes)
#   bash scripts/install.sh --dev        run straight from this checkout (development)
#   bash scripts/install.sh --yes        do not ask questions
#   bash scripts/install.sh --no-background-daemon
#                                        keep whisplay-daemon's own user interface
#   bash scripts/install.sh --no-driver  do not install or update the Whisplay driver
#   bash scripts/install.sh --reboot     reboot by itself when the driver needs it
#                                        (otherwise it asks, or with --yes only says so)
#   bash scripts/install.sh --radio      also set up a LoRa radio HAT (scripts/setup-radio.sh:
#                                        packages, UART, dialout, module settings, after
#                                        the reboot by itself) and install the Fruit Store
#                                        apps that need it (RadioConnect)
#   bash scripts/install.sh --no-radio   do not offer the radio setup
#                                        (otherwise it asks; with --yes it is skipped)
#   bash scripts/install.sh --app ID     also install this Fruit Store app and the system
#                                        packages it needs (scripts/setup-app.sh, e.g.
#                                        whisplay-ai-chatbot); repeatable. Without it the
#                                        installer offers such apps (with --yes: skipped)
#   bash scripts/install.sh --no-power   do not install mFruit OS's power management
#                                        (mfruit-power.service and its shutdown hook)
#   bash scripts/install.sh --no-wifi-setup
#                                        do not install Wi-Fi from a phone (PiSugar's
#                                        sugar-wifi-conf, run by mFruit OS on demand)
#
# Run as your normal user (the one whisplay-daemon runs as). sudo is used for
# the Whisplay driver (drivers/whisplay/install.sh: packages, SPI/I2C/I2S
# overlays, sound card module, whisplay-daemon.service; docs/WHISPLAY_DRIVER.md),
# missing Python dependencies, NetworkManager, narrowly scoped polkit/sudoers
# rules, the systemd units (launcher, power management), the power-off
# shutdown hook and /usr/local/bin/mfruitctl link.
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
INSTALL_DRIVER=1
INSTALL_POWER=1
WIFI_SETUP=1
REBOOT_NOW=0
RADIO=ask
DEV=0
ASSUME_YES=0
APPS=()
while [ $# -gt 0 ]; do
  arg="$1"
  case "$arg" in
    --app) [ -n "${2:-}" ] || { echo "--app needs an app id" >&2; exit 2; }; APPS+=("$2"); shift ;;
    --app=*) APPS+=("${arg#--app=}") ;;
    --no-service) INSTALL_SERVICE=0 ;;
    --no-background-daemon) BACKGROUND_DAEMON=0 ;;
    --no-driver) INSTALL_DRIVER=0 ;;
    --no-power) INSTALL_POWER=0 ;;
    --no-wifi-setup) WIFI_SETUP=0 ;;
    --reboot) REBOOT_NOW=1 ;;
    --radio) RADIO=1 ;;
    --no-radio) RADIO=0 ;;
    --dev) DEV=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }
fail() { printf '    \033[0;31mxx\033[0m  %s\n' "$*"; exit 1; }
as_user() { if [ "$(id -un)" = "$TARGET_USER" ]; then "$@"; else sudo -u "$TARGET_USER" "$@"; fi; }
TMP_FILES=()
cleanup() { if [ "${#TMP_FILES[@]}" -gt 0 ]; then rm -f -- "${TMP_FILES[@]}"; fi; }
trap cleanup EXIT

if [ "$TARGET_USER" = "root" ]; then
  fail "run this as your normal user (the whisplay-daemon user), not root"
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/mfruitos/__init__.py")"
say "mFruit OS $VERSION for user $TARGET_USER"

# ------------------------------------------------------------------ checks
say "Checking system"
OFFLINE_PACK="$(bash "$SRC/scripts/offline.sh" find 2>/dev/null || true)"
[ -z "$OFFLINE_PACK" ] || ok "offline pack: $OFFLINE_PACK (packages and the sound card build need no internet)"
[ "$(uname -s)" = "Linux" ] || fail "mFruit OS needs Linux"
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
  sudo bash "$SRC/scripts/offline.sh" install python3-pil || fail "could not install Pillow"
fi
PIL_VERSION="$("$PYTHON" -c 'import PIL; print(PIL.__version__)')"
# Pillow 9.0 (Ubuntu 22.04's) is the oldest tested; 8.1 (Debian 11, Raspberry Pi
# OS Bullseye) lacks the rounded rectangles every screen is drawn with.
"$PYTHON" - "$PIL_VERSION" <<'PY' || fail "Pillow 9.0 or newer is required; this system has $PIL_VERSION (Debian 11 / Raspberry Pi OS Bullseye are not supported)"
import re, sys
match = re.match(r"(\d+)\.(\d+)", sys.argv[1])
sys.exit(0 if match and (int(match.group(1)), int(match.group(2))) >= (9, 0) else 1)
PY
ok "Pillow $PIL_VERSION"
if ! "$PYTHON" -c "import venv, ensurepip" 2>/dev/null; then
  warn "Python venv support missing; installing python3-venv"
  sudo bash "$SRC/scripts/offline.sh" install python3-venv || fail "python3-venv is required for App installer"
  "$PYTHON" -c "import venv, ensurepip" 2>/dev/null || fail "venv support is still unavailable in $PYTHON"
fi
command -v git >/dev/null && ok "git (updates for git-installed apps)" || warn "git not found: git-tracked app updates disabled"
command -v aplay >/dev/null && ok "aplay (speaker test)" || warn "aplay not found: speaker test disabled"

say "Whisplay driver"
DRIVER_DIR=/usr/local/share/whisplay
REBOOT_REQUIRED=0
AUDIO_FAILED=0
if [ "$INSTALL_SERVICE" = 0 ] || [ "$INSTALL_DRIVER" = 0 ]; then
  warn "driver not installed or updated (--no-service or --no-driver)"
else
  DRIVER_RC=0
  sudo bash "$SRC/drivers/whisplay/install.sh" --user "$TARGET_USER" --restart-later || DRIVER_RC=$?
  case "$DRIVER_RC" in
    0)
      STATUS=/run/mfruitos/whisplay-driver.status
      [ "$(sed -n 's/^REBOOT_REQUIRED=//p' "$STATUS" 2>/dev/null)" = 1 ] && REBOOT_REQUIRED=1
      [ "$(sed -n 's/^DAEMON_CHANGED=//p' "$STATUS" 2>/dev/null)" = 1 ] && RESTART_DAEMON=1
      [ "$(sed -n 's/^AUDIO_FAILED=//p' "$STATUS" 2>/dev/null)" = 1 ] && AUDIO_FAILED=1
      ok "Whisplay driver ($DRIVER_DIR)" ;;
    3) warn "no supported Whisplay board detected; the Whisplay driver was not installed" ;;
    *) fail "Whisplay driver installation failed (messages above; docs/WHISPLAY_DRIVER.md)" ;;
  esac
fi
WHISPLAY_ROOT=""
if command -v systemctl >/dev/null && systemctl cat "$DAEMON_SERVICE" >/dev/null 2>&1; then
  WHISPLAY_ROOT="$(systemctl show -p WorkingDirectory "$DAEMON_SERVICE" | cut -d= -f2)"
  ok "$DAEMON_SERVICE installed ($(systemctl is-active "$DAEMON_SERVICE" || true))"
else
  warn "$DAEMON_SERVICE not found (the Whisplay driver installs it on a supported board)"
fi
[ -n "$WHISPLAY_ROOT" ] || WHISPLAY_ROOT="$DRIVER_DIR"
if [ -f "$WHISPLAY_ROOT/runtime/whisplay.py" ]; then ok "Whisplay runtime at $WHISPLAY_ROOT"
else warn "Whisplay runtime not found (daemon-down fallback display disabled)"; fi
if [ -S "$SOCKET" ]; then ok "daemon socket $SOCKET"; else warn "daemon socket not present yet"; fi

# ------------------------------------------------------------------ files
# Capture first-install status before defaults and the current symlink exist.
FIRST_INSTALL=0
if [ ! -e "$OS_HOME/config/settings.json" ] && [ ! -e "$OS_HOME/system/current" ] \
    && [ ! -L "$OS_HOME/system/current" ]; then
  FIRST_INSTALL=1
fi
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
  for item in mfruitos assets config scripts templates docs bundled drivers manifest.json LICENSE README.md \
      APP_DEVELOPMENT.md INSTALL.md CHANGELOG.md CONTRIBUTING.md; do
    [ -e "$SRC/$item" ] && ITEMS+=("$item")
  done
  (cd "$SRC" && tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' -cf - "${ITEMS[@]}") \
    | as_user tar -xf - -C "$CODE_DIR"
  ok "code: $CODE_DIR"
fi
# Only an existing link: readlink -f also answers for a missing "current"
# (its folder exists), and that name was then "restored" as a self-loop.
PREVIOUS=""
if [ -e "$OS_HOME/system/current" ]; then
  PREVIOUS="$(readlink -f "$OS_HOME/system/current" 2>/dev/null || true)"
fi
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
  # A first installation: there is nothing to go back to, so nothing stays active.
  as_user rm -f "$OS_HOME/system/current"
  fail "self-test failed; nothing was activated"
fi

# Record local installs too, so Settings can roll back without a GitHub release.
as_user env PYTHONPATH="$CODE_DIR" "$PYTHON" - "$OS_HOME" "$CODE_DIR" "$PREVIOUS" <<'PY'
import os
import sys
from mfruitos.apps.manifest import load_manifest
from mfruitos.paths import is_within
from mfruitos.system.settings import atomic_write_json

home, current, previous = sys.argv[1:]
manifest = load_manifest(current)
versions = os.path.join(home, "system", "versions")
if not previous or previous == current or not is_within(previous, versions):
    previous = ""
previous_version = load_manifest(previous).version if previous else ""
atomic_write_json(os.path.join(home, "system", "app.json"), {
    "id": manifest.id, "name": manifest.name, "installed_version": manifest.version,
    "installed_dir": current, "previous_dir": previous, "previous_version": previous_version,
    "repository": manifest.repository, "source": "local",
})
PY

# Wi-Fi is an offline OS component; do not depend on a second manual clone.
PROVISION_ARGS=()
if [ "$FIRST_INSTALL" = 1 ]; then PROVISION_ARGS+=(--first-install); fi
as_user env PYTHONPATH="$CODE_DIR" "$PYTHON" -m mfruitos.provision \
  --home "$OS_HOME" --daemon-home "$TARGET_HOME/.whisplay-daemon" --whisplay "$WHISPLAY_ROOT" "${PROVISION_ARGS[@]}"

# Wi-Fi from a phone (docs/platform/ADR/0013-phone-wifi-setup.md): PiSugar's
# sugar-wifi-conf, one pinned release checked by SHA-256, from the offline pack
# or GitHub, into the OS home. It runs as the user only while wanted (Settings
# > Wi-Fi > Phone Setup); nothing here needs root.
if [ "$WIFI_SETUP" = 1 ]; then
  say "Wi-Fi from a phone (PiSugar sugar-wifi-conf)"
  WS_ARGS=(--home "$OS_HOME" install)
  [ -z "$OFFLINE_PACK" ] || WS_ARGS+=(--offline "$OFFLINE_PACK")
  if WS_OUT="$(as_user env PYTHONPATH="$CODE_DIR" "$PYTHON" -m mfruitos.system.wifi_setup "${WS_ARGS[@]}" 2>&1)"; then
    ok "$(echo "$WS_OUT" | tail -n 1)"
  else
    warn "$(echo "$WS_OUT" | tail -n 1); Settings > Wi-Fi > Phone Setup stays unavailable until this installer runs again with internet or an offline pack"
  fi
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
  [ "$RADIO" != 1 ] || warn "--radio is skipped with --no-service; run: bash $OS_HOME/system/current/scripts/setup-radio.sh"
  exit 0
fi

# ------------------------------------------------------------------ system
say "Installing $SERVICE"
sudo ln -sfn "$OS_HOME/bin/mfruitctl" /usr/local/bin/mfruitctl && ok "/usr/local/bin/mfruitctl"

# The launcher is a system service without an interactive polkit session.
# Permit only NetworkManager Wi-Fi actions for this installation's user.
if ! command -v nmcli >/dev/null; then
  sudo bash "$SRC/scripts/offline.sh" install network-manager || fail "NetworkManager is required for Settings > Wi-Fi"
  command -v nmcli >/dev/null || fail "nmcli is still unavailable after installing NetworkManager"
fi
# >>> wifi permission
sudo mkdir -p /etc/polkit-1/rules.d
POLKIT_TMP="$(mktemp)"
TMP_FILES+=("$POLKIT_TMP")
"$PYTHON" - "$TARGET_USER" > "$POLKIT_TMP" <<'PYRULE'
import json, sys
user = json.dumps(sys.argv[1])
print('polkit.addRule(function(action, subject) {')
print('  if (subject.user === ' + user + ' && [')
for action in ['wifi.scan', 'network-control', 'settings.modify.system', 'enable-disable-wifi']:
    print('    "org.freedesktop.NetworkManager.' + action + '",')
print('  ].indexOf(action.id) !== -1) return polkit.Result.YES;')
print('});')
PYRULE
sudo install -m 0644 "$POLKIT_TMP" /etc/polkit-1/rules.d/49-mfruit-wifi.rules
# polkit before 0.106 (Ubuntu 22.04, Debian 11) ignores JavaScript rules and
# reads .pkla files only; Debian's polkitd-pkla package adds .pkla support to
# newer versions. Write the same grant as a .pkla wherever one is read.
POLKIT_VERSION="$(pkaction --version 2>/dev/null | awk '{ print $NF }' || true)"
POLKIT_PKLA=/etc/polkit-1/localauthority/50-local.d/49-mfruit-wifi.pkla
if { [ -n "$POLKIT_VERSION" ] && [ "$(printf '%s\n' "$POLKIT_VERSION" 0.106 | sort -V | head -n 1)" != 0.106 ]; } \
    || [ -d /etc/polkit-1/localauthority ]; then
  if "$PYTHON" - "$TARGET_USER" > "$POLKIT_TMP" <<'PYPKLA'
import re, sys
user = sys.argv[1]
if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]*[$]?", user):
    sys.exit(1)   # no quoting exists in .pkla files
print("[mFruit OS: Wi-Fi settings for " + user + "]")
print("Identity=unix-user:" + user)
print("Action=" + ";".join("org.freedesktop.NetworkManager." + action for action in
      ["wifi.scan", "network-control", "settings.modify.system", "enable-disable-wifi"]))
print("ResultAny=yes")
print("ResultInactive=yes")
print("ResultActive=yes")
PYPKLA
  then
    sudo mkdir -p "$(dirname "$POLKIT_PKLA")"
    sudo install -m 0644 "$POLKIT_TMP" "$POLKIT_PKLA"
    ok "polkit ${POLKIT_VERSION:-?}: Wi-Fi permission also as $POLKIT_PKLA"
  else
    warn "user name $TARGET_USER cannot be written to a polkit .pkla file; Settings > Wi-Fi may be refused"
  fi
fi
rm -f "$POLKIT_TMP"
# <<< wifi permission

# >>> wifi checks
# Whether NetworkManager now lets this user scan and join from outside a login
# session, as the launcher runs (a systemd --user unit has no session either).
NM_PERMS="$(as_user timeout 20 systemd-run --user --pipe --wait --quiet \
            nmcli -t -f permission,value general permissions 2>/dev/null || true)"
if [ -n "$NM_PERMS" ]; then
  if echo "$NM_PERMS" | grep -qx 'org.freedesktop.NetworkManager.wifi.scan:yes' \
      && echo "$NM_PERMS" | grep -qx 'org.freedesktop.NetworkManager.network-control:yes'; then
    ok "NetworkManager lets mFruit OS scan and join Wi-Fi (checked outside a login session)"
  else
    warn "NetworkManager refuses Wi-Fi scans or joins outside a login session (polkit ${POLKIT_VERSION:-?}): Settings > Wi-Fi will not work; docs/quality/TROUBLESHOOTING.md"
  fi
fi
# Ubuntu Server, also for Raspberry Pi, leaves Wi-Fi to netplan and
# systemd-networkd, and netplan marks that interface unmanaged for
# NetworkManager. Settings > Wi-Fi cannot change it then; say how to hand it over.
WIFI_UNMANAGED="$(nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null \
                  | awk -F: '$2 == "wifi" && $3 == "unmanaged" { printf "%s ", $1 }' || true)"
if [ -n "$WIFI_UNMANAGED" ]; then
  warn "NetworkManager does not manage ${WIFI_UNMANAGED% }: Settings > Wi-Fi cannot scan or join with it"
  if [ -d /etc/netplan ]; then
    warn "netplan gives it to systemd-networkd. To give it to NetworkManager (the configured network is kept):"
    echo "        printf 'network:\\n  version: 2\\n  renderer: NetworkManager\\n' | sudo tee /etc/netplan/90-networkmanager.yaml"
    echo "        sudo chmod 600 /etc/netplan/90-networkmanager.yaml && sudo netplan generate && sudo reboot"
    echo "    (docs/platform/INSTALLATION.md#ubuntu-server-wi-fi-and-netplan)"
  fi
fi
# <<< wifi checks

# A fresh Raspberry Pi OS image can start with Bluetooth soft-blocked (rfkill),
# and Settings > Bluetooth then fails with org.bluez.Error.Failure. Lift that on
# the first install only (a later block is the user's choice); systemd-rfkill
# keeps the state across reboots. Settings also lifts it when turning Bluetooth on.
if [ "$FIRST_INSTALL" = 1 ]; then
  for RFKILL in /sys/class/rfkill/rfkill*; do
    [ "$(cat "$RFKILL/type" 2>/dev/null)" = bluetooth ] && [ "$(cat "$RFKILL/soft" 2>/dev/null)" = 1 ] || continue
    echo 0 | sudo tee "$RFKILL/soft" >/dev/null && ok "Bluetooth unblocked ($(cat "$RFKILL/name"))"
  done
fi

# >>> service groups
# Groups the launcher gets on top of the user's own: the LCD and button (SPI,
# GPIO) for the fallback screen, sound and input. Only existing groups may be
# listed: systemd refuses a unit naming a missing one (216/GROUP). Ubuntu for
# Raspberry Pi has no gpio group and gives SPI, GPIO and I2C to dialout.
GROUPS_LIST=""
for g in audio video gpio spi input; do getent group "$g" >/dev/null && GROUPS_LIST="$GROUPS_LIST $g"; done
if ! getent group gpio >/dev/null && getent group dialout >/dev/null; then GROUPS_LIST="$GROUPS_LIST dialout"; fi
# <<< service groups

SUDOERS_TMP="$(mktemp)"
TMP_FILES+=("$SUDOERS_TMP")
SYSTEMCTL="$(command -v systemctl)"
# poweroff/reboot: the power service's safe shutdown (low battery, the power
# button) also works when the Whisplay driver's Power page rule is absent.
printf '%s ALL=(root) NOPASSWD: %s restart %s, %s restart %s, %s poweroff, %s reboot\n' \
  "$TARGET_USER" "$SYSTEMCTL" "$DAEMON_SERVICE" "$SYSTEMCTL" "$SERVICE" "$SYSTEMCTL" "$SYSTEMCTL" \
  > "$SUDOERS_TMP"
if sudo visudo -cf "$SUDOERS_TMP" >/dev/null; then
  sudo install -o root -g root -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/whisplay-os
  ok "sudoers: only 'systemctl restart' of the daemon and launcher, poweroff and reboot"
fi

sudo tee /etc/systemd/system/$SERVICE >/dev/null <<EOF
[Unit]
Description=mFruit OS - app launcher for Whisplay
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
  TMP_FILES+=("$DROPIN_TMP")
  cat > "$DROPIN_TMP" <<DROPIN
# Installed by mFruit OS. While mFruit OS runs, whisplay-daemon does not draw
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
# ------------------------------------------------------------------ power
# mFruit OS's own power management (docs/platform/ADR/0012-own-power-management.md).
# mfruit-power.service drives a PiSugar battery board over I2C as the user,
# with the i2c group and CAP_SYS_TIME (only to move the clock forward from the
# board's clock at boot). It starts before the daemon, which looks for the
# PiSugar socket once at start. The root-owned shutdown hook switches the
# board off after a power-off, when nothing is mounted read-write any more.
# PiSugar's own services drive the same board, so they are stopped and
# disabled; scripts/uninstall.sh enables them again.
POWER_SERVICE=mfruit-power.service
POWER_HOOK_DIR=/usr/lib/systemd/system-shutdown
[ -d "$POWER_HOOK_DIR" ] || POWER_HOOK_DIR=/lib/systemd/system-shutdown
RESTART_POWER=0
if [ "$INSTALL_POWER" = 1 ]; then
  say "Power management ($POWER_SERVICE)"
  # >>> power groups
  # The group that owns /dev/i2c-* (i2c on Raspberry Pi OS and Orange Pi OS,
  # dialout on Ubuntu for Raspberry Pi); before the bus exists, the usual one.
  POWER_GROUPS="$(stat -c %G /dev/i2c-[0-9]* 2>/dev/null | grep -vx root | head -n 1 || true)"
  if [ -z "$POWER_GROUPS" ]; then
    if getent group i2c >/dev/null; then POWER_GROUPS=i2c
    elif getent group dialout >/dev/null; then POWER_GROUPS=dialout; fi
  fi
  # <<< power groups
  [ -n "$POWER_GROUPS" ] || warn "no i2c group: the power service may not reach /dev/i2c-*"
  # /dev/i2c-N comes from the kernel's i2c-dev module. Turning the bus on in the
  # boot config (dtparam=i2c_arm=on, as the Whisplay driver does) does not load
  # it on Raspberry Pi OS; only raspi-config's I2C switch lists it in
  # /etc/modules. So it is loaded now and listed for every boot; uninstall.sh
  # removes the list file and leaves the module loaded.
  I2C_DEV_CONF=/etc/modules-load.d/mfruit-power.conf
  I2C_MODULE_LISTS="/etc/modules /etc/modules-load.d/*.conf"
  # >>> i2c-dev
  if sudo modprobe i2c-dev 2>/dev/null; then
    # shellcheck disable=SC2086  # the second list is a glob
    if grep -qsE '^[[:space:]]*i2c[-_]dev([[:space:]]|$)' $I2C_MODULE_LISTS; then
      ok "i2c-dev kernel module loaded (already loaded at boot)"
    else
      echo i2c-dev | sudo tee "$I2C_DEV_CONF" >/dev/null
      ok "i2c-dev kernel module loaded, and at every boot ($I2C_DEV_CONF), for /dev/i2c-*"
    fi
  else
    warn "could not load the i2c-dev kernel module: the power service cannot open /dev/i2c-*"
  fi
  # <<< i2c-dev
  PISUGAR_DISABLED="$OS_HOME/state/pisugar-services-disabled"
  for unit in pisugar-server.service pisugar-poweroff.service; do
    if systemctl is-enabled --quiet "$unit" 2>/dev/null || systemctl is-active --quiet "$unit" 2>/dev/null; then
      sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
      grep -qx "$unit" "$PISUGAR_DISABLED" 2>/dev/null || echo "$unit" | as_user tee -a "$PISUGAR_DISABLED" >/dev/null
      ok "PiSugar's $unit stopped and disabled (mFruit OS drives the battery board now)"
    fi
  done
  POWER_TMP="$(mktemp)"
  TMP_FILES+=("$POWER_TMP")
  cat > "$POWER_TMP" <<EOF
[Unit]
Description=mFruit OS - power management (battery board, safe shutdown)
Documentation=https://github.com/Mengkungkao/MFruitOS
Before=$DAEMON_SERVICE $SERVICE
StartLimitIntervalSec=0

[Service]
Type=notify
NotifyAccess=main
User=$TARGET_USER
Group=$TARGET_GROUP
SupplementaryGroups=$POWER_GROUPS
AmbientCapabilities=CAP_SYS_TIME
Environment=HOME=$TARGET_HOME
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$OS_HOME/system/current
WorkingDirectory=$OS_HOME/system/current
ExecStart=$PYTHON -m mfruitos.power serve
Restart=always
RestartSec=3
WatchdogSec=60
TimeoutStartSec=20
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF
  if ! sudo cmp -s "$POWER_TMP" "/etc/systemd/system/$POWER_SERVICE"; then
    sudo install -m 0644 "$POWER_TMP" "/etc/systemd/system/$POWER_SERVICE"
  fi
  sudo systemd-analyze verify "/etc/systemd/system/$POWER_SERVICE" 2>&1 | grep -v "^$" | sed 's/^/    /' || true
  HOOK_TMP="$(mktemp)"
  TMP_FILES+=("$HOOK_TMP")
  sed "s|@POWER_CONFIG@|$OS_HOME/config/power.json|" "$SRC/scripts/mfruit-power-off" > "$HOOK_TMP"
  sudo install -D -o root -g root -m 0755 "$HOOK_TMP" "$POWER_HOOK_DIR/mfruit-power-off"
  ok "shutdown hook $POWER_HOOK_DIR/mfruit-power-off (the battery board switches off after a power-off)"
  RESTART_POWER=1
fi

# PiSugar's own installer runs sugar-wifi-conf as an always-on root service with
# the default key; mFruit OS runs the same tool on demand as the user, so that
# service is stopped and disabled (scripts/uninstall.sh enables it again).
if [ "$WIFI_SETUP" = 1 ]; then
  for unit in sugar-wifi-config.service; do
    if systemctl is-enabled --quiet "$unit" 2>/dev/null || systemctl is-active --quiet "$unit" 2>/dev/null; then
      sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
      PISUGAR_DISABLED="$OS_HOME/state/pisugar-services-disabled"
      grep -qx "$unit" "$PISUGAR_DISABLED" 2>/dev/null || echo "$unit" | as_user tee -a "$PISUGAR_DISABLED" >/dev/null
      ok "PiSugar's $unit stopped and disabled (mFruit OS runs Wi-Fi from a phone on demand)"
    fi
  done
fi

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" >/dev/null 2>&1
[ "$RESTART_POWER" = 0 ] || sudo systemctl enable "$POWER_SERVICE" >/dev/null 2>&1

# Radio apps need a LoRa HAT set up (packages, UART, dialout, module settings).
# setup-radio.sh owns that; it stops before provisioning when a reboot is due.
RADIO_SCRIPT="$OS_HOME/system/current/scripts/setup-radio.sh"
[ -f "$RADIO_SCRIPT" ] || RADIO_SCRIPT="$SRC/scripts/setup-radio.sh"
RADIO_PENDING=0
# Python with the installed mFruit OS (Fruit Store list, install queue).
os_py() { as_user env PYTHONPATH="$OS_HOME/system/current" python3 "$@"; }
# Fruit Store apps that need the radio, e.g. "RadioConnect" (updater/autoinstall.py).
RADIO_APPS="$(os_py -c 'from mfruitos.updater import autoinstall, catalog
ids = autoinstall.needing("radio")
print(", ".join(i["name"] for i in catalog.entries() if i["id"] in ids))' 2>/dev/null || true)"
if [ "$RADIO" = ask ]; then
  RADIO=0
  if [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
    read -r -p "    Set up a LoRa radio HAT${RADIO_APPS:+ and install $RADIO_APPS}? [y/N] " answer || answer=n
    case "$answer" in [yY]*) RADIO=1 ;; esac
  fi
fi
if [ "$RADIO" = 1 ]; then
  say "LoRa radio"
  RADIO_ARGS=(--no-reboot)
  [ "$ASSUME_YES" = 0 ] || RADIO_ARGS+=(--yes)
  radio_status=0
  as_user bash "$RADIO_SCRIPT" "${RADIO_ARGS[@]}" || radio_status=$?
  case "$radio_status" in
    0) ok "radio set up" ;;
    3) REBOOT_REQUIRED=1; RADIO_PENDING=1 ;;
    *) warn "radio setup incomplete; run it again later: bash $RADIO_SCRIPT" ;;
  esac
  if [ -n "$RADIO_APPS" ]; then
    # The launcher installs them once the radio is ready and the network is up.
    if queued="$(os_py -m mfruitos.updater.autoinstall add --requires radio --home "$OS_HOME")"; then
      ok "queued for installation: $queued (the device installs them by itself)"
    else
      warn "could not queue $RADIO_APPS; install from the Fruit Store"
    fi
  fi
else
  echo "    LoRa radio not set up; for RadioConnect run: bash $RADIO_SCRIPT"
fi

# Fruit Store apps that need system packages (e.g. AI Chatbot): setup-app.sh
# installs the packages with sudo and queues the apps; the launcher installs them.
APP_SCRIPT="$OS_HOME/system/current/scripts/setup-app.sh"
[ -f "$APP_SCRIPT" ] || APP_SCRIPT="$SRC/scripts/setup-app.sh"
if [ "${#APPS[@]}" -eq 0 ] && [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
  while IFS=$'\t' read -r app_id app_name; do
    [ -n "$app_id" ] || continue
    read -r -p "    Install $app_name (needs system packages)? [y/N] " answer </dev/tty || answer=n
    case "$answer" in [yY]*) APPS+=("$app_id") ;; esac
  done < <(os_py - "$OS_HOME" <<'PY' 2>/dev/null || true
import os, sys
from mfruitos.updater import catalog
home = sys.argv[1]
for item in catalog.entries(home):
    if catalog.system_packages(item) and \
            not os.path.exists(os.path.join(home, "apps", item["id"], "current")):
        print(f"{item['id']}\t{item['name']}")
PY
)
fi
if [ "${#APPS[@]}" -gt 0 ]; then
  say "Fruit Store apps: ${APPS[*]}"
  as_user bash "$APP_SCRIPT" --yes "${APPS[@]}" \
    || warn "app setup incomplete; run it again later: bash $APP_SCRIPT ${APPS[*]}"
fi

if [ "$REBOOT_REQUIRED" = 1 ]; then
  # The display bus and sound card appear only after a reboot; both services
  # are enabled and start then.
  say "mFruit OS $VERSION installed; reboot to finish the setup"
  [ "$AUDIO_FAILED" = 0 ] || warn "no sound card yet: rerun this installer with internet or an offline pack (docs/WHISPLAY_DRIVER.md)"
  echo "    After the reboot mFruit OS starts by itself. To check it: bash $SRC/scripts/setup-device.sh --check"
  if [ "$RADIO_PENDING" = 1 ] && [ -f /etc/systemd/system/mfruit-radio-setup.service ]; then
    echo "    After the reboot the radio settings are written by themselves${RADIO_APPS:+, then $RADIO_APPS installs}."
  elif [ "$RADIO_PENDING" = 1 ]; then
    echo "    After the reboot finish the radio (writes the module settings): bash $RADIO_SCRIPT"
  fi
  if [ "$REBOOT_NOW" = 0 ] && [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
    read -r -p "    Reboot now? [Y/n] " answer || answer=n
    case "$answer" in [nN]*) ;; *) REBOOT_NOW=1 ;; esac
  fi
  if [ "$REBOOT_NOW" = 1 ]; then
    say "Rebooting"
    sudo systemctl reboot
  else
    echo "    Reboot when ready: sudo reboot"
  fi
  exit 0
fi
# The power service first: the daemon looks for its PiSugar socket at start.
[ "$RESTART_POWER" = 0 ] || sudo systemctl restart "$POWER_SERVICE"
if [ "${RESTART_DAEMON:-0}" = 1 ]; then
  warn "restarting whisplay-daemon (running apps are closed)"
  sudo systemctl restart "$DAEMON_SERVICE"
fi
sudo systemctl restart "$SERVICE"
sleep 4
if systemctl is-active --quiet "$SERVICE"; then
  ok "$SERVICE is running"
else
  warn "$SERVICE is not running; see: journalctl -u $SERVICE -n 50"
fi
if [ "$RESTART_POWER" = 1 ]; then
  if systemctl is-active --quiet "$POWER_SERVICE"; then
    POWER_STATE="$(as_user env PYTHONPATH="$OS_HOME/system/current" WHISPLAY_OS_HOME="$OS_HOME" "$PYTHON" -c '
from mfruitos import power
from mfruitos.paths import resolve_paths
from mfruitos.power.client import PowerClient
status = PowerClient(power.api_socket(resolve_paths())).status()
print(status["model"] or status["error"])' 2>/dev/null || true)"
    ok "$POWER_SERVICE is running${POWER_STATE:+: $POWER_STATE}"
  else
    warn "$POWER_SERVICE is not running; see: journalctl -u $POWER_SERVICE -n 50"
  fi
fi
systemctl status "$SERVICE" --no-pager -n 5 || true

say "mFruit OS $VERSION installed"
[ "$AUDIO_FAILED" = 0 ] || warn "no sound card yet: rerun this installer with internet or an offline pack (docs/WHISPLAY_DRIVER.md)"
echo "    status:  systemctl status whisplay-os"
echo "    logs:    journalctl -u whisplay-os -f    (or $OS_HOME/logs/)"
echo "    control: mfruitctl help"
