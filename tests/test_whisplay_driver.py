"""The bundled Whisplay driver (drivers/whisplay/runtime/whisplay.py) on recorded hardware.

``spidev`` and ``gpiod`` are replaced by recorders, so these tests show what
the driver sends to the board: which SPI bus and speed, which GPIO lines,
the LCD reset and ST7789 initialisation sequence, backlight and RGB LED duty
cycles and button callbacks. The expected values are Whisplay's (upstream
c73051e); a change to the driver that alters what reaches the hardware fails
here. Both libgpiod Python APIs (v1 on Ubuntu 22.04, v2 on Debian 13) are
covered. Physical behaviour is checked on devices (docs/quality/VALIDATION.md).
"""

import importlib.util
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from helpers import ROOT

RUNTIME = os.path.join(ROOT, "drivers", "whisplay", "runtime", "whisplay.py")

# BOARD pin -> line offset on gpiochip0: DC 13, RST 7, backlight 15, R 22, G 18, B 16, button 11.
PIN_LINES = {
    "rpi": {"dc": 27, "rst": 4, "led": 22, "red": 25, "green": 24, "blue": 23, "button": 17},
    "orangepi": {"dc": 227, "rst": 269, "led": 261, "red": 262, "green": 228, "blue": 270,
                 "button": 226},
}
SPI = {"rpi": (0, 0, 100_000_000), "orangepi": (1, 0, 48_000_000)}
MODELS = {"rpi": "Raspberry Pi Zero 2 W Rev 1.0", "orangepi": "OrangePi Zero2 W"}

# ST7789 initialisation (command, parameters) then a black full-screen frame.
INIT = [
    (0x11, b""), (0x36, b"\xC0"), (0x3A, b"\x05"), (0xB2, bytes([0x0C, 0x0C, 0x00, 0x33, 0x33])),
    (0xB7, b"\x35"), (0xBB, b"\x32"), (0xC2, b"\x01"), (0xC3, b"\x15"), (0xC4, b"\x20"),
    (0xC6, b"\x0F"), (0xD0, b"\xA4\xA1"),
    (0xE0, bytes([0xD0, 0x08, 0x0E, 0x09, 0x09, 0x05, 0x31, 0x33, 0x48, 0x17, 0x14, 0x15, 0x31, 0x34])),
    (0xE1, bytes([0xD0, 0x08, 0x0E, 0x09, 0x09, 0x15, 0x31, 0x33, 0x48, 0x17, 0x14, 0x15, 0x31, 0x34])),
    (0x21, b""), (0x29, b""),
]
# Columns 0..239; rows 20..299 (the panel's 240x280 window starts at row 20).
FULL_WINDOW = [(0x2A, bytes([0, 0, 0, 239])), (0x2B, bytes([0, 20, 1, 43]))]


class Recorder:
    """One ordered log of GPIO writes and SPI transfers made by the driver."""

    def __init__(self):
        self.events = []
        self.lock = threading.Lock()
        self.chips = {}
        self.inputs = {}

    def add(self, *event):
        with self.lock:
            self.events.append(event)

    def lcd(self, dc_line):
        """(command, parameters) pairs, decoded with the DC line as the driver set it."""
        dc, out = None, []
        with self.lock:
            events = list(self.events)
        for event in events:
            if event[0] == "gpio" and event[1] == dc_line:
                dc = event[2]
            elif event[0] == "xfer":
                assert dc == 0, "command sent with DC high"
                out.append([event[1][0], b""])
            elif event[0] == "write":
                assert dc == 1, "data sent with DC low"
                out[-1][1] += event[1]
        return [(cmd, data) for cmd, data in out]

    def writes(self, line):
        with self.lock:
            return [e[2] for e in self.events if e[0] == "gpio" and e[1] == line]


def fake_spidev(rec):
    module = types.ModuleType("spidev")

    class SpiDev:
        def open(self, bus, cs):
            rec.add("spi.open", bus, cs)
            rec.spi = self

        def xfer2(self, data):
            rec.add("xfer", bytes(data))

        def writebytes2(self, data):
            rec.add("write", bytes(data))

        def close(self):
            rec.add("spi.close")

    module.SpiDev = SpiDev
    return module


