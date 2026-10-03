#!/usr/bin/env bash
# MFruit OS Whisplay driver installer. scripts/install.sh runs it; it can also
# be run on its own to repair or check the driver.
#
#   sudo bash drivers/whisplay/install.sh --user USER   install or update the driver
#   bash drivers/whisplay/install.sh --check            report the driver state (read-only, no root)
#   sudo bash drivers/whisplay/install.sh --rollback    put the previous driver copy back
#
# Options for an install:
#   --rebuild-audio    rebuild the sound card module even when it is installed
#   --restart-daemon   restart whisplay-daemon when it changed
#   --restart-later    the caller restarts it (scripts/install.sh passes this)
#
# It performs the steps of PiSugar/Whisplay's install_driver.sh,
# script/install_<board>.sh and daemon/install_whisplay_daemon_service.sh
# (docs/WHISPLAY_DRIVER.md), without the demo apps, and:
#   - asks no questions (Whisplay's Raspberry Pi script prompts);
#   - skips the sound card build when it is already installed for this kernel;
#   - keeps an existing ~/.whisplay-daemon/settings.json (Whisplay overwrites it);
#   - installs the runtime and daemon to /usr/local/share/whisplay through a
#     staged copy, keeping the previous copy for --rollback.
# Exit codes: 0 done, 1 failed, 2 usage, 3 unsupported board (nothing changed).
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER_DIR="${MFRUIT_WHISPLAY_DIR:-/usr/local/share/whisplay}"
SOUNDCARD_DIR="$HERE/audio/whisplay-soundcard"
SERVICE=whisplay-daemon.service
UNIT_PATH="/etc/systemd/system/$SERVICE"
UNIT_MARK="# Installed by MFruit OS (drivers/whisplay/install.sh)."
BACKUP_DIR=/var/backups/mfruitos
STATUS_FILE=/run/mfruitos/whisplay-driver.status
SYSROOT="${SYSROOT:-}"   # tests point the board detection at a fake tree
PACK=""                  # offline pack for this board (scripts/offline.sh), if any
# Offline packs: install_packages_from, offline_find, offline_shims, pack_value.
if [ -z "${OFFLINE_SH_LOADED:-}" ]; then
  # shellcheck source=../../scripts/offline.sh
  source "$HERE/../../scripts/offline.sh"
fi

log()  { echo "[*] $*"; }
ok()   { echo "[+] $*"; }
warn() { echo "[!] $*" >&2; }
die()  { echo "[X] $*" >&2; exit 1; }

dt_string() { [ -r "$SYSROOT$1" ] && tr -d '\0' <"$SYSROOT$1" 2>/dev/null || true; }
dt_list()   { [ -r "$SYSROOT$1" ] && tr '\0' '\n' <"$SYSROOT$1" 2>/dev/null || true; }
read_file() { [ -r "$SYSROOT$1" ] && cat "$SYSROOT$1" 2>/dev/null || true; }

# Same order and rules as Whisplay's install_driver.sh and sound card installer.
detect_platform() {
  local model compat release boot_env
  model="$(dt_string /proc/device-tree/model)"
  compat="$(dt_list /proc/device-tree/compatible)"
  release="$(read_file /etc/orangepi-release)"
  boot_env="$(read_file /boot/orangepiEnv.txt)"
  if echo "$release" | grep -qi '^BOARD=orangepizero3w$' || \
      echo "$boot_env" | grep -qi 'orangepi-zero3w\.dtb'; then
    echo orangepi_zero3w; return 0
  fi
  if [[ "$model" == *"Raspberry Pi"* ]]; then echo raspberry_pi; return 0; fi
  if [[ "$model" == *"OrangePi Zero2 W"* ]] || echo "$compat" | grep -qi 'xunlong,orangepi-zero2w'; then
    echo orangepi_zero2w; return 0
  fi
  if [[ "$model" == *"Cubie"* ]] || echo "$compat" | grep -qi 'cubie-a7z'; then
    echo radxa_cubie_a7z; return 0
  fi
  if [[ "$model" == *"Radxa"* ]] || echo "$compat" | grep -qi 'radxa'; then
    echo radxa_zero3w; return 0
  fi
  echo unknown
}

