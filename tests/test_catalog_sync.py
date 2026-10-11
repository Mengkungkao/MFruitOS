"""scripts/catalog-sync.py: Fruit Store pins follow the apps' releases, safely.

A pin moves only to a release whose package was downloaded, matched its
published SHA-256 and holds the right manifest; anything else keeps the pin.
GitHub is faked; no network.
"""
import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
import urllib.error

from helpers import ROOT

spec = importlib.util.spec_from_file_location("catalog_sync", os.path.join(ROOT, "scripts", "catalog-sync.py"))
sync_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_mod)

API = sync_mod.API
OWNER = "Mengkungkao"
COMMIT = "c" * 40


def package(app_id="demo", version="1.1.0", **manifest) -> bytes:
    data = json.dumps(dict({"id": app_id, "version": version, "name": "Demo",
                            "entrypoint": "run.sh"}, **manifest)).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(f"{app_id}/manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def entry(app_id="demo", version="1.0.0", owner=OWNER, native=True) -> dict:
    item = {"id": app_id, "name": "Demo", "description": "A demo",
            "repository": f"https://github.com/{owner}/{app_id}", "ref": "a" * 40,
            "url": f"https://github.com/{owner}/{app_id}/releases/download/v{version}/{app_id}-{version}.tar.gz",
            "sha256": "b" * 64, "native": native, "version": version}
    if not native:
        item.update({"entry": "app/main.py", "dependencies": []})
        del item["version"]
    return item


class FakeGitHub:
    """Serves one release per repository; counts every request."""

    def __init__(self):
        self.files = {}
        self.calls = []

    def release(self, app_id="demo", version="1.1.0", body=None, digest=True, sums=None,
                owner=OWNER):
        body = package(app_id, version) if body is None else body
        name = f"{app_id}-{version}-linux-arm64.tar.gz"
        url = f"https://github.com/{owner}/{app_id}/releases/download/v{version}/{name}"
        asset = {"name": name, "browser_download_url": url}
        if digest:
            asset["digest"] = "sha256:" + hashlib.sha256(body).hexdigest()
        assets = [asset]
        if sums is not None:
            sums_url = url.rsplit("/", 1)[0] + "/SHA256SUMS"
            assets.append({"name": "SHA256SUMS", "browser_download_url": sums_url})
            self.files[sums_url] = f"{sums}  {name}\n".encode()
        self.files[url] = body
        self.files[f"{API}/repos/{owner}/{app_id}/releases/latest"] = json.dumps(
            {"tag_name": f"v{version}", "assets": assets}).encode()
        self.files[f"{API}/repos/{owner}/{app_id}/commits/v{version}"] = json.dumps(
            {"sha": COMMIT}).encode()
        return url

    def get(self, url, limit):
        self.calls.append(url)
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return self.files[url]


def run(items, gh, os_version="1.5.0"):
    lines = []
    result, changes, problems = sync_mod.sync(items, OWNER, gh.get, os_version, say=lines.append)
    return result, changes, problems


class CatalogSyncTests(unittest.TestCase):
    def test_a_newer_release_moves_the_pin(self):
        gh = FakeGitHub()
        url = gh.release(version="1.1.0")
        result, changes, problems = run([entry(version="1.0.0")], gh)
        self.assertEqual(problems, [])
        self.assertEqual(changes, ["demo 1.0.0 -> 1.1.0"])
        moved = result[0]
        self.assertEqual((moved["version"], moved["url"], moved["ref"]), ("1.1.0", url, COMMIT))
        self.assertEqual(moved["sha256"], hashlib.sha256(gh.files[url]).hexdigest())
        self.assertEqual(moved["description"], "A demo")          # nothing else touched

    def test_checksum_from_a_sums_file_when_github_records_none(self):
        gh = FakeGitHub()
        body = package(version="1.1.0")
        gh.release(version="1.1.0", body=body, digest=False, sums=hashlib.sha256(body).hexdigest())
        result, changes, problems = run([entry()], gh)
        self.assertEqual((changes, problems), (["demo 1.0.0 -> 1.1.0"], []))

    def test_a_package_that_does_not_match_its_checksum_keeps_the_pin(self):
        gh = FakeGitHub()
        gh.release(version="1.1.0", digest=False, sums="0" * 64)
        result, changes, problems = run([entry()], gh)
        self.assertEqual(changes, [])
        self.assertIn("does not match", problems[0])
        self.assertEqual(result[0]["version"], "1.0.0")

    def test_no_checksum_at_all_keeps_the_pin(self):
        gh = FakeGitHub()
        gh.release(version="1.1.0", digest=False)
        _, changes, problems = run([entry()], gh)
        self.assertEqual(changes, [])
        self.assertIn("no checksum", problems[0])

    def test_a_package_with_the_wrong_manifest_keeps_the_pin(self):
        for body in (package("other", "1.1.0"), package("demo", "1.0.9")):
            gh = FakeGitHub()
            gh.release(version="1.1.0", body=body)
            _, changes, problems = run([entry()], gh)
            self.assertEqual(changes, [])
            self.assertIn("holds", problems[0])

    def test_a_release_needing_a_newer_os_keeps_the_pin(self):
        gh = FakeGitHub()
        gh.release(version="1.1.0", body=package(version="1.1.0", min_os_version="9.0.0"))
        _, changes, problems = run([entry()], gh)
        self.assertEqual(changes, [])
        self.assertIn("needs mFruit OS 9.0.0", problems[0])

    def test_no_newer_release_downloads_nothing(self):
        gh = FakeGitHub()
        url = gh.release(version="1.0.0")
        result, changes, problems = run([entry(version="1.0.0")], gh)
        self.assertEqual((changes, problems), ([], []))
        self.assertNotIn(url, gh.calls)

    def test_no_release_or_no_package_asset(self):
        gh = FakeGitHub()
        _, changes, problems = run([entry()], gh)               # 404: nothing published
        self.assertEqual((changes, problems), ([], []))
        gh.files[f"{API}/repos/{OWNER}/demo/releases/latest"] = json.dumps(
            {"tag_name": "v1.1.0", "assets": []}).encode()
        _, changes, problems = run([entry()], gh)
        self.assertEqual(changes, [])
        self.assertIn("no package asset", problems[0])

    def test_other_owners_and_adopted_entries_are_never_looked_up(self):
        gh = FakeGitHub()
        gh.release(app_id="demo", version="2.0.0", owner="someone")
        items = [entry(owner="someone"), entry(app_id="adopted", native=False)]
        result, changes, problems = run(items, gh)
        self.assertEqual((result, changes, problems, gh.calls), (items, [], [], []))

    def test_main_rewrites_only_the_moved_fields(self):
        gh = FakeGitHub()
        gh.release(version="1.1.0")
        tmp = tempfile.mkdtemp(prefix="mfsync-")
        path = os.path.join(tmp, "catalog.json")
        items = [entry(), entry(app_id="other", owner="someone")]
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(json.dumps(items, indent=2, ensure_ascii=False) + "\n")
        original = sync_mod.http_get
        sync_mod.http_get = lambda url, token="", limit=0: gh.get(url, limit)
        try:
            self.assertEqual(sync_mod.main(["--catalog", path, "--owner", OWNER, "--dry-run"]), 0)
            with open(path, encoding="utf-8") as fp:
                self.assertEqual(json.load(fp), items)         # dry run writes nothing
            self.assertEqual(sync_mod.main(["--catalog", path, "--owner", OWNER]), 0)
        finally:
            sync_mod.http_get = original
        with open(path, encoding="utf-8") as fp:
            written = json.load(fp)
        self.assertEqual(written[0]["version"], "1.1.0")
        self.assertEqual(written[1], items[1])


if __name__ == "__main__":
    unittest.main()
