#!/usr/bin/env bash
# Offline packs: install MFruit OS and its Whisplay driver without internet.
#
#   bash scripts/offline.sh find                  print the offline pack for this board, if any
#   sudo bash scripts/offline.sh install PKG...   install the missing packages: from the
#                                                 offline pack when there is one, else online
#
# A pack is a directory under offline/ (or $MFRUIT_OFFLINE_DIR) made by
# scripts/make-offline-pack.sh on a board with internet that runs the same
# OS image: debs/ is a local apt repository (with a Packages index), files/
# holds downloads that Whisplay's sound card installer would fetch, pack.env
# says which board, OS, architecture and kernel it is for
# (docs/WHISPLAY_DRIVER.md#offline-installation).
# drivers/whisplay/install.sh sources this file; scripts/install.sh runs it.

OFFLINE_SH_LOADED=1
OFFLINE_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_APT_GET="$(command -v apt-get || echo /usr/bin/apt-get)"

pack_value() { sed -n "s/^$2=//p" "$1/pack.env" 2>/dev/null | head -n 1; }

os_value() { sed -n "s/^$1=//p" "${SYSROOT:-}/etc/os-release" 2>/dev/null | tr -d '"' | head -n 1; }

# The first pack for this board, OS release and architecture.
offline_find() {
  local platform="$1" root="${MFRUIT_OFFLINE_DIR:-$OFFLINE_REPO/offline}" pack arch
  arch="$(dpkg --print-architecture 2>/dev/null || true)"
  for pack in "$root"/*/; do
    pack="${pack%/}"
    [ -f "$pack/pack.env" ] || continue
    [ "$(pack_value "$pack" PLATFORM)" = "$platform" ] || continue
    [ "$(pack_value "$pack" ARCH)" = "$arch" ] || continue
    [ "$(pack_value "$pack" OS_ID)" = "$(os_value ID)" ] || continue
    [ "$(pack_value "$pack" OS_CODENAME)" = "$(os_value VERSION_CODENAME)" ] || continue
    echo "$pack"
    return 0
  done
  return 1
}

# apt-get options that make apt see only the pack's repository (plus what is
# installed). State lives in a private directory, never in /var/lib/apt.
offline_apt_options() {
  local pack="$1" state="$2"
  mkdir -p "$state/lists/partial" "$state/parts" "$state/cache/archives/partial"
  echo "deb [trusted=yes] file:$pack/debs ./" >"$state/sources.list"
  printf '%s\n' -o "Dir::Etc::SourceList=$state/sources.list" -o "Dir::Etc::SourceParts=$state/parts" \
    -o "Dir::State::Lists=$state/lists" -o "Dir::Cache=$state/cache" -o "APT::Get::List-Cleanup=false" \
    -o "APT::Sandbox::User=root"  # the pack and private state are not readable by _apt
}

offline_apt() {  # PACK apt-get-arguments...
  local pack="$1" state opts=()
  shift
  state="$(mktemp -d)"
  mapfile -t opts < <(offline_apt_options "$pack" "$state")
  "$REAL_APT_GET" "${opts[@]}" -qq update >/dev/null && "$REAL_APT_GET" "${opts[@]}" "$@"
  local rc=$?
  rm -rf "$state"
  return $rc
}

package_installed() {
  [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" = installed ]
}

# Install the packages that are not installed yet; one by one if the batch fails.
install_packages_from() {  # PACK-or-empty PKG...
  local pack="$1" pkg missing=()
  shift
  for pkg in "$@"; do package_installed "$pkg" || missing+=("$pkg"); done
  [ "${#missing[@]}" -gt 0 ] || return 0
  export DEBIAN_FRONTEND=noninteractive
  if [ -n "$pack" ]; then
    echo "[*] Installing ${missing[*]} from the offline pack $pack"
    offline_apt "$pack" install -y --no-install-recommends "${missing[@]}" && return 0
    for pkg in "${missing[@]}"; do
      offline_apt "$pack" install -y --no-install-recommends "$pkg" || echo "[!] $pkg is not in the offline pack" >&2
    done
  else
    echo "[*] Installing ${missing[*]}"
    "$REAL_APT_GET" update -y || true
    "$REAL_APT_GET" install -y "${missing[@]}" && return 0
    for pkg in "${missing[@]}"; do "$REAL_APT_GET" install -y "$pkg" || echo "[!] could not install $pkg" >&2; done
  fi
  for pkg in "${missing[@]}"; do package_installed "$pkg" || return 1; done
}

# PATH shims for Whisplay's sound card installer: apt-get sees only the pack,
# wget is served from files/. Prints the shim directory.
offline_shims() {  # PACK
  local pack="$1" dir state opt
  dir="$(mktemp -d)"
  state="$dir/apt-state"
  {
    echo '#!/usr/bin/env bash'
    echo '# apt-get against the MFruit OS offline pack only (scripts/offline.sh).'
    printf 'exec %q' "$REAL_APT_GET"
    while IFS= read -r opt; do printf ' %q' "$opt"; done < <(offline_apt_options "$pack" "$state")
    echo ' "$@"'
  } >"$dir/apt-get"
  cat >"$dir/wget" <<EOF
#!/usr/bin/env bash
# wget served from the MFruit OS offline pack (scripts/offline.sh).
out="" url=""
while [ \$# -gt 0 ]; do
  case "\$1" in
    -O) out="\$2"; shift ;;
    http://*|https://*) url="\$1" ;;
  esac
  shift
done
key="\$(printf '%s' "\$url" | sha256sum | cut -c1-16)-\$(basename "\$url")"  # = offline_file_key
if [ -f "$pack/files/\$key" ] && [ -n "\$out" ]; then
  cp "$pack/files/\$key" "\$out"
else
  echo "[X] \$url is not in the offline pack $pack" >&2
  exit 4
fi
EOF
  chmod 0755 "$dir/apt-get" "$dir/wget"
  echo "$dir"
}

# Packages index for a directory of .deb files (a flat apt repository).
# "apt-get download" writes an epoch as %3a, which apt would decode in a file:
# URI, so such files are renamed first.
write_packages_index() {  # DEBS-DIR
  local dir="$1" deb
  (
    cd "$dir"
    for deb in *%*.deb; do [ -f "$deb" ] && mv -- "$deb" "${deb//%3a/_}"; done
    for deb in *.deb; do
      [ -f "$deb" ] || continue
      dpkg-deb -f "$deb"
      printf 'Filename: ./%s\nSize: %s\nSHA256: %s\n\n' "$deb" "$(stat -c %s "$deb")" \
        "$(sha256sum "$deb" | cut -d' ' -f1)"
    done >Packages
  )
}

offline_file_key() { printf '%s-%s' "$(printf '%s' "$1" | sha256sum | cut -c1-16)" "$(basename "$1")"; }

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  # shellcheck source=../drivers/whisplay/install.sh
  source "$OFFLINE_REPO/drivers/whisplay/install.sh"
  case "${1:-}" in
    find) offline_find "$(detect_platform)" ;;
    install)
      shift
      [ "${EUID:-$(id -u)}" -eq 0 ] || { echo "run as root: sudo bash $0 install PKG..." >&2; exit 1; }
      install_packages_from "$(offline_find "$(detect_platform)" || true)" "$@" ;;
    *) sed -n '2,15p' "$0"; exit 2 ;;
  esac
fi
