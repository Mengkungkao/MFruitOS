# Testing an app

What to test before an app is called ready, from fast unit tests to the
device. Status words follow [Part I §20](../platform/DEVELOPMENT_RULES.md#20-quality-status-language):
an automated pass is not a device verification.

## Controls tests

Drive the real `InputController` into the app's real dispatch:

```python
from mfruit_sdk.input import InputController

clock = FakeClock()
controller = InputController(app.on_action, keyboard=False, threaded=False,
                             clock=clock, active=lambda: app.has_screen)
controller.press(); clock.advance(0.05); controller.release(); clock.advance(0.5)
controller.key_event(KeyEvent(...))      # keys without a keyboard
```

Cover every action on every screen, footer hints matching handlers, keys that
went down while another app had the screen being ignored, and nothing
happening while inactive. Talk screens: a hold talks; elsewhere a hold only
arms and acts on release.

## Rendering tests

Compose each screen with the chrome and assert that content stays between
`CONTENT_TOP` and `CONTENT_BOTTOM`, long text truncates, and empty and error
states render ([UI guidelines](UI_GUIDELINES.md)).

## Smoke test hook

The manifest `test` hook runs on the device before activation; run it locally
too (`bash test.sh`). It must be fast and deterministic and must not take the
screen, send messages, transmit or need credentials.

## Static preflight

```bash
python3 ~/MFruitOS/scripts/check-app.py <package>   # manifest, contract, hooks, SDK, artifacts
~/MFruitOS/scripts/sdk-sync.sh <python root> --check
```

## Package lifecycle

On a configured device, with disposable data:

1. `mfruitctl sideload <package>`; wait for `mfruitctl jobs` to be idle.
2. Launch from Home and with `mfruitctl launch <id>`; check the first frame,
   status bar, footer, loading and error states and the return to Home.
3. Leave the app; confirm its process is gone within about 5 seconds unless it
   is a `background` app (`pgrep -af <app>`).
4. Reinstall, update to a newer version, downgrade.
5. Install a version whose smoke test fails: the previous version must stay
   active and its data intact.
6. Roll back; uninstall; confirm what removal deletes.

## On the device

Test with the button **and** a keyboard: navigate, open, Back rows, Esc,
wake-only presses, keys held across a focus change, and that typing while
another app is in front does nothing in yours. Exercise app-specific hardware
(audio, radio, pairing, Wi-Fi) separately; SSH checks cannot verify sound,
buttons or LED colours. Record results, including what was not verified,
with the [validation template](../quality/VALIDATION.md#record-template).
