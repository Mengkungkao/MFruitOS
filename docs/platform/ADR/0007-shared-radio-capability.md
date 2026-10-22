# ADR 0007 — The LoRa radio is a shared, platform-owned capability

Status: Accepted 2026-10-03 (owner's decisions: one-time SSH setup, AU915,
pair once for both apps). Implementation: platform and SDK done; app
adoption in progress ([known issues](../../quality/KNOWN_ISSUES.md)).

## Context

WalkieTalkie and Messenger share one Waveshare SX126X HAT. Before this
decision:

- Each app carried its own `provision_radio.py` and SX126X driver; radio
  setup (packages incl. `libcodec2`, UART, serial console, getty, module
  provisioning) lived only in WalkieTalkie's own installer and needs root and
  often a reboot, which mFruit OS app hooks cannot do (they run as the user,
  noninteractively, [Part I §11](../DEVELOPMENT_RULES.md#11-application-dependencies)).
- Messenger found the radio settings by reading `../WalkieTalkie/config.yaml`,
  which does not exist under managed installs.
- Pairing (X25519 + ChaCha20-Poly1305) existed only in WalkieTalkie, with its
  own Device ID; Messenger derived another ID from the hostname.

## Decision

1. **Setup is a host capability.** `mfruitos/hosts/lora/` provisions the module
   (ported from WalkieTalkie) and reports readiness. `scripts/setup-radio.sh`
   is the one-time privileged setup the user runs over SSH with their sudo
   password: packages, UART, serial console, getty, `dialout`, reboot
   handling, provisioning (default band AU915, 920 MHz, 2400 bps). No
   passwordless root rule is added.
2. **One shared radio store** at `<mFruit OS home>/shared/radio/` (0700), owned
   by the SDK module `mfruit_sdk.radio` (SDK 1.3.0): `radio.json` (written only
   by the setup), `device.json` (Device ID and name), `keys.json` (the existing
   WalkieTalkie key format), `contacts.json`. Pairing in one app is pairing in
   all. Writes are atomic, 0600, under an exclusive lock; readers notice
   another app's changes.
3. **Catalogue requirements.** Catalogue entries list `requires: ["radio"]`; the
   Fruit Store and `mfruitctl catalog` show what is missing before install.
   (`catalog.json` is platform data, so no manifest field was added; a manifest
   field for native packages is a later decision.)
4. Apps keep their own transport (send/receive) for now.

## Alternatives

- **Passwordless setup helper** (sudoers rule for a root-owned script) — easier
  from the device, rejected by the owner for now: any process running as the
  user could run it as root.
- **Leave setup in WalkieTalkie** — Messenger and future radio apps would depend
  on another app's installer (an app → app dependency).
- **A platform radio daemon owning the port** — would allow receiving in the
  background while another app is in front; too large for this step.

## Consequences

One place to set up and configure the radio; one identity; apps no longer
guess each other's settings. Until both apps use the store, their pairings
stay separate. The SDK gains an optional dependency (`cryptography`, radio
apps only), installed by the setup.

## Compatibility

Existing installs keep working: apps that do not yet use the store behave as
before. WalkieTalkie's existing keys are adopted into the store once (the
original file is kept), so radios already paired stay paired. Re-provisioning
to AU915 makes a radio unable to hear radios still on 868 MHz until they are
re-provisioned too.

## Validation

`tests/test_sdk_radio.py` (store, pairing round-trip, two apps sharing keys,
legacy adoption), `tests/test_radio_host.py` (register encoding, handshake,
provisioning, readiness), installer/CLI requirement tests; on a device:
`setup-radio.sh --check`, then the setup, `mfruitctl catalog`, and a radio
exchange between two provisioned radios.

## Amendment (2026-10-22): the module is checked, not trusted

**Context.** Provisioning wrote the module once and recorded `radio.json`;
afterwards everything trusted the record. On 2026-10-22 a new Orange Pi found
no radio to pair with: the other board's module was on its factory settings
(868 MHz, transparent, no signal reports) while its `radio.json`, RadioConnect
and `setup-radio.sh` all said 920 MHz. `setup-radio.sh` would have skipped it
("already provisioned"), and provisioning's read-back compared the frequency
only ([record](../../quality/records/2026-10-22-radio-module-settings.md)).

**Decision.** `radio.json` is the wanted state and the module is compared
with it: at every boot by `mfruit-radio-setup.service`
(`python3 -m mfruitos.hosts.lora ensure`, as the user, before whisplay-daemon
takes M0/M1), and by every `setup-radio.sh`/`provision` run. All readable
registers are compared (`sx126x.differences`), only differences are written,
and the whole read-back must match. The result goes to `module.json` and
into the readiness check. The system setup installs the unit wherever a radio
is recorded, so System updates bring it to radios set up earlier.

**Alternatives.** Root-owned unit with a copy of the code: rejected, the
user already holds the lines and the port (the daemon runs as the user), and
root would run user-writable code at every boot. A check inside RadioConnect:
rejected, the app has no mode lines and other radio apps would need the same.

**Compatibility.** Same unit name; the old one-time unit is replaced in place.
A module that matches is never written (no flash wear); `provisioned_at`
changes only when the module is written, which makes RadioConnect learn the
module's abilities again. An OS rolled back below the check leaves a unit
whose `ensure` is unknown: it fails at boot without stopping the daemon.

**Validation.** `tests/test_radio_host.py` (both boards' register dumps,
boot check, provisioning read-back with a negative control),
`tests/test_autoinstall.py` (unit), `tests/test_system_setup.py` (installer);
on a device: a module on factory settings restored at boot and two radios
pairing.
