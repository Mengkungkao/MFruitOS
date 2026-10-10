#!/usr/bin/env bash
# Make an offline pack so mFruit OS installs without internet.
#
#   bash scripts/make-offline-pack.sh            write offline/<board>-<os>-<release>-<arch>/
#   bash scripts/make-offline-pack.sh --archive  also write that directory as a .tar.gz
#                                                (for example to attach to a GitHub release)
#
# Run it as your normal user on a board WITH internet that runs the same OS
# image as the boards you will install offline: best straight after flashing
# the image and `sudo apt-get update`, before upgrading (the sound card is
# built for the kernel the pack was made on). It changes nothing on the board.
# The pack holds the .deb files mFruit OS and its Whisplay driver may install,
# with all their dependencies, and the files Whisplay's sound card installer
# downloads on this board (about 200 MB).
# Use: put it in MFruitOS/offline/ next to the code; scripts/install.sh finds
# it. docs/WHISPLAY_DRIVER.md#offline-installation
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../drivers/whisplay/install.sh
source "$REPO/drivers/whisplay/install.sh"   # detect_platform, REQUIRED/OPTIONAL, offline.sh

ARCHIVE=0
[ "${1:-}" = "--archive" ] && ARCHIVE=1

# Packages that scripts/install.sh, drivers/whisplay/install.sh and Whisplay's
# sound card installer (install_build_deps) may ask apt for on this board.
pack_packages() {
  local platform="$1" kernel="$2" entry
  echo python3-pil python3-venv network-manager
  for entry in "${REQUIRED[@]}" "${OPTIONAL[@]}"; do echo "${entry##*:}"; done
  case "$platform" in
    raspberry_pi) echo raspberrypi-kernel-headers "linux-headers-$kernel" device-tree-compiler alsa-utils libasound2-plugins sox ;;
    orangepi_zero2w|orangepi_zero3w) echo device-tree-compiler alsa-utils libasound2-plugins sox wget xz-utils make gcc kmod ;;
    radxa_cubie_a7z) echo "linux-headers-$kernel" device-tree-compiler alsa-utils libasound2-plugins sox kmod ;;
    *) echo "linux-headers-$kernel" device-tree-compiler alsa-utils libasound2-plugins sox ;;
  esac
}

# Downloads Whisplay's sound card installer makes on this board (it checks them by SHA-256).
pack_urls() {
  local platform="$1" kernel="$2" series
  series="$(echo "$kernel" | cut -d. -f1-2)"
  case "$platform" in
    orangepi_zero2w)
      echo "https://raw.githubusercontent.com/MJD19994/WM8960_AudioHAT_OrangePiZero_Drivers/58a1ea03d6efb6c59f66a291492517b26342a091/dkms/kheaders-6.1.31-sun50iw9.tar.xz"
      echo "https://raw.githubusercontent.com/MJD19994/WM8960_AudioHAT_OrangePiZero_Drivers/58a1ea03d6efb6c59f66a291492517b26342a091/dkms/wm8960.c"
      echo "https://raw.githubusercontent.com/MJD19994/WM8960_AudioHAT_OrangePiZero_Drivers/58a1ea03d6efb6c59f66a291492517b26342a091/dkms/wm8960.h" ;;
    orangepi_zero3w)
      echo "https://apt.armbian.com/pool/main/l/linux-headers-vendor-sun60iw2/linux-headers-vendor-sun60iw2_26.8.3_arm64__6.6.98-S8a9b-D5397-P6965-C16f9-H213f-HKca97-Vc222-B4990-R448a.deb" ;;
    radxa_cubie_a7z)
      echo "https://raw.githubusercontent.com/torvalds/linux/v$series/sound/soc/codecs/wm8960.c"
      echo "https://raw.githubusercontent.com/torvalds/linux/v$series/sound/soc/codecs/wm8960.h" ;;
  esac
}

# Every package needed to install these, base libraries included: the pack
# holds the archive's current versions, which may need newer libraries than an
# older image has. apt installs only what is missing or too old.
closure() {
  apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks \
      --no-replaces --no-enhances "$@" 2>/dev/null | grep -v '^ ' | grep -v '[<>]' | sort -u
}

main() {
  local platform kernel arch os_id codename name out pkg url wanted=() missing=() list
  platform="$(detect_platform)"
  [ "$platform" != unknown ] || { echo "Not a board the Whisplay driver supports" >&2; exit 3; }
  kernel="$(uname -r)"
  arch="$(dpkg --print-architecture)"
  os_id="$(os_value ID)"
  codename="$(os_value VERSION_CODENAME)"
  name="$platform-$os_id-$codename-$arch"
  out="${MFRUIT_OFFLINE_DIR:-$REPO/offline}/$name"
  echo "Offline pack for $platform, $os_id $codename $arch, kernel $kernel -> $out"

  for pkg in $(pack_packages "$platform" "$kernel"); do
    if apt-cache show --no-all-versions "$pkg" >/dev/null 2>&1; then wanted+=("$pkg"); else missing+=("$pkg"); fi
  done
  [ "${#wanted[@]}" -gt 0 ] || { echo "apt knows none of the packages; run: sudo apt-get update" >&2; exit 1; }
  [ "${#missing[@]}" = 0 ] || echo "[!] not available from apt here (skipped): ${missing[*]}"

  rm -rf "$out.partial"
  mkdir -p "$out.partial/debs" "$out.partial/files"
  list="$(closure "${wanted[@]}")"
  echo "[*] Downloading $(echo "$list" | wc -l) packages"
  # shellcheck disable=SC2086
  if ! (cd "$out.partial/debs" && apt-get download $list); then
    for pkg in $list; do (cd "$out.partial/debs" && apt-get download "$pkg") || echo "[!] could not download $pkg"; done
  fi
  write_packages_index "$out.partial/debs"

  for url in $(pack_urls "$platform" "$kernel"); do
    echo "[*] $url"
    wget -q -O "$out.partial/files/$(offline_file_key "$url")" "$url"
  done
  # Wi-Fi from a phone: PiSugar's sugar-wifi-conf for this architecture
  # (scripts/install.sh checks it by SHA-256; docs/platform/ADR/0013-phone-wifi-setup.md).
  url="$(PYTHONPATH="$REPO" python3 -m mfruitos.system.wifi_setup url 2>/dev/null || true)"
  if [ -n "$url" ]; then
    echo "[*] $url"
    wget -q -O "$out.partial/files/$(offline_file_key "$url")" "$url" || echo "[!] could not download $url"
  fi

  cat >"$out.partial/pack.env" <<EOF
PLATFORM=$platform
OS_ID=$os_id
OS_CODENAME=$codename
ARCH=$arch
KERNEL=$kernel
CREATED=$(date -u +%Y-%m-%d)
MFRUIT_OS=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/mfruitos/__init__.py")
WHISPLAY_UPSTREAM=$(upstream_commit)
REQUESTED=${wanted[*]}
EOF
  (cd "$out.partial" && find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs -r sha256sum >SHA256SUMS)
  rm -rf "$out"
  mv -T "$out.partial" "$out"
  echo "[+] $out ($(du -sh "$out" | cut -f1))"
  if [ "$ARCHIVE" = 1 ]; then
    tar -C "$(dirname "$out")" -czf "$out.tar.gz" "$name"
    echo "[+] $out.tar.gz"
  fi
  echo "Copy it to MFruitOS/offline/$name on the board to install, then: bash scripts/install.sh"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
