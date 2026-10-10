# Security and safety

**mFruit OS does not provide a security sandbox.** Apps run as the device user
with that user's permissions. Package checks protect the device from
malformed or accidentally unsafe packages and keep installs recoverable; they
do not contain a malicious app once it runs
([Part I §28](DEVELOPMENT_RULES.md#28-security-and-safety)).

## Trust model

| Party | Trust |
|---|---|
| The device user and processes running as that user | trusted (they can already do anything the launcher can) |
| Package archives, sideloaded folders, release metadata, catalogue downloads | untrusted input until validated |
| whisplay-daemon and its socket | trusted host service |
| The power service (`mfruit-power.service`) and its sockets | trusted platform service running as the user; both sockets are 0600 |
| The launch gate (tickets, lock) | lifecycle correctness, **not** a security boundary: any process running as the user can write a ticket |

## Implemented protections

| Area | Enforcement | Source |
|---|---|---|
| Manifest | rejected as a whole on any invalid field; 64 KiB limit; IDs restricted to `[a-z0-9][a-z0-9_-]{0,47}`; reserved IDs refused; only `mfruit-os` may be `type: system`; entrypoint, icon and test must be safe relative paths inside the package; repository must match the download source; `min_os_version` enforced | `apps/manifest.py` |
| Archive extraction | no absolute paths, `..` or NUL in names; symlinks and hard links must stay inside the package (zip: no symlinks at all); device files and FIFOs refused; at most 20,000 files and 600 MB extracted; set-uid/set-gid and group/world-write bits removed | `updater/verifier.py` (`safe_extract`) |
| Sideloaded folders | the same rules checked before copying (relative in-package symlinks only, no special files, the same limits; `.git`, `__pycache__` and `*.pyc` are not part of the payload); permission bits normalized after copying; the source folder is never moved or changed | `updater/verifier.py` (`copy_package_dir`) |
| Downloads | HTTPS only; size limit `updater.max_download_mb`; SHA-256 verified when the release publishes one (asset digest, `SHA256SUMS`, `<asset>.sha256`); `updater.require_checksum` refuses unverified downloads; catalogue entries pinned to a commit and SHA-256; the online Fruit Store list comes only from `system.repository` on GitHub over HTTPS (as trusted as system updates), at most 256 KiB, and each entry is validated before it is listed ([ADR 0010](ADR/0010-online-fruit-store-catalogue.md)); `system_packages` must be Debian package names and are installed only by `scripts/setup-app.sh`, run by the user with sudo, never by the Store ([ADR 0011](ADR/0011-catalogue-system-packages.md)) | `updater/installer.py`, `github.py`, `catalog.py` |
| Activation | staged in a new version directory; the running version is never modified; activation is an atomic symlink swap after hooks and the smoke test pass | `updater/installer.py`, `rollback.py` |
| Package hooks | run as the user, stdin `/dev/null`, new session, allowlisted environment (`PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_ALL`, `XDG_RUNTIME_DIR` plus the `WHISPLAY_*` contract), timeouts 15 min (install/update) and 2 min (test/uninstall) | `updater/installer.py` |
| Deletion | managed deletions only strictly inside an allowed root; symlinks are unlinked, never followed; protected system paths and `$HOME` refused | `updater/rollback.py` (`safe_rmtree`), `paths.py` |
| Stopping apps | signals only a process group whose leader `/proc` confirms is `mfruit-run <id>`; refuses PGID ≤ 1 and the launcher's own group | `launcher/app_manager/lifecycle.py` |
| Local sockets | `state/` is mode 0700; `control.sock`, `keys.sock` and `power.sock` are 0600; the PiSugar-protocol socket `/tmp/pisugar-server.sock` is 0600 and is not taken over when another program (PiSugar's server) answers on it | `paths.py`, `launcher/control.py`, `launcher/keyhub.py`, `power/server.py` |
| Power | the power service runs as the user with the `i2c` group and only `CAP_SYS_TIME` (ambient; dropped for every command and hook it starts), used only to move the clock forward from the battery board's clock when the clock is not synchronised; it never moves the clock backwards. PiSugar-protocol commands that cut the power at once, change the board's I2C address or set web credentials are refused. The shutdown hook is a root-owned copy in `/usr/lib/systemd/system-shutdown/`, never a link into user-writable files, and acts only on *poweroff* | `power/`, `scripts/mfruit-power-off` ([ADR 0012](ADR/0012-own-power-management.md)) |
| Keyboard | all keyboards grabbed exclusively, so typed keys never reach the console shell (RC6) | `sdk/keys.py`, `launcher/runtime.py` |
| Privileges | launcher and power service run as the user, never root; sudoers allows only two `systemctl restart` commands plus `systemctl poweroff` and `systemctl reboot` (validated with `visudo -c`); polkit grants only the listed NetworkManager actions to one user | `scripts/install.sh` ([Installation](INSTALLATION.md#system-changes-and-why-they-are-needed)) |

## Known gaps

These are tracked in [known issues](../quality/KNOWN_ISSUES.md) where a fix is
planned. Do not describe them as protected.

- **No isolation:** an app can read and write anything the user can, including
  other apps' data and `settings.json` (which may hold `updater.github_token`
  in plain text).
- **`persist` paths** are checked only during installation; unsafe entries are
  skipped with a warning instead of rejecting the manifest.
- **Unverified downloads** are accepted by default when a release publishes no
  checksum (integrity then relies on HTTPS and GitHub).
- **Git-tracked apps** fast-forward to whatever upstream contains; the only
  pre-activation check is that changed Python files compile.
- **The daemon socket** (`/tmp/whisplay-daemon.sock`) is whisplay-daemon's; any
  local process allowed to connect can request focus, LED or backlight
  changes.
- **Shared radio keys** (`shared/radio/keys.json`, 0600) are readable by every
  app running as the user, like all user files; any app can therefore read or
  impersonate this radio's encrypted traffic.
- **Capabilities/permissions** for apps are PLANNED only; no manifest field
  restricts what an app may do.
- **Wi-Fi from a phone** ([ADR 0013](ADR/0013-phone-wifi-setup.md)): while
  PiSugar's sugar-wifi-conf runs, anyone in Bluetooth range can read the
  device's Wi-Fi name, addresses and the configured information, and the key
  (8 random characters by default) is all that guards setting the Wi-Fi
  network and running the configured commands. The tool does not pair, so the
  key travels unencrypted and could be captured by a nearby BLE sniffer while
  it is used; make a new key afterwards if that matters. Its SSH tunnel
  reaches the local sshd without the key (an SSH login is still needed). It
  runs only while wanted (by default only while Settings → Wi-Fi → Phone Setup is open),
  as the user, never as root; the binary is PiSugar's, pinned by SHA-256.
- **Power control is open to the user's processes:** any app running as the
  user can ask the power service (or `sudo -n systemctl poweroff`) to shut the
  device down, change power settings, or set PiSugar-protocol tap hooks, which
  run shell commands as the user (no escalation: the same user could run
  them directly).

## Handling secrets

No credentials in source, manifests, tests, examples, logs or validation
records ([Part I §15](DEVELOPMENT_RULES.md#15-configuration)). Apps keep
secrets in their data directory and ship `.env.example` files;
`scripts/check-app.py` rejects live `.env` files in a package.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the repository owner
([Mengkungkao](https://github.com/Mengkungkao)) before publishing details.
Include the mFruit OS version, the package or input involved and the observed
effect.
