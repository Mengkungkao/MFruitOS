"""Hello Whisplay — a template app: tap to count, hold to reset, 4 taps to exit.

The exit gesture (four quick clicks) is handled by whisplay-daemon, which
sends app_exit_requested; the app then releases the screen and quits, and
MFruit OS takes over again.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from whisplay_app import HEIGHT, WIDTH, WhisplayApp

HOLD_SEC = 0.7
DATA_DIR = os.environ.get("WHISPLAY_OS_APP_DATA", os.path.dirname(os.path.abspath(__file__)))
COUNT_FILE = os.path.join(DATA_DIR, "count.txt")


def font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


class Counter:
    def __init__(self):
        self.app = WhisplayApp()
        self.count = self._load()
        self.pressed_at = 0.0
        self.done = threading.Event()
        self.big, self.small, self.hint = font(64), font(16), font(12)

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
        image = Image.new("RGB", (WIDTH, HEIGHT), (10, 12, 16))
        d = ImageDraw.Draw(image)
        d.text((WIDTH // 2, 60), "Hello Whisplay", font=self.small, fill=(150, 158, 170), anchor="mm")
        d.text((WIDTH // 2, HEIGHT // 2), str(self.count), font=self.big, fill=(255, 255, 255),
               anchor="mm")
        d.text((WIDTH // 2, HEIGHT - 50), "tap +1 · hold reset · 4× exit", font=self.hint,
               fill=(46, 140, 255), anchor="mm")
        self.app.show(image)

    def on_press(self) -> None:
        self.pressed_at = time.monotonic()

    def on_release(self) -> None:
        held = time.monotonic() - self.pressed_at
        self.count = 0 if held >= HOLD_SEC else self.count + 1
        self._save()
        self.draw()

    def run(self) -> int:
        self.app.on_press = self.on_press
        self.app.on_release = self.on_release
        self.app.on_exit_request = self.done.set
        self.app.on_focus_changed = lambda has_focus: has_focus and self.draw()
        try:
            self.app.start()
        except (OSError, RuntimeError) as exc:
            print(f"hello-whisplay: whisplay-daemon unavailable: {exc}", file=sys.stderr)
            return 1
        self.draw()
        self.done.wait()
        self.app.stop()
        return 0


if __name__ == "__main__":
    sys.exit(Counter().run())
