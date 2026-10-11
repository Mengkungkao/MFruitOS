# 2026-10-11 — AI Chatbot 1.1.0: lip-synced, livelier face

## Request

The owner asked (on the Raspberry Pi Zero 2 W) for the chatbot's animated face
to be "cooler" and livelier: the mouth moving while it talks, and not while it
listens.

## Problem (1.0.1/1.0.2)

- The mouth was driven by the status text: any status starting with
  `answering` flapped it on two sine waves. `answering...` is shown while the
  reply is still being written, so the mouth moved before any sound, through
  the pauses between sentences, and in time with nothing.
- Apart from blinks and breathing the face was still (ear flicks had been
  switched off in `face_gen.py`).

## Change (ai-chatbot, uncommitted; package 1.1.0 sideloaded)

- **Lip sync from the audio.** `src/device/speech-envelope.ts` works out each
  TTS clip's mouth openness per 20 ms: loudness relative to the clip, gated
  24 dB down, plus each frame's contrast with its ±140 ms neighbourhood (TTS
  speech dips only 2-4 dB between syllables; contrast takes the open-and-close
  rate from ~2 to ~3.3 a second on OpenAI `tts-1` "nova"). WAV is read in
  process, mp3 decoded by sox to 8 kHz (72 ms for 5 s of audio on the Pi).
  `ChatFlow` starts it as soon as a sentence is synthesised.
- `playAudioData` announces every clip (`onSpeech`): `start` (with the
  envelope when ready and `at`, the epoch ms it went to the player),
  `envelope` (if late), `end` (also when cut off). `ChatFlow` forwards them to
  the UI as `{"speech": …}`.
- `python/face_engine.py` `FaceAnimator`: the mouth follows the clip through a
  fast attack / quicker release, is drawn shut below 0.16 (pauses between
  words), picks one of the five measured talk shapes by loudness band,
  alternating per syllable; shut and ignoring clips while listening; a clip
  never ended is dropped 1.5 s after its length; no envelope within 0.3 s →
  made-up syllables. Modes from the status (`face_mode` in `chatbot-ui.py`):
  listening (sprung 4.5° head tilt, eyes on you and 7% wider), thinking (eyes
  up and to the side, tilt toward them), idle (glances, an occasional curious
  tilt, slow cat blinks). Quick, double and gaze-triggered blinks; brows follow
  the gaze; head lifts slightly on loud syllables. Gaze and eye widening are
  clamped per face so no eye touches a whisker. LRU frame caches (320 frames,
  64 tilted).
- `chatbot-ui.py`: face redrawn at 20 fps while speaking (15 otherwise), frames
  placed by their centre, repaint band widened for the tilt (header 1 px
  taller), `WHISPLAY_FACE_SYNC_MS` (default 80).

## Measurements on the Pi Zero 2 W (pizero, Debian 13, mFruit OS 1.4.0)

| What | Result |
|---|---|
| sox mp3 player spawn → sound at the mic (`latency_probe.py`, 3 tries) | 68, 68, 87 ms, of which 46 ms is the mp3's own lead-in: 22-40 ms |
| Real proactive reply, first 1.1.0 build (start timed on arrival, lead 30 ms) | mouth in the app framebuffer **lagged** the voice 110-270 ms; it stayed shut in 930 ms of silent stretches |
| Cause | the `start` message reached the UI thread late while it redrew the scrolling text; fixed by timing from `at` |
| Tone bursts via `syncprobe.py` (app idle), rebuilt 1.1.0, lead 80 ms | mouth leads the voice by 90-120 ms (r = 0.90-0.93, 3 runs; one earlier run r = 0.49 discarded) |
| Real proactive reply, rebuilt 1.1.0 | mouth **leads** by 50-60 ms (r = 0.57 on the clearer clip); shut in all 1 190 ms of silent stretches; 0 mouth pixels during |
| Listening (status sent to the running UI, then a loud clip) | 0 mouth pixels; head tilted, eyes wider, red ring; idle restored afterwards |
| CPU of `chatbot-ui.py` | 4.4-5.1% of one core idle, 24% while speaking |
| Face frames in the app framebuffer while speaking | 12-19 a second (full-screen text redraws slow some) |

The LCD itself was not observed: whisplay-daemon copies the app framebuffer
to the panel at most 20 times a second with a full-screen SPI push. From its
code that adds ~45 ms on average plus one refresh on screen, so the mouth on
the LCD should be about in time, slightly early. **NOT VERIFIED** on the
panel.

## Automated tests

| Test | Result |
|---|---|
| `python/test/test_face_engine.py` (14) | PASS. Negative controls, each failing the named tests: listening not clamping the mouth; a thinking status opening it; the mouth never drawn shut; clips never expiring; `at` ignored |
| `scripts/test-speech-sync.js` (16 checks, fake player) | PASS. Negative controls: no `end` event (4 checks fail); a late envelope after `end` not suppressed (1 fails) |
| `npm test` (tsc + 4 scripts) | exit 0 |
| `test_keyboard_input.py`, `test_startup_wrapper.py` | PASS; `test_image_utils.py` not run here (no `cairosvg` on the dev machine, as before) |
| UI smoke run of `RenderThread` against a fake panel (dev machine) | every face repaint inside the header band, all modes |

## Device state left

Pi Zero: AI Chatbot 1.1.0 (`versions/1.1.0-cec9de`, sideload, `verified=False`)
active and open, previous 1.0.1 (the owner had rolled 1.0.2 back to 1.0.1 on
2026-10-08, around Wi-Fi DNS failures that both versions logged). Rollback:
`mfruitctl rollback whisplay-ai-chatbot`. The user's `.env` was not changed.
Three TTS sentences were synthesised once with the owner's OpenAI key for the
measurements.

## Not verified

- The mouth on the LCD (only the app framebuffer was measured).
- A button conversation by the owner (only proactive replies and injected
  speech/listening messages were exercised).
- The Orange Pi (not deployed).
- No release: 1.1.0 is not tagged, and the Fruit Store still pins 1.0.2.
