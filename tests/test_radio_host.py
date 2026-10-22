"""LoRa radio capability (mfruitos.hosts.lora): provisioning and readiness."""

import os
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401
from mfruitos.hosts.lora import __main__ as cli
from mfruitos.hosts.lora import sx126x
from mfruitos.hosts.lora.readiness import radio_status
from mfruitos.sdk.radio import settings as rs


class FakeLines:
    def __init__(self):
        self.calls = []
        self.closed = False

    def set(self, m0, m1):
        self.calls.append((m0, m1))

    def close(self):
        self.closed = True


class FakeSerial:
    def __init__(self, replies):
        self.replies = list(replies)
        self.written = []
        self.closed = False

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written.append(bytes(data))

    def flush(self):
        pass

    def read(self, size):
        return self.replies.pop(0) if self.replies else b""

    def close(self):
        self.closed = True


class RegisterTests(unittest.TestCase):
    def test_au915_register_matches_walkietalkie_layout(self):
        reg = sx126x.encode(0, 920, air_speed=2400, power=22)
        self.assertEqual(reg[0], sx126x.REG_PERSIST)
        self.assertEqual(reg[8], 70)                  # 920 - 850
        self.assertEqual(reg[6], 0x60 + 0x02)         # 9600 baud UART, 2.4k air
        self.assertEqual(reg[9], 0xC3)                # fixed transmission + RSSI byte
        info = sx126x.describe(bytes([0xC1]) + reg[1:])
        self.assertEqual((info["frequency_mhz"], info["air_speed"], info["power_dbm"]), (920, 2400, 22))

    # Read from the two Orange Pis on 2026-10-22 (docs/quality/records/
    # 2026-10-22-radio-module-settings.md): the new board as provisioned, the
    # old one on factory settings while its radio.json said 920 MHz.
    PROVISIONED = bytes.fromhex("c10009000000622046c30000")
    FACTORY = bytes.fromhex("c10009000000620012030000")

    def test_a_module_on_factory_settings_differs_in_every_way_that_matters(self):
        found = sx126x.differences(self.FACTORY, sx126x.encode(0, 920))
        self.assertEqual(found, [
            "frequency 868 (wanted 920)",
            "addressed (fixed) transmission False (wanted True)",
            "signal strength after each packet False (wanted True)",
            "channel level replies False (wanted True)",
        ])

    def test_a_provisioned_module_matches_and_the_key_bytes_are_not_compared(self):
        self.assertEqual(sx126x.differences(self.PROVISIONED, sx126x.encode(0, 920)), [])
        # The key registers are write-only: they always read back as zero.
        self.assertEqual(sx126x.differences(self.PROVISIONED[:10] + b"\xff\xff",
                                            sx126x.encode(0, 920)), [])
        self.assertEqual(sx126x.differences(self.PROVISIONED, sx126x.encode(0, 915)),
                         ["frequency 920 (wanted 915)"])

    def test_register_bits_without_a_name_still_count(self):
        wor_cycle_changed = self.PROVISIONED[:9] + bytes([0xC1]) + self.PROVISIONED[10:]
        found = sx126x.differences(wor_cycle_changed, sx126x.encode(0, 920))
        self.assertEqual(len(found), 1)
        self.assertIn("registers", found[0])

    def test_out_of_range_values_are_refused(self):
        with self.assertRaises(ValueError):
            sx126x.encode(0, 940)
        with self.assertRaises(ValueError):
            sx126x.encode(0, 920, air_speed=1000)


class ConfiguratorTests(unittest.TestCase):
    def make(self, replies):
        lines, port = FakeLines(), FakeSerial(replies)
        return sx126x.Configurator("/dev/null", lines, serial_port=port, settle=0), lines, port

    def test_write_retries_until_acknowledged_and_leaves_transparent_mode(self):
        conf, lines, port = self.make([b"", b"\xc1" + bytes(11)])
        self.assertTrue(conf.write(b"\xc0" + bytes(11)))
        self.assertEqual(len(port.written), 2)
        self.assertEqual(lines.calls[0], (0, 1))
        self.assertEqual(lines.calls[-1], (0, 0))

    def test_failed_write_and_short_read_report_failure(self):
        conf, lines, _ = self.make([b"", b"", b"", b"\xc1\x00"])
        self.assertFalse(conf.write(b"\xc0" + bytes(11)))
        self.assertIsNone(conf.read())
        self.assertEqual(lines.calls[-1], (0, 0))
        conf.close()
        self.assertTrue(lines.closed)


