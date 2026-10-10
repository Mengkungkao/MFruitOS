#!/usr/bin/env bash
# Run the repository checks CI runs, locally (no hardware needed).
#
#   bash scripts/check.sh           all checks
#   bash scripts/check.sh --quick   skip the full unit/integration suite
#
# Real-daemon tests run the daemon bundled in drivers/whisplay (WHISPLAY_SRC
# substitutes another Whisplay checkout). Never run two real-daemon suites at
# once on one machine.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1
PYTHON="${PYTHON:-python3}"
FAILED=()

step() {
  local name="$1"; shift
  printf '\n==> %s\n' "$name"
  if "$@"; then printf '    ok  %s\n' "$name"; else printf '    FAIL  %s\n' "$name"; FAILED+=("$name"); fi
}

py39_syntax() {
  "$PYTHON" - <<'PY'
import ast, pathlib, sys
bad = 0
TYPE_NAMES = {"int", "str", "float", "bool", "bytes", "dict", "list", "tuple", "set", "type", "object"}

def typeish(node):
    return ((isinstance(node, ast.Constant) and node.value is None)
            or (isinstance(node, ast.Name) and node.id in TYPE_NAMES)
            or isinstance(node, ast.Subscript)
            or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)))

def runtime_unions(tree):
    """'X | None' outside annotations: valid 3.9 syntax, but evaluated at run
    time it raises TypeError before Python 3.10 (annotations are strings with
    'from __future__ import annotations')."""
    skip = set()
    for node in ast.walk(tree):
        parts = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            parts = [a.annotation for a in args.posonlyargs + args.args + args.kwonlyargs
                     + [args.vararg, args.kwarg] if a is not None] + [node.returns]
        elif isinstance(node, ast.AnnAssign):
            parts = [node.annotation]
        for part in parts:
            if part is not None:
                skip.update(id(n) for n in ast.walk(part))
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
            and id(node) not in skip and typeish(node.left) and typeish(node.right)]

# Python scripts without the .py suffix are listed explicitly. The bundled
# Whisplay driver is upstream's (not edited here).
for path in sorted(pathlib.Path(".").rglob("*.py")) + [pathlib.Path("scripts/mfruit-power-off")]:
    if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in path.parts):
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path), feature_version=(3, 9))
    except SyntaxError as exc:
        print(f"{path}:{exc.lineno}: not Python 3.9 syntax: {exc.msg}")
        bad += 1
        continue
    if path.parts[:2] == ("drivers", "whisplay"):
        continue
    for node in runtime_unions(tree):
        print(f"{path}:{node.lineno}: 'X | Y' evaluated at run time needs Python 3.10; use Optional/Union")
        bad += 1
sys.exit(1 if bad else 0)
PY
}

shell_syntax() {
  local ok=0 f
  for f in scripts/*.sh templates/whisplay-app-template/*.sh bundled/connectwifi/*.sh drivers/whisplay/*.sh; do
    [ -f "$f" ] || continue
    if head -1 "$f" | grep -q bash; then bash -n "$f" || ok=1; else sh -n "$f" || ok=1; fi
  done
  for f in tests/fresh_install/*.sh tests/fresh_install/fakes/systemctl tests/distro/*.sh; do bash -n "$f" || ok=1; done
  for f in tests/fresh_install/fakes/udevadm tests/fresh_install/fakes/uname tests/fresh_install/fakes/depmod; do
    sh -n "$f" || ok=1
  done
  # Whisplay's sound card scripts start as sh and re-run themselves under bash.
  for f in drivers/whisplay/audio/whisplay-soundcard/scripts/*.sh; do bash -n "$f" || ok=1; done
  sh -n scripts/mfruit-run || ok=1
  sh -n scripts/mfruitctl || ok=1
  return $ok
}

line_endings() {
  local bad
  bad="$(git ls-files -z -- '*.py' '*.sh' 'scripts/mfruit-run' 'scripts/mfruitctl' \
         | xargs -0 grep -lI $'\r' 2>/dev/null || true)"
  [ -z "$bad" ] || { echo "CRLF line endings in:"; echo "$bad"; return 1; }
}

whitespace() {
  git diff --check 4b825dc642cb6eb9a060e54bf8d69288fbee4904 HEAD -- . && git diff --check && git diff --cached --check
}

step "Python 3.9 syntax and run-time unions" py39_syntax
step "shell syntax" shell_syntax
step "LF line endings" line_endings
step "whitespace" whitespace
step "Markdown links" "$PYTHON" scripts/check-docs.py
step "Whisplay driver files match upstream" bash scripts/whisplay-driver-sync.sh --check
step "Whisplay daemon upstream tests" "$PYTHON" -m unittest discover -s drivers/whisplay/daemon/tests \
  -t drivers/whisplay/daemon/tests
step "template package preflight" "$PYTHON" scripts/check-app.py templates/whisplay-app-template
step "template SDK copy" sh scripts/sdk-sync.sh templates/whisplay-app-template/app --check
step "offscreen self-test" "$PYTHON" -m mfruitos --self-test
if [ "$QUICK" = 0 ]; then
  step "unit, integration and real-daemon tests" "$PYTHON" -m unittest discover -s tests
fi

printf '\n'
if [ "${#FAILED[@]}" -gt 0 ]; then
  printf 'FAILED: %s\n' "${FAILED[@]}"
  exit 1
fi
echo "All checks passed."