def fake_gpiod_v1(rec):
    module = types.ModuleType("gpiod")
    module.LINE_REQ_DIR_OUT, module.LINE_REQ_DIR_IN, module.LINE_REQ_FLAG_BIAS_DISABLE = 1, 2, 4

    class Line:
        def __init__(self, offset):
            self.offset = offset

        def request(self, consumer, type, default_val=None, flags=None):
            rec.add("request", self.offset, "out" if type == module.LINE_REQ_DIR_OUT else "in", consumer)

        def set_value(self, value):
            rec.add("gpio", self.offset, value)

        def get_value(self):
            return rec.inputs.get(self.offset, 0)

        def release(self):
            rec.add("release", self.offset)

    class Chip:
        def __init__(self, path):
            rec.chips[path] = self

        def get_line(self, offset):
            return Line(offset)

        def close(self):
            rec.add("chip.close")

    module.Chip = Chip
    return {"gpiod": module}


def fake_gpiod_v2(rec):
    module = types.ModuleType("gpiod")
    line = types.ModuleType("gpiod.line")

    class Enum:
        def __init__(self, name):
            self.name = name

    line.Direction = types.SimpleNamespace(OUTPUT=Enum("out"), INPUT=Enum("in"))
    line.Value = types.SimpleNamespace(ACTIVE=Enum("active"), INACTIVE=Enum("inactive"))
    line.Bias = types.SimpleNamespace(DISABLED=Enum("disabled"))

    class LineSettings:
        def __init__(self, direction, output_value=None, bias=None):
            self.direction, self.output_value, self.bias = direction, output_value, bias

    class Request:
        def __init__(self, offsets):
            self.offsets = offsets

        def set_value(self, offset, value):
            rec.add("gpio", offset, 1 if value is line.Value.ACTIVE else 0)

        def get_value(self, offset):
            return line.Value.ACTIVE if rec.inputs.get(offset, 0) else line.Value.INACTIVE

        def release(self):
            for offset in self.offsets:
                rec.add("release", offset)

    class Chip:
        def __init__(self, path):
            rec.chips[path] = self

        def request_lines(self, consumer, config):
            for offset, settings in config.items():
                rec.add("request", offset, settings.direction.name, consumer)
            return Request(list(config))

        def close(self):
            rec.add("chip.close")

    module.LineSettings, module.Chip, module.line = LineSettings, Chip, line
    return {"gpiod": module, "gpiod.line": line}


def load_board(platform, gpiod_api="v1", model=None):
    rec = Recorder()
    stubs = {"spidev": fake_spidev(rec)}
    stubs.update(fake_gpiod_v1(rec) if gpiod_api == "v1" else fake_gpiod_v2(rec))
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("whisplay_driver_under_test", RUNTIME)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.PLATFORM, module.PLATFORM_MODEL = platform, model or MODELS[platform]
        module._detect_orangepi_board = lambda: "zero2w"
        with patch("builtins.print"):
            board = module.WhisplayBoard()
    return board, rec


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.005)
    return True


