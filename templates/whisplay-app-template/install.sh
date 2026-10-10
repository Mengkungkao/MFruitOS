#!/bin/sh
# Runs inside the new version's folder during install AND update, before the
# version is activated. A non-zero exit aborts the install and mFruit OS
# restores the previous version. Runs as the normal user, without a terminal.
#
# Useful environment: WHISPLAY_APP_ID, WHISPLAY_OS_APP_DIR (this folder),
# WHISPLAY_OS_APP_DATA (persistent data dir), WHISPLAY_OS_VERSION,
# WHISPLAY_OS_PREVIOUS_VERSION (empty on first install).
set -e

python3 -c "import PIL" || { echo "Pillow is required: sudo apt install python3-pil"; exit 1; }

# Extra Python packages? Put them in a venv inside the data dir, e.g.:
#   python3 -m venv --system-site-packages "$WHISPLAY_OS_APP_DATA/venv"
#   "$WHISPLAY_OS_APP_DATA/venv/bin/pip" install -r requirements.txt
echo "hello-whisplay: nothing else to install"
