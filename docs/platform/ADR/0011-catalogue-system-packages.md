# ADR 0011: Fruit Store entries declare system packages; setup-app.sh installs them

## Context

AI Chatbot needs Debian packages (sox, mpg123, python3-cairosvg, …). Store
installs run as the user without sudo (package hooks have no terminal and must
not escalate), so its install could only fail. The radio has its own device
setup (`setup-radio.sh`, ADR 0007), but packages that belong to one app are
not a device capability.

## Decision

- A catalogue entry may list `system_packages`: Debian package names
  (validated, at most 40). MFruit OS treats missing ones as an unmet
  requirement (`dpkg-query`): the Store shows *Needs setup first* and the
  command, and queued installs wait.
- `scripts/setup-app.sh <id>…`, run by the user over SSH, installs only the
  missing packages with sudo through `scripts/offline.sh` and queues the app
  (`updater/autoinstall.py`); the launcher installs it like the Store does.
  `install.sh --app <id>` runs it, and the installer offers such apps.
- The app's own `install.sh` still checks what it needs and names the command.

## Alternatives

- **Sudo from the Store or package hooks:** a privileged path driven by
  downloaded content; refused.
- **An installer option per app (`--chatbot`):** special-cases an app ID in
  platform code (Part II); the field keeps it generic.
- **A device capability per app (`requires: ["chatbot"]`):** the same
  special case in `REQUIREMENTS`.

## Consequences

Packages are installed only with the user's sudo and only the names the
validated list declares; the list is as trusted as `system.repository`
(ADR 0010). Package names are Debian's: an entry for a board whose OS names a
package differently fails at setup with apt's message.

## Compatibility

Older MFruit OS versions ignore the field: they list the entry and its own
`install.sh` stops with the instruction (whose script they lack). Entries
without the field are unchanged.

## Validation

`tests/test_system_packages.py` (field validation, dpkg parsing, requirement
and queue wait, Store text, `setup-app.sh` with command doubles). Device:
[record](../../quality/records/2026-10-05-ai-chatbot-store.md).
