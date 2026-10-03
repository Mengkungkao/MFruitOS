"""The shared radio store (SDK ``radio``): settings, identity, keys, contacts."""

import json
import os
import stat
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401
from mfruitos.sdk.radio import settings as rs
from mfruitos.sdk.radio.contacts import Contacts

try:
    from mfruitos.sdk.radio import crypto
    from mfruitos.sdk.radio.keyring import Keyring, adopt_legacy
except ImportError:          # the cryptography package is only needed by radio apps
    crypto = None


class RadioStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "shared", "radio")


class SettingsTests(RadioStoreTestCase):
    def test_directory_follows_the_mfruit_home(self):
        with mock.patch.dict(os.environ, {"MFRUIT_HOME": "/x/os"}):
            self.assertEqual(rs.radio_dir(), "/x/os/shared/radio")
        self.assertEqual(rs.radio_dir("/y"), "/y/shared/radio")

    def test_radio_settings_absent_until_setup_then_round_trip_private(self):
        self.assertIsNone(rs.load_radio(self.dir))
        rs.save_radio(rs.RadioSettings(frequency_mhz=920, band="au915"), self.dir)
        loaded = rs.load_radio(self.dir)
        self.assertEqual((loaded.frequency_mhz, loaded.band, loaded.air_speed), (920, "au915", 2400))
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "radio.json")).st_mode), 0o600)

    def test_malformed_radio_settings_read_as_not_set_up(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "radio.json"), "w") as fp:
            fp.write('{"frequency_mhz": "fast"}')
        self.assertIsNone(rs.load_radio(self.dir))

    def test_device_id_is_assigned_once_and_kept(self):
        first = rs.load_device(self.dir, avoid={5})
        self.assertTrue(1 <= first.address <= rs.MAX_ADDRESS)
        self.assertEqual(rs.load_device(self.dir), first)
        self.assertEqual(rs.load_device(self.dir, legacy_address=42), first,
                         "a legacy ID never replaces an existing identity")

    def test_legacy_identity_is_handed_over(self):
        device = rs.load_device(self.dir, legacy_address=4242, legacy_name="Base")
        self.assertEqual((device.address, device.name), (4242, "Base"))
        with self.assertRaises(ValueError):
            rs.save_device(rs.Device(0xFFFF, "x"), self.dir)


class ContactsTests(RadioStoreTestCase):
    def test_names_are_shared_and_validated(self):
        Contacts(self.dir).set(17, "  Bushwalk partner with a long name  ")
        other_app = Contacts(self.dir)
        self.assertEqual(other_app.name_for(17), "Bushwalk partner wit")
        self.assertEqual(other_app.name_for(99), "Radio 99")
        other_app.remove(17)
        self.assertEqual(Contacts(self.dir).all(), {})
        with self.assertRaises(ValueError):
            Contacts(self.dir).set(0xFFFF, "everyone")


