"""The daemon wrapper parks the LCD's DC line low after every data transfer.

On a stacked SX126X LoRa HAT that line is the module's M1; upstream Whisplay
leaves it high after each frame, which holds the radio in configuration mode
(deaf: Messenger and WalkieTalkie show "Radio deaf: check M0/M1").
"""

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch

from helpers import ROOT
from real_daemon import find_whisplay_src

spec = importlib.util.spec_from_file_location(
    "mfruit_daemon_dc", os.path.join(ROOT, "scripts", "whisplay-daemon-mfruit.py"))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)

WHISPLAY_SRC = find_whisplay_src()


class Line:
    def __init__(self):
        self.value = None

    def set_value(self, value):
        self.value = value


class Spi:
    def __init__(self):
        self.writes = []

    def writebytes2(self, data):
        self.writes.append(bytes(data))

    def xfer2(self, data):
        self.writes.append(bytes(data))


def upstream_board_class():
    """The transfer methods as upstream 1066486 has them: DC left high."""
    class WhisplayBoard:
        DC_PIN = 13

        def _gpio_output(self, pin, value):
            self._gpio_lines[pin].set_value(1 if value else 0)

        def _send_command(self, cmd, *args):
            self._gpio_output(self.DC_PIN, 0)
            self.spi.xfer2([cmd])
            if args:
                self._gpio_output(self.DC_PIN, 1)
                self._send_data(list(args))

        def _send_data(self, data):
            self._gpio_output(self.DC_PIN, 1)
            self.spi.writebytes2(data)

        def _send_data_bytes(self, data):
            self._gpio_output(self.DC_PIN, 1)
            self.spi.writebytes2(data)
    return WhisplayBoard


def board_of(cls):
    board = cls.__new__(cls)
    board._gpio_lines = {cls.DC_PIN: Line()}
    board.spi = Spi()
    return board


def transfers(board):
    """Each transfer a frame flush makes, with DC's level after it."""
    dc = board._gpio_lines[board.DC_PIN]
    after = {}
    board._send_command(0x2A, 0, 0, 0, 239)
    after["command with data"] = dc.value
    board._send_data([1, 2, 3])
    after["data"] = dc.value
    board._send_data_bytes(bytearray(8))
    after["frame bytes"] = dc.value
    return after


class DcParkTests(unittest.TestCase):
    def test_upstream_leaves_dc_high_after_every_data_transfer(self):
        # Negative control: what the fix exists for.
        board = board_of(upstream_board_class())
        self.assertEqual(set(transfers(board).values()), {1})

    def test_parked_dc_is_low_after_every_transfer_and_data_still_sent(self):
        cls = upstream_board_class()
        self.assertEqual(wrapper.park_dc_low(types.SimpleNamespace(WhisplayBoard=cls)),
                         ["_send_data", "_send_data_bytes"])
        board = board_of(cls)
        self.assertEqual(set(transfers(board).values()), {0})
        self.assertEqual(board.spi.writes,
                         [b"\x2a", bytes([0, 0, 0, 239]), bytes([1, 2, 3]), bytes(8)])

    def test_dc_is_parked_even_when_the_transfer_fails(self):
        cls = upstream_board_class()
        wrapper.park_dc_low(types.SimpleNamespace(WhisplayBoard=cls))
        board = board_of(cls)
        board.spi.writebytes2 = lambda data: (_ for _ in ()).throw(OSError("spi"))
        with self.assertRaises(OSError):
            board._send_data_bytes(b"\0")
        self.assertEqual(board._gpio_lines[cls.DC_PIN].value, 0)

    def test_applying_twice_wraps_once(self):
        cls = upstream_board_class()
        module = types.SimpleNamespace(WhisplayBoard=cls)
        wrapper.park_dc_low(module)
        self.assertEqual(wrapper.park_dc_low(module), [])

    def test_unfamiliar_or_missing_board_is_left_alone(self):
        self.assertEqual(wrapper.park_dc_low(None), [])
        self.assertEqual(wrapper.park_dc_low(types.SimpleNamespace()), [])
        self.assertEqual(wrapper.park_dc_low(
            types.SimpleNamespace(WhisplayBoard=type("WhisplayBoard", (), {}))), [])


@unittest.skipIf(WHISPLAY_SRC is None, "Whisplay source not found (set WHISPLAY_SRC)")
class RealWhisplayBoardTests(unittest.TestCase):
    """Against the real runtime/whisplay.py (hardware modules stubbed)."""

    def load(self):
        gpiod = types.ModuleType("gpiod")
        stubs = {"spidev": types.ModuleType("spidev"), "gpiod": gpiod,
                 "gpiod.line": types.ModuleType("gpiod.line")}
        with patch.dict(sys.modules, stubs):
            path = os.path.join(WHISPLAY_SRC, "runtime", "whisplay.py")
            spec = importlib.util.spec_from_file_location("whisplay_under_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_real_board_rests_dc_low_after_a_frame_with_the_wrapper(self):
        module = self.load()
        self.assertEqual(wrapper.park_dc_low(module), ["_send_data", "_send_data_bytes"])
        board = board_of(module.WhisplayBoard)
        self.assertEqual(set(transfers(board).values()), {0})


if __name__ == "__main__":
    unittest.main()
