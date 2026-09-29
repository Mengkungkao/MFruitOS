#!/bin/sh
# Optional. Runs after install.sh when upgrading or downgrading (not on first
# install). Use it to migrate files in $WHISPLAY_OS_APP_DATA. The data dir is
# snapshotted beforehand and restored if this script fails.
set -e
echo "hello-whisplay: updating from ${WHISPLAY_OS_PREVIOUS_VERSION:-?}"
