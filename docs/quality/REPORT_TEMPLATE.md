# Validation report template

Copy this outline into a dated report when an investigation or validation
produces evidence worth retaining.

```markdown
# <Feature or issue> — YYYY-MM-DD

## Scope
- Source commit and working-tree state:
- Board/OS/architecture:
- Python/Pillow and relevant dependency versions:

## Reproduction or change
- Expected behavior:
- Observed behavior:
- Root cause (or current hypothesis):
- Fix and regression coverage:

## Results
| Check | Command or procedure | Result |
|---|---|---|

## Remaining limitations
- Automated checks not run or skipped:
- Physical/service checks not verified:
- Follow-up owner/action:
```

Separate observation from hypothesis and confirmed root cause. Keep sensitive
device details and private app data out of reports. Link the report from
[known issues](KNOWN_ISSUES.md) while work remains open, then retain it under
[dated records](README.md#dated-records).
