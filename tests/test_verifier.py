import io
import os
import tarfile
import unittest
import zipfile

from helpers import TempHomeTestCase
from mfruitos.updater.verifier import (VerificationError, expected_from_digest, parse_checksums,
                                       safe_extract, sha256_file, verify_sha256)


def add_file(tar, name, data=b"x", mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    tar.addfile(info, io.BytesIO(data))


class ExtractTests(TempHomeTestCase):
    def tar(self, build):
        path = os.path.join(self.tmp, "a.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            build(tar)
        return path

    def dest(self):
        return os.path.join(self.tmp, "out")

    def test_strips_single_top_level_directory(self):
        path = self.tar(lambda t: (add_file(t, "owner-repo-abc/manifest.json", b"{}"),
                                   add_file(t, "owner-repo-abc/run.sh", b"#!/bin/sh", 0o755)))
        root = safe_extract(path, self.dest())
        self.assertTrue(root.endswith("owner-repo-abc"))
        self.assertTrue(os.access(os.path.join(root, "run.sh"), os.X_OK))

    def test_rejects_traversal_and_absolute_paths(self):
        for bad in ("../evil", "a/../../evil", "/etc/evil"):
            with self.subTest(bad=bad):
                path = self.tar(lambda t: add_file(t, bad))
                with self.assertRaises(VerificationError):
                    safe_extract(path, self.dest() + bad.replace("/", "_"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))

    def test_rejects_escaping_symlinks_allows_internal(self):
        def escaping(t):
            info = tarfile.TarInfo("pkg/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            t.addfile(info)
        with self.assertRaises(VerificationError):
            safe_extract(self.tar(escaping), self.dest())

        def absolute(t):
            info = tarfile.TarInfo("pkg/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            t.addfile(info)
        with self.assertRaises(VerificationError):
            safe_extract(self.tar(absolute), self.dest() + "2")

        def internal(t):
            add_file(t, "pkg/real.txt")
            info = tarfile.TarInfo("pkg/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "real.txt"
            t.addfile(info)
        root = safe_extract(self.tar(internal), self.dest() + "3")
        self.assertTrue(os.path.islink(os.path.join(root, "link")))

    def test_rejects_device_files(self):
        def device(t):
            info = tarfile.TarInfo("pkg/dev")
            info.type = tarfile.CHRTYPE
            t.addfile(info)
        with self.assertRaises(VerificationError):
            safe_extract(self.tar(device), self.dest())

    def test_strips_setuid_and_world_write(self):
        root = safe_extract(self.tar(lambda t: add_file(t, "pkg/x", b"1", 0o4777)), self.dest())
        mode = os.stat(os.path.join(root, "x")).st_mode & 0o7777
        self.assertEqual(mode, 0o755)

    def test_zip_slip_rejected(self):
        path = os.path.join(self.tmp, "a.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(VerificationError):
            safe_extract(path, self.dest())

    def test_garbage_is_rejected(self):
        path = os.path.join(self.tmp, "junk.tar.gz")
        with open(path, "wb") as fp:
            fp.write(b"not an archive")
        with self.assertRaises(VerificationError):
            safe_extract(path, self.dest())


class ChecksumTests(TempHomeTestCase):
    def test_checksums(self):
        path = os.path.join(self.tmp, "f")
        with open(path, "wb") as fp:
            fp.write(b"hello")
        digest = sha256_file(path)
        verify_sha256(digest, digest.upper())
        with self.assertRaises(VerificationError):
            verify_sha256(digest, "0" * 64)
        table = parse_checksums(f"{digest}  pkg.tar.gz\n{'a' * 64} *other.zip\n")
        self.assertEqual(table["pkg.tar.gz"], digest)
        self.assertEqual(table["other.zip"], "a" * 64)
        self.assertEqual(expected_from_digest("sha256:" + digest), digest)
        self.assertIsNone(expected_from_digest("md5:abc"))


if __name__ == "__main__":
    unittest.main()
