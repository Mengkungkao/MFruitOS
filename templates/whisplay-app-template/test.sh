#!/bin/sh
# Optional smoke test, declared as "test" in manifest.json. Runs after install,
# before activation; a non-zero exit rolls the install back. Keep it fast and
# do not touch the display (another app owns it).
set -e
cd "$(dirname "$0")"
# Imports the app and its mFruit App SDK copy (nothing runs on import).
(cd app && python3 -c "import main; main.render(1)")
echo "hello-whisplay: test passed"
