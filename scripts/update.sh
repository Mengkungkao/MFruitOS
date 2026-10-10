#!/usr/bin/env bash
# Update mFruit OS from this git checkout and reinstall it.
#
# For devices without a checkout, use Settings > System > System update
# (GitHub releases) instead.
#
# The previous installed version is kept in ~/.whisplay-os/system/versions,
# and install.sh restores it automatically if the new one fails its self-test.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -d "$SRC/.git" ]; then
  if [ -n "$(git -C "$SRC" status --porcelain --untracked-files=no)" ]; then
    echo "Local changes in $SRC; commit or stash them first." >&2
    exit 1
  fi
  echo "==> git pull --ff-only"
  git -C "$SRC" pull --ff-only
fi
exec bash "$SRC/scripts/install.sh" --yes "$@"
