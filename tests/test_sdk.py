"""MFruit App SDK: keyboard decoding, button gestures, the input controller, chrome."""

import os
import tempfile
import unittest

from helpers import FakeClock
from mfruitos.sdk import input as sdk_input
from mfruitos.sdk.gestures import ButtonGestures
from mfruitos.sdk.input import (BACK, CHAR, ERASE, EXTRA, NEXT, PREVIOUS, SELECT, TALK_END,
                                TALK_START, InputController)
from mfruitos.sdk.keys import (DOWN, EVENT, EV_KEY, KEY_ENTER, KEY_ESC, KEY_SPACE, REPEAT, UP,
                               KeyDecoder, KeyEvent, KeyReader, has_keys)
from mfruitos.sdk import keys as sdk_keys

KEY_H, KEY_I, LEFTSHIFT, LEFTCTRL, KEY_C = 35, 23, 42, 29, 46


def raw(code, value=1):
    return EVENT.pack(0, 0, EV_KEY, code, value)


def tap(code):
    return raw(code, 1) + raw(code, 0)


def bitmap(*codes, words=4):
    value = sum(1 << code for code in codes)
    mask = (1 << sdk_keys.LONG_BITS) - 1
    parts = [(value >> (sdk_keys.LONG_BITS * n)) & mask for n in reversed(range(words))]
    return " ".join(f"{part:x}" for part in parts) + "\n"


class KeyDecoderTests(unittest.TestCase):
    def test_only_devices_with_letter_keys_are_keyboards(self):
        self.assertTrue(has_keys(bitmap(*range(1, 120))))
        self.assertFalse(has_keys(bitmap(116)))                  # power button
        self.assertFalse(has_keys(bitmap(*range(2, 12), 28)))    # remote: digits + OK

    def test_letters_shift_caps(self):
        d = KeyDecoder()
        stream = (tap(KEY_H) + raw(LEFTSHIFT) + tap(KEY_I) + raw(LEFTSHIFT, 0)
                  + tap(sdk_keys.KEY_CAPSLOCK) + tap(KEY_H))
        self.assertEqual([(e.kind, e.value) for e in d.feed(stream)],
                         [("char", "h"), ("char", "I"), ("char", "H")])

    def test_named_keys_report_down_repeat_and_up(self):
        d = KeyDecoder()
        events = d.feed(raw(KEY_SPACE, 1) + raw(KEY_SPACE, 2) + raw(KEY_SPACE, 0))
        self.assertEqual([(e.value, e.action) for e in events],
                         [("space", DOWN), ("space", REPEAT), ("space", UP)])

    def test_key_up_without_its_down_is_dropped(self):
        # The key went down before this reader opened the device.
        self.assertEqual(KeyDecoder().feed(raw(KEY_ENTER, 0)), [])

    def test_ctrl_chords_do_not_type(self):
        d = KeyDecoder()
        self.assertEqual(d.feed(raw(LEFTCTRL) + tap(KEY_C) + raw(LEFTCTRL, 0)), [])

    def test_events_split_across_reads(self):
        d = KeyDecoder()
        stream = tap(KEY_ENTER) + tap(KEY_ESC)
        got = d.feed(stream[:5]) + d.feed(stream[5:30]) + d.feed(stream[30:])
        self.assertEqual([(e.value, e.action) for e in got],
                         [("enter", DOWN), ("enter", UP), ("escape", DOWN), ("escape", UP)])

    def test_release_all_reports_held_keys(self):
        d = KeyDecoder()
        d.feed(raw(KEY_SPACE, 1))
        self.assertEqual([(e.value, e.action) for e in d.release_all()], [("space", UP)])
        self.assertEqual(d.release_all(), [])