pi_boot_config() {
  if [ -f "$SYSROOT/boot/firmware/config.txt" ]; then echo "$SYSROOT/boot/firmware/config.txt"
  else echo "$SYSROOT/boot/config.txt"; fi
}

# The LCD's SPI device per board (runtime/whisplay.py: bus, CS 0).
spi_device() {
  case "$1" in
    raspberry_pi) echo /dev/spidev0.0 ;;
    orangepi_zero2w|radxa_cubie_a7z) echo /dev/spidev1.0 ;;
    orangepi_zero3w|radxa_zero3w) echo /dev/spidev3.0 ;;
  esac
}

# Where the sound card installer puts the compiled overlay.
overlay_file() {
  case "$1" in
    raspberry_pi) echo "$SYSROOT/boot/firmware/overlays/whisplay-soundcard.dtbo" ;;
    orangepi_zero2w) echo "$SYSROOT/boot/overlay-user/whisplay-soundcard-orangepi-zero2w.dtbo" ;;
    orangepi_zero3w) echo "$SYSROOT/boot/overlay-user/whisplay-soundcard-orangepi-zero3w.dtbo" ;;
    radxa_zero3w) echo "$SYSROOT/boot/dtbo/whisplay-soundcard-radxa-zero3w.dtbo" ;;
    radxa_cubie_a7z) echo "$SYSROOT/boot/dtbo/whisplay-soundcard-radxa-cubie-a7z.dtbo" ;;
  esac
}

# Orange Pi /boot/orangepiEnv.txt "overlays=" handling, as in Whisplay's
# script/install_orangepi_zero2w.sh and _zero3w.sh.
add_kernel_overlay() {
  local name="$1" boot_env="$2"
  [ -f "$boot_env" ] || die "Missing Orange Pi boot environment: $boot_env"
  if grep -q '^overlays=' "$boot_env"; then
    if ! awk -v wanted="$name" 'BEGIN { FS="[= ]" } $1 == "overlays" { for (i=2; i<=NF; i++) if ($i == wanted) found=1 } END { exit !found }' "$boot_env"; then
      sed -i "/^overlays=/ s/$/ $name/" "$boot_env"
    fi
  else
    echo "overlays=$name" >>"$boot_env"
  fi
}

remove_kernel_overlay() {
  local name="$1" boot_env="$2" current item
  local kept=()
  [ -f "$boot_env" ] || die "Missing Orange Pi boot environment: $boot_env"
  current="$(sed -n 's/^overlays=//p' "$boot_env" | tail -n 1)"
  [ -n "$current" ] || return 0
  for item in $current; do
    [ "$item" = "$name" ] || kept+=("$item")
  done
  sed -i "/^overlays=/c\\overlays=${kept[*]}" "$boot_env"
}

# Radxa: enable a vendor overlay by restoring its .dtbo (Whisplay's script/install_radxa_*.sh).
enable_overlay_copy() {
  local overlay="$1" label="$2" dir="$SYSROOT/boot/dtbo"
  if [ -f "$dir/$overlay" ]; then
    ok "$label already enabled"
  elif [ -f "$dir/$overlay.disabled" ]; then
    cp "$dir/$overlay.disabled" "$dir/$overlay"
    ok "$label enabled: $overlay"
    REBOOT=1
  else
    warn "$label overlay not found; enable it manually with rsetup: $overlay"
  fi
}

# What the driver uses, with the Debian package providing each. The daemon
# draws its pages with DejaVu Sans; Pillow before 9.2 cannot measure text with
# its fallback font, so without it the pages crash (found by
# tests/fresh_install on Ubuntu 22.04). Optional: numpy (fast RGB565), smbus
# (PiSugar 3 button), i2c-tools (codec probe), bluez, python3-dbus and
# python3-gi (the daemon's Bluetooth page and pairing agent).
REQUIRED=(module:spidev:python3-spidev module:gpiod:python3-libgpiod module:PIL:python3-pil
          command:aplay:alsa-utils command:amixer:alsa-utils
          file:/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:fonts-dejavu-core)
