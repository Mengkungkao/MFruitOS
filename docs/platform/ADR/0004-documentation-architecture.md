# ADR 0004 — Constitution and three-domain documentation

Status: Accepted 2026-10-02.

## Context

Guidance had grown in three overlapping places (root guides, `docs/os/`,
`docs/quality/`), dated reports sat beside current guides, the hand-off file
repeated an archived record, and links pointed to a deleted `CLAUDE.md`. The
project owner supplied a development constitution and a target documentation
tree.

## Decision

- The constitution is Part I of
  [docs/platform/DEVELOPMENT_RULES.md](../DEVELOPMENT_RULES.md); Part II applies
  it to this repository.
- Documentation has three domains — `docs/platform/`, `docs/apps/`,
  `docs/quality/` — with one canonical document per concept; others link to it.
- Dated evidence lives in `docs/quality/records/`; `CONTINUE.md` is a short,
  current hand-off; `CLAUDE.md` and `AGENTS.md` point agents at the rules.
- Former paths referenced by app repositories keep short pointer files
  (`APP_DEVELOPMENT.md`, `INSTALL.md`, `docs/APP_RULES.md`,
  `docs/ARCHITECTURE.md`).
- `scripts/check-docs.py` checks relative links and anchors, locally and in CI.

## Alternatives

- **Keep `docs/os/`** — rejected: does not match the owner's tree and kept
  duplicates.
- **Delete old paths outright** — rejected for paths app repositories cite.

## Consequences

Contributors find one authoritative document per topic. The app contract
moved, so app repositories must refresh `.claude/rules/mfruit-os-app.md`.

## Compatibility

`scripts/check-app.py` compares app copies with `docs/apps/APP_CONTRACT.md`;
the in-repo template copy is updated, companion app copies need a refresh.
Installed versions ship the `docs/` tree as before.

## Validation

`scripts/check-docs.py` passes; `tests/test_check_app.py`,
`tests/test_template.py` and `tests/test_device_setup.py` pass with the new
paths.
