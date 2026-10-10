#!/bin/sh
# Entrypoint. mFruit OS runs this with the working directory set to the app
# and WHISPLAY_APP_ID / WHISPLAY_OS_APP_DATA in the environment.
cd "$(dirname "$0")" || exit 1
PYTHON=python3
# Use a virtualenv created by install.sh, if any (kept in the data dir so it
# survives updates).
if [ -n "${WHISPLAY_OS_APP_DATA:-}" ] && [ -x "$WHISPLAY_OS_APP_DATA/venv/bin/python" ]; then
  PYTHON="$WHISPLAY_OS_APP_DATA/venv/bin/python"
fi
exec "$PYTHON" app/main.py