@unittest.skipIf(crypto is None, "cryptography is not installed")
class KeyringTests(RadioStoreTestCase):
    def test_two_radios_pair_and_derive_the_same_secrets(self):
        a = Keyring(os.path.join(self.tmp.name, "a"))
        b = Keyring(os.path.join(self.tmp.name, "b"))
        body = a.pair_body(b.public, src=1, dst=2, name="Alpha")
        public, broadcast, name = b.open_pair_body(body, src=1, dst=2)
        self.assertEqual((public, broadcast, name), (a.public, a.broadcast_key, "Alpha"))
        self.assertIsNone(b.open_pair_body(body, src=1, dst=3), "bound to sender and receiver")
        b.add_peer(1, public, broadcast)
        a.add_peer(2, b.public, b.broadcast_key)
        self.assertEqual(a.pairwise(2), b.pairwise(1))
        self.assertEqual(a.code_with(b.public), b.code_with(a.public))

    def test_a_pairing_made_in_one_app_is_seen_by_the_other(self):
        walkie, messenger = Keyring(self.dir), Keyring(self.dir)
        self.assertEqual(walkie.public, messenger.public, "one identity per radio")
        walkie.add_peer(7, os.urandom(32), os.urandom(32))
        self.assertTrue(messenger.is_paired(7))
        messenger.add_peer(8, os.urandom(32), os.urandom(32))
        walkie.add_peer(9, os.urandom(32), os.urandom(32))   # must not drop 8
        self.assertEqual(Keyring(self.dir).paired, [7, 8, 9])
        self.assertEqual(stat.S_IMODE(os.stat(walkie.path).st_mode), 0o600)

    def test_legacy_keys_are_adopted_once_and_the_original_is_kept(self):
        legacy_dir = os.path.join(self.tmp.name, "walkie-data")
        old = Keyring(legacy_dir)
        old.add_peer(3, os.urandom(32), os.urandom(32))
        shared = Keyring(self.dir, legacy_path=old.path)
        self.assertEqual((shared.public, shared.paired), (old.public, [3]))
        self.assertTrue(os.path.isfile(old.path))
        other = Keyring(os.path.join(self.tmp.name, "other"))
        self.assertFalse(adopt_legacy(other.path, self.dir), "never overwrites shared keys")
        self.assertEqual(Keyring(self.dir).public, old.public)

    def test_unreadable_keys_are_replaced_not_crashed_on(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "keys.json"), "w") as fp:
            json.dump({"private": "zz"}, fp)
        self.assertEqual(len(Keyring(self.dir).public), 32)

    def test_generic_seal_authenticates_header_and_context(self):
        key = crypto.new_key()
        sealed = crypto.seal_with(key, b"\x00\x01\x02\x03", b"header", b"hello")
        self.assertEqual(crypto.open_with(key, b"\x00\x01\x02\x03", b"header", sealed), b"hello")
        self.assertIsNone(crypto.open_with(key, b"\x00\x01\x02\x03", b"HEADER", sealed))
        self.assertIsNone(crypto.open_with(key, b"\x00\x01\x02\x04", b"header", sealed))
        self.assertIsNone(crypto.open_with(crypto.new_key(), b"\x00\x01\x02\x03", b"header", sealed))


class WalkieMigrationTests(RadioStoreTestCase):
    def setUp(self):
        super().setUp()
        self.walkie = os.path.join(self.tmp.name, "walkie")
        os.makedirs(self.walkie)
        patcher = mock.patch.dict(os.environ, {"WALKIE_DATA_DIR": self.walkie})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_walkie(self, **settings):
        with open(os.path.join(self.walkie, "settings.json"), "w") as fp:
            json.dump(settings, fp)

    def test_walkietalkie_identity_and_keys_are_adopted_before_any_app_picks_an_id(self):
        # Pairing is keyed by Device ID: an app that invented its own ID first
        # would be unrecognisable to every radio already paired with WalkieTalkie.
        from mfruitos.sdk.radio import legacy
        self.write_walkie(radio={"address": 4321}, identity={"callsign": "Base"})
        with open(os.path.join(self.walkie, "keys.json"), "w") as fp:
            json.dump({"private": "00" * 32, "broadcast": "11" * 32, "peers": {}}, fp)
        self.assertEqual(legacy.adopt_walkietalkie(self.dir), {"device": 4321, "keys": True})
        self.assertEqual(rs.load_device(self.dir, legacy_address=999), rs.Device(4321, "Base"))
        self.assertTrue(os.path.isfile(os.path.join(self.walkie, "keys.json")), "original kept")
        self.assertEqual(legacy.adopt_walkietalkie(self.dir), {}, "adopted once only")

    def test_nothing_to_adopt_leaves_the_store_untouched(self):
        from mfruitos.sdk.radio import legacy
        self.assertEqual(legacy.adopt_walkietalkie(self.dir), {})
        self.write_walkie(radio={"address": "x"})
        self.assertEqual(legacy.walkie_identity(), (None, ""))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "device.json")))

    def test_an_existing_shared_identity_is_never_replaced(self):
        from mfruitos.sdk.radio import legacy
        rs.save_device(rs.Device(77, "Mine"), self.dir)
        self.write_walkie(radio={"address": 4321})
        self.assertEqual(legacy.adopt_walkietalkie(self.dir), {})
        self.assertEqual(rs.load_device(self.dir).address, 77)


if __name__ == "__main__":
    unittest.main()
