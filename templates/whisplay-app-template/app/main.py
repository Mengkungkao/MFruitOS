"""Hello MFruit -- the MFruit OS app template: a counter.

    button            keyboard            action
    tap               Down, Right, Tab    +1
    2 clicks          Up, Left            -1
    hold, release     Enter               reset to 0
    4 clicks          Esc                 leave the app, back to MFruit OS

It shows how an MFruit OS app is put together (docs/APP_RULES.md in the
MFruit OS repository):

* All input goes through mfruit_sdk.input.InputController -- the button and
  any USB or Bluetooth keyboard -- so the controls are MFruit OS's own. It
  acts only while this app has the screen.
* The screen uses MFruit OS's status bar (page name, WiFi, battery) and
  footer hints, from mfruit_sdk.ui.
* The manifest sets exit_gesture "none" and disable_esc_exit_key, and the
  app claims Esc at start-up: 4 clicks and Esc are the app's "back", and
  back from here leaves.

mfruit_sdk/ is a copy of MFruit OS's mfruitos/sdk; refresh it with
MFruitOS/scripts/sdk-sync.sh <this app>/app.
"""

from __future__ import annotations

import os
import sys
import threading

from mfruit_sdk.daemon import own_escape_key
from mfruit_sdk.input import BACK, NEXT, PREVIOUS, SELECT, InputController
from mfruit_sdk.status import StatusMonitor
from mfruit_sdk.ui import Canvas, footer, status_bar
from mfruit_sdk.ui.theme import CONTENT_BOTTOM, CONTENT_TOP, SCREEN_W

from whisplay_app import WhisplayApp

DATA_DIR = os.environ.get("WHISPLAY_OS_APP_DATA", os.path.dirname(os.path.abspath(__file__)))
COUNT_FILE = os.path.join(DATA_DIR, "count.txt")
HINTS = [("tap", "+1"), ("hold", "reset"), ("4×", "exit")]


def render(count: int, status=None, armed: bool = False):
    """The whole screen, from state: a pure function, easy to test."""
    c = Canvas()
    status_bar(c, "Counter", status)
    middle = (CONTENT_TOP + CONTENT_BOTTOM) // 2
    c.text(SCREEN_W // 2, middle, str(count), 64, "bold", anchor="mm")
    c.text(SCREEN_W // 2, middle + 48, "Hello MFruit", 14, "medium", c.theme.text_muted,
           anchor="mm")
    footer(c, [("release", "to reset")] if armed else HINTS)
    return c.image


class Counter:
    def __init__(self, app: WhisplayApp | None = None):
        self.app = app or WhisplayApp()
        self.count = self._load()
        self.armed = False
        self.done = threading.Event()
        self.status = StatusMonitor(on_change=lambda _s: self.draw())
        self.input = InputController(self.on_action, active=lambda: self.app.has_focus,
                                     on_armed=self.on_armed, app_id=self.app.app_id)

    def _load(self) -> int:
        try:
            with open(COUNT_FILE) as fp:
                return int(fp.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(COUNT_FILE, "w") as fp:
            fp.write(str(self.count))

    def draw(self) -> None:
        self.app.show(render(self.count, self.status.sample(), self.armed))

    def on_armed(self, armed: bool) -> None:
        self.armed = armed
        self.draw()

    def on_action(self, action) -> None:
        if action.name == BACK:
            self.done.set()             # back from the only screen: leave
            return
        if action.name == NEXT:
            self.count += 1
        elif action.name == PREVIOUS:
            self.count -= 1
        elif action.name == SELECT:
            self.count = 0
        else:
            return
        self._save()
        self.draw()

    def on_focus_changed(self, has_focus: bool) -> None:
        self.input.reset()              # keys pressed elsewhere are not ours
        if has_focus:
            self.draw()

    def run(self) -> int:
        self.app.on_press = self.input.press
        self.app.on_release = self.input.release
        self.app.on_exit_request = self.done.set
        self.app.on_focus_changed = self.on_focus_changed
        # Before taking the screen: a registration makes the daemon redraw
        # its desktop. (MFruit OS registers the package with the manifest's
        # disable_esc_exit_key too; this covers a copy started by hand.)
        own_escape_key(self.app.app_id)
        try:
            self.app.start()
        except (OSError, RuntimeError) as exc:
            print(f"hello-whisplay: whisplay-daemon unavailable: {exc}", file=sys.stderr)
            return 1
        self.status.start()
        self.input.start()
        self.draw()
        self.done.wait()
        self.input.stop()
        self.status.stop()
        self.app.stop()
        return 0


if __name__ == "__main__":
    sys.exit(Counter().run())
