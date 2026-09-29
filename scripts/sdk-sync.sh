#!/bin/sh
# Copy the MFruit App SDK into an app as its own package, mfruit_sdk/.
#
#   scripts/sdk-sync.sh <app python root>           copy (replaces mfruit_sdk/)
#   scripts/sdk-sync.sh <app python root> --check   exit 1 if the copy is out of date
#
# <app python root> is the directory the app's Python code imports from
# (where "import mfruit_sdk" must work), e.g. ~/Messenger or
# ~/ai-chatbot/whisplay-ai-chatbot/python.
set -eu

SRC="$(cd "$(dirname "$0")/.." && pwd)/mfruitos/sdk"
[ $# -ge 1 ] || { echo "usage: $0 <app python root> [--check]" >&2; exit 2; }
ROOT="$1"
DEST="$ROOT/mfruit_sdk"
[ -d "$ROOT" ] || { echo "no such directory: $ROOT" >&2; exit 2; }

if [ "${2:-}" = "--check" ]; then
  if diff -r -q -x __pycache__ -x VENDORED "$SRC" "$DEST" >/dev/null 2>&1; then
    echo "mfruit_sdk in $ROOT is up to date"
    exit 0
  fi
  echo "mfruit_sdk in $ROOT differs from $SRC; run: $0 $ROOT" >&2
  exit 1
fi

TMP="$DEST.new.$$"
rm -rf "$TMP"
mkdir -p "$TMP"
(cd "$SRC" && tar --exclude='__pycache__' --exclude='*.pyc' -cf - .) | (cd "$TMP" && tar -xf -)
VERSION="$(sed -n 's/^SDK_VERSION = "\(.*\)"/\1/p' "$SRC/__init__.py")"
cat > "$TMP/VENDORED" <<EOF
MFruit App SDK $VERSION, copied from MFruit OS (mfruitos/sdk).
Do not edit these files here: change them in MFruit OS, then run
MFruitOS/scripts/sdk-sync.sh <the directory that contains mfruit_sdk/>
EOF
rm -rf "$DEST"
mv "$TMP" "$DEST"
echo "mfruit_sdk $VERSION -> $DEST"