OPTIONAL=(module:numpy:python3-numpy module:smbus:python3-smbus command:i2cdetect:i2c-tools
          command:bluetoothctl:bluez module:dbus:python3-dbus module:gi:python3-gi)

missing_packages() {  # required|optional|all
  local entry kind name list=()
  case "$1" in
    required) list=("${REQUIRED[@]}") ;;
    optional) list=("${OPTIONAL[@]}") ;;
    *) list=("${REQUIRED[@]}" "${OPTIONAL[@]}") ;;
  esac
  for entry in "${list[@]}"; do
    kind="${entry%%:*}"; name="${entry#*:}"; name="${name%%:*}"
    case "$kind" in
      module) python3 -c "import $name" >/dev/null 2>&1 || echo "${entry##*:}" ;;
      file) [ -e "$SYSROOT$name" ] || echo "${entry##*:}" ;;
      *) command -v "$name" >/dev/null 2>&1 || echo "${entry##*:}" ;;
    esac
  done | sort -u | tr '\n' ' ' | sed 's/ $//'
}

kernel_module_installed() {
  [ -f "/lib/modules/$(uname -r)/kernel/sound/soc/codecs/snd-soc-whisplay-soundcard.ko" ] || \
    modinfo -n snd-soc-whisplay-soundcard >/dev/null 2>&1
}

audio_installed() {
  local platform="$1"
  kernel_module_installed && [ -f "$(overlay_file "$platform")" ] && \
    grep -qs whisplaysound /etc/asound.conf
}

upstream_commit() { sed -n 's/^Commit: `\([0-9a-f]*\)`.*/\1/p' "$HERE/UPSTREAM.md"; }
bundle_digest() { sha256sum "$HERE/upstream.sha256" | cut -d' ' -f1; }
installed_value() { sed -n "s/^$1=//p" "$DRIVER_DIR/MFRUIT_DRIVER" 2>/dev/null || true; }

# ------------------------------------------------------------------ check
check() {
  local platform bad=0 missing state dev
  platform="$(detect_platform)"
  echo "Board: $platform ($(dt_string /proc/device-tree/model))"
  [ "$platform" != unknown ] || { echo "FAIL: not a board the Whisplay driver supports"; return 3; }
  missing="$(missing_packages required)"
  if [ -z "$missing" ]; then echo "OK: Python modules and tools"; else echo "FAIL: missing packages: $missing"; bad=1; fi
  missing="$(missing_packages optional)"
  [ -z "$missing" ] || echo "WARN: optional packages missing (an install adds them): $missing"
  dev="$(spi_device "$platform")"
  if [ -e "$SYSROOT$dev" ]; then echo "OK: LCD SPI $dev"; else echo "FAIL: $dev missing (SPI not enabled, or reboot pending)"; bad=1; fi
  if audio_installed "$platform"; then echo "OK: sound card module, overlay and ALSA config installed"
  else echo "FAIL: sound card driver not installed for kernel $(uname -r)"; bad=1; fi
  if grep -qs whisplaysound "$SYSROOT/proc/asound/cards"; then echo "OK: sound card whisplaysound loaded"
  else echo "FAIL: sound card whisplaysound not loaded (reboot pending?)"; bad=1; fi
  if [ -f "$DRIVER_DIR/MFRUIT_DRIVER" ]; then
    if [ "$(installed_value manifest_sha256)" = "$(bundle_digest)" ]; then
      echo "OK: driver files at $DRIVER_DIR (upstream $(installed_value upstream))"
    else
      echo "FAIL: driver files at $DRIVER_DIR differ from this MFruit OS (installed upstream $(installed_value upstream), bundled $(upstream_commit))"; bad=1
    fi
  else
    echo "FAIL: driver files not installed at $DRIVER_DIR"; bad=1
  fi
  if grep -qsF "$UNIT_MARK" "$UNIT_PATH"; then echo "OK: $SERVICE uses the MFruit OS driver"
  elif [ -f "$UNIT_PATH" ]; then
    echo "FAIL: $SERVICE runs $(systemctl show -p WorkingDirectory --value "$SERVICE" 2>/dev/null) (not the MFruit OS driver)"; bad=1
  else echo "FAIL: $SERVICE not installed"; bad=1; fi
  state="$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
  if [ "$state" = active ]; then echo "OK: $SERVICE active"; else echo "FAIL: $SERVICE ${state:-unknown}"; bad=1; fi
  return $bad
}

