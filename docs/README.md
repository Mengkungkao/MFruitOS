# MFruit OS documentation

Three domains, one canonical document per concept
([ADR 0004](platform/ADR/0004-documentation-architecture.md)). Status words
(IMPLEMENTED, AUTOMATED, DEVICE VERIFIED, NOT VERIFIED, PLANNED) mean exactly
what [Part I §20](platform/DEVELOPMENT_RULES.md#20-quality-status-language)
says.

| Domain | For | Start at |
|---|---|---|
| [Platform / OS development](platform/README.md) | changing MFruit OS itself: rules, architecture, lifecycle, host API, installation, configuration, security, roadmap, ADRs | [Development rules](platform/DEVELOPMENT_RULES.md) |
| [App development](apps/README.md) | building, packaging, publishing and migrating apps | [Getting started](apps/GETTING_STARTED.md) |
| [Quality](quality/README.md) | testing, validation, known issues, troubleshooting, records | [Known issues](quality/KNOWN_ISSUES.md) |

## I want to…

| Task | Read |
|---|---|
| Install, update or remove MFruit OS | [Installation](platform/INSTALLATION.md) |
| Understand who owns what | [Architecture](platform/ARCHITECTURE.md) |
| Fix a launch, input or focus problem | [Lifecycle](platform/LIFECYCLE.md), [Troubleshooting](quality/TROUBLESHOOTING.md) |
| Build a new app | [Getting started](apps/GETTING_STARTED.md), [App contract](apps/APP_CONTRACT.md) |
| Bring an existing Whisplay app over | [Migrating an existing app](apps/MIGRATING_EXISTING_APP.md) |
| Run the tests | [Testing](quality/TESTING.md) |
| Record a validation or a bug | [Validation](quality/VALIDATION.md), [Bug template](quality/BUG_TEMPLATE.md) |
| See what changed | [Changelog](../CHANGELOG.md) |
| Continue the current work | [CONTINUE.md](../CONTINUE.md) |