class FakeModule:
    """A module in configuration mode: answers reads with its registers,
    takes writes (unless ``accepts`` is False) and remembers them."""

    def __init__(self, registers=None, accepts=True, keeps=True):
        self.registers = registers
        self.accepts, self.keeps = accepts, keeps
        self.writes = []

    def read(self):
        return self.registers

    def write(self, register):
        self.writes.append(register)
        if self.accepts and self.keeps:
            self.registers = bytes([0xC1]) + register[1:10] + b"\x00\x00"
        return self.accepts


FACTORY = RegisterTests.FACTORY
PROVISIONED = RegisterTests.PROVISIONED


class RadioCommandTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = rs.radio_dir(self.tmp.name)
        self.sessions = 0

    def run_cli(self, module, *argv):
        def session(port, action):
            self.sessions += 1
            return action(module)
        with mock.patch.object(cli, "_session", side_effect=session), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            return cli.main(list(argv))

    def status(self):
        return rs.read_json(os.path.join(self.dir, "module.json"))


class ProvisionCommandTests(RadioCommandTestCase):
    def provision(self, module, *extra):
        return self.run_cli(module, "provision", "--home", self.tmp.name, *extra)

    def test_au915_provision_writes_a_factory_module_and_records_shared_settings(self):
        module = FakeModule(FACTORY)
        self.assertEqual(self.provision(module), 0)
        self.assertEqual(module.writes[0][8], 70)
        saved = rs.load_radio(self.dir)
        self.assertEqual((saved.band, saved.frequency_mhz, saved.air_speed), ("au915", 920, 2400))
        self.assertTrue(saved.provisioned_at)
        self.assertEqual(self.status()["result"], "restored")
        self.assertIn("frequency 868 (wanted 920)", self.status()["differences"])

    def test_a_module_that_already_has_the_settings_is_not_written(self):
        module = FakeModule(PROVISIONED)
        self.assertEqual(self.provision(module), 0)
        self.assertEqual(module.writes, [])
        first = rs.load_radio(self.dir).provisioned_at
        self.assertEqual(self.provision(module), 0)
        self.assertEqual(rs.load_radio(self.dir).provisioned_at, first)   # nothing changed
        self.assertEqual(self.status()["result"], "ok")

    def test_the_whole_read_back_must_match_not_only_the_frequency(self):
        # Regression (2026-10-22): only the frequency was compared, so a module
        # that kept sending transparently passed.
        module = FakeModule(FACTORY, keeps=False)
        module.registers = FACTORY[:8] + bytes([70]) + FACTORY[9:]     # 920 MHz, transparent
        self.assertEqual(self.provision(module), 1)
        self.assertIsNone(rs.load_radio(self.dir))
        self.assertEqual(self.status()["result"], "failed")

    def test_frequency_outside_the_band_or_no_reply_records_nothing(self):
        self.assertEqual(self.provision(FakeModule(FACTORY), "--frequency", "868"), 2)
        self.assertEqual(self.provision(FakeModule(None)), 1)
        self.assertEqual(self.provision(FakeModule(FACTORY, accepts=False)), 1)
        self.assertIsNone(rs.load_radio(self.dir))


