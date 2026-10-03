# Architecture decision records

Significant architectural decisions, one file each, using the structure in
[Part I §23](../DEVELOPMENT_RULES.md#23-architecture-decision-records):
Context, Decision, Alternatives, Consequences, Compatibility, Validation.
Trivial implementation details do not get an ADR.

Name new records `NNNN-short-title.md` with the next number. A record is never
rewritten to change its decision; a later record supersedes it.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-application-manager-single-launch-authority.md) | ApplicationManager is the single launch authority | Accepted (1.1.0, recorded 2026-10-02) |
| [0002](0002-launch-gate-and-background-daemon-ui.md) | Launch gate tickets and the daemon UI in the background | Accepted (1.1.0/1.2.0, recorded 2026-10-02) |
| [0003](0003-vendored-sdk-distribution.md) | Vendored SDK distribution with drift checks | Accepted (1.3.0, recorded 2026-10-02) |
| [0004](0004-documentation-architecture.md) | Constitution and three-domain documentation | Accepted (2026-10-02) |
| [0005](0005-incremental-host-boundary-extraction.md) | Incremental host boundary extraction | Accepted (2026-10-02); implementation PLANNED |
| [0007](0007-shared-radio-capability.md) | The LoRa radio is a shared, platform-owned capability | Accepted 2026-10-03 |
| [0006](0006-settings-provider-apps.md) | Settings provider apps instead of a hard-coded Wi-Fi app | **Proposed** — awaiting the owner's decision |
