#!/usr/bin/env bash
# Build mFruit OS's system package, the asset devices update from in
# Settings > System > System update.
#
#   bash scripts/build-release.sh [OUT_DIR]     (default: ./release)
#
# Produces OUT_DIR/mfruit-os-<version>.tar.gz and its .sha256: one folder,
# mfruit-os/, holding the tracked files scripts/install.sh installs (the same
# list; tests/test_build_release.py keeps them equal). The archive is checked
# the way a device checks it before activation: its manifest is the system
# package of this version and `python3 -m mfruitos --self-test` passes in it.
# .github/workflows/release.yml runs this for every new manifest version.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mkdir -p "${1:-$ROOT/release}" && cd "${1:-$ROOT/release}" && pwd)"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/manifest.json")"
NAME="mfruit-os-$VERSION"
# What scripts/install.sh copies into ~/.whisplay-os/system/versions/.
ITEMS=(mfruitos assets config scripts templates docs bundled drivers manifest.json LICENSE README.md
       APP_DEVELOPMENT.md INSTALL.md CHANGELOG.md CONTRIBUTING.md)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PKG="$WORK/mfruit-os"
mkdir -p "$PKG"
(cd "$ROOT" && git ls-files -z -- "${ITEMS[@]}") \
  | (cd "$ROOT" && tar --null -T - -cf -) | tar -xf - -C "$PKG"

python3 - "$PKG" "$VERSION" <<'PY'
import json, sys
manifest = json.load(open(f"{sys.argv[1]}/manifest.json"))
assert manifest["id"] == "mfruit-os" and manifest["type"] == "system", manifest
assert manifest["version"] == sys.argv[2], manifest
PY
(cd "$PKG" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PKG" python3 -m mfruitos --self-test)
find "$PKG" -name __pycache__ -prune -exec rm -rf {} +

tar --sort=name --owner=0 --group=0 --numeric-owner -C "$WORK" -czf "$OUT/$NAME.tar.gz" mfruit-os
(cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "$OUT/$NAME.tar.gz: $(du -h "$OUT/$NAME.tar.gz" | cut -f1), $(find "$PKG" -type f | wc -l) files"
cat "$OUT/$NAME.tar.gz.sha256"
