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


class ProvisionCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_provision(self, *extra, read_back=920):
        written = []

        class Conf:
            def write(self, register):
                written.append(register)
                return True

            def read(self):
                return bytes([0xC1, 0, 9, 0, 0, 0, 0x62, 0x20, read_back - 850, 0xC3, 0, 0])

        with mock.patch.object(cli, "_session", side_effect=lambda port, action: action(Conf())):
            code = cli.main(["provision", "--home", self.tmp.name, *extra])
        return code, written

    def test_au915_provision_records_shared_settings(self):
        code, written = self.run_provision()
        self.assertEqual(code, 0)
        self.assertEqual(written[0][8], 70)
        saved = rs.load_radio(rs.radio_dir(self.tmp.name))
        self.assertEqual((saved.band, saved.frequency_mhz, saved.air_speed), ("au915", 920, 2400))

    def test_frequency_outside_the_band_or_bad_readback_records_nothing(self):
        self.assertEqual(self.run_provision("--frequency", "868")[0], 2)
        self.assertEqual(self.run_provision(read_back=868)[0], 1)
        self.assertIsNone(rs.load_radio(rs.radio_dir(self.tmp.name)))


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
