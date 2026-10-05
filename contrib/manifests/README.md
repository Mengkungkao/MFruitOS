# Manifests for existing MFruit OS apps

These `manifest.json` files turn existing apps into MFruit OS packages. The
Messenger manifest is also included in its app checkout. Copy a file into the root of its
repository (or the path noted below) when you want the app to be installable
and updatable through the MFruit OS Updater.

| Repository | App id (matches its daemon registration) | Notes |
|---|---|---|
| Mengkungkao/Messenger | `whisplay-lora-messenger` | Keeps `.venv` and `config.yaml` across updates. `disable_esc_exit_key` preserved. |
| Mengkungkao/WalkieTalkie | `whisplay-lora-walkie` | Its `install.sh` preflight fails if Python modules are missing — an install then rolls back cleanly. Run `setup.sh` once for codec2/serial setup. |
| Mengkungkao/whisplay-crypto-dashboard | `whisplay-crypto-dashboard` | Keeps `.venv`, `config.yaml` and `.env` (API keys). |
| Mengkungkao/ai-chatbot | `whisplay-ai-chatbot` | **Native package since 1.0.0** (`whisplay-ai-chatbot/manifest.json`, release asset built by its release workflow); in the Fruit Store. The draft in this folder is superseded. |
| ConnectWifi | — | Repository not public, not drafted. |

## Publishing a version

1. Add `manifest.json` (from this folder) to the repository root.
2. Tag a release whose tag matches the manifest version:
   `git tag v1.0.0 && git push origin v1.0.0`, then create a GitHub release from the tag.
3. Optional but recommended: attach a package archive and a `SHA256SUMS` file
   so MFruit OS can verify the download.
4. Add the GitHub topic `whisplay-app` so the app shows up in *Updater → Install app → Discover*.

Until then, these apps are still fully usable from MFruit OS (they are
discovered from the daemon registry), and if they were installed as `git
clone`s the Updater offers *commit tracking* updates (fast-forward only,
clean working tree only, rollback to the previous commit).
