#!/usr/bin/env bash
# setup-radio.sh -- one-time LoRa radio setup for MFruit OS radio apps
# (WalkieTalkie, Messenger, ...) on a Waveshare SX126X HAT.
#
#   bash setup-radio.sh                 check, then fix what is missing (asks first)
#   bash setup-radio.sh --check         report only; change nothing
#   bash setup-radio.sh --yes           accept every prompt
#   bash setup-radio.sh --no-reboot     never reboot; exit 3 when a reboot is due
#   bash setup-radio.sh --band au915    au915 (default), eu868 or us915
#   bash setup-radio.sh --frequency 920 MHz inside the band (default: its middle)
#   bash setup-radio.sh --air-speed 2400
#   bash setup-radio.sh --board raspberrypi|orangepi   skip board detection
#
# Run as your normal user; sudo is used for system packages, the UART and
# serial-console settings, the dialout group and provisioning the module
# (which stops whisplay-daemon for a few seconds). Every radio must use the
# same band, frequency and air rate. Steps that need a reboot say so and
# stop; run the script again afterwards -- it skips what is already done.
# Documentation: docs/platform/INSTALLATION.md ("Radio setup").
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OS_HOME="${WHISPLAY_OS_HOME:-$HOME/.whisplay-os}"
PORT=/dev/ttyS0
BAND=au915
FREQUENCY=""
AIR_SPEED=2400
BOARD=""
CHECK_ONLY=0
ASSUME_YES=0
NO_REBOOT=0
NEED_REBOOT=0
FAILED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --no-reboot) NO_REBOOT=1 ;;
    --band) BAND="${2:-}"; shift ;;
    --frequency) FREQUENCY="${2:-}"; shift ;;
    --air-speed) AIR_SPEED="${2:-}"; shift ;;
    --board) BOARD="${2:-}"; shift ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }
bad()  { printf '    \033[0;31mfail\033[0m %s\n' "$*"; FAILED=1; }
info() { printf '        %s\n' "$*"; }
ask() {
  [ "$CHECK_ONLY" = 1 ] && return 1
  [ "$ASSUME_YES" = 1 ] && return 0
  local reply; read -r -p "        $1 [y/N] " reply; [[ "$reply" =~ ^[Yy] ]]
}

[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user, not root (sudo is used where needed)." >&2; exit 2; }
case "$BAND" in au915|eu868|us915) ;; *) echo "unknown band: $BAND" >&2; exit 2 ;; esac
PY() { PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"; }

# ------------------------------------------------------------------ 1. host
say "Checking the host"
if [ -z "$BOARD" ]; then
  MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)
  case "$MODEL" in
    *"Raspberry Pi"*) BOARD=raspberrypi ;;
    *[Oo]range*[Pp]i*) BOARD=orangepi ;;
  esac
fi
case "$BOARD" in
  raspberrypi|orangepi) ok "board: $BOARD" ;;
  *) echo "Cannot tell which board this is; pass --board raspberrypi or --board orangepi." >&2; exit 2 ;;
esac
[ -f "$ROOT/mfruitos/hosts/lora/__main__.py" ] || { echo "MFruit OS code not found under $ROOT" >&2; exit 2; }
ok "MFruit OS code: $ROOT; data: $OS_HOME"

# -------------------------------------------------------------- 2. packages
say "System packages"
codec2_package() {
  local pkg
  for pkg in libcodec2-1.2 libcodec2-1.0; do
    dpkg -s "$pkg" >/dev/null 2>&1 && { echo "$pkg"; return; }
  done
  for pkg in libcodec2-1.2 libcodec2-1.0; do
    apt-cache show "$pkg" >/dev/null 2>&1 && { echo "$pkg"; return; }
  done
  echo libcodec2-1.2
}
PACKAGES=(python3-serial python3-cryptography python3-numpy python3-yaml alsa-utils gpiod
          python3-libgpiod "$(codec2_package)")
MISSING=()
for pkg in "${PACKAGES[@]}"; do dpkg -s "$pkg" >/dev/null 2>&1 || MISSING+=("$pkg"); done
if [ "${#MISSING[@]}" -eq 0 ]; then
  ok "installed: ${PACKAGES[*]}"
else
  warn "missing: ${MISSING[*]}"
  if ask "install them with apt?"; then
    sudo apt-get update -qq && sudo apt-get install -y "${MISSING[@]}" \
      && ok "installed" || bad "apt-get install failed"
  else
    bad "install them: sudo apt-get install ${MISSING[*]}"
  fi
fi