class KeyReaderTests(unittest.TestCase):
    def test_finds_keyboards_and_reports_held_keys_when_one_goes_away(self):
        with tempfile.TemporaryDirectory() as tmp:
            sysdir = os.path.join(tmp, "sys")
            for name, codes in (("event0", (116,)), ("event1", range(1, 120))):
                caps = os.path.join(sysdir, name, "device", "capabilities")
                os.makedirs(caps)
                with open(os.path.join(caps, "key"), "w") as handle:
                    handle.write(bitmap(*codes))
            devdir = os.path.join(tmp, "dev")
            os.makedirs(devdir)
            fifo = os.path.join(devdir, "event1")
            os.mkfifo(fifo)
            seen = []
            reader = KeyReader(seen.append, input_dir=devdir, sys_dir=sysdir)
            self.assertEqual(reader.keyboards(), ["event1"])
            writer = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            try:
                reader._scan()
                self.assertTrue(reader.connected)
                os.write(writer, raw(KEY_SPACE, 1))
                fd = next(iter(reader._open))
                reader._read(fd)
                self.assertEqual([(e.value, e.action) for e in seen], [("space", DOWN)])
                os.remove(os.path.join(sysdir, "event1", "device", "capabilities", "key"))
                reader._scan()                      # unplugged
                self.assertFalse(reader.connected)
                self.assertEqual([(e.value, e.action) for e in seen],
                                 [("space", DOWN), ("space", UP)])
            finally:
                os.close(writer)


    def test_stop_is_prompt(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            reader = KeyReader(lambda e: None, input_dir=tmp, sys_dir=tmp, rescan_seconds=5.0)
            reader.start()
            time.sleep(0.05)
            started = time.monotonic()
            reader.stop()
            self.assertLess(time.monotonic() - started, 0.5)


    def test_a_keyboard_plugged_in_later_is_picked_up_at_once(self):
        """inotify, not polling: found well inside the (here 60 s) rescan period."""
        import threading
        import time
        from mfruitos.sdk.keys import DeviceWatch
        with tempfile.TemporaryDirectory() as tmp:
            sysdir, devdir = os.path.join(tmp, "sys"), os.path.join(tmp, "dev")
            os.makedirs(sysdir)
            os.makedirs(devdir)
            if DeviceWatch.open(devdir) is None:
                self.skipTest("no inotify here")
            seen, got = [], threading.Event()

            def on_event(event):
                seen.append((event.value, event.action))
                got.set()

            reader = KeyReader(on_event, input_dir=devdir, sys_dir=sysdir, rescan_seconds=60)
            reader.start()
            writer = None
            try:
                time.sleep(0.1)
                caps = os.path.join(sysdir, "event7", "device", "capabilities")
                os.makedirs(caps)
                with open(os.path.join(caps, "key"), "w") as handle:
                    handle.write(bitmap(*range(1, 120)))
                fifo = os.path.join(devdir, "event7")
                os.mkfifo(fifo)                      # the device node appears
                writer = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
                deadline = time.monotonic() + 2.0
                while not reader.connected and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(reader.connected)
                os.write(writer, raw(KEY_SPACE, 1))
                self.assertTrue(got.wait(2.0))
                got.clear()
                import shutil
                shutil.rmtree(os.path.join(sysdir, "event7"))
                os.remove(fifo)                      # unplugged while Space is down
                self.assertTrue(got.wait(2.0))
                self.assertEqual(seen, [("space", DOWN), ("space", UP)])
                self.assertFalse(reader.connected)
            finally:
                reader.stop()
                if writer is not None:
                    os.close(writer)


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.events = []
        self.g = ButtonGestures(lambda name, held: self.events.append(name), click_window_ms=300,
                                long_press_ms=700, debounce_ms=40, clock=self.clock,
                                threaded=False)

    def step(self, seconds):
        self.clock.advance(seconds)
        self.g.poll()

    def click(self, hold=0.08, gap=0.1):
        self.g.press()
        self.step(hold)
        self.g.release()
        self.step(gap)

    def test_click_counts(self):
        for count, name in ((1, "tap"), (2, "double"), (3, "triple")):
            self.events.clear()
            for _ in range(count):
                self.click()
            self.step(0.4)
            self.assertEqual(self.events, [name])

    def test_four_clicks_fire_on_the_fourth_release(self):
        for _ in range(4):
            self.click(gap=0.05)
        self.assertEqual(self.events, ["quad"])

    def test_hold_starts_while_held_and_ends_on_release(self):
        self.g.press()
        self.step(0.69)
        self.assertEqual(self.events, [])
        self.step(0.02)
        self.assertEqual(self.events, ["hold_start"])
        self.step(2.0)
        self.g.release()
        self.step(0.5)
        self.assertEqual(self.events, ["hold_start", "hold_end"])

    def test_tap_then_hold_reports_the_tap_first(self):
        self.click()
        self.g.press()
        self.step(0.8)
        self.assertEqual(self.events, ["tap", "hold_start"])

    def test_chatter_after_release_is_ignored(self):
        self.g.press()
        self.step(0.05)
        self.g.release()
        self.clock.advance(0.01)
        self.g.press()                 # bounce: within the debounce window
        self.step(0.02)
        self.g.release()
        self.step(0.4)
        self.assertEqual(self.events, ["tap"])


class ThreadedGestureTests(unittest.TestCase):
    def test_worker_thread_fires_holds_and_taps_on_time(self):
        import threading
        import time
        events = []
        done = threading.Event()

        def record(name, held):
            events.append((name, time.monotonic()))
            if name == "tap":
                done.set()

        g = ButtonGestures(record, click_window_ms=150, long_press_ms=200)
        g.start()
        try:
            start = time.monotonic()
            g.press()
            time.sleep(0.3)
            self.assertEqual([e[0] for e in events], ["hold_start"])   # while held
            self.assertLess(events[0][1] - start, 0.28)
            g.release()
            time.sleep(0.1)
            g.press()
            time.sleep(0.03)
            g.release()
            self.assertTrue(done.wait(1.0))
            self.assertEqual([e[0] for e in events], ["hold_start", "hold_end", "tap"])
        finally:
            g.stop()


class IdleTests(unittest.TestCase):
    def test_an_idle_button_worker_makes_no_wakeups(self):
        """On a device meant to sit idle all day, nothing pending means no polling."""
        import time
        polls = []

        class Counting(ButtonGestures):
            def poll(self):
                polls.append(1)
                super().poll()

        g = Counting(lambda name, held: None)
        g.start()
        try:
            time.sleep(1.3)
            self.assertEqual(len(polls), 1)          # the first look, then asleep
            g.press()
            time.sleep(0.05)
            g.release()
            time.sleep(0.6)                          # resolves the tap, then sleeps
            settled = len(polls)
            time.sleep(1.2)
            self.assertEqual(len(polls), settled)
        finally:
            g.stop()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.actions = []
        self.armed = []
        self.talk = False
        self.typing = False
        self.active = True
        self.c = InputController(self.actions.append, talk=lambda: self.talk,
                                 typing=lambda: self.typing, active=lambda: self.active,
                                 on_armed=self.armed.append, click_window_ms=300,
                                 long_press_ms=700, keyboard=False, clock=self.clock,
                                 threaded=False)

    def names(self):
        return [a.name for a in self.actions]

    def step(self, seconds):
        self.clock.advance(seconds)
        self.c.gestures.poll()

    def click(self, count=1):
        for _ in range(count):
            self.c.press()
            self.step(0.08)
            self.c.release()
            self.step(0.1)
        self.step(0.4)

    def hold(self, seconds=1.0):
        self.c.press()
        self.step(seconds)
        self.c.release()
        self.step(0.4)

    def key(self, name, action=DOWN, code=None):
        codes = {"enter": KEY_ENTER, "escape": KEY_ESC, "space": KEY_SPACE, "up": 103,
                 "down": 108, "left": 105, "right": 106, "tab": 15, "backspace": 14}
        self.c.key_event(KeyEvent("key", name, action, code or codes[name]))

    def test_button_menu_semantics(self):
        self.click(1)
        self.click(2)
        self.click(3)
        for _ in range(4):
            self.c.press()
            self.step(0.05)
            self.c.release()
            self.step(0.1)
        self.assertEqual(self.names(), [NEXT, PREVIOUS, EXTRA, BACK])

    def test_hold_arms_then_selects_on_release(self):
        self.c.press()
        self.step(0.8)
        self.assertEqual(self.armed, [True])
        self.assertEqual(self.names(), [])            # nothing happens while held
        self.c.release()
        self.assertEqual(self.names(), [SELECT])
        self.assertEqual(self.armed, [True, False])

    def test_talk_starts_sooner_than_a_menu_hold_arms(self):
        """talk_press_ms: the mic opens promptly; opening stays a deliberate hold."""
        self.c = InputController(self.actions.append, talk=lambda: self.talk,
                                 on_armed=self.armed.append, long_press_ms=700,
                                 talk_press_ms=350, keyboard=False, clock=self.clock,
                                 threaded=False)
        self.talk = True
        self.c.press()
        self.step(0.36)
        self.assertEqual(self.names(), [TALK_START])
        self.c.release()
        self.step(0.5)
        self.talk = False
        self.c.press()
        self.step(0.4)
        self.assertEqual(self.armed, [])             # 400 ms is not yet a menu hold
        self.step(0.35)
        self.assertEqual(self.armed, [True])
        self.c.release()
        self.assertEqual(self.names(), [TALK_START, TALK_END, SELECT])

    def test_hold_talks_on_talk_screens(self):
        self.talk = True
        self.c.press()
        self.step(0.8)
        self.assertEqual(self.names(), [TALK_START])  # while still held
        self.step(1.2)
        self.c.release()
        self.assertEqual(self.names(), [TALK_START, TALK_END])
        self.assertAlmostEqual(self.actions[-1].held, 2.0, places=1)
        self.assertEqual(self.armed, [])

    def test_keyboard_map(self):
        for name in ("down", "right", "tab", "up", "left", "enter", "escape", "backspace"):
            self.key(name)
        self.assertEqual(self.names(), [NEXT, NEXT, NEXT, PREVIOUS, PREVIOUS, SELECT, BACK,
                                        ERASE])

    def test_enter_and_escape_do_not_repeat(self):
        self.key("enter")
        self.key("enter", REPEAT)
        self.key("escape")
        self.key("escape", REPEAT)
        self.key("down")
        self.key("down", REPEAT)
        self.assertEqual(self.names(), [SELECT, BACK, NEXT, NEXT])

    def test_space_talks_while_held_on_talk_screens(self):
        self.talk = True
        self.key("space")
        self.key("space", REPEAT)
        self.clock.advance(1.5)
        self.key("space", UP)
        self.assertEqual(self.names(), [TALK_START, TALK_END])
        self.assertAlmostEqual(self.actions[-1].held, 1.5)

    def test_space_types_while_typing_or_off_talk_screens(self):
        self.key("space")
        self.talk, self.typing = True, True
        self.key("space")
        self.assertEqual([(a.name, a.char) for a in self.actions], [(CHAR, " "), (CHAR, " ")])

    def test_keys_pressed_elsewhere_are_ignored(self):
        # The Enter that launched this app goes up here; its repeat too.
        self.key("enter", REPEAT)
        self.key("enter", UP)
        self.key("space", UP)
        self.assertEqual(self.actions, [])

    def test_nothing_while_inactive_and_keys_owned_before_do_not_carry_over(self):
        self.active = False
        self.key("down")
        self.click(1)
        self.assertEqual(self.actions, [])
        self.active = True
        self.key("down", REPEAT)                     # went down while inactive
        self.assertEqual(self.actions, [])
        self.key("down")
        self.assertEqual(self.names(), [NEXT])

    def test_losing_the_screen_ends_a_talk(self):
        self.talk = True
        self.key("space")
        self.active = False
        self.key("space", UP)                         # detected on the next event
        self.assertEqual(self.names(), [TALK_START, TALK_END])

    def test_reset_ends_a_button_talk_once(self):
        self.talk = True
        self.c.press()
        self.step(0.8)
        self.c.reset()
        self.c.release()
        self.step(0.5)
        self.assertEqual(self.names(), [TALK_START, TALK_END])

    def test_handler_errors_do_not_break_input(self):
        calls = []

        def boom(action):
            calls.append(action.name)
            raise RuntimeError("app bug")

        self.c.on_action = boom
        with self.assertLogs("mfruit_sdk.input", "ERROR"):
            self.key("down")
            self.key("up")
        self.assertEqual(calls, [NEXT, PREVIOUS])


class ChromeTests(unittest.TestCase):
    def test_chrome_renders(self):
        from mfruitos.sdk.status import Status
        from mfruitos.sdk.ui import Canvas, Row, draw_list, footer, menu_hints, message, \
            status_bar, text_field, toast
        from mfruitos.sdk.ui.rgb565 import to_rgb565
        c = Canvas()
        status_bar(c, "Settings", Status(2, 55, True), badge=("LIVE", c.theme.success))
        rows = [Row(f"Row {i}", subtitle="detail" if i % 2 else None,
                    value=("on" if i % 3 else None), kind=("nav", "toggle", "action")[i % 3])
                for i in range(12)]
        draw_list(c, rows, 9)
        footer(c, menu_hints())
        toast(c, "Saved", "success")
        text_field(c, "hello " * 12, 120)
        message(Canvas(), "No data", "Retrying in a moment", "warning")
        self.assertEqual(len(to_rgb565(c.image)), 240 * 280 * 2)
        # The status bar drew something at the top right (battery) and top left (title).
        self.assertNotEqual(c.image.getpixel((22, 17)), c.theme.bg)

    def test_canvas_over_an_existing_draw(self):
        from PIL import Image, ImageDraw
        from mfruitos.sdk.ui import Canvas
        image = Image.new("RGB", (240, 280))
        draw = ImageDraw.Draw(image)
        c = Canvas.over(draw)
        c.text(20, 20, "Hi", 20, "bold")
        self.assertIs(c.image, image)
        self.assertNotEqual(image.getbbox(), None)

    def test_status_bar_reserves_a_slot_for_the_app(self):
        from mfruitos.sdk.status import Status
        from mfruitos.sdk.ui import Canvas, status_bar
        c = Canvas()
        slot = status_bar(c, "Walkie", Status(3, 50), reserve=20)
        plain = status_bar(Canvas(), "Walkie", Status(3, 50))
        self.assertEqual(plain - slot, 20)
        box = c.image.crop((slot, 0, slot + 20, 35))
        self.assertEqual(box.getcolors(), [(20 * 35, c.theme.bg)])

    def test_a_long_title_shrinks_before_it_is_cut(self):
        from mfruitos.sdk.status import Status
        from mfruitos.sdk.ui import Canvas, status_bar
        drawn = []
        c = Canvas()
        real = c.text
        c.text = lambda *a, **k: drawn.append((a, k)) or real(*a, **k)
        status_bar(c, "orangepizero2w", Status(3, 100, True), title_sizes=(17, 15, 13))
        (x, y, text, size, *_), kwargs = drawn[-1]
        self.assertEqual(text, "orangepizero2w")
        self.assertLess(size, 17)
        self.assertEqual(c.fit(text, size, "bold", kwargs["max_width"]), text)   # not cut

    def test_status_bar_without_hardware_draws_only_the_title(self):
        from mfruitos.sdk.status import Status
        from mfruitos.sdk.ui import Canvas, status_bar
        c = Canvas()
        status_bar(c, "Apps", Status())
        box = c.image.crop((150, 0, 240, 35))
        self.assertEqual(box.getcolors(), [(90 * 35, c.theme.bg)])

    def test_fonts_prefer_inter_from_the_mfruit_source(self):
        from mfruitos.sdk.ui.fonts import Fonts
        self.assertTrue(Fonts().is_inter)
        self.assertFalse(Fonts(dirs=[]).is_inter)

    def test_wifi_level_reads_proc(self):
        from mfruitos.sdk import status
        self.assertIn(status.wifi_level(), (None, 0, 1, 2, 3))


class DaemonTests(unittest.TestCase):
    def test_own_escape_key_sets_only_that_flag(self):
        from fake_daemon import FakeDaemon
        from mfruitos.sdk.daemon import own_escape_key
        daemon = FakeDaemon().start()
        try:
            daemon.handle({"cmd": "app.register", "payload": {
                "app_id": "demo", "display_name": "Demo", "launch_command": "./run.sh"}}, None)
            self.assertTrue(own_escape_key("demo", daemon.socket_path))
            record = daemon.apps["demo"]
            self.assertTrue(record["disable_esc_exit_key"])
            self.assertEqual((record["display_name"], record["launch_command"]),
                             ("Demo", "./run.sh"))
        finally:
            daemon.stop()
        with self.assertLogs("mfruit_sdk.daemon", "WARNING"):
            self.assertFalse(own_escape_key("demo", "/nonexistent.sock"))


class KeyboardDiagnosticsTests(unittest.TestCase):
    def test_the_diagnostics_row_names_the_keyboards_or_says_none(self):
        from mfruitos.system.diagnostics import check_keyboard
        self.assertEqual((check_keyboard(["event3"]).ok, check_keyboard(["event3"]).detail),
                         (True, "event3"))
        self.assertIsNone(check_keyboard([]).ok)             # no keyboard is not a fault

    def test_reader_lists_its_devices(self):
        reader = KeyReader(lambda e: None)
        self.assertEqual(reader.devices, [])
        reader._open = {7: ("event5", None), 4: ("event2", None)}
        self.assertEqual(reader.devices, ["event2", "event5"])


class ModuleTests(unittest.TestCase):
    def test_sdk_uses_relative_imports_only(self):
        # Apps vendor the SDK as ``mfruit_sdk``; an absolute import would break that.
        root = os.path.dirname(sdk_input.__file__)
        for folder, _, files in os.walk(root):
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name)) as handle:
                        source = handle.read()
                    self.assertNotIn("mfruitos", source.replace("mfruitos/", ""),
                                     f"{name} names mfruitos")


