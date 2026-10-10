#!/usr/bin/env bash
# Keep a device's ~/MFruitOS identical to this checkout, then install it.
#
#   scripts/deploy.sh orangepi@192.168.0.130               sync, then install.sh --yes
#   scripts/deploy.sh orangepi@192.168.0.130 --no-service  sync, then install files only
#   scripts/deploy.sh orangepi@192.168.0.130 --sync-only   sync only
#
# One folder per device: ~/MFruitOS becomes an exact copy of this working tree
# (files removed here are removed there); the device's own .git and offline/
# packs are kept. When ~/MFruitOS is a git clone it is first moved to this
# checkout's commit (only a fast-forward, after a fetch), so `git status`
# matches on both machines. Other options go to scripts/install.sh.
set -euo pipefail
HOST="${1:?usage: deploy.sh user@host [--sync-only | install.sh options]}"
shift
SYNC_ONLY=0
if [ "${1:-}" = "--sync-only" ]; then SYNC_ONLY=1; shift; fi
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="MFruitOS"
HEAD="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)"

if [ -n "$HEAD" ]; then
  echo "==> moving $HOST:~/$DEST to commit ${HEAD:0:7}"
  # reset --mixed moves the branch and index only; the files come from rsync below.
  ssh "$HOST" "cd ~/$DEST 2>/dev/null && [ -d .git ] || exit 0
    git fetch -q origin 2>/dev/null || true
    if ! git cat-file -e $HEAD^{commit} 2>/dev/null; then
      echo '    !! that commit is not on the device (not pushed yet); files are synced anyway'
    elif git merge-base --is-ancestor HEAD $HEAD; then
      git reset -q --mixed $HEAD
    else
      echo '    !! the device clone has its own commits; left on' \$(git rev-parse --short HEAD)
    fi"
fi

echo "==> syncing to $HOST:~/$DEST"
EXCLUDES=(--exclude=.git/ --exclude=/offline/ --exclude=__pycache__/ --exclude='*.pyc')
if command -v rsync >/dev/null && ssh "$HOST" "command -v rsync >/dev/null"; then
  rsync -a --delete "${EXCLUDES[@]}" "$SRC"/ "$HOST:$DEST/"
else
  echo "    rsync missing: copying with tar (files removed here stay there)"
  tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='./offline' -C "$SRC" -czf - . \
    | ssh "$HOST" "mkdir -p ~/$DEST && tar -xzf - -C ~/$DEST"
fi

if [ -n "$HEAD" ]; then
  here="$(git -C "$SRC" status --porcelain | sort | md5sum)"
  there="$(ssh "$HOST" "cd ~/$DEST && [ -d .git ] && git status --porcelain | sort | md5sum" || true)"
  if [ "$here" = "$there" ]; then echo "    in sync: the same commit and the same changes"
  else echo "    !! git status differs between here and the device"; fi
fi

[ "$SYNC_ONLY" = 0 ] || exit 0
echo "==> installing"
ssh -t "$HOST" "bash ~/$DEST/scripts/install.sh --yes $*"
