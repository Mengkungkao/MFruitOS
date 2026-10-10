#!/usr/bin/env bash
# The test suite on other distributions, without root or Docker
# (docs/quality/TESTING.md#other-distributions).
#
#   bash tests/distro/run.sh prepare NAME     download, verify and unpack NAME, then install the
#                                            packages a board has (python3-pil, gpiod, codec2, ...)
#   bash tests/distro/run.sh check NAME       scripts/check.sh inside NAME, as a normal user
#   bash tests/distro/run.sh install NAME     scripts/install.sh --no-service, twice, as that user
#   bash tests/distro/run.sh user NAME [CMD]  any command as that user (default: a shell)
#   bash tests/distro/run.sh root NAME [CMD]  any command as root inside NAME
#
# NAME: ubuntu-22.04, ubuntu-24.04, debian-12, debian-13 (arm64 on an arm64
# host, amd64 on an amd64 one; MFRUIT_DISTRO_ARCH=armhf on an arm64 host whose
# CPU runs 32-bit code tests a 32-bit system on a 64-bit kernel, like 32-bit
# Raspberry Pi OS on a Pi Zero 2 W). Root filesystems come from Canonical's
# ubuntu-base tarballs (checked against SHA256SUMS) and Docker Hub's official
# debian images (checked against their digest), and stay in
# ${MFRUIT_DISTRO_DIR:-~/.cache/mfruit-distro}; nothing there is deleted by
# this script. This checkout is mounted read-only at /src/MFruitOS, so a test
# that writes into the source tree fails. An app checkout can be added with
# APP_DIR=... (mounted at /src/app).
#
# It needs unprivileged user namespaces (unshare -r). Only one user is mapped,
# so "root" inside is you outside, and the normal user (uid 1000, no
# capabilities) is a second namespace inside that one. Package scripts that
# hand files to other system users fail; that does not affect the packages
# the tests need. Containers have no systemd, udev, kernel modules or
# hardware: device behaviour still needs a board.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BASE="${MFRUIT_DISTRO_DIR:-$HOME/.cache/mfruit-distro}"
ROOTS="$BASE/roots" CACHE="$BASE/cache" WORK="$BASE/work"
mkdir -p "$ROOTS" "$CACHE" "$WORK"

case "$(uname -m)" in
  aarch64) ARCH="${MFRUIT_DISTRO_ARCH:-arm64}" ;;
  x86_64) ARCH="${MFRUIT_DISTRO_ARCH:-amd64}" ;;
  *) echo "unsupported host architecture $(uname -m)" >&2; exit 2 ;;
esac
case "$ARCH" in
  arm64|amd64) DOCKER_ARCH="$ARCH" DOCKER_VARIANT="" ;;
  armhf) DOCKER_ARCH=arm DOCKER_VARIANT=v7 ;;
  *) echo "unsupported MFRUIT_DISTRO_ARCH $ARCH (arm64, amd64, armhf)" >&2; exit 2 ;;
esac

die() { echo "$*" >&2; exit 1; }

ubuntu_release() {
  case "$1" in
    ubuntu-22.04) echo "22.04 22.04.5" ;;
    ubuntu-24.04) echo "24.04 24.04.5" ;;
    *) return 1 ;;
  esac
}

debian_tag() {
  case "$1" in debian-12) echo bookworm ;; debian-13) echo trixie ;; *) return 1 ;; esac
}

fetch_ubuntu() {
  local series point base file
  read -r series point <<<"$(ubuntu_release "$1")"
  base="https://cdimage.ubuntu.com/ubuntu-base/releases/$series/release"
  file="ubuntu-base-$point-base-$ARCH.tar.gz"
  [ -f "$CACHE/$file" ] || curl -fsSL --retry 3 -o "$CACHE/$file.part" "$base/$file"
  [ ! -f "$CACHE/$file.part" ] || mv "$CACHE/$file.part" "$CACHE/$file"
  curl -fsSL --retry 3 "$base/SHA256SUMS" | grep " \*$file\$" | sed 's/ \*/  /' \
    | (cd "$CACHE" && sha256sum -c - >&2) || die "checksum mismatch for $file"
  echo "$CACHE/$file"
}

fetch_debian() {
  local tag token index digest manifest layer out
  tag="$(debian_tag "$1")"
  token="$(curl -fsSL "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/debian:pull" \
           | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')"
  index="$(curl -fsSL -H "Authorization: Bearer $token" \
           -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
           "https://registry-1.docker.io/v2/library/debian/manifests/$tag")"
  digest="$(python3 -c '
import json, sys
for m in json.loads(sys.argv[1])["manifests"]:
    p = m.get("platform", {})
    if p.get("os") == "linux" and p.get("architecture") == sys.argv[2] \
            and (not sys.argv[3] or p.get("variant") == sys.argv[3]):
        print(m["digest"]); break' "$index" "$DOCKER_ARCH" "$DOCKER_VARIANT")"
  [ -n "$digest" ] || die "no $ARCH image for debian:$tag"
  manifest="$(curl -fsSL -H "Authorization: Bearer $token" \
              -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
              "https://registry-1.docker.io/v2/library/debian/manifests/$digest")"
  layer="$(python3 -c 'import json, sys; ls = json.loads(sys.argv[1])["layers"]; assert len(ls) == 1, ls; print(ls[0]["digest"])' "$manifest")"
  out="$CACHE/debian-$tag-$ARCH-${layer#sha256:}.tar.gz"
  if [ ! -f "$out" ]; then
    curl -fsSL --retry 3 -H "Authorization: Bearer $token" -o "$out.part" \
      "https://registry-1.docker.io/v2/library/debian/blobs/$layer"
    echo "${layer#sha256:}  $out.part" | sha256sum -c - >&2 || die "digest mismatch for debian:$tag"
    mv "$out.part" "$out"
  fi
  echo "$out"
}