class BootCheckTests(RadioCommandTestCase):
    """``ensure``: the module is compared with radio.json at every boot."""

    def record(self, **values):
        rs.save_radio(rs.RadioSettings(**dict(dict(frequency_mhz=920, band="au915",
                                                   provisioned_at="2026-10-05T23:38:03+1100"),
                                              **values)), self.dir)

    def ensure(self, module):
        return self.run_cli(module, "ensure", "--home", self.tmp.name)

    def test_a_module_back_on_factory_settings_gets_the_recorded_ones_again(self):
        # The old Orange Pi on 2026-10-22: radio.json 920 MHz, module 868 MHz.
        self.record()
        module = FakeModule(FACTORY)
        self.assertEqual(self.ensure(module), 0)
        self.assertEqual(sx126x.differences(module.registers, sx126x.encode(0, 920)), [])
        self.assertEqual(self.status()["result"], "restored")
        # A new date: RadioConnect learns the module's abilities again.
        self.assertNotEqual(rs.load_radio(self.dir).provisioned_at, "2026-10-05T23:38:03+1100")

    def test_a_matching_module_is_left_alone(self):
        self.record()
        module = FakeModule(PROVISIONED)
        self.assertEqual(self.ensure(module), 0)
        self.assertEqual(module.writes, [])
        self.assertEqual(rs.load_radio(self.dir).provisioned_at, "2026-10-05T23:38:03+1100")
        self.assertEqual(self.status()["result"], "ok")

    def test_settings_recorded_for_the_next_boot_are_written_and_dated(self):
        self.assertEqual(self.run_cli(None, "record", "--home", self.tmp.name), 0)
        self.assertEqual(self.sessions, 0)                     # record never opens the module
        self.assertEqual(rs.load_radio(self.dir).provisioned_at, "")
        self.assertEqual(self.ensure(FakeModule(FACTORY)), 0)
        self.assertTrue(rs.load_radio(self.dir).provisioned_at)

    def test_no_reply_or_a_refused_write_is_recorded_for_the_readiness_check(self):
        self.record()
        self.assertEqual(self.ensure(FakeModule(None)), 1)
        self.assertEqual(self.status()["result"], "no_reply")
        problems = radio_status(self.tmp.name)["problems"]
        self.assertTrue(any("did not answer" in p for p in problems), problems)
        self.assertEqual(self.ensure(FakeModule(FACTORY, accepts=False)), 1)
        self.assertEqual(self.status()["result"], "failed")
        self.assertEqual(self.ensure(FakeModule(PROVISIONED)), 0)
        problems = radio_status(self.tmp.name)["problems"]
        self.assertFalse(any("LoRa module" in p for p in problems), problems)

    def test_nothing_to_check_without_a_radio_and_unusable_settings_are_reported(self):
        self.assertEqual(self.ensure(FakeModule(FACTORY)), 0)
        self.assertEqual(self.sessions, 0)
        self.record(frequency_mhz=940)
        self.assertEqual(self.ensure(FakeModule(FACTORY)), 1)
        self.assertEqual(self.sessions, 0)
        self.assertEqual(self.status()["result"], "invalid")

    def test_check_compares_with_the_record_and_writes_nothing(self):
        self.record()
        module = FakeModule(FACTORY)
        self.assertEqual(self.run_cli(module, "check", "--home", self.tmp.name), 1)
        self.assertEqual(self.run_cli(FakeModule(PROVISIONED), "check", "--home", self.tmp.name), 0)
        self.assertEqual(module.writes, [])
        self.assertIsNone(self.status())


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_not_set_up_explains_the_next_step(self):
        report = radio_status(self.tmp.name)
        self.assertFalse(report["ready"])
        self.assertIn("setup-radio.sh", report["problems"][0])

    def test_ready_when_provisioned_port_usable_and_libraries_present(self):
        port = os.path.join(self.tmp.name, "ttyS0")
        open(port, "w").close()
        rs.save_radio(rs.RadioSettings(frequency_mhz=920, port=port, band="au915"),
                      rs.radio_dir(self.tmp.name))
        with mock.patch("ctypes.util.find_library", return_value="libcodec2.so.1.2"), \
                mock.patch("importlib.util.find_spec", return_value=object()):
            report = radio_status(self.tmp.name)
        self.assertEqual(report["problems"], [])
        self.assertTrue(report["ready"])
        with mock.patch("ctypes.util.find_library", return_value=None), \
                mock.patch("importlib.util.find_spec", return_value=None):
            problems = radio_status(self.tmp.name)["problems"]
        self.assertEqual(len(problems), 3)


if __name__ == "__main__":
    unittest.main()