# ------------------------------------------------------------------ install steps
install_packages() {
  local missing
  missing="$(missing_packages all)"
  [ -n "$missing" ] || { ok "Python modules and tools present"; return 0; }
  # shellcheck disable=SC2086
  install_packages_from "$PACK" $missing || true
  if [ -z "$PACK" ] && ! python3 -c "import spidev" >/dev/null 2>&1; then
    # The Cubie A7Z image may lack python3-spidev; Whisplay falls back to pip.
    local pip_args=(install spidev)
    python3 -m pip help install 2>/dev/null | grep -q -- --break-system-packages && \
      pip_args=(install --break-system-packages spidev)
    python3 -m pip "${pip_args[@]}" || true
  fi
  [ -z "$(missing_packages required)" ] || die "required packages are still missing: $(missing_packages required)"
  [ -z "$(missing_packages optional)" ] || warn "optional packages could not be installed: $(missing_packages optional)"
  ok "Python modules and tools present"
}

enable_buses() {
  local platform="$1" boot_env before
  case "$platform" in
    raspberry_pi)
      # I2C and I2S are enabled by the sound card installer (dtparam lines).
      local boot_cfg; boot_cfg="$(pi_boot_config)"
      if grep -Eq '^[[:space:]]*dtparam=spi=on' "$boot_cfg" 2>/dev/null; then
        ok "SPI enabled"
      else
        log "Enabling SPI for the LCD"
        if command -v raspi-config >/dev/null 2>&1; then raspi-config nonint do_spi 0 || warn "raspi-config could not enable SPI"
        else echo "dtparam=spi=on" >>"$boot_cfg"; fi
        [ -e /dev/spidev0.0 ] || REBOOT=1
      fi
      ;;
    orangepi_zero2w|orangepi_zero3w)
      boot_env="$SYSROOT/boot/orangepiEnv.txt"
      before="$(cksum <"$boot_env" 2>/dev/null || true)"
      if [ "$platform" = orangepi_zero2w ]; then
        add_kernel_overlay pi-i2c1 "$boot_env"
        remove_kernel_overlay spi0-spidev "$boot_env"
        add_kernel_overlay spi1-cs0-spidev "$boot_env"
      else
        add_kernel_overlay i2c0 "$boot_env"
        add_kernel_overlay spi3-cs0-cs1-spidev "$boot_env"
      fi
      if [ "$before" != "$(cksum <"$boot_env")" ]; then ok "I2C and SPI overlays enabled in $boot_env"; REBOOT=1
      else ok "I2C and SPI overlays already enabled"; fi
      ;;
    radxa_zero3w)
      enable_overlay_copy rk3568-spi3-m1-cs0-spidev.dtbo SPI3
      enable_overlay_copy rk3568-i2c3-m0.dtbo I2C3-M0
      ;;
    radxa_cubie_a7z)
      enable_overlay_copy sun60iw2p1-spi1-spidev.dtbo SPI1
      enable_overlay_copy sun60iw2p1-twi7.dtbo TWI7
      ;;
  esac
}

# Whisplay's own sound card installer, run from a temporary copy (it builds
# in its source folder, which may be a git checkout or a FAT SD card); with an
# offline pack its apt-get and wget calls are served from the pack. A failure
# leaves the display, button and LED working and is reported, so the rest of
# the installation finishes.
install_audio() {
  local platform="$1" shims="" rc=0 work
  if [ "$REBUILD_AUDIO" = 0 ] && audio_installed "$platform"; then
    ok "sound card driver already installed for kernel $(uname -r)"
    return 0
  fi
  log "Building and installing the Whisplay sound card driver"
  if [ -n "$PACK" ]; then
    [ "$(pack_value "$PACK" KERNEL)" = "$(uname -r)" ] || \
      warn "the offline pack was made on kernel $(pack_value "$PACK" KERNEL); this board runs $(uname -r)"
    shims="$(offline_shims "$PACK")"
  fi
  work="$(mktemp -d /var/tmp/mfruit-soundcard.XXXXXX)"
  cp -R "$SOUNDCARD_DIR/." "$work/"
  PATH="${shims:+$shims:}$PATH" WHISPLAY_PLATFORM="$platform" bash "$work/scripts/install.sh" || rc=$?
  rm -rf "$work"
  [ -z "$shims" ] || rm -rf "$shims"
  if [ "$rc" = 0 ]; then
    REBOOT=1
    return 0
  fi
  AUDIO_FAILED=1
  warn "the sound card driver was not installed (installer exit $rc); display, button and LED still work"
  warn "rerun scripts/install.sh with internet, or with an offline pack made on this board's kernel"
}

