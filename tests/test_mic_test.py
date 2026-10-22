"""Settings → Audio → Test microphone, and the Microphone diagnostics check.

On 2026-10-22 a new Orange Pi's microphone failed three ways in one
afternoon, and nothing on the device said so: a leftover recorder from
another app held it ("Device or resource busy"), the Whisplay card was
missing after a boot (the Audio check still said OK: the board has a sound
card of its own), and an app asking the card for one channel got the
microphone 35 dB down. These tests pin what the test and the check report
in each case.
"""

import os
import struct
import subprocess
import sys
import tempfile
import textwrap
from unittest.mock import Mock, patch

import helpers
from helpers import ROOT, TempHomeTestCase
from mfruitos.launcher.runtime import Runtime
from mfruitos.launcher.ui.painter import Painter
from mfruitos.launcher.ui.screens.diagnostics import CHECK_ORDER, DiagnosticsScreen, MicTestScreen
from mfruitos.launcher.ui.screens.settings import AudioScreen
from mfruitos.launcher.ui.theme import DARK
from mfruitos.system import diagnostics as d

VOICE = 16000                       # about -6 dBFS


def stereo(left: int, right: int, seconds: float) -> bytes:
    return struct.pack("<hh", left, right) * int(seconds * d.MIC_RATE)


# Output of `arecord -l` on the Orange Pi opi2w (2026-10-22).
ARECORD_L = textwrap.dedent("""\
    **** List of CAPTURE Hardware Devices ****
    card 2: ahubhdmi [ahubhdmi], device 0: ahub_plat-i2s-hifi i2s-hifi-0 [ahub_plat-i2s-hifi i2s-hifi-0]
      Subdevices: 1/1
      Subdevice #0: subdevice #0
    card 3: whisplaysound [Whisplay Sound], device 0: Whisplay HiFi wm8960-hifi-0 [Whisplay HiFi wm8960-hifi-0]
      Subdevices: 1/1
      Subdevice #0: subdevice #0
    """)


class MicLevelTests(TempHomeTestCase):
    def test_a_microphone_on_one_channel_works_and_says_which(self):
        levels = d.analyse_stereo(stereo(VOICE, 0, 3))
        self.assertEqual(levels.side, "left")
        self.assertAlmostEqual(levels.left_peak, -6.2, places=1)
        result = d.judge_microphone(levels)
        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "OK (-6 dB, left)")

    def test_quiet_silent_and_empty_recordings_are_problems(self):
        quiet = d.judge_microphone(d.analyse_stereo(stereo(500, 0, 3)))
        self.assertFalse(quiet.ok)
        self.assertEqual(quiet.detail, "very quiet (-36 dB)")
        silent = d.judge_microphone(d.analyse_stereo(stereo(0, 0, 3)))
        self.assertEqual((silent.ok, silent.detail), (False, "no sound at all"))
        empty = d.judge_microphone(d.analyse_stereo(stereo(VOICE, VOICE, 0.1)))
        self.assertEqual((empty.ok, empty.detail), (False, "recorded nothing"))


class FindMicrophoneTests(TempHomeTestCase):
    def test_capture_cards_are_read_from_arecord(self):
        with patch.object(d.subprocess, "run", return_value=Mock(stdout=ARECORD_L)):
            self.assertEqual(d.capture_cards(), [(2, "ahubhdmi"), (3, "whisplaysound")])

    def test_the_whisplay_card_is_chosen_not_hdmi(self):
        with patch.object(d, "capture_cards", return_value=[(2, "ahubhdmi"), (3, "whisplaysound")]):
            self.assertEqual(d.find_microphone(), ("plughw:3", "whisplaysound"))

    def test_a_missing_whisplay_card_is_reported_not_another_card(self):
        """The 18:06 boot: only the board's HDMI capture, and the driver installed."""
        with patch.object(d, "capture_cards", return_value=[(2, "ahubhdmi"), (1, "Device")]), \
                patch.object(d.os.path, "isdir", return_value=True):
            self.assertEqual(d.find_microphone(), (None, "Whisplay sound card missing"))
            check = d.check_microphone()
        self.assertEqual((check.ok, check.detail), (False, "Whisplay sound card missing"))

    def test_without_the_whisplay_driver_another_microphone_is_used(self):
        with patch.object(d, "capture_cards", return_value=[(1, "Device")]), \
                patch.object(d.os.path, "isdir", return_value=False):
            self.assertEqual(d.find_microphone(), ("plughw:1", "Device"))

    def test_no_microphone_at_all_is_not_a_failure(self):
        with patch.object(d, "capture_cards", return_value=[]), \
                patch.object(d.os.path, "isdir", return_value=False):
            check = d.check_microphone()
        self.assertEqual((check.ok, check.detail), (None, "no microphone"))