codec2_package() {
  case "$1" in ubuntu-22.04|debian-12) echo libcodec2-1.0 ;; *) echo libcodec2-1.2 ;; esac
}

prepare() {
  local name="$1" root="$ROOTS/$1-$ARCH" archive
  if [ ! -e "$root/etc/os-release" ]; then
    case "$name" in
      ubuntu-*) archive="$(fetch_ubuntu "$name")" ;;
      debian-*) archive="$(fetch_debian "$name")" ;;
      *) die "unknown distribution $name" ;;
    esac
    mkdir -p "$root"
    unshare -r tar -xzf "$archive" -C "$root" --exclude='./dev/*' --exclude='dev/*' --no-same-owner 2>/dev/null || true
    [ -e "$root/etc/os-release" ] || die "could not unpack $archive"
  fi
  cp /etc/resolv.conf "$root/etc/resolv.conf"
  mkdir -p "$root/etc/apt/apt.conf.d"
  printf 'APT::Sandbox::User "root";\nAcquire::Retries "3";\n' > "$root/etc/apt/apt.conf.d/99mfruit-distro"
  grep -q '^tester:' "$root/etc/passwd" || {
    echo 'tester:x:1000:1000:tester:/home/tester:/bin/bash' >> "$root/etc/passwd"
    echo 'tester:x:1000:' >> "$root/etc/group"
  }
  mkdir -p "$root/home/tester"
  # What a board image has and a container lacks (procps: pkill in the
  # real-daemon tests), plus the packages the installers would install.
  as_root "$name" bash -c "apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    python3 python3-pil python3-venv python3-numpy python3-serial python3-cryptography \
    python3-yaml python3-pytest python3-dbus python3-gi python3-spidev python3-libgpiod \
    python3-smbus git fonts-dejavu-core procps ca-certificates $(codec2_package "$name")" \
    > "$WORK/$name-$ARCH-prepare.log" 2>&1 || {
      echo "package installation failed: $WORK/$name-$ARCH-prepare.log" >&2; exit 1; }
  as_user "$name" python3 -c 'import sys, PIL; print("ready:", sys.version.split()[0], "Pillow", PIL.__version__)'
}

mounts() {  # the shared setup of the outer namespace (root, work dir)
  cat <<'EOF'
set -e
root="$1"; work="$2"; src="$3"; app="$4"; shift 4
mkdir -p "$root/src/MFruitOS" "$root/src/app" "$root/work"
mount --rbind /dev "$root/dev"
mount -t proc proc "$root/proc"
mount --rbind /sys "$root/sys" 2>/dev/null || true
mount -t tmpfs -o mode=1777 tmpfs "$root/tmp"
mount --bind "$src" "$root/src/MFruitOS"
mount -o remount,bind,ro "$root/src/MFruitOS"
if [ -n "$app" ]; then mount --bind "$app" "$root/src/app"; mount -o remount,bind,ro "$root/src/app"; fi
mount --bind "$work" "$root/work"
EOF
}

as_root() {
  local name="$1" root="$ROOTS/$1-$ARCH"
  shift
  [ -d "$root/etc" ] || die "no $name yet: bash $0 prepare $name"
  [ $# -gt 0 ] || set -- bash
  mkdir -p "$WORK/$name-$ARCH"
  unshare -r --mount --pid --fork --kill-child bash -c "$(mounts)
    exec chroot \"\$root\" /usr/bin/env -i HOME=/root TERM=xterm LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \"\$@\"" \
    _ "$root" "$WORK/$name-$ARCH" "${MFRUIT_SRC:-$REPO}" "${APP_DIR:-}" "$@"
}

as_user() {
  local name="$1" root="$ROOTS/$1-$ARCH"
  shift
  [ -d "$root/etc" ] || die "no $name yet: bash $0 prepare $name"
  [ $# -gt 0 ] || set -- bash
  mkdir -p "$WORK/$name-$ARCH"
  unshare -r --mount --pid --fork --kill-child bash -c "$(mounts)
    exec unshare --user --map-user=1000 --map-group=1000 --keep-caps chroot \"\$root\" \
      setpriv --inh-caps=-all --ambient-caps=-all --bounding-set=-all -- \
      /usr/bin/env -i HOME=/home/tester USER=tester LOGNAME=tester TERM=xterm LANG=C.UTF-8 \
      PATH=/usr/local/bin:/usr/bin:/bin \"\$@\"" \
    _ "$root" "$WORK/$name-$ARCH" "${MFRUIT_SRC:-$REPO}" "${APP_DIR:-}" "$@"
}

command="${1:-}"
name="${2:-}"
[ -n "$name" ] || { sed -n '2,25p' "$0"; exit 2; }
shift 2
case "$command" in
  prepare) prepare "$name" ;;
  check)
    as_user "$name" bash -c 'cd /src/MFruitOS && bash scripts/check.sh > /work/check.log 2>&1; rc=$?
      grep -E "FAIL|^Ran [0-9]+ tests in|^OK|^FAILED|All checks" /work/check.log | grep -v "^Ran 7 tests"; exit $rc'
    ;;
  install)
    as_user "$name" bash -c 'cd /src/MFruitOS && for run in 1 2; do
        bash scripts/install.sh --no-service --yes > /work/install-$run.log 2>&1 || { echo "install $run failed:"; tail -5 /work/install-$run.log; exit 1; }
      done
      PYTHONPATH=$HOME/.whisplay-os/system/current python3 -m mfruitos --self-test'
    ;;
  user) as_user "$name" "$@" ;;
  root) as_root "$name" "$@" ;;
  *) sed -n '2,25p' "$0"; exit 2 ;;
esac