# From Whisplay's daemon service installer: Orange Pi device nodes for the gpio group.
configure_orangepi_access() {
  local user="$1"
  case "$PLATFORM" in orangepi_zero2w|orangepi_zero3w) ;; *) return 0 ;; esac
  getent group gpio >/dev/null 2>&1 || groupadd --system gpio
  case " $(id -nG "$user") " in
    *" gpio "*) ;;
    *) usermod -aG gpio "$user"; REBOOT=1 ;;  # takes effect at the next login/boot
  esac
  local rules=/etc/udev/rules.d/60-whisplay-orangepi.rules tmp
  tmp="$(mktemp)"
  cat >"$tmp" <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip[0-9]*", GROUP="gpio", MODE="0660"
SUBSYSTEM=="spidev", KERNEL=="spidev[0-9]*.[0-9]*", GROUP="gpio", MODE="0660"
EOF
  if ! cmp -s "$tmp" "$rules"; then
    install -m 0644 "$tmp" "$rules"
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=gpio || true
    udevadm trigger --subsystem-match=spidev || true
  fi
  rm -f "$tmp"
  chgrp gpio /dev/gpiochip* /dev/spidev* 2>/dev/null || true
  chmod g+rw /dev/gpiochip* /dev/spidev* 2>/dev/null || true
  ok "GPIO and SPI device access for group gpio"
}

# The daemon's built-in Power page runs these two commands (same rule as Whisplay).
install_power_sudoers() {
  local user="$1" systemctl_bin tmp
  systemctl_bin="$(command -v systemctl)"
  tmp="$(mktemp)"
  printf '%s ALL=(root) NOPASSWD: %s poweroff, %s reboot\n' "$user" "$systemctl_bin" "$systemctl_bin" >"$tmp"
  visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; die "power sudoers rule failed validation"; }
  install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/whisplay-daemon-power
  rm -f "$tmp"
  ok "sudoers: only 'systemctl poweroff' and 'systemctl reboot' for the Power page"
}

# check -> stage -> verify -> activate; the previous copy stays for --rollback.
install_driver_files() {
  local stage previous="$DRIVER_DIR.previous"
  if [ -f "$DRIVER_DIR/MFRUIT_DRIVER" ] && [ "$(installed_value manifest_sha256)" = "$(bundle_digest)" ]; then
    ok "driver files at $DRIVER_DIR are current (upstream $(upstream_commit))"
    return 0
  fi
  stage="$(mktemp -d "$(dirname "$DRIVER_DIR")/.whisplay-stage.XXXXXX")"
  cp -a "$HERE/runtime" "$HERE/daemon" "$HERE/LICENSE" "$HERE/UPSTREAM.md" "$stage/"
  rm -rf "$stage/daemon/tests"
  find "$stage" -name '__pycache__' -prune -exec rm -rf {} +
  python3 -m compileall -q "$stage/runtime" "$stage/daemon" >/dev/null || { rm -rf "$stage"; die "driver files failed to compile"; }
  cat >"$stage/MFRUIT_DRIVER" <<EOF
name=MFruit OS Whisplay driver
upstream=$(upstream_commit)
manifest_sha256=$(bundle_digest)
installed=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
  [ "$(id -u)" != 0 ] || chown -R root:root "$stage"
  chmod -R u=rwX,go=rX "$stage"
  if [ -e "$DRIVER_DIR" ]; then
    if [ ! -f "$DRIVER_DIR/MFRUIT_DRIVER" ]; then
      # Not ours: keep it aside instead of deleting it.
      previous="$DRIVER_DIR.preexisting-$(date +%Y%m%d%H%M%S)"
      warn "$DRIVER_DIR was not installed by MFruit OS; moved to $previous"
    else
      rm -rf "$DRIVER_DIR.previous"
    fi
    mv -T "$DRIVER_DIR" "$previous"
  fi
  mv -T "$stage" "$DRIVER_DIR"
  DAEMON_CHANGED=1
  ok "driver files installed at $DRIVER_DIR (upstream $(upstream_commit))"
}

