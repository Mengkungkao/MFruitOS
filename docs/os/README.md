# MFruit OS development

This section is for people installing, maintaining or extending MFruit OS itself.
For an independent application, start with [app integration](../apps/README.md).
For failures, test evidence and fixes, use [quality and troubleshooting](../quality/README.md).

| Need | Read |
|---|---|
| Understand the purpose, priorities and next milestones | [Project direction and goals](DIRECTION.md) |
| Find the component responsible for a change | [Current architecture](../ARCHITECTURE.md) |
| Follow the engineering rules and contribution workflow | [Development guide](DEVELOPMENT.md) |
| Build consistent screens and readable code | [UI and code style](STYLE.md) |
| Install or update an already prepared device | [Installation](../../INSTALL.md) |
| Prepare, deploy, validate and recover another board | [Device setup](../DEVICE_SETUP.md) |
| Resume the current development work | [Current handoff](../../CONTINUE.md) |

MFruit OS is a lightweight application platform on Linux. The current full
launcher uses whisplay-daemon; hardware independence is a staged development
goal. Offline screen previews and core tests already work without a physical
HAT. See the [capability boundary](DIRECTION.md#current-capability-and-target)
before planning a port or integration.

The documentation describes the source tree; it does not certify a device or a
release. Check [known issues](../quality/KNOWN_ISSUES.md) and record verification
against the exact revision being installed.

[All documentation](../README.md)
