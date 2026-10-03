#!/usr/bin/env bash
# Rehearse a fresh, offline MFruit OS installation in a disposable container.
#
#   bash tests/fresh_install/rehearse.sh PACK_DIR [--suite] [--keep]
#
# PACK_DIR is an offline pack (scripts/make-offline-pack.sh). Run this on a
# Docker host with the pack's architecture (for example the board itself):
#   1. with network: the pack's OS image (ubuntu:22.04 for an Orange Pi Zero
#      2W pack) plus what the board image has and a container lacks
#      (python3, sudo, kmod, systemd, udev);
#   2. WITHOUT network: copy this checkout and the pack in as the board user
#      would, run `bash scripts/install.sh --yes`, then check the result
#      (tests/fresh_install/verify.sh) and, with --suite, run the real-daemon
#      tests against the installed driver.
# Only what a container cannot have is faked (tests/fresh_install/fakes/):
# the board's device tree (SYSROOT), systemctl/udevadm (no systemd running)
# and the kernel release reported to the build (uname -r, depmod -a). apt,
# the sound card module build, dtc, file installs, provisioning and the
# self-test are real. Nothing on the host is changed; containers and the
# image are removed afterwards unless --keep.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PACK="$(cd "${1:?usage: rehearse.sh PACK_DIR [--suite] [--keep]}" && pwd)"
shift
SUITE=0 KEEP=0
for arg in "$@"; do
  case "$arg" in --suite) SUITE=1 ;; --keep) KEEP=1 ;; *) echo "unknown option $arg" >&2; exit 2 ;; esac
done
value() { sed -n "s/^$1=//p" "$PACK/pack.env"; }
PLATFORM="$(value PLATFORM)" KERNEL="$(value KERNEL)"
case "$PLATFORM" in
  orangepi_zero2w)
    BASE="ubuntu:22.04" MODEL="OrangePi Zero2 W" COMPAT="xunlong,orangepi-zero2w"
    # A stock Orange Pi OS boot environment: no Whisplay overlays yet.
    BOOT_FILE=/boot/orangepiEnv.txt
    BOOT_TEXT='verbosity=1\nbootlogo=false\nconsole=both\ndisp_mode=1920x1080p60\noverlay_prefix=sun50i-h616\nrootdev=UUID=00000000-0000-0000-0000-000000000000\nrootfstype=ext4\n' ;;
  *) echo "no rehearsal profile for $PLATFORM yet" >&2; exit 3 ;;
esac
case "$(value ARCH)-$(uname -m)" in
  arm64-aarch64|amd64-x86_64|armhf-armv7l) ;;
  *) echo "the pack is for $(value ARCH); run this on such a host (for example the board)" >&2; exit 3 ;;
esac

TAG="mfruit-rehearsal:$PLATFORM"
PREP="mfruit-rehearsal-prep-$$" RUN="mfruit-rehearsal-run-$$"
cleanup() {
  docker rm -f "$PREP" "$RUN" >/dev/null 2>&1 || true
  [ "$KEEP" = 1 ] || docker rmi -f "$TAG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> 1. Image: $BASE as a fresh $PLATFORM system (network allowed)"
docker run --name "$PREP" -e DEBIAN_FRONTEND=noninteractive "$BASE" bash -c \
  'apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 sudo kmod systemd udev >/dev/null &&
   rm -rf /var/lib/apt/lists/*'
docker cp "$HERE/fakes/." "$PREP:/usr/local/sbin/"
docker commit "$PREP" "$TAG.base" >/dev/null
docker rm -f "$PREP" >/dev/null
docker run --name "$PREP" "$TAG.base" bash -c "
  set -e
  chmod 0755 /usr/local/sbin/systemctl /usr/local/sbin/udevadm /usr/local/sbin/uname /usr/local/sbin/depmod
  echo 'FAKE_KERNEL=$KERNEL' > /etc/mfruit-rehearsal.env
  useradd -m -s /bin/bash -G audio,video,input orangepi
  printf 'orangepi ALL=(ALL) NOPASSWD:ALL\nDefaults env_keep += \"SYSROOT\"\n' > /etc/sudoers.d/rehearsal
  chmod 0440 /etc/sudoers.d/rehearsal
  mkdir -p /lib/modules/$KERNEL /fakeroot/proc/device-tree /etc/systemd/system
  printf '$MODEL\0' > /fakeroot/proc/device-tree/model
  printf '$COMPAT\0' > /fakeroot/proc/device-tree/compatible
  for d in boot etc dev usr; do ln -s /\$d /fakeroot/\$d; done; ln -s /proc/asound /fakeroot/proc/asound
  printf '$BOOT_TEXT' > $BOOT_FILE"
docker commit "$PREP" "$TAG" >/dev/null
docker rm -f "$PREP" >/dev/null
docker rmi -f "$TAG.base" >/dev/null

echo "==> 2. Offline install (no network): bash scripts/install.sh --yes"
NAME="$(basename "$PACK")"
# The board user runs the installer directly (not via sudo, so no SUDO_USER).
docker run --name "$RUN" --network none --hostname orangepizero2w --add-host orangepizero2w:127.0.1.1 \
  -v "$REPO:/src:ro" -v "$PACK:/pack:ro" "$TAG" \
  sudo -u orangepi -H env -u SUDO_USER -u SUDO_UID -u SUDO_GID -u SUDO_COMMAND \
  SYSROOT=/fakeroot SUITE="$SUITE" NAME="$NAME" bash -c '
  set -uo pipefail
  cd ~ && mkdir -p MFruitOS/offline && tar -C /src --exclude=./offline --exclude=./.git -cf - . | tar -C MFruitOS -xf -
  cp -R /pack "MFruitOS/offline/$NAME"
  cd MFruitOS
  bash scripts/install.sh --yes > ~/install.log 2>&1; rc=$?
  sed "s/\x1b\[[0-9;]*m//g" ~/install.log | grep -E "^==>|ok  |!!|xx|^\[[+!X]\]" | grep -v "^\[\*\]"
  echo "install.sh exit status: $rc"
  bash ~/MFruitOS/tests/fresh_install/verify.sh
  status=$?
  if [ "$SUITE" = 1 ]; then
    echo "==> real-daemon tests against the installed driver (WHISPLAY_SRC=/usr/local/share/whisplay)"
    for t in test_background_ui test_launch_lifecycle test_daemon_unregister test_dc_park; do
      printf "    %s: " "$t"
      WHISPLAY_SRC=/usr/local/share/whisplay PYTHONDONTWRITEBYTECODE=1 \
        python3 -m unittest discover -s tests -p "$t.py" > ~/$t.log 2>&1
      tail -1 ~/$t.log
      grep -q "^OK" ~/$t.log || { status=1; sed -n "/^ERROR:\|^FAIL:/,/^----------------------------------------------------------------------$/p" ~/$t.log | sed -n "1,40p"; ls /tmp/mfruit-realdaemon-*/daemon.log 2>/dev/null | head -1 | xargs -r tail -20; }
    done
  fi
  exit $(( rc || status ))'
