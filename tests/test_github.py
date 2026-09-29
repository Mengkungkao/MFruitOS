import email.message
import io
import json
import os
import unittest
import urllib.error

from helpers import TempHomeTestCase
from mfruitos.updater.github import (GitHubClient, GitHubError, NotFoundError, OfflineError,
                                     RateLimitError, Release, Asset, check_url, checksum_asset,
                                     pick_asset)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def http_error(code, headers=None):
    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", msg, io.BytesIO(b""))


class ScriptedGitHub(GitHubClient):
    def __init__(self, cache_dir, script):
        super().__init__(cache_dir)
        self.script = script
        self.requests = []

    def _request(self, url, headers):
        check_url(url)
        self.requests.append((url, dict(headers)))
        result = self.script(url, headers)
        if isinstance(result, Exception):
            raise result
        return result


RELEASES = [
    {"tag_name": "v1.10.0", "name": "1.10", "body": "notes", "draft": False, "prerelease": False,
     "assets": [{"name": "weather-1.10.0.tar.gz", "browser_download_url": "https://github.com/a",
                 "size": 10, "digest": "sha256:" + "ab" * 32}]},
    {"tag_name": "v1.9.0", "draft": False, "prerelease": False, "assets": []},
    {"tag_name": "v2.0.0-beta.1", "draft": False, "prerelease": True, "assets": []},
    {"tag_name": "nightly", "draft": False, "prerelease": False, "assets": []},
    {"tag_name": "v3.0.0", "draft": True, "prerelease": False, "assets": []},
]


class GitHubTests(TempHomeTestCase):
    def client(self, script):
        return ScriptedGitHub(self.paths.cache_dir, script)

    def test_releases_semver_sorted_and_filtered(self):
        gh = self.client(lambda url, h: FakeResponse(json.dumps(RELEASES).encode()))
        versions = [r.version for r in gh.releases("o", "r")]
        self.assertEqual(versions, ["1.10.0", "1.9.0"])
        versions = [r.version for r in gh.releases("o", "r", include_prereleases=True)]
        self.assertEqual(versions, ["2.0.0-beta.1", "1.10.0", "1.9.0"])

    def test_falls_back_to_tags(self):
        def script(url, headers):
            if "/releases" in url:
                return FakeResponse(b"[]")
            return FakeResponse(json.dumps([{"name": "v0.2.0"}, {"name": "latest"}]).encode())
        releases = self.client(script).releases("o", "r")
        self.assertEqual([(r.version, r.source) for r in releases], [("0.2.0", "tag")])
        self.assertIn("/tarball/v0.2.0", releases[0].tarball_url)

    def test_etag_revalidation_uses_cache(self):
        calls = []

        def script(url, headers):
            calls.append(headers.get("If-None-Match"))
            if len(calls) == 1:
                return FakeResponse(b'[{"tag_name": "v1.0.0"}]', headers={"ETag": '"abc"'})
            return http_error(304)
        gh = self.client(script)
        self.assertEqual(gh.releases("o", "r")[0].version, "1.0.0")
        self.assertEqual(gh.releases("o", "r")[0].version, "1.0.0")
        self.assertEqual(calls, [None, '"abc"'])

    def test_max_age_reuses_cache_without_request(self):
        gh = self.client(lambda u, h: FakeResponse(b'[{"tag_name": "v1.0.0"}]'))
        gh.releases("o", "r")
        count = len(gh.requests)
        self.assertEqual(gh.releases("o", "r", max_age=300)[0].version, "1.0.0")
        self.assertEqual(len(gh.requests), count)

    def test_error_mapping(self):
        cases = [
            (http_error(404), NotFoundError),
            (http_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2000000000"}),
             RateLimitError),
            (urllib.error.URLError(OSError("Name or service not known")), OfflineError),
            (TimeoutError("timed out"), OfflineError),
            (http_error(500), GitHubError),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                with self.assertRaises(expected):
                    self.client(lambda u, h, e=error: e).releases("o", "r")

    def test_rate_limit_short_circuits(self):
        gh = self.client(lambda u, h: http_error(
            403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4000000000"}))
        with self.assertRaises(RateLimitError):
            gh.releases("o", "r")
        count = len(gh.requests)
        with self.assertRaises(RateLimitError):
            gh.releases("o", "other")
        self.assertEqual(len(gh.requests), count)  # no request sent while limited

    def test_malformed_json(self):
        with self.assertRaises(GitHubError):
            self.client(lambda u, h: FakeResponse(b"<html>")).releases("o", "r")

    def test_https_and_host_allowlist(self):
        with self.assertRaises(GitHubError):
            check_url("http://github.com/x")
        with self.assertRaises(GitHubError):
            check_url("https://evil.example.com/x")
        check_url("https://objects.githubusercontent.com/x")

    def test_token_only_sent_to_api(self):
        gh = self.client(lambda u, h: FakeResponse(b"[]"))
        gh.token = "secret"
        gh.get_json("https://api.github.com/repos/o/r/tags")
        self.assertEqual(gh.requests[-1][1].get("Authorization"), "Bearer secret")
        try:
            gh.fetch_small("https://objects.githubusercontent.com/f")
        except GitHubError:
            pass
        self.assertNotIn("Authorization", gh.requests[-1][1])

    def test_download_size_limit_and_incomplete(self):
        dest = os.path.join(self.tmp, "dl")
        gh = self.client(lambda u, h: FakeResponse(b"x" * 100))
        with self.assertRaises(GitHubError):
            gh.download("https://github.com/f", dest, max_bytes=10)
        self.assertFalse(os.path.exists(dest + ".part"))
        gh = self.client(lambda u, h: FakeResponse(b"x" * 10, headers={"Content-Length": "50"}))
        with self.assertRaises(GitHubError):
            gh.download("https://github.com/f", dest, max_bytes=100)
        gh = self.client(lambda u, h: FakeResponse(b"x" * 10, headers={"Content-Length": "10"}))
        size, digest = gh.download("https://github.com/f", dest, max_bytes=100)
        self.assertEqual(size, 10)
        self.assertEqual(len(digest), 64)

    def test_download_accept_header_works_for_tarball_endpoint(self):
        # Regression: api.github.com/.../tarball/<tag> returns HTTP 415 for
        # Accept: application/octet-stream.
        gh = self.client(lambda u, h: FakeResponse(b"x", headers={"Content-Length": "1"}))
        gh.download("https://api.github.com/repos/o/r/tarball/v1.0.0",
                    os.path.join(self.tmp, "t"), max_bytes=10)
        self.assertEqual(gh.requests[-1][1]["Accept"], "*/*")

    def test_asset_selection(self):
        rel = Release("1.0.0", "v1.0.0", assets=[
            Asset("source.zip", "https://github.com/s"),
            Asset("weather-1.0.0.tar.gz", "https://github.com/w"),
            Asset("SHA256SUMS", "https://github.com/sums"),
        ])
        self.assertEqual(pick_asset(rel, "weather").name, "weather-1.0.0.tar.gz")
        self.assertEqual(checksum_asset(rel, pick_asset(rel, "weather")).name, "SHA256SUMS")
        self.assertIsNone(pick_asset(Release("1.0.0", "v1.0.0"), "weather"))


if __name__ == "__main__":
    unittest.main()
