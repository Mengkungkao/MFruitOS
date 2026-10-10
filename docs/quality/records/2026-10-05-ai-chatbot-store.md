# 2026-10-05 — AI Chatbot in the Fruit Store; RadioConnect 0.5.0

## Context

The user asked for AI Chatbot in the Fruit Store (prebuilt release, system
packages through an mFruit OS installer option, API keys copied by the user)
and for RadioConnect 0.5.0 to reach devices.

## Revisions

- ai-chatbot `e6de86e` (tag `v1.0.0`): native package, release workflow.
  Release asset `whisplay-ai-chatbot-1.0.0-linux-arm64.tar.gz`, 56,789,417
  bytes, SHA-256 `15de0dd7…8deb` (GitHub digest and the published `.sha256`
  agree with the download), 13,908 archive entries, manifest
  `whisplay-ai-chatbot` 1.0.0. Built by GitHub Actions run 37250167955
  (ubuntu-24.04-arm).
- RadioConnect `29694c4` (0.5.0): source snapshot SHA-256 `8751ab02…dc32`,
  downloaded twice with the same digest; manifest `radioconnect` 0.5.0.
- mFruit OS `1d18b35` plus uncommitted changes (catalogue entries,
  `system_packages`, `setup-app.sh`, `install.sh --app`, Store updates for
  installed catalogue apps).

## Automated

| Check | Result |
|---|---|
| `tests/test_system_packages.py` (9), Store update tests in `tests/test_app_installer_screen.py`, catalogue tests | pass |
| Negative control: Store update test with `newer_version` returning nothing | fails, passes with the change |
| `bash scripts/check.sh` | 521 tests, all checks passed |

## Device: Raspberry Pi Zero 2 W (`meng@192.168.0.33`)

| Step | Observed |
|---|---|
| Local build of the package, mFruit OS `safe_extract` + `load_manifest` on the Pi | accepted (32 s to extract) |
| The package's `install.sh` on the Pi | "AI Chatbot needs: mpg123 python3 cairosvg." and the setup command, exit 1 |
| The same with that check bypassed (test copy) | Node.js 20.19.5 downloaded, SHA-256 checked, `runtime/` 94 MB, `node --version` v20.19.5 |
| `test.sh` | Node checks pass; Python import stops at `cairosvg` (not installed) |
| mFruit OS candidate `1.4.0-local20261005121024`, the new Store list loaded into `cache/catalog.json` | radioconnect 0.5.0 (installed 0.4.0: update offered); whisplay-ai-chatbot 1.0.0 with "System packages missing: libsox-fmt-mp3 mpg123 python3-cairosvg (run 'bash …/setup-app.sh whisplay-ai-chatbot' …)" |
| `setup-app.sh --check whisplay-ai-chatbot` | lists the same three packages, changes nothing |

## Not verified

- `setup-app.sh` installing the packages (needs the user's sudo), then the
  launcher installing AI Chatbot from the release asset.
- AI Chatbot running from the package: the "Add your API keys" screen on the
  device, and a conversation with a real `.env`.
- The RadioConnect update 0.4.0 → 0.5.0 on the device (RadioConnect was open).
- The Orange Pi (offline today; Ubuntu 22.04 would use the downloaded Node.js).
