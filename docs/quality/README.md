# Quality, testing and troubleshooting

This section separates current issues, repeatable test procedures and dated
evidence. A successful focused test is not a full-suite pass; an automated pass
does not certify physical hardware.

| Need | Read |
|---|---|
| Run the right local, integration and hardware checks | [Testing guide](TESTING.md) |
| See the current unresolved items and their status | [Known issues](KNOWN_ISSUES.md) |
| Reproduce the app launch/input guarantees | [Launch lifecycle](../LAUNCH_LIFECYCLE.md) |
| Perform physical button, keyboard, display and device checks | [Hardware tests](../HARDWARE_TESTS.md) |
| Record a new investigation or validation result | [Report template](REPORT_TEMPLATE.md) |
| Review dated validation results | [Validation records](#dated-records) |

## Dated records

These reports describe specific revisions and devices. Their results are
historical and should not be presented as verification of the current checkout.

- [MFruit OS and companion integration validation, 2026-09-30](../VALIDATION_2026-09-30.md)
- [Settings and package validation, 2026-09-30](../VALIDATION_SETTINGS_2026-09-30.md)
- [Git integration record, 2026-09-30](../INTEGRATION_2026-09-30.md)
- [Installer validation handoff, 2026-10-01](records/HANDOFF_2026-10-01.md)
- [Current development handoff](../../CONTINUE.md)

For new evidence, include the source revision, environment, exact command,
pass/fail/skip counts, relevant logs and the checks that remain unverified.
Keep credentials, private messages and personal data out of committed reports.

[Documentation home](../README.md) · [OS development](../os/README.md) · [App integration](../apps/README.md)
