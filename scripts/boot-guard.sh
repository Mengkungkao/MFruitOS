#!/bin/sh
# boot-guard.sh — runs before every launcher start (systemd ExecStartPre).
#
# After a system update is activated, MFruit OS writes
# state/pending_system_update.env. The launcher deletes it once the new
# version has run healthily for 15 s. If instead the service keeps failing,
# this guard switches ~/.whisplay-os/system/current back to the previous
# version after MAX_ATTEMPTS starts. It is plain sh so it works even when the
# new Python code cannot start at all.
OS_HOME="${WHISPLAY_OS_HOME:-$HOME/.whisplay-os}"
STATE="$OS_HOME/state"
SYSTEM="$OS_HOME/system"
PENDING="$STATE/pending_system_update.env"
MAX_ATTEMPTS=3

[ -f "$PENDING" ] || exit 0

PREVIOUS_DIR=$(sed -n 's/^PREVIOUS_DIR=//p' "$PENDING" | head -n 1)
ATTEMPTS=$(sed -n 's/^ATTEMPTS=//p' "$PENDING" | head -n 1)
case "$ATTEMPTS" in ''|*[!0-9]*) ATTEMPTS=0 ;; esac
ATTEMPTS=$((ATTEMPTS + 1))

if [ "$ATTEMPTS" -le "$MAX_ATTEMPTS" ]; then
  printf 'PREVIOUS_DIR=%s\nATTEMPTS=%s\n' "$PREVIOUS_DIR" "$ATTEMPTS" > "$PENDING.tmp" \
    && mv "$PENDING.tmp" "$PENDING"
  echo "boot-guard: new system version, start attempt $ATTEMPTS/$MAX_ATTEMPTS"
  exit 0
fi

case "$PREVIOUS_DIR" in
  "$SYSTEM"/versions/*) ;;
  *)
    echo "boot-guard: no valid previous version recorded ('$PREVIOUS_DIR'); keeping current" >&2
    rm -f "$PENDING" "$STATE/pending_system_update.json"
    exit 0 ;;
esac

if [ -d "$PREVIOUS_DIR" ]; then
  ln -sfn "versions/$(basename "$PREVIOUS_DIR")" "$SYSTEM/current.tmp" \
    && mv -T "$SYSTEM/current.tmp" "$SYSTEM/current"
  printf 'ROLLED_BACK_TO=%s\n' "$PREVIOUS_DIR" > "$STATE/system_rollback.env"
  echo "boot-guard: new version failed to start $MAX_ATTEMPTS times; rolled back to $PREVIOUS_DIR"
else
  echo "boot-guard: previous version $PREVIOUS_DIR is gone; cannot roll back" >&2
fi
rm -f "$PENDING" "$STATE/pending_system_update.json"
exit 0
