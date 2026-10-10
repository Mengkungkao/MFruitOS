# Style guide

Launcher UI and code conventions for mFruit OS itself. Use the existing
components before introducing a new pattern. Apps follow the
[UI guidelines](../apps/UI_GUIDELINES.md), which use the SDK's own geometry;
the four screen questions come from
[Part I §7](DEVELOPMENT_RULES.md#7-user-experience-rules).

## Screen layout

The current display is a 240 × 280 RGB canvas. Source tokens live in
`mfruitos/launcher/ui/theme.py` and `components.py`; apps use the corresponding
SDK modules rather than importing launcher internals.

| Element | Current convention |
|---|---|
| Rounded corners | Keep text within the 20 px corner inset; normal content margin is 14 px. |
| Status bar | Page label left, Wi-Fi strength and battery right; status text starts near y=9. No product-name or clock title. |
| Content | Begins at y=40 and ends at y=248, above the footer. |
| Footer | Hint text at y=256, with a separator 5 px above; prioritize hints that fit. |
| Launcher lists | 46 px rows; section headings are not selectable. Scroll in whole rows. (SDK lists differ; see the [UI guidelines](../apps/UI_GUIDELINES.md).) |
| Typography | Bundled Inter, DejaVu fallback; use the shared font cache and text-fitting methods. |
| Color | Semantic dark/light theme tokens for backgrounds, surfaces, text, accent, success, warning and error. |

Every screen answers four questions: where am I, what is selected, what will
confirmation do, and how do I go back? Put a short page name in the status bar,
use selection highlighting and a meaningful action label, and keep Back
available unless a documented modal operation must finish first. A long heading
belongs in the content, not a duplicate title row.

Prefer `Screen` / `ListScreen`, `Item`, `back_item`, shared status/footer/list
drawing and the existing `Painter`. Use semantic color tokens rather than
hard-coded values. Long text must fit or truncate through the shared helpers;
never leave a half row under the status bar. Keep disabled actions visibly
disabled and provide their reason when useful.

## Controls and feedback

- Button defaults: tap next, double-click previous, hold then release select,
  four clicks back. The launcher mapping is configurable; use `hints()` so
  displayed instructions follow the current settings.
- Keyboard: Up/Left previous, Down/Right/Tab next, Enter select, Esc back and
  Home home. Respect the screen's input handling and modal state.
- A hold shows release feedback when armed; selection occurs on release.
  The rendering path never performs the action.
- Before an app handoff, draw the launch screen so the daemon can retain it
  until the app draws. The current Connect WiFi flow intentionally retains
  Settings instead of an Opening screen, then returns to the preserved stack.
- Progress and errors should state what happened and expose a next action
  such as Retry, Logs or Back. Keep implementation details in diagnostics unless
  they help the user decide what to do.
- Use redraw requests for changed state. Avoid continuous animation and keep
  heavy lookups in workers; `draw()` reads cached state only.

Run `python3 -m mfruitos --preview /tmp/mfruit-preview` after meaningful layout
changes and inspect the relevant PNGs in both themes where affected. Check
long titles, empty lists, disabled rows, errors and selection near the bottom.
A PNG preview does not validate corner clipping, brightness or readability on
the physical LCD; record those separately.

## Python and shell conventions

- Support Python 3.9+. Match surrounding formatting, four-space indentation,
  small functions and descriptive names. Use type hints where they clarify
  contracts; existing modules commonly use `from __future__ import annotations`.
- Use snake_case for functions/modules, PascalCase for classes and uppercase
  constants. Prefer named shared constants over unexplained timing or geometry
  literals. Do not add a formatter/linter dependency solely for a small change.
- Keep modules focused. Navigation owns screen state, the application manager
  owns sessions, the host owns handoff, package services own installation, and
  drawing code owns presentation. Follow [Architecture](ARCHITECTURE.md).
- Use module loggers for runtime events and errors. Include app/session IDs,
  transitions and relevant state for lifecycle debugging. Explain ignored or
  invalid events rather than silently swallowing them. CLI output may use print.
- Prefer specific exceptions. Broad catches require an explained recovery or
  isolation boundary, with the failure reported. Avoid bare `except: pass`.
- Keep SDK imports relative so the copied `mfruit_sdk` package remains usable.
  Avoid core/launcher imports from app SDK modules.
- Preserve each shell script's declared interpreter. Installer/deployment
  helpers use Bash; the boot guard and stable wrappers may need plain `sh`.
  Quote paths/variables, validate destructive targets and keep install steps
  repeatable. Never place credentials in scripts, manifests or examples.

## Documentation style

Give each contract one canonical home. Link to it from old entrypoints and
other guides. Write actionable commands with their working directory and
required environment. Use placeholders for device addresses and dated quality
records for historical devices/results. Distinguish **implemented**, **planned**
and **verified**; do not advertise example APIs or commands as supported.

[Platform docs](README.md) · [Development rules](DEVELOPMENT_RULES.md)