# ------------------------------------------------------------------ 3. UART
say "Serial port for the LoRa HAT ($PORT)"
if [ "$BOARD" = raspberrypi ]; then
  BOOT_CONFIG=/boot/firmware/config.txt; [ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
  BOOT_CMDLINE=/boot/firmware/cmdline.txt; [ -f "$BOOT_CMDLINE" ] || BOOT_CMDLINE=/boot/cmdline.txt
  if grep -qE '^\s*enable_uart=1' "$BOOT_CONFIG" 2>/dev/null; then
    ok "enable_uart=1 in $BOOT_CONFIG"
  elif ask "add enable_uart=1 to $BOOT_CONFIG (needs a reboot)?"; then
    sudo cp -n "$BOOT_CONFIG" "$BOOT_CONFIG.mfruit.bak"
    echo "enable_uart=1" | sudo tee -a "$BOOT_CONFIG" >/dev/null && ok "added" && NEED_REBOOT=1
  else
    bad "the LoRa HAT needs the UART: enable_uart=1 in $BOOT_CONFIG"
  fi
  if grep -qE 'console=(serial0|ttyS0|ttyAMA0)' "$BOOT_CMDLINE" 2>/dev/null; then
    warn "a kernel console shares the LoRa port ($BOOT_CMDLINE); it corrupts every packet"
    if ask "remove the serial console from $BOOT_CMDLINE (needs a reboot)?"; then
      sudo cp -n "$BOOT_CMDLINE" "$BOOT_CMDLINE.mfruit.bak"
      sudo sed -i -E 's/console=(serial0|ttyS0|ttyAMA0),[0-9]+ ?//g' "$BOOT_CMDLINE" \
        && ok "removed (backup: $BOOT_CMDLINE.mfruit.bak)" && NEED_REBOOT=1
    else
      bad "the radio is unreliable while a console shares the port"
    fi
  else
    ok "no serial console on the LoRa port"
  fi
  GETTY="$(systemctl is-enabled serial-getty@ttyS0.service 2>/dev/null || true)"
  if [ "$GETTY" = enabled ] && ask "disable the serial login on ttyS0?"; then
    sudo systemctl disable --now serial-getty@ttyS0.service >/dev/null 2>&1 && ok "disabled"
  else
    ok "serial login on ttyS0: ${GETTY:-not enabled}"
  fi
else
  BOOT_ENV=/boot/orangepiEnv.txt; [ -f "$BOOT_ENV" ] || BOOT_ENV=/boot/armbianEnv.txt
  BOOT_CMD="$(dirname "$BOOT_ENV")/boot.cmd"
  # Orange Pi OS's boot script puts ttyS0 on the command line for "display"
  # too; only a value it ignores keeps the console off the LoRa port.
  if grep -qE '"display".*console=ttyS0' "$BOOT_CMD" 2>/dev/null; then
    WANT_CONSOLE=none; WANT_EXTRA=console=tty1
  else
    WANT_CONSOLE=display; WANT_EXTRA=""
  fi
  set_env() {
    if grep -q "^$1=" "$BOOT_ENV"; then sudo sed -i "s|^$1=.*|$1=$2|" "$BOOT_ENV"
    else echo "$1=$2" | sudo tee -a "$BOOT_ENV" >/dev/null; fi
  }
  if [ ! -f "$BOOT_ENV" ]; then
    bad "neither /boot/orangepiEnv.txt nor /boot/armbianEnv.txt exists; move the console off ttyS0 by hand"
  else
    CONSOLE=$(sed -n 's/^console=//p' "$BOOT_ENV" | tail -1)
    EXTRA=$(sed -n 's/^extraargs=//p' "$BOOT_ENV" | tail -1)
    EXTRA_OK=1
    if [ -n "$WANT_EXTRA" ] && ! printf ' %s ' "$EXTRA" | grep -q " $WANT_EXTRA "; then EXTRA_OK=0; fi
    if [ "$CONSOLE" = "$WANT_CONSOLE" ] && [ "$EXTRA_OK" = 1 ]; then
      ok "console=$CONSOLE in $BOOT_ENV"
    elif ask "move the kernel console off ttyS0 in $BOOT_ENV (needs a reboot)?"; then
      sudo cp -n "$BOOT_ENV" "$BOOT_ENV.mfruit.bak"
      set_env console "$WANT_CONSOLE"
      [ "$EXTRA_OK" = 0 ] && set_env extraargs "${EXTRA:+$EXTRA }$WANT_EXTRA"
      ok "set console=$WANT_CONSOLE (backup: $BOOT_ENV.mfruit.bak)"; NEED_REBOOT=1
    else
      bad "the radio is unreliable while a console shares the port"
    fi
  fi
  GETTY="$(systemctl is-enabled serial-getty@ttyS0.service 2>/dev/null || true)"
  if [ "$GETTY" = masked ]; then
    ok "serial login on ttyS0 is masked"
  elif ask "mask the serial login on ttyS0 (it would log a shell in on the LoRa port)?"; then
    sudo systemctl mask --now serial-getty@ttyS0.service >/dev/null 2>&1 && ok "masked" \
      || bad "could not mask serial-getty@ttyS0"
  else
    bad "a shell may be logged in on the LoRa port"
  fi
fi
if grep -qE 'console=(serial0|ttyS0|ttyAMA0)' /proc/cmdline && [ "$NEED_REBOOT" = 0 ]; then
  warn "the running kernel still has a console on the LoRa port; a reboot is required"
  NEED_REBOOT=1
fi
[ -e "$PORT" ] && ok "$PORT exists" || { warn "$PORT does not exist yet"; [ "$NEED_REBOOT" = 1 ] || NEED_REBOOT=1; }

# --------------------------------------------------------------- 4. dialout
say "Serial port permission"
if id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
  ok "$USER is in the dialout group"
elif ask "add $USER to the dialout group?"; then
  sudo usermod -aG dialout "$USER" && ok "added (services restart below; log in again for shells)"
else
  bad "radio apps cannot open $PORT without the dialout group"
fi

# ---------------------------------------------------------------- 5. reboot
if [ "$NEED_REBOOT" = 1 ]; then
  say "Reboot required"
  info "The UART/console changes take effect after a reboot. Reboot, then run"
  info "this script again to provision the radio module."
  if [ "$NO_REBOOT" = 0 ] && ask "reboot now?"; then sudo reboot; fi
  exit 3
fi

# ------------------------------------------------------------- 6. provision
say "Radio module ($BAND${FREQUENCY:+, $FREQUENCY MHz}, $AIR_SPEED bps)"
CURRENT=$(PY -c "from mfruitos.sdk.radio.settings import load_radio, radio_dir
s = load_radio(radio_dir('$OS_HOME')); print(f'{s.band} {s.frequency_mhz} {s.air_speed}' if s else '')" 2>/dev/null)
info "recorded now: ${CURRENT:-nothing (never provisioned by MFruit OS)}"
WANT_FREQ="$FREQUENCY"
[ -n "$WANT_FREQ" ] || WANT_FREQ=$(PY -c "from mfruitos.sdk.radio.settings import BANDS; print(BANDS['$BAND'][2])")
if [ "$CURRENT" = "$BAND $WANT_FREQ $AIR_SPEED" ]; then
  ok "already provisioned for $BAND, $WANT_FREQ MHz, $AIR_SPEED bps"
elif ask "write these settings into the module (stops whisplay-daemon for a few seconds, closing open apps)?"; then
  if sudo env PYTHONPATH="$ROOT" python3 -m mfruitos.hosts.lora provision --band "$BAND" \
       --frequency "$WANT_FREQ" --air-speed "$AIR_SPEED" --port "$PORT" \
       --home "$OS_HOME" --owner "$USER"; then
    ok "provisioned"
  else
    bad "provisioning failed (is the LoRa HAT seated and its M0/M1 jumpers removed?)"
  fi
else
  [ "$CHECK_ONLY" = 1 ] && warn "not provisioned for $BAND, $WANT_FREQ MHz" || bad "the module is not provisioned"
fi

# -------------------------------------------------------------- 7. services
if [ "$CHECK_ONLY" = 0 ] && systemctl is-active --quiet whisplay-os.service; then
  say "Launcher"
  JOB=$(PY -m mfruitos.ctl jobs 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('active',{}).get('jobs',''))" 2>/dev/null)
  if [ -n "$JOB" ]; then
    warn "an install is running ($JOB); not restarting the launcher now"
    info "restart it later so it sees the dialout group: sudo systemctl restart whisplay-os"
  else
    sudo systemctl restart whisplay-os.service && ok "restarted (it now sees the radio setup)"
  fi
fi

# ----------------------------------------------------------------- 8. status
say "Readiness"
PY -m mfruitos.hosts.lora status --home "$OS_HOME" | python3 -c "
import json, sys
report = json.load(sys.stdin)
print('    ready' if report['ready'] else '    not ready yet:')
for problem in report['problems']:
    print('      - ' + problem)"
[ "$FAILED" = 0 ] || exit 1
