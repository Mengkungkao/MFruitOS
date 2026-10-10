# Orange Pi Wi-Fi/RGB and 1.4.0 deployment checkpoint — 2026-09-30

> Moved from the former `docs/HARDWARE_TESTS.md` on 2026-10-02. Historical
> results for the revisions named below; not a statement about the current
> checkout. Current procedure: [Validation](../VALIDATION.md).

Latest Wi-Fi/RGB follow-up (active OS `1.4.0-local20260930054411`):

- ConnectWifi 1.1.0: 136 tests passed, 1 skipped. MFruitOS focused launch,
  Settings, runtime, gesture and hardware checks: 46 tests passed. The install
  self-test rendered 37 screens. Earlier full-suite results below predate this
  follow-up and were not rerun in full.
- A private instance of the real daemon with simulated GPIO accepted 24 rapid
  hub taps and 28 network-list taps without exiting. All three Back routes
  acted only on a 1.12-second hold. No real network changes were performed.
- Live key-hub navigation verified direct Wi-Fi opening, no `LoadingScreen`,
  12 repeated hub moves without losing focus, and both bottom Back rows
  returning to Settings. Inspected the actual ConnectWifi RGB565 framebuffer.
- Both services active; left on Settings with an idle app session. Physical
  LED appearance and hand-operated buttons still need observation.

Earlier deployment checks:

Deployed mFruit OS 1.4.0 and the matching SDK 1.2.0 apps to
`orangepi@192.168.0.130`. Both systemd services are active.

- Automated Linux suite: 260 tests passed, including the real-daemon harness;
  self-test rendered 37 screens. Connect WiFi: 129 passed, 1 skipped;
  Messenger: 141 passed; WalkieTalkie: 578 passed; chatbot keyboard/startup: 12 passed.
  Chatbot TypeScript compiled successfully with the existing dependencies.
- Live control-socket keys opened Settings and Wi-Fi, launched Connect WiFi,
  and exited it through the key hub back to Wi-Fi. Bluetooth opened and
  completed discovery. Live screenshots were inspected.
- Messenger, WalkieTalkie and chatbot launched on the board and returned via
  key-hub Escape. The chatbot initially missed the launch deadline; deferring
  its optional OpenCV import reduced UI import time from 4.345 s to 2.078 s,
  and its subsequent live launch succeeded without changing the timeout.
- BlueZ queries, discovery, and registration/shutdown of our connection's
  pairing agent succeeded as `orangepi` while the daemon was running.
- Home excludes Connect WiFi; it remains in Settings → Apps. Hello Whisplay
  and Run Test were removed and remained absent after the daemon restart.
- Physical USB/Bluetooth keyboard input, tty1 isolation, physical button
  gestures, actual pairing/confirmation/cancellation, and grab release in
  Daemon desktop mode remain **not verified on hardware**. No keyboards were
  attached during these checks. Boot appearance was verified in a rendered
  preview, not observed during a physical reboot.
