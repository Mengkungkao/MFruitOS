#!/usr/bin/env bash
# Refresh drivers/whisplay from a PiSugar/Whisplay checkout (developer tool).
#
#   bash scripts/whisplay-driver-sync.sh /path/to/Whisplay          copy the driver files
#   bash scripts/whisplay-driver-sync.sh --check                    verify upstream.sha256
#
# Copies exactly the files listed in drivers/whisplay/upstream.sha256 (plus any
# new file in the same driver directories, which is reported for review),
# rewrites the checksums and the commit line in UPSTREAM.md. It never edits
# the copied files. See drivers/whisplay/UPSTREAM.md.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=drivers/whisplay

if [ "${1:-}" = "--check" ]; then
  (cd "$DEST" && sha256sum --quiet --strict -c upstream.sha256)
  exit $?
fi
SRC="${1:?usage: whisplay-driver-sync.sh /path/to/Whisplay | --check}"
[ -f "$SRC/daemon/whisplay_daemon.py" ] || { echo "not a Whisplay checkout: $SRC" >&2; exit 1; }
COMMIT="$(git -C "$SRC" rev-parse HEAD)"
[ -z "$(git -C "$SRC" status --porcelain)" ] || { echo "$SRC has local changes; use a clean checkout" >&2; exit 1; }

LISTED="$(cut -c67- "$DEST/upstream.sha256")"
# Same selection as the first copy: driver directories only (UPSTREAM.md lists what is left out).
CANDIDATES="$(git -C "$SRC" ls-files LICENSE runtime/whisplay.py runtime/whisplay_client.py \
  'daemon/*.py' 'daemon/internal_apps/*.py' 'daemon/img/wifi-*.png' 'daemon/tests/*.py' \
  'audio/whisplay-soundcard/configs/*' audio/whisplay-soundcard/scripts/install.sh \
  audio/whisplay-soundcard/scripts/uninstall.sh audio/whisplay-soundcard/scripts/recover-a7z-i2c.sh \
  'audio/whisplay-soundcard/src/*')"
for f in $LISTED; do
  [ -f "$SRC/$f" ] || { echo "removed upstream: $f (review, then delete it from $DEST)"; }
done
for f in $CANDIDATES; do
  echo "$LISTED" | grep -qx "$f" || echo "new upstream file: $f"
  mkdir -p "$DEST/$(dirname "$f")"
  cp -p "$SRC/$f" "$DEST/$f"
done
(cd "$SRC" && sha256sum $CANDIDATES) > "$DEST/upstream.sha256"
sed -i "s|^Commit: \`[0-9a-f]*\`.*|Commit: \`$COMMIT\` ($(git -C "$SRC" log -1 --format='%cs, "%s"'))|" "$DEST/UPSTREAM.md"
echo "drivers/whisplay now matches PiSugar/Whisplay $COMMIT; run bash scripts/check.sh"
