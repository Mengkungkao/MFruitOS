"""Stand-in for Whisplay's runtime/whisplay.py so the real daemon runs without hardware.

Only the WhisplayBoard surface the daemon uses is provided. Button presses are
injected by the harness runner through ``BOARD.press()`` / ``BOARD.release()``,
which invoke the daemon's registered callbacks exactly like the GPIO monitor
thread of the real board does.
"""

BOARD = None


class WhisplayBoard:
    LCD_WIDTH = 240
    LCD_HEIGHT = 280
    CornerHeight = 20

    def __init__(self):
        global BOARD
        BOARD = self
        self._pressed = False
        self._on_press = None
        self._on_release = None
        self.backlight = 100
        self.rgb = (0, 0, 0)
        self.frames = 0
        self.last_frame = b""

    def on_button_press(self, callback):
        self._on_press = callback

    def on_button_release(self, callback):
        self._on_release = callback

    def button_pressed(self):
        return self._pressed

    def press(self):
        self._pressed = True
        if self._on_press:
            self._on_press()

    def release(self):
        self._pressed = False
        if self._on_release:
            self._on_release()

    def set_backlight(self, brightness):
        self.backlight = brightness

    def set_backlight_mode(self, mode):
        pass

    def set_rgb(self, r, g, b):
        self.rgb = (r, g, b)

    def set_rgb_fade(self, r, g, b, duration_ms=100):
        self.rgb = (r, g, b)

    def draw_image(self, x, y, width, height, pixel_data):
        self.frames += 1
        self.last_frame = bytes(pixel_data)

    def fill_screen(self, color):
        pass

    def cleanup(self):
        pass
