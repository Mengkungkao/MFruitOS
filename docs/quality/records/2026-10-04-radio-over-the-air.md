# 2026-10-04 — Radio over the air: Raspberry Pi ↔ Orange Pi

| | |
|---|---|
| Date | 2026-10-04 (about 13:00 AEDT) |
| Boards | Raspberry Pi Zero 2 W `jarvis@192.168.0.33` (trixie, MFruit OS `1.4.0-local20261004063326`); Orange Pi Zero 2W `orangepi@192.168.0.130` (Ubuntu 22.04, `1.4.0-local20261003193341`); both with the Whisplay HAT and the SX126X LoRa HAT on stock M0/M1 jumpers, a few metres apart indoors |
| Radio | both provisioned by `scripts/setup-radio.sh`: AU915, 920 MHz (channel 70), 2400 bps air rate, 22 dBm, net 0, fixed transmission, RSSI byte on |
| App | RadioConnect 0.4.0 (Fruit Store) |
| Tool | `scripts/radio-link-test.py` (added this day; the runs below used its first version, see the note) |

## Results

| Test | Result |
|---|---|
| RadioConnect, used by the owner at 12:45 | pairing (code 1779) both ways; voice Orange Pi → Pi (600 B, 4 packets: one fragment lost, repaired by `repair-ask`/`resend`, acknowledged); voice Pi → Orange Pi (656 B, 4 packets, acknowledged); RSSI −63 to −83 dBm |
| 1. Pi pings, Orange Pi echoes, 40 × 32 B, both backlights 100% | 40/40 heard and echoed; RTT median 944 ms (max 994); RSSI −61 to −71 dBm |
| 2. Orange Pi pings, Pi echoes, 40 × 32 B | 40/40; RTT median 995 ms; RSSI −61 to −72 dBm |
| 3. Orange Pi pings, Pi echoes, 20 × 200 B (RadioConnect's largest fragment) | 20/20; RTT median 3.18 s (about 1.6 s per 200 B one way); RSSI at the Pi −69 to −78 dBm |
| 4. Control: Pi backlight at 80% (MFruit OS's setting), then 15% (its dim level) | **0/20 heard** at each level |
| First attempt of test 1, with MFruit OS's normal brightness on both boards | 0/40 |
| RadioConnect reopened on both boards | it pins the backlight at 100% itself ("GPIO22 is both the LCD backlight and the radio's M0"); `hello`/`hello-ack` within a second, both "in range" (−81 to −83 dBm); MFruit OS display settings unchanged (Pi 80%, Orange Pi 90%, auto-dim 30 s → 15%, off after 120 s) |

Root cause of tests 4 and the first attempt: with the stock jumpers the
backlight pin (header 15, BCM 22 on the Pi) is the radio's **M0**. Dimming is
software PWM on that pin, and screen-off holds it high, so the module leaves
normal mode and hears nothing. Only 100% keeps M0 low. RadioConnect handles
this while it is open; MFruit OS dims only while it is itself on screen at
Home, so the two do not conflict (KI-11 covers the background case).

Note: one RSSI reading of test 3 (−210 dBm) was an artifact of the first tool
version (a long echo read in two bursts; a padding byte taken as RSSI). The
committed tool waits for the expected length; it was not re-run.

## Listen in background (later the same day)

MFruit OS with the per-app *Keep screen bright* and SDK 1.4.0 `background`
(ADR 0009) and RadioConnect 0.5.0 installed on both boards (MFruit OS by
`install.sh --no-service`, RadioConnect by `mfruitctl sideload`; app data
kept). Driven with `mfruitctl key` and the app's framebuffer captured as PNG.

| Step (Pi) | Result |
|---|---|
| RadioConnect › Settings | new row "Listen in background — off · closes when you leave" |
| Enter on it | "on · listens after you leave" and a confirmation; launcher log `APP_BACKGROUND app=radioconnect background=True screen_bright=True (requested by the app)`; SDK `get()` → both true |
| Esc, Esc (leave from its first screen) | app log "leaving to the background; still listening"; MFruit OS in front; process still running; `SESSION_END … outcome=exited` without `APP_CLOSED`; "Backlight held at 100% for radioconnect"; GPIO22 (M0) and GPIO27 (M1) steadily low (`pinctrl`) |
| 8 minutes later (past dim at 30 s and screen-off at 120 s) | DEVICE: the Orange Pi sent a quick reply "Where are you?"; the backgrounded Pi logged `rx text from 36265 … -73 dBm` and `sent ack/157` within a second; the Orange Pi showed ✓✓ "pizero2w got your message" |
| Open RadioConnect from Home | the same process (PID 2647) came back to the screen, "Chats: 1 new message" |
| Enter on the row again | "off · closes when you leave"; both flags false (MFruit OS log) |

Left as found: the switch off on the Pi, RadioConnect open on both boards.
Not verified: the lit screen's effect on battery life; leaving the app in the
background for hours; voice (needs a person to hold the button).

## Not verified

- Range: the boards were a few metres apart (strong signal). No long-distance
  or outdoor test; no test at other air rates.
- Background reception with RadioConnect set to Keep running (KI-11).
- Encryption and SOS over the air beyond the pairing and voice above.
