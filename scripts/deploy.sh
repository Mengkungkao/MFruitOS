#!/usr/bin/env bash
# Copy this checkout to a device over SSH and install it (development helper).
#
#   scripts/deploy.sh jarvis@192.168.0.33
#   scripts/deploy.sh orangepi@192.168.0.130 --no-service
set -euo pipefail
HOST="${1:?usage: deploy.sh user@host [install.sh options]}"
shift
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="MFruitOS"

echo "==> syncing to $HOST:~/$DEST"
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' -C "$SRC" -czf - . \
  | ssh "$HOST" "mkdir -p ~/$DEST && tar -xzf - -C ~/$DEST"
echo "==> installing"
ssh -t "$HOST" "bash ~/$DEST/scripts/install.sh --yes $*"