if __name__ == "__main__":
    unittest.main()


class KeyHubTests(unittest.TestCase):
    """MFruit OS holds the keyboards and hands keys to the app on screen."""

    def setUp(self):
        from mfruitos.launcher.keyhub import KeyHub
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "state", "keys.sock")
        self.hub = KeyHub(self.path)
        self.hub.start()
        self.addCleanup(self.hub.stop)

    def wait(self, condition, timeout=3.0):
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.02)
        return False

    def reader(self, app_id="demo"):
        seen = []
        reader = KeyReader(seen.append, app_id=app_id, hub=self.path,
                           input_dir=self.tmp.name, sys_dir=self.tmp.name)
        reader.start()
        self.addCleanup(reader.stop)
        self.assertTrue(self.wait(lambda: self.hub.connected(app_id)), "never connected")
        return reader, seen

    def test_keys_reach_the_app_they_are_sent_to(self):
        reader, seen = self.reader()
        other, other_seen = self.reader("other")
        self.hub.set_devices(["event3"])
        self.assertTrue(self.wait(lambda: reader.connected))
        self.assertEqual(reader.devices, ["event3"])
        self.assertTrue(self.hub.send("demo", KeyEvent("key", "enter", DOWN, KEY_ENTER)))
        self.assertTrue(self.wait(lambda: seen))
        self.assertEqual(seen, [KeyEvent("key", "enter", DOWN, KEY_ENTER)])
        self.assertEqual(other_seen, [])
        self.assertFalse(self.hub.send("nobody", KeyEvent("key", "enter", DOWN, KEY_ENTER)))

    def test_a_held_key_is_released_when_mfruit_os_goes_away(self):
        reader, seen = self.reader()
        self.hub.send("demo", KeyEvent("key", "space", DOWN, KEY_SPACE))
        self.assertTrue(self.wait(lambda: seen))
        self.hub.stop()
        self.assertTrue(self.wait(lambda: len(seen) == 2))
        self.assertEqual(seen[-1], KeyEvent("key", "space", UP, KEY_SPACE))
        self.assertTrue(self.wait(lambda: not reader.via_hub))

    def test_an_app_that_leaves_is_forgotten(self):
        reader, _ = self.reader()
        reader.stop()
        self.assertTrue(self.wait(lambda: not self.hub.connected("demo")))

    def test_the_socket_is_private(self):
        import stat
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


