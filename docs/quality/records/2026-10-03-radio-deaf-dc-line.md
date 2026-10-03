# 2026-10-03 — "Radio deaf: check M0/M1" in Messenger

| | |
|---|---|
| Revision | uncommitted working tree on top of `f15afe5` (MFruit OS); Messenger and WalkieTalkie working trees (uncommitted) |
| Device | Raspberry Pi Zero 2 W, `jarvis@192.168.0.33`, Whisplay HAT + Waveshare SX126X LoRa HAT (stock M0/M1 jumpers assumed: not inspected) |
| Whisplay | upstream `1066486`, a fresh clone (`git reflog`: clone only) |
| Installed Messenger | the catalogue build (868 MHz, before the shared radio store) |

## Bug record

- **Problem:** the user reported Messenger showing "Radio deaf: check M0/M1".
- **Expected:** the radio idles in transparent mode (M0=0, M1=0) and can send and hear.
- **Evidence:** Messenger and WalkieTalkie logs on the Pi: `THE RADIO IS DEAF:
  module is in configuration mode (100% of the time). M0=GPIO22 M1=GPIO27, and
  GPIO27 is not going low`. Pi `~/Whisplay/runtime/whisplay.py` `_send_data` and
  `_send_data_bytes` raise DC and never lower it (no DC fix applied).
- **Root cause:** GPIO27 is both the LCD's DC line and the radio's M1. Upstream
  Whisplay leaves DC high after each frame, which holds the module in
  configuration mode. WalkieTalkie's installers used to patch the Whisplay
  checkout (`docs/whisplay-dc-fix.patch`); this Pi's checkout was cloned fresh for
  MFruit OS and never had that patch, and MFruit OS does not edit the checkout.
- **Fix:** `scripts/whisplay-daemon-mfruit.py` `park_dc_low` lowers DC after each
  data transfer, always (Host API, "LCD DC line parked low"). Messenger and
  WalkieTalkie `modepins.sample` no longer call the radio deaf when only M1 is
  high a minority of the time (frames being drawn); M1 high most of the time is
  still reported.
- **Regression tests:** MFruit OS `tests/test_dc_park.py` (6; the upstream-shaped
  board leaves DC high: negative control; real `runtime/whisplay.py` from both
  the local copy and upstream `1066486`). Messenger `tests/test_display.py` +2,
  WalkieTalkie `tests/test_modepins.py` +3.
- **Compatibility:** display unaffected in principle (DC is sampled only while
  SPI clocks); one extra GPIO write per transfer.

## Commands and results

| Check | Result |
|---|---|
| `bash scripts/check.sh` (MFruit OS) | all steps ok; 401 tests |
| Messenger `python3 -m pytest -q` | 187 passed |
| WalkieTalkie `python3 -m pytest -q` | 646 passed |
| Pi: `install.sh --no-service --yes`; restart whisplay-daemon and whisplay-os (no install job running) | daemon log lists `_send_data, _send_data_bytes` as patched |
| Pi: launch the installed Messenger | mode-pin check at start-up: configuration mode **8%** of the time (was 100%); the old Messenger build still shows the note for that |
| Pi: `modepins.sample(22, 27, 200 samples, 4 s)` ×3 with Messenger idle | 100% transparent each time |

## Follow-up the same day: new Messenger and WalkieTalkie on the Pi

Sideloaded from the uncommitted working trees (`mfruitctl sideload`, folders
staged in `~/sideload/`; WalkieTalkie needed the catalogue's generated
`manifest.json`, `run.sh` and `test.sh`, plus `.venv` in `persist`). No install
job was running at any point.

| Check | Result |
|---|---|
| Messenger start-up | `mode pins M0=0 M1=0 (transparent)`; no "Radio deaf" note; the chat history copied from `~/.lora-messenger` into the MFruit OS data folder (old files kept) |
| Shared identity | Messenger now uses WalkieTalkie's Device ID 32478 (was 33072 from the hostname); `shared/radio/keys.json` holds WalkieTalkie's pairing with 6235 |
| WalkieTalkie start-up | transparent; link up; its contact 6235 "orangepizero2w" published to `shared/radio/contacts.json` |
| Both apps | launch and leave with Esc (simulated via `mfruitctl key escape`) |

Incident: the first WalkieTalkie sideload failed at **test** (no `.venv`),
and the installer rolled it back correctly. Its `install.sh` had already
re-registered the app with whisplay-daemon pointing at the rolled-back folder.
The next successful install registered the active folder. App `install.sh`
scripts that call `app.register` themselves can leave such a stale
registration after a failed install (candidate known issue).

## Not verified

- Anything sent or received over the air (only one radio reachable; no second radio).
- The display looking unchanged with DC parked (no one looked at the LCD).
- Orange Pi (PH3).
- The Messenger/WalkieTalkie `modepins` change on the device (not deployed; the
  Pi still runs the catalogue builds).
- How the HAT is actually wired (jumpers fitted or rewired).
