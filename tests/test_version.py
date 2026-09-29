import unittest

import helpers  # noqa: F401  (sets sys.path)
from mfruitos.updater.version import Version, is_newer, parse_version, sort_versions


class VersionTests(unittest.TestCase):
    def test_numeric_not_string_comparison(self):
        self.assertTrue(Version.parse("10.0.0") > Version.parse("2.0.0"))
        self.assertTrue(is_newer("1.10.0", "1.9.9"))

    def test_v_prefix_and_short_form(self):
        self.assertEqual(Version.parse("v1.2"), Version.parse("1.2.0"))
        self.assertEqual(str(Version.parse("V2.0.1")), "2.0.1")

    def test_prerelease_ordering(self):
        ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
                   "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        parsed = [Version.parse(v) for v in ordered]
        self.assertEqual(parsed, sorted(parsed))

    def test_build_metadata_ignored_for_precedence(self):
        self.assertEqual(Version.parse("1.0.0+abc"), Version.parse("1.0.0+def"))

    def test_invalid(self):
        for text in ["", "latest", "1", "1.2.3.4", "01.2.3", "1.2.3-01", None, 3]:
            self.assertIsNone(parse_version(text), text)

    def test_is_newer_with_unknown_installed(self):
        self.assertTrue(is_newer("1.0.0", ""))
        self.assertFalse(is_newer("garbage", "1.0.0"))
        self.assertFalse(is_newer("1.0.0", "1.0.0"))

    def test_sort_versions_drops_invalid(self):
        self.assertEqual(sort_versions(["v1.0.0", "nightly", "v2.0.0", "v1.10.0"]),
                         ["v2.0.0", "v1.10.0", "v1.0.0"])


if __name__ == "__main__":
    unittest.main()