class GrabTests(unittest.TestCase):
    def test_a_grabbing_reader_holds_each_keyboard_exclusively(self):
        from unittest import mock
        from mfruitos.sdk import keys
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(keys.fcntl, "ioctl", lambda fd, req, arg: calls.append((req, arg))):
            caps = os.path.join(tmp, "sys", "event4", "device", "capabilities")
            os.makedirs(caps)
            with open(os.path.join(caps, "key"), "w") as handle:
                handle.write(bitmap(*range(1, 120)))
            os.makedirs(os.path.join(tmp, "dev"))
            fifo = os.path.join(tmp, "dev", "event4")
            os.mkfifo(fifo)
            writer = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            try:
                reader = KeyReader(lambda e: None, input_dir=os.path.join(tmp, "dev"),
                                   sys_dir=os.path.join(tmp, "sys"), grab=True)
                reader._scan()
                self.assertEqual(calls, [(keys.EVIOCGRAB, 1)])
                reader.set_grab(False)              # the daemon desktop: let others read
                self.assertEqual(calls[-1], (keys.EVIOCGRAB, 0))
                for fd in list(reader._open):
                    reader._close(fd)
            finally:
                os.close(writer)

    def test_a_grabbing_reader_never_uses_the_hub(self):
        reader = KeyReader(lambda e: None, app_id="mfruit-os", hub="/tmp/whatever", grab=True)
        self.assertIsNone(reader._hub_path())
