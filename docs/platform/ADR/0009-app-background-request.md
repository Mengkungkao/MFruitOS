# ADR 0009 — Apps can ask to keep running with the screen held bright

Status: Accepted 2026-10-04 (owner: "make a switch, turn it on or off from
the app", for RadioConnect only).

## Context

The LoRa HAT's stock M0 jumper is the LCD backlight pin. Any brightness below
100% is software PWM on that pin, and screen-off holds it high: the radio is
then deaf (measured 0/20 packets at 80% and 15%, 40/40 at 100%;
[record](../../quality/records/2026-10-04-radio-over-the-air.md), KI-11).
RadioConnect pins the backlight while it is open, and MFruit OS dims only
while it is itself on screen, so a radio app could not keep listening after
the user leaves it: either it exits, or it keeps running while MFruit OS dims.
MFruit OS already had a per-app *Keep running* (`background`), but only the
user could set it, in MFruit OS's Settings, and nothing kept the screen bright.

## Decision

1. A per-app flag `screen_bright` (*Keep screen bright*, default off) next to
   `background`. While an app with both flags runs in the background,
   `BacklightController` holds 100%: dimming and screen-off leave it at full;
   when that app stops, the user's display settings apply again
   (`Runtime._update_backlight_hold`, on every registry refresh and focus
   change).
2. A control command `app.background` (get, or set `keep_running` and
   `screen_bright`) and SDK 1.4.0 `mfruit_sdk.background.get()/set()`, so an
   app can offer the switch in its own settings. Only these two flags; the app
   names itself (`WHISPLAY_APP_ID`).
3. Both flags stay visible and changeable in Settings > Apps.
4. With *Keep running*, the app's "leave" releases the screen instead of
   exiting (the existing background-app contract).

No application ID appears in platform code: any app may ask; RadioConnect is
the one that does.

## Alternatives

- **Hold the backlight while any app requiring the radio runs.** Ties the
  platform to the radio, needs the capability in the manifest (only in the
  catalogue today) and gives the user no switch.
- **Never dim while a radio is set up.** Costs the screen and battery even
  when no radio app runs; the owner asked for RadioConnect only.
- **Rewire M0/M1 to free GPIOs.** Removes the conflict entirely and remains
  the better hardware answer (KI-11), but needs work on every board.
- **Let the app call `backlight.set` while in the background.** Breaks "a
  background app stays quiet" and fights MFruit OS's own backlight.

## Consequences

- A radio app can listen in the background; the screen stays lit at 100%
  meanwhile (more power), which the app's switch says.
- The control socket is the user's own (mode 0600): any of the user's
  processes could set another app's two flags. A convenience contract, not a
  permission (Security).

## Compatibility

Additive. Apps on SDK ≤ 1.3.0 are unaffected; with an MFruit OS that lacks
`app.background`, the SDK returns None and the app shows the switch as
unavailable. Settings files gain the optional flag; older files load.

## Validation

`tests/test_background_screen.py` (backlight hold, control command limits,
SDK client, end-to-end through the real Runtime, control socket and fake
daemon; negative control); RadioConnect 0.5.0 tests (leave releases the
screen, the switch sets both flags; negative control). Device: see the
radio over-the-air record.
