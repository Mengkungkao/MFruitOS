#!/bin/sh
# Optional smoke test, declared as "test" in manifest.json. Runs after install,
# before activation; a non-zero exit rolls the install back. Keep it fast and
# do not touch the display (another app owns it).
set -e
cd "$(dirname "$0")"
python3 -c "import ast, sys; [ast.parse(open(f).read(), f) for f in ('app/main.py', 'app/whisplay_app.py')]"
echo "hello-whisplay: test passed"
