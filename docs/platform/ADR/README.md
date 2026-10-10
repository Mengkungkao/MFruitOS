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
| [0008](0008-bundled-whisplay-driver.md) | mFruit OS ships the Whisplay driver | Accepted 2026-10-03 |
| [0009](0009-app-background-request.md) | Apps can ask to keep running with the screen held bright | Accepted 2026-10-04 |
| [0010](0010-online-fruit-store-catalogue.md) | The Fruit Store list is downloaded, the bundled list is the fallback | Accepted 2026-10-05 |
| [0011](0011-catalogue-system-packages.md) | Fruit Store entries declare system packages; setup-app.sh installs them | Accepted 2026-10-05 |
| [0012](0012-own-power-management.md) | mFruit OS has its own power management | Accepted 2026-10-10 |
| [0013](0013-phone-wifi-setup.md) | Wi-Fi from a phone with PiSugar's sugar-wifi-conf, run by mFruit OS | Accepted 2026-10-10 |
| [0006](0006-settings-provider-apps.md) | Settings provider apps instead of a hard-coded Wi-Fi app | **Proposed** — awaiting the owner's decision |
