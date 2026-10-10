# ADR 0008 — mFruit OS ships the Whisplay driver

Status: Accepted 2026-10-03 (owner's request: "replace the external Whisplay
driver with an mFruit OS-owned Whisplay driver; keep everything else
stable"). Canonical description: [Whisplay driver](../../WHISPLAY_DRIVER.md).

## Context

Before this decision, a device needed two installations: PiSugar/Whisplay
(`install_driver.sh` plus `daemon/install_whisplay_daemon_service.sh`, which
needed a `git clone`, a prompt, a board-specific script and a reboot), then
mFruit OS. mFruit OS depended on that checkout at run time:

- `whisplay-daemon.service` ran `~/Whisplay/daemon/whisplay_daemon.py`;
- mFruit OS's drop-in started the daemon wrapper with `--whisplay ~/Whisplay`;
- the recovery display imported `~/Whisplay/runtime/whisplay.py`;
- catalogue apps import `whisplay_client` from `~/Whisplay/runtime` or
  `/usr/local/share/whisplay/runtime`;
- CI cloned Whisplay at a pinned commit for the real-daemon tests.

The Whisplay repository also contains demo apps, an OS image builder and
documentation, none of which is needed for the hardware to work.

## Decision

1. `drivers/whisplay/` holds the driver files from Whisplay commit `c73051e`
   **unmodified**: runtime (`whisplay.py`, `whisplay_client.py`), daemon,
   sound card sources, overlays, ALSA config and the sound card installer.
   `upstream.sha256` records them and `scripts/check.sh` verifies them.
   Daemon behaviour changes stay in `scripts/whisplay-daemon-mfruit.py`
   (unchanged by this decision).
2. mFruit OS's own `drivers/whisplay/install.sh` replaces Whisplay's seven
   install scripts. It performs the same steps, asks no questions, skips work
   that is already done, keeps the daemon's settings, and installs the runtime
   and daemon to `/usr/local/share/whisplay` through a staged copy, keeping
   the previous copy for `--rollback`.
3. `scripts/install.sh` runs it on a supported board (opt-out
   `--no-driver`). `whisplay-daemon.service` keeps its name, user,
   groups and restart policy; only its paths change.
4. The real-daemon tests use the bundled daemon; CI no longer clones Whisplay.

## Alternatives

- **Rewrite the driver and daemon as mFruit OS code.** Rejected for now. It
  would change hardware timing and daemon semantics that mFruit OS and its
  apps rely on ([Host API](../HOST_API.md)), against the owner's instruction
  to keep behaviour unchanged. Extraction stays incremental
  ([ADR 0005](0005-incremental-host-boundary-extraction.md)).
- **Keep cloning Whisplay from `install.sh`.** Rejected: it still depends on an
  external repository at install time and on its moving `main` branch.
- **Install inside `~/.whisplay-os/system/current`.** Rejected: the
  unprivileged launcher updater would change the hardware service's code
  without updating its kernel half, and apps already search
  `/usr/local/share/whisplay/runtime`.
- **Copy the whole Whisplay repository.** Rejected: demo apps and the image
  builder are not driver (see the left-out table in
  [UPSTREAM.md](../../../drivers/whisplay/UPSTREAM.md)).

## Consequences

- One installation command. A reboot is still needed the first time the
  buses or the sound card are enabled.
- mFruit OS now carries about 620 KB of upstream files and must follow
  upstream deliberately (`scripts/whisplay-driver-sync.sh`, then the full
  checks and a device validation).
- The driver updates only with `scripts/install.sh`/`update.sh` (root). The
  in-app system update does not touch it.
- New installations no longer get Whisplay's demo games, which came from
  `daemon/default_apps`.
- Offline installation (owner's requirement, 2026-10-03): the code is complete
  in the repository; packages and the sound card build inputs come from an
  offline pack (`scripts/make-offline-pack.sh`, a local apt repository plus
  Whisplay's pinned downloads, served to Whisplay's unmodified sound card
  installer through `apt-get`/`wget` PATH shims). A failed sound card build no
  longer aborts the installation.

## Compatibility

- Existing devices: the sound card module is not rebuilt (same source). The
  service unit is saved in `/var/backups/mfruitos/` and then points to
  `/usr/local/share/whisplay`. `~/Whisplay`, `~/.whisplay-daemon/settings.json`
  and every app registration are left as they are.
- Apps: `whisplay_client.py` is at `/usr/local/share/whisplay/runtime`, a
  path the existing apps already search. On devices that still have
  `~/Whisplay`, apps that search it first keep using it.
- Devices that ran Whisplay `1066486` move to `c73051e`, which adds the
  PiSugar 3 power button as a way home.

## Validation

- AUTOMATED: checksums; Whisplay's daemon tests; driver SPI/GPIO tests on the
  Pi and Orange Pi maps (libgpiod v1 and v2); installer detection, boot
  configuration and staged-copy tests with negative controls; full suite with
  the bundled daemon.
- Device: a fresh install on each supported board, and a changeover of an
  existing `~/Whisplay` device, with the hardware checklist
  ([Validation](../../quality/VALIDATION.md)). Records go in
  `docs/quality/records/`.
