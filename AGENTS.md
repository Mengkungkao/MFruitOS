# Agent orientation

You are working on **MFruit OS**, an application platform for small Linux
devices (today: whisplay-daemon on a Whisplay HAT). Before changing anything:

1. Read [docs/platform/DEVELOPMENT_RULES.md](docs/platform/DEVELOPMENT_RULES.md)
   — Part I is the project constitution and binds every change; Part II applies
   it to this code.
2. Read [CONTINUE.md](CONTINUE.md) (current hand-off) and
   [docs/quality/KNOWN_ISSUES.md](docs/quality/KNOWN_ISSUES.md).
3. Find the owner of the responsibility in
   [docs/platform/ARCHITECTURE.md](docs/platform/ARCHITECTURE.md) and its tests.

For a substantial request, give the engineering assessment first (current
state, problem, owning layer, proposed change, compatibility, tests,
documentation) and report afterwards what changed, what was verified, what was
not verified and the risks (Part I §32).

## Everyday commands (Linux, repository root)

```bash
bash scripts/check.sh                              # what CI runs
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python3 -m mfruitos --preview /tmp/mfruit-preview
python3 scripts/check-docs.py                      # Markdown links and anchors
```

Real-daemon tests need a Whisplay checkout (`WHISPLAY_SRC`); never run two
real-daemon suites at once.

## Hard rules worth repeating

- `ApplicationManager` is the only launch authority; selection never launches.
- No sleeps to fix races; synchronize on observed state.
- No app IDs special-cased in platform code; no new daemon socket code outside
  `mfruitos/daemon/`.
- Never destroy user data; never install over the active version.
- Never claim a test, device check or feature that was not performed or built
  (IMPLEMENTED ≠ AUTOMATED ≠ DEVICE VERIFIED).
- Commit or push only when the user asks. Keep `CONTINUE.md` current.
