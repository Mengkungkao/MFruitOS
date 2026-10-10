# UI guidelines for apps

How an app's screens look and behave so that every app feels like part of the
same device. The binding rules are in [App contract §3](APP_CONTRACT.md); this
document gives the geometry and the SDK calls behind them. The launcher's own
conventions are in the platform [style guide](../platform/STYLE_GUIDE.md).

## The four questions

Every screen answers: where am I, what is selected, what will confirmation
do, and how do I go back ([Part I §7](../platform/DEVELOPMENT_RULES.md#7-user-experience-rules)).
The page name in the status bar answers the first; selection highlighting and
a meaningful action label answer the next two; Back rows, 4× and Esc answer
the last.

## Geometry (`mfruit_sdk.ui.theme`)

| Constant | Value | Use |
|---|---|---|
| `SCREEN_W` × `SCREEN_H` | 240 × 280 | the display; corners are rounded |
| `CORNER_INSET` | 20 px | keep text this far from the side edges near the top and bottom corners |
| `MARGIN` | 14 px | normal content margin |
| `STATUS_Y` | 9 | status bar text top |
| `CONTENT_TOP` / `CONTENT_BOTTOM` | 40 / 248 | content area between status bar and footer |
| `FOOTER_Y` | 256 | footer hint text (separator 5 px above) |
| `ROW_H` / `ROW_H_SUB` | 36 / 46 px | list rows without / with a subtitle |

SDK list rows differ from the launcher's 46 px rows on purpose; use the SDK
helpers rather than copying launcher code.

## Screen anatomy

- **Status bar** on every screen: `status_bar(canvas, page_name, status)` —
  page name top-left (bold 17), Wi-Fi and battery top-right from
  `StatusMonitor`. No app-name header row; an app state light goes in `dot=` or
  `badge=`.
- **Content** between `CONTENT_TOP` and `CONTENT_BOTTOM`; never leave a half row
  under the status bar.
- **Lists:** `draw_list(canvas, rows, selected)` with `Row(label, subtitle,
  value, kind, tone, enabled)`; `kind` is `action`, `nav`, `toggle`, `info`,
  `back` or `danger`. Menus with a parent include a visible Back row.
- **Footer:** `footer(canvas, menu_hints(select="open", armed=armed))` — hints
  and handlers come from one table, so the screen never advertises a gesture
  the code does not implement. While a hold is armed, show "release to …".
- **Feedback:** `toast()` for short confirmations ("Exiting"), `message()` for
  empty and error states, `text_field()` for typing screens.

## States every app needs

List each screen and its loading, empty, offline and error states. An error
says what failed, what the user can do, and whether previous state was kept;
offer Retry, Details or Back rather than a dead end. A press on a dimmed-off
screen only wakes it.

## Look

- Colours from `mfruit_sdk.ui.theme.DARK` (or `LIGHT`); fonts from
  `mfruit_sdk.ui.fonts`. An app may keep one brand accent inside its content
  (for example Bitcoin orange); chrome stays mFruit.
- Sentence case ("Refreshing…", "Network error"), not ALL CAPS. Hint labels:
  `tap`, `2×`, `3×`, `4×`, `hold`, `release`.

## Performance

Draw the first frame as soon as possible: until then the user sees mFruit OS's
"Opening <App>" screen. Render only when state changes, convert with
`to_rgb565`, and keep network, radio and model work off the input and render
path.

## Checking a layout

A rendering test composes each screen with the chrome and asserts that content
stays between the status bar and the footer ([Testing](TESTING.md)). PNG
renders do not validate corner clipping, brightness or readability on the
physical LCD; check those on a device and record them
([Validation](../quality/VALIDATION.md)).
