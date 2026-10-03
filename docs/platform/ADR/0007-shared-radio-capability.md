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
  often a reboot, which MFruit OS app hooks cannot do (they run as the user,
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
2. **One shared radio store** at `<MFruit OS home>/shared/radio/` (0700), owned
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