class StandInArecord(TempHomeTestCase):
    """A real arecord stand-in on PATH, modelled on opi2w's card: in stereo
    the microphone is on the left; asked for one channel it is 35 dB down;
    busy while a flag file exists."""

    def setUp(self):
        super().setUp()
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        self.busy = os.path.join(self.tmp, "busy")
        script = os.path.join(bin_dir, "arecord")
        with open(script, "w") as fp:
            fp.write(textwrap.dedent(f"""\
                #!{sys.executable}
                import os, struct, sys
                if os.path.exists({self.busy!r}):
                    sys.stderr.write("arecord: main:831: audio open error: Device or resource busy\\n")
                    sys.exit(1)
                args = sys.argv
                frames = int(args[args.index("-s") + 1])
                if args[args.index("-c") + 1] == "2":
                    frame = struct.pack("<hh", {VOICE}, 0)
                else:
                    frame = struct.pack("<h", {round(VOICE * 10 ** (-35 / 20))})
                sys.stdout.buffer.write(frame * frames)
                """))
        os.chmod(script, 0o755)
        path = patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]})
        path.start()
        self.addCleanup(path.stop)
        cards = patch.object(d, "capture_cards", return_value=[(3, "whisplaysound")])
        cards.start()
        self.addCleanup(cards.stop)

    def test_the_test_records_in_stereo_and_hears_the_left_channel(self):
        test = d.record_microphone(1)
        self.assertTrue(test.result.ok, test.result.detail)
        self.assertEqual(test.levels.side, "left")
        self.assertEqual(len(test.audio), d.MIC_RATE * 4)
        self.assertEqual(test.card, "whisplaysound")

    def test_the_quick_check_passes_on_a_working_microphone(self):
        check = d.check_microphone()
        self.assertEqual((check.ok, check.detail), (True, "whisplaysound"))

    def test_a_busy_microphone_says_so_and_names_who_has_it(self):
        open(self.busy, "w").close()
        test = d.record_microphone(1)
        self.assertEqual((test.result.ok, test.result.detail),
                         (False, "busy: another program has it"))
        with patch.object(d, "mic_holder", return_value="sox (7221)"):
            self.assertEqual(d.check_microphone().detail, "busy: used by sox (7221)")

    def test_the_process_holding_the_capture_device_is_found(self):
        proc = tempfile.mkdtemp(dir=self.tmp)
        for pid, target, name in (("7221", "/dev/snd/pcmC3D0c", "sox"),
                                  ("8000", "/dev/snd/pcmC3D0p", "aplay")):
            os.makedirs(os.path.join(proc, pid, "fd"))
            os.symlink(target, os.path.join(proc, pid, "fd", "4"))
            with open(os.path.join(proc, pid, "comm"), "w") as fp:
                fp.write(name + "\n")
        self.assertEqual(d.mic_holder("plughw:3", proc=proc), "sox (7221)")
        self.assertEqual(d.mic_holder("plughw:2", proc=proc), "")


class MicTestScreenTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.rt = Runtime(self.paths, ROOT, socket_path=self.tmp + "/none.sock",
                          input_dir=helpers.NO_INPUT_DEVICES)
        self.rt.router.set_root(self.rt.home_screen)
        self.rt.run_task = Mock()
        self.painter = Painter(DARK, self.rt.fonts)

    def task(self, index=-1):
        """(name, done callback) of a run_task call."""
        call = self.rt.run_task.call_args_list[index]
        return call.args[0], call.args[2]

    def draws(self, screen):
        screen.draw(self.painter)          # must not raise in any state

    def recorded(self, ok=True):
        levels = d.analyse_stereo(stereo(VOICE if ok else 0, 0, 1))
        return d.MicTest(d.judge_microphone(levels), levels, stereo(VOICE, 0, 1), "whisplaysound")

    def test_record_play_back_then_test_again(self):
        screen = MicTestScreen(self.rt)
        self.rt.push(screen)
        self.assertEqual(screen.state, "recording")
        self.draws(screen)
        name, done = self.task()
        self.assertEqual(name, "mic-test")
        done(self.recorded())
        self.assertEqual(screen.state, "playing")
        self.draws(screen)
        name, played = self.task()
        self.assertEqual(name, "mic-playback")
        played(d.CheckResult("Speaker", True, "played back"))
        self.assertEqual(screen.state, "done")
        self.assertEqual(screen.advice(), "Did you hear yourself?")
        self.draws(screen)
        self.assertTrue(screen.handle("select"))
        self.assertEqual(screen.state, "recording")
        self.assertEqual(self.rt.run_task.call_count, 3)

    def test_leaving_while_recording_plays_nothing_back(self):
        screen = MicTestScreen(self.rt)
        self.rt.push(screen)
        self.rt.pop()
        _name, done = self.task()
        done(self.recorded())
        self.assertEqual(screen.state, "done")
        self.assertEqual(self.rt.run_task.call_count, 1, "no playback after the user left")

    def test_select_does_nothing_while_recording(self):
        screen = MicTestScreen(self.rt)
        self.rt.push(screen)
        self.assertTrue(screen.handle("select"))
        self.assertEqual(self.rt.run_task.call_count, 1)

    def test_the_footer_offers_only_what_a_press_does(self):
        screen = MicTestScreen(self.rt)
        self.rt.push(screen)
        self.assertEqual([label for _g, label in screen.footer_hints()], ["back"])
        _name, done = self.task()
        done(d.MicTest(d.CheckResult("Microphone", False, "no microphone")))
        self.assertEqual([label for _g, label in screen.footer_hints()], ["test again", "back"])
        screen.footer(self.painter)

    def test_problems_come_with_what_to_do(self):
        screen = MicTestScreen(self.rt)
        self.rt.push(screen)
        _name, done = self.task()
        done(d.MicTest(d.CheckResult("Microphone", False, "busy: used by sox (7221)")))
        self.assertEqual(screen.state, "done")
        self.assertIn("Close the app", screen.advice())
        self.draws(screen)
        screen.start()
        _name, done = self.task()
        done(d.MicTest(d.CheckResult("Microphone", False, "Whisplay sound card missing")))
        self.assertIn("Restart the device", screen.advice())
        screen.start()
        _name, done = self.task()
        done(self.recorded(ok=False))
        _name, played = self.task()
        played(d.CheckResult("Speaker", True, "played back"))
        self.assertIn("Speak close", screen.advice())
        self.draws(screen)

    def test_a_failed_recording_task_is_shown_not_stuck(self):
        screen = MicTestScreen(self.rt)
        self.rt.push(screen)
        failed = self.rt.run_task.call_args.args[3]
        failed(OSError("arecord vanished"))
        self.assertEqual(screen.state, "done")
        self.assertFalse(screen.test.result.ok)
        self.draws(screen)

    def test_the_test_is_in_settings_audio_and_diagnostics(self):
        self.assertIn("Test microphone", [i.label for i in AudioScreen(self.rt).items()])
        self.assertIn("Test microphone", [i.label for i in DiagnosticsScreen(self.rt).items()])
        self.assertIn("Microphone", CHECK_ORDER)
