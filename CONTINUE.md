# CONTINUE — current hand-off

Read this first, then [known issues](docs/quality/KNOWN_ISSUES.md). The rules
are in [docs/platform/DEVELOPMENT_RULES.md](docs/platform/DEVELOPMENT_RULES.md).
History: [docs/quality/records/](docs/quality/records/README.md) (the previous
hand-off is preserved verbatim in
[2026-10-01-handoff.md](docs/quality/records/2026-10-01-handoff.md)).

## Session 2026-10-02 — constitution, docs architecture, CI, launch-window test

The user supplied the project constitution, target architecture and
documentation tree. Work proceeds in checkpoints; nothing is committed or
pushed unless the user asks.

| # | Checkpoint | Status |
|---|---|---|
| 0 | Baseline full suite on this machine (aarch64, Python 3.12.3, Pillow 10.2.0, Whisplay `e57cc4c`) | AUTOMATED: 348/348 passed, 0 skipped |
| 1 | Launch-window test: root cause and fix | DONE: daemon hold→tap race (not MFruit OS); test synchronizes on daemon state, retries across pages, plus a deterministic variant; 20/20 iterations pass (was 5/20 failing); negative control fails both tests |
| 2 | Docs restructure into `docs/platform`, `docs/apps`, `docs/quality` | IN PROGRESS |
| 3 | CI workflow + `scripts/check.sh` + docs link checker | TODO |
| 4 | Sideloaded-folder validation (same rules as archives) + regression tests | TODO |
| 5 | Full suite rerun, dated record, CHANGELOG, final report | TODO |

### Checkpoint 2 progress

Done: files moved with `git mv`; written `docs/platform/{DEVELOPMENT_RULES,
ARCHITECTURE, HOST_API, LIFECYCLE, INSTALLATION, CONFIGURATION, SECURITY,
DIRECTORY_STRUCTURE}.md`; `STYLE_GUIDE.md` intro/links updated.
Paused here at the user's request (2026-10-02).
Remaining: `ROADMAP`, `ADR/` (0001–0005 are referenced already),
platform `README`; all of `docs/apps/` (APP_CONTRACT update + template copy +
`scripts/check-app.py` path); `docs/quality/` docs; records index and link
fixes; `docs/platform/DEVICE_SETUP.md` is merged into `INSTALLATION.md` and
must be deleted; root stubs (`INSTALL.md`, `APP_DEVELOPMENT.md`,
`docs/APP_RULES.md`, `docs/ARCHITECTURE.md`); `README.md`, `CONTRIBUTING.md`,
`CLAUDE.md`, `AGENTS.md`; code/test references to old doc paths
(`scripts/install.sh` doc list, `tests/test_device_setup.py`,
`tests/test_check_app.py`, `scripts/setup-device.sh`, docstrings citing
`CLAUDE.md §N`). Until finished, some relative links are broken.

### Evidence for checkpoint 1 (scratch, may be deleted)

`/tmp/claude-1000/-home-meng-MFruitOS/c08a7400-e590-4d22-b812-0da4f6293880/scratchpad/`:
`baseline-full.log`, `flaky-run-*.log`, `diag/` (daemon traces), `fixed-run-*.log`,
`negative_control.py`. The durable summary goes into
`docs/quality/records/2026-10-02-baseline-and-launch-window.md`.

## Standing facts

- Boards: Raspberry Pi Zero 2 W (`jarvis@192.168.0.33`) has commit `cfe8ac2`
  installed (2026-10-01); Orange Pi state is older (see the 2026-10-01 record).
  Physical checks remain the user's (see [Validation](docs/quality/VALIDATION.md)).
- Never run two real-daemon test suites at once (they share fake-app clean-up).
- Companion app repos (`~/Messenger`, `~/WalkieTalkie`, `~/ai-chatbot`,
  `~/whisplay-crypto-dashboard`) carry copies of the app contract and SDK; do
  not change them without the user's go-ahead.
