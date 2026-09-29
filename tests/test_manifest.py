import os
import unittest

from helpers import TempHomeTestCase, make_package
from mfruitos.apps.manifest import (ManifestError, is_safe_relative_path, load_manifest,
                                    normalize_repository, validate_manifest)

BASE = {"id": "weather", "name": "Weather", "version": "1.0.0", "entrypoint": "run.sh"}


def m(**changes):
    data = dict(BASE)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


class ManifestValidationTests(unittest.TestCase):
    def test_valid_minimal(self):
        manifest = validate_manifest(m())
        self.assertEqual(manifest.id, "weather")
        self.assertEqual(manifest.exit_gesture, "quad_click")

    def test_missing_required_fields(self):
        for field in ("id", "name", "version", "entrypoint"):
            with self.assertRaises(ManifestError, msg=field):
                validate_manifest(m(**{field: None}))

    def test_invalid_ids(self):
        for bad in ["Weather", "../x", "a b", "", "-x", "x" * 49, "mfruit-os", "whisplay-wifi"]:
            with self.assertRaises(ManifestError, msg=bad):
                validate_manifest(m(id=bad))

    def test_invalid_version(self):
        with self.assertRaises(ManifestError):
            validate_manifest(m(version="latest"))

    def test_path_traversal_rejected(self):
        for bad in ["../run.sh", "/bin/sh", "app/../../x", "run.sh; rm -rf /", "~/x", "a\\b"]:
            with self.assertRaises(ManifestError, msg=bad):
                validate_manifest(m(entrypoint=bad))
            with self.assertRaises(ManifestError, msg=bad):
                validate_manifest(m(icon=bad))

    def test_min_os_version(self):
        validate_manifest(m(min_os_version="1.0.0"), os_version="1.0.0")
        with self.assertRaises(ManifestError):
            validate_manifest(m(min_os_version="2.0.0"), os_version="1.0.0")

    def test_repository_normalised(self):
        manifest = validate_manifest(m(repository="github.com/Example/whisplay-weather.git"))
        self.assertEqual(manifest.repository, "https://github.com/Example/whisplay-weather")
        with self.assertRaises(ManifestError):
            validate_manifest(m(repository="http://github.com/a/b"))
        with self.assertRaises(ManifestError):
            validate_manifest(m(repository="https://gitlab.com/a/b"))

    def test_env_validation(self):
        validate_manifest(m(env={"FOO": "1"}))
        with self.assertRaises(ManifestError):
            validate_manifest(m(env={"BAD KEY": "1"}))
        with self.assertRaises(ManifestError):
            validate_manifest(m(env={"FOO": 1}))

    def test_exit_gesture_and_priority(self):
        with self.assertRaises(ManifestError):
            validate_manifest(m(exit_gesture="triple"))
        with self.assertRaises(ManifestError):
            validate_manifest(m(priority="high"))

    def test_disable_esc_exit_key(self):
        self.assertTrue(validate_manifest(m(disable_esc_exit_key=True)).disable_esc_exit_key)
        with self.assertRaises(ManifestError):
            validate_manifest(m(disable_esc_exit_key="yes"))

    def test_system_type_reserved_for_os(self):
        validate_manifest(m(id="mfruit-os", type="system"))
        with self.assertRaises(ManifestError):
            validate_manifest(m(type="system"))

    def test_safe_relative_path(self):
        self.assertTrue(is_safe_relative_path("app/main.py"))
        self.assertFalse(is_safe_relative_path("app//main.py"))
        self.assertFalse(is_safe_relative_path("./main.py"))

    def test_normalize_shorthand(self):
        self.assertEqual(normalize_repository("user/repo"), "https://github.com/user/repo")


class ManifestFileTests(TempHomeTestCase):
    def test_load_checks_entrypoint_exists(self):
        pkg = make_package(os.path.join(self.tmp, "pkg"))
        load_manifest(pkg)
        os.remove(os.path.join(pkg, "run.sh"))
        with self.assertRaises(ManifestError):
            load_manifest(pkg)

    def test_symlinked_entrypoint_escaping_package_rejected(self):
        pkg = make_package(os.path.join(self.tmp, "pkg"))
        os.remove(os.path.join(pkg, "run.sh"))
        os.symlink("/bin/sh", os.path.join(pkg, "run.sh"))
        with self.assertRaises(ManifestError):
            load_manifest(pkg)

    def test_missing_icon_is_not_fatal(self):
        pkg = make_package(os.path.join(self.tmp, "pkg"), extra_manifest={"icon": "assets/icon.png"})
        self.assertEqual(load_manifest(pkg).icon, "")

    def test_invalid_json(self):
        pkg = os.path.join(self.tmp, "pkg")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "manifest.json"), "w") as fp:
            fp.write("{nope")
        with self.assertRaises(ManifestError):
            load_manifest(pkg)


if __name__ == "__main__":
    unittest.main()