install_daemon_service() {
  local user="$1" home uid group python_bin tmp
  home="$(getent passwd "$user" | cut -d: -f6)"
  uid="$(id -u "$user")"
  group="$(id -gn "$user")"
  python_bin="$(command -v python3)"
  install -d -m 0755 -o "$user" -g "$group" "$home/.whisplay-daemon" "$home/.whisplay-daemon/app"
  if [ ! -f "$home/.whisplay-daemon/settings.json" ]; then
    printf '{\n  "apps_dir": "%s"\n}\n' "$home/.whisplay-daemon/app" >"$home/.whisplay-daemon/settings.json"
    chown "$user:$group" "$home/.whisplay-daemon/settings.json"
    ok "daemon settings created"
  else
    ok "daemon settings and app registrations kept"
  fi
  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
$UNIT_MARK
# The Whisplay hardware service: LCD, backlight, RGB LED, button, foreground app.
[Unit]
Description=Whisplay Hardware Daemon
Documentation=https://github.com/Mengkungkao/MFruitOS/blob/main/docs/WHISPLAY_DRIVER.md
After=network.target

[Service]
Type=simple
User=$user
Group=audio
SupplementaryGroups=audio video gpio input
WorkingDirectory=$DRIVER_DIR
ExecStart=$python_bin $DRIVER_DIR/daemon/whisplay_daemon.py
Environment=HOME=$home
Environment=XDG_RUNTIME_DIR=/run/user/$uid
Environment=PYTHONUNBUFFERED=1
PrivateDevices=no
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
  if ! cmp -s "$tmp" "$UNIT_PATH"; then
    if [ -f "$UNIT_PATH" ] && ! grep -qF "$UNIT_MARK" "$UNIT_PATH"; then
      install -d -m 0700 "$BACKUP_DIR"
      cp -p "$UNIT_PATH" "$BACKUP_DIR/$SERVICE.$(date +%Y%m%d%H%M%S)"
      ok "previous $SERVICE saved in $BACKUP_DIR"
    fi
    install -m 0644 "$tmp" "$UNIT_PATH"
    DAEMON_CHANGED=1
  fi
  rm -f "$tmp"
  if [ "$PLATFORM" = radxa_cubie_a7z ]; then
    # Whisplay's Cubie A7Z installer: apps use the Whisplay card for audio.
    install -d -m 0755 "/etc/systemd/system/$SERVICE.d"
    cat >"/etc/systemd/system/$SERVICE.d/20-cubie-a7z-audio.conf" <<'EOF'
[Unit]
After=sound.target whisplay-soundcard-a7z-recover.service

[Service]
Environment=ALSA_CARD=whisplaysound
Environment=AUDIODEV=whisplaysound
Environment=SDL_AUDIODRIVER=alsa
Environment=WHISPLAY_ALSA_CARD=whisplaysound
Environment=WHISPLAY_ALSA_PLAYBACK_DEVICE=whisplaysound
Environment=WHISPLAY_ALSA_CAPTURE_DEVICE=whisplaysound
Environment=WHISPLAY_AUDIO_RATE=48000
EOF
  fi
  systemctl daemon-reload
  systemctl enable "$SERVICE" >/dev/null 2>&1
  ok "$SERVICE runs the MFruit OS driver ($DRIVER_DIR)"
}

write_status() {
  install -d -m 0755 "$(dirname "$STATUS_FILE")"
  printf 'REBOOT_REQUIRED=%s\nDAEMON_CHANGED=%s\nAUDIO_FAILED=%s\nDRIVER_DIR=%s\n' \
    "$REBOOT" "$DAEMON_CHANGED" "$AUDIO_FAILED" "$DRIVER_DIR" >"$STATUS_FILE"
}