class DriverOnBoards(unittest.TestCase):
    def check_board(self, platform, gpiod_api):
        board, rec = load_board(platform, gpiod_api)
        self.addCleanup(board.cleanup)
        pins = PIN_LINES[platform]
        bus, cs, speed = SPI[platform]

        self.assertEqual(list(rec.chips), ["/dev/gpiochip0"])
        requested = {e[1]: e[2] for e in rec.events if e[0] == "request"}
        self.assertEqual(requested, {pins["dc"]: "out", pins["rst"]: "out", pins["led"]: "out",
                                     pins["red"]: "out", pins["green"]: "out", pins["blue"]: "out",
                                     pins["button"]: "in"})
        self.assertIn(("spi.open", bus, cs), rec.events)
        self.assertEqual((rec.spi.max_speed_hz, rec.spi.mode), (speed, 0))

        # Reset pulse high-low-high, then the panel initialisation and a black frame.
        self.assertEqual(rec.writes(pins["rst"]), [1, 0, 1])
        frame = rec.lcd(pins["dc"])
        self.assertEqual(frame[:len(INIT)], INIT)
        self.assertEqual(frame[len(INIT):len(INIT) + 2], FULL_WINDOW)
        self.assertEqual(frame[len(INIT) + 2], (0x2C, bytes(240 * 280 * 2)))
        self.assertEqual(len(frame), len(INIT) + 3)

    def test_raspberry_pi_gpiod_v1(self):
        self.check_board("rpi", "v1")

    def test_raspberry_pi_gpiod_v2(self):
        self.check_board("rpi", "v2")

    def test_orange_pi_zero_2w_gpiod_v1(self):
        self.check_board("orangepi", "v1")

    def test_orange_pi_zero_2w_gpiod_v2(self):
        self.check_board("orangepi", "v2")

    def test_unsupported_board_is_refused_before_touching_hardware(self):
        with self.assertRaises(RuntimeError):
            load_board("unknown", model="NVIDIA Jetson")


class DriverFunctions(unittest.TestCase):
    def setUp(self):
        self.board, self.rec = load_board("rpi", "v2")
        self.addCleanup(self.board.cleanup)
        self.pins = PIN_LINES["rpi"]

    def test_draw_image_sets_the_window_then_sends_pixels(self):
        start = len(self.rec.lcd(self.pins["dc"]))
        pixels = bytes(range(256)) * 2
        self.board.draw_image(10, 20, 16, 16, pixels)
        self.assertEqual(self.rec.lcd(self.pins["dc"])[start:], [
            (0x2A, bytes([0, 10, 0, 25])), (0x2B, bytes([0, 40, 0, 55])), (0x2C, pixels)])
        with self.assertRaises(ValueError):
            self.board.draw_image(230, 0, 16, 16, pixels)

    def test_backlight_is_inverted_software_pwm_on_a_pi_zero_2(self):
        self.assertTrue(self.board.backlight_mode)
        self.board.set_backlight(30)
        self.assertEqual(self.board.backlight_pwm.duty_cycle, 70)  # LOW = lit
        self.board.set_backlight(100)
        self.assertEqual(self.board.backlight_pwm.duty_cycle, 0)

    def test_rgb_led_duty_cycles_are_inverted(self):
        self.board.set_rgb(255, 0, 51)
        self.assertEqual((self.board.red_pwm.duty_cycle, self.board.green_pwm.duty_cycle,
                          self.board.blue_pwm.duty_cycle), (0.0, 100.0, 80.0))

    def test_button_high_is_pressed_and_callbacks_follow_edges(self):
        seen = []
        self.board.on_button_press(lambda: seen.append("press"))
        self.board.on_button_release(lambda: seen.append("release"))
        self.rec.inputs[self.pins["button"]] = 1
        self.assertTrue(wait_for(lambda: seen == ["press"]))
        self.assertTrue(self.board.button_pressed())
        self.rec.inputs[self.pins["button"]] = 0
        self.assertTrue(wait_for(lambda: seen == ["press", "release"]))
        self.assertFalse(self.board.button_pressed())

    def test_cleanup_releases_every_line_and_the_spi_device(self):
        self.board.cleanup()
        released = {e[1] for e in self.rec.events if e[0] == "release"}
        self.assertEqual(released, set(self.pins.values()))
        self.assertIn(("spi.close",), self.rec.events)
        self.assertFalse(self.board._btn_thread.is_alive())


class FirstPiZeroBacklight(unittest.TestCase):
    def test_original_pi_zero_uses_a_plain_backlight_switch(self):
        board, rec = load_board("rpi", "v1", model="Raspberry Pi Zero W Rev 1.1")
        self.addCleanup(board.cleanup)
        self.assertFalse(board.backlight_mode)
        led = PIN_LINES["rpi"]["led"]
        board.set_backlight(0)
        board.set_backlight(80)
        self.assertEqual(rec.writes(led)[-2:], [1, 0])  # off = HIGH, on = LOW


if __name__ == "__main__":
    unittest.main()