start_daemon() {
  if [ "$REBOOT" = 1 ]; then
    warn "reboot required to load the SPI/I2C/I2S overlays and the sound card: sudo reboot"
  elif ! systemctl is-active --quiet "$SERVICE"; then
    systemctl start "$SERVICE" && ok "$SERVICE started"
  elif [ "$DAEMON_CHANGED" = 1 ] && [ "$RESTART_DAEMON" = 1 ]; then
    warn "restarting $SERVICE (running apps are closed)"
    systemctl restart "$SERVICE"
  elif [ "$DAEMON_CHANGED" = 1 ] && [ "$RESTART_LATER" = 1 ]; then
    ok "$SERVICE changed; it is restarted at the end of the installation"
  elif [ "$DAEMON_CHANGED" = 1 ]; then
    warn "$SERVICE changed; restart it to use the new driver: sudo systemctl restart $SERVICE"
  fi
}

rollback() {
  [ "${EUID:-$(id -u)}" -eq 0 ] || die "run as root (sudo)"
  [ -d "$DRIVER_DIR.previous" ] || die "no previous driver copy at $DRIVER_DIR.previous"
  local swap="$DRIVER_DIR.rollback-$$"
  mv -T "$DRIVER_DIR" "$swap"
  mv -T "$DRIVER_DIR.previous" "$DRIVER_DIR"
  mv -T "$swap" "$DRIVER_DIR.previous"
  ok "previous driver restored (upstream $(installed_value upstream)); restarting $SERVICE"
  systemctl restart "$SERVICE"
}

main() {
  local mode=install user="${SUDO_USER:-}"
  REBUILD_AUDIO=0; RESTART_DAEMON=0; RESTART_LATER=0; REBOOT=0; DAEMON_CHANGED=0; AUDIO_FAILED=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --check) mode=check ;;
      --rollback) mode=rollback ;;
      --user) user="${2:?--user needs a name}"; shift ;;
      --rebuild-audio) REBUILD_AUDIO=1 ;;
      --restart-daemon) RESTART_DAEMON=1 ;;
      --restart-later) RESTART_LATER=1 ;;
      -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
      *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
  done
  case "$mode" in
    check) check; exit $? ;;
    rollback) rollback; exit 0 ;;
  esac

  [ "${EUID:-$(id -u)}" -eq 0 ] || die "run as root: sudo bash $0 --user <daemon user>"
  [ -n "$user" ] && [ "$user" != root ] || die "name the non-root user the daemon runs as: --user <name>"
  getent passwd "$user" >/dev/null || die "unknown user: $user"
  PLATFORM="$(detect_platform)"
  if [ "$PLATFORM" = unknown ]; then
    warn "no supported Whisplay board detected; the driver was not installed"
    exit 3
  fi
  (cd "$HERE" && sha256sum --quiet -c upstream.sha256) || die "bundled driver files do not match upstream.sha256"

  echo "MFruit OS Whisplay driver (upstream $(upstream_commit)) on $PLATFORM for $user"
  PACK="$(offline_find "$PLATFORM" || true)"
  [ -z "$PACK" ] || ok "offline pack: $PACK (made $(pack_value "$PACK" CREATED) on kernel $(pack_value "$PACK" KERNEL))"
  case "$PLATFORM" in
    orangepi_zero3w|radxa_cubie_a7z)
      warn "this board requires Whisplay V2 hardware."
      warn "Do not use Whisplay V1: its 5 V button circuit can cut board power." ;;
  esac
  install_packages
  enable_buses "$PLATFORM"
  install_audio "$PLATFORM"
  configure_orangepi_access "$user"
  install_power_sudoers "$user"
  install_driver_files
  install_daemon_service "$user"
  write_status
  start_daemon
  [ "$AUDIO_FAILED" = 0 ] || warn "Whisplay driver installed WITHOUT the sound card (see above)"
  if [ "$REBOOT" = 1 ]; then ok "Whisplay driver installed; reboot to finish: sudo reboot"
  else ok "Whisplay driver ready"; fi
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
