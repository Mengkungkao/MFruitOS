"""GitHub as the software distribution source.

* HTTPS only; redirects are followed only to GitHub-owned hosts.
* JSON responses are cached with their ETag, so unchanged data is not
  downloaded again. Note: for unauthenticated requests a 304 still counts
  against GitHub's rate limit (60/hour, verified 2026-09), so callers that may
  repeat a lookup pass ``max_age`` to reuse a fresh cache without a request.
* Every failure maps to a typed error so the UI can say *why* (offline,
  rate-limited, not found) instead of showing a traceback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from mfruitos import __version__
from mfruitos.updater.version import parse_version

log = logging.getLogger("mfruitos.updater.github")

API = "https://api.github.com"
ALLOWED_HOSTS = {
    "github.com", "api.github.com", "codeload.github.com", "raw.githubusercontent.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip", ".tar")
CHECKSUM_NAMES = ("sha256sums", "sha256sums.txt", "checksums.txt", "checksums.sha256")


class GitHubError(Exception):
    pass


class OfflineError(GitHubError):
    pass


class NotFoundError(GitHubError):
    pass


class RateLimitError(GitHubError):
    def __init__(self, reset_at: float):
        self.reset_at = reset_at
        when = time.strftime("%H:%M", time.localtime(reset_at)) if reset_at else "later"
        super().__init__(f"GitHub rate limit reached; try again after {when}")


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    digest: str = ""          # "sha256:<hex>" when GitHub provides it


@dataclass
class Release:
    version: str
    tag: str
    name: str = ""
    body: str = ""
    published_at: str = ""
    prerelease: bool = False
    tarball_url: str = ""
    assets: list[Asset] = field(default_factory=list)
    source: str = "release"   # release | tag


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise GitHubError(f"refusing non-HTTPS URL: {url}")
    if parts.hostname not in ALLOWED_HOSTS:
        raise GitHubError(f"refusing URL outside GitHub: {parts.hostname}")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != "api.github.com":
            # Never forward the API token to download hosts.
            new.remove_header("Authorization")
        return new


class GitHubClient:
    def __init__(self, cache_dir: str, token: str = "", timeout: float = 12.0):
        self.cache_dir = os.path.join(cache_dir, "github")
        self.token = token
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_SafeRedirect())
        self.rate_remaining: int | None = None
        self.rate_reset: float = 0.0

    # ----------------------------------------------------------- transport
    def _headers(self, url: str, accept: str = "application/vnd.github+json") -> dict:
        headers = {"User-Agent": f"MFruitOS/{__version__}", "Accept": accept}
        if self.token and urllib.parse.urlsplit(url).hostname == "api.github.com":
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, url: str, headers: dict):
        """Open ``url``; returns a response object. Overridden in tests."""
        request = urllib.request.Request(check_url(url), headers=headers)
        return self._opener.open(request, timeout=self.timeout)

    def _open(self, url: str, headers: dict):
        if self.rate_remaining == 0 and time.time() < self.rate_reset:
            raise RateLimitError(self.rate_reset)
        try:
            response = self._request(url, headers)
        except urllib.error.HTTPError as exc:
            self._note_rate(exc.headers)
            if exc.code == 304:
                return exc
            if exc.code == 404:
                raise NotFoundError(f"not found: {_short(url)}") from exc
            if exc.code in (403, 429) and (exc.headers or {}).get("X-RateLimit-Remaining") == "0":
                raise RateLimitError(self.rate_reset) from exc
            if exc.code == 401:
                raise GitHubError("GitHub rejected the access token") from exc
            raise GitHubError(f"GitHub returned HTTP {exc.code} for {_short(url)}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, GitHubError):
                raise reason
            raise OfflineError(f"cannot reach GitHub ({reason})") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise OfflineError("GitHub request timed out") from exc
        except OSError as exc:
            raise OfflineError(f"network error: {exc}") from exc
        self._note_rate(getattr(response, "headers", None))
        return response

    def _note_rate(self, headers) -> None:
        if not headers:
            return
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        try:
            if remaining is not None:
                self.rate_remaining = int(remaining)
            if reset is not None:
                self.rate_reset = float(reset)
        except ValueError:
            pass

    # ---------------------------------------------------------- JSON + cache
    def _cache_path(self, url: str) -> str:
        return os.path.join(self.cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".json")

    def _read_cache(self, url: str) -> dict | None:
        try:
            with open(self._cache_path(url), "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (OSError, ValueError):
            return None

    def _write_cache(self, url: str, etag: str, data) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = self._cache_path(url) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump({"url": url, "etag": etag, "fetched_at": time.time(), "data": data}, fp)
            os.replace(tmp, self._cache_path(url))
        except OSError as exc:
            log.warning("Cannot write GitHub cache: %s", exc)

    def get_json(self, url: str, max_age: float = 0.0):
        """GET JSON with ETag revalidation; fresh cache (``max_age``) skips the network."""
        cached = self._read_cache(url)
        if cached and max_age and time.time() - cached.get("fetched_at", 0) < max_age:
            return cached["data"]
        headers = self._headers(url)
        if cached and cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        response = self._open(url, headers)
        status = getattr(response, "status", None) or getattr(response, "code", 200)
        if status == 304 and cached:
            self._write_cache(url, cached.get("etag", ""), cached["data"])
            return cached["data"]
        try:
            body = response.read(8 * 1024 * 1024)
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubError("GitHub returned malformed JSON") from exc
        finally:
            _close(response)
        etag = (getattr(response, "headers", None) or {}).get("ETag", "")
        self._write_cache(url, etag, data)
        return data

    def cached_json(self, url: str):
        cached = self._read_cache(url)
        return cached["data"] if cached else None

    # --------------------------------------------------------------- API
    def repo(self, owner: str, repo: str) -> dict:
        data = self.get_json(f"{API}/repos/{owner}/{repo}", max_age=3600)
        if not isinstance(data, dict):
            raise GitHubError("unexpected repository response")
        return data

    def releases(self, owner: str, repo: str, include_prereleases: bool = False,
                 max_age: float = 0.0) -> list[Release]:
        """Semver releases, newest first; falls back to semver tags."""
        data = self.get_json(f"{API}/repos/{owner}/{repo}/releases?per_page=30", max_age=max_age)
        if not isinstance(data, list):
            raise GitHubError("unexpected releases response")
        result: list[Release] = []
        for item in data:
            if not isinstance(item, dict) or item.get("draft"):
                continue
            tag = str(item.get("tag_name") or "")
            version = parse_version(tag)
            is_pre = version is not None and (version.is_prerelease or bool(item.get("prerelease")))
            if version is None or (is_pre and not include_prereleases):
                continue
            assets = [Asset(str(a.get("name", "")), str(a.get("browser_download_url", "")),
                            int(a.get("size") or 0), str(a.get("digest") or ""))
                      for a in item.get("assets") or [] if isinstance(a, dict)]
            result.append(Release(
                version=str(version), tag=tag, name=str(item.get("name") or tag),
                body=str(item.get("body") or ""), published_at=str(item.get("published_at") or ""),
                prerelease=bool(item.get("prerelease")),
                tarball_url=f"{API}/repos/{owner}/{repo}/tarball/{urllib.parse.quote(tag)}",
                assets=assets))
        if not result:
            result = self.tags(owner, repo, include_prereleases, max_age)
        result.sort(key=lambda r: parse_version(r.version), reverse=True)
        return result

    def tags(self, owner: str, repo: str, include_prereleases: bool = False,
             max_age: float = 0.0) -> list[Release]:
        data = self.get_json(f"{API}/repos/{owner}/{repo}/tags?per_page=50", max_age=max_age)
        if not isinstance(data, list):
            raise GitHubError("unexpected tags response")
        result = []
        for item in data:
            tag = str((item or {}).get("name") or "")
            version = parse_version(tag)
            if version is None or (version.is_prerelease and not include_prereleases):
                continue
            result.append(Release(version=str(version), tag=tag, name=tag, source="tag",
                                  tarball_url=f"{API}/repos/{owner}/{repo}/tarball/{urllib.parse.quote(tag)}"))
        return result

    def raw_file(self, owner: str, repo: str, ref: str, path: str, max_bytes: int = 65536) -> bytes:
        url = (f"https://raw.githubusercontent.com/{owner}/{repo}/"
               f"{urllib.parse.quote(ref)}/{urllib.parse.quote(path)}")
        response = self._open(url, self._headers(url, accept="*/*"))
        try:
            data = response.read(max_bytes + 1)
        finally:
            _close(response)
        if len(data) > max_bytes:
            raise GitHubError(f"{path} is too large")
        return data

    def search_topic(self, topic: str) -> list[dict]:
        query = urllib.parse.quote(f"topic:{topic}")
        data = self.get_json(f"{API}/search/repositories?q={query}&sort=stars&per_page=30",
                             max_age=3600)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [{"full_name": i.get("full_name", ""), "description": i.get("description") or "",
                 "stars": i.get("stargazers_count", 0), "url": i.get("html_url", "")}
                for i in items if isinstance(i, dict) and i.get("full_name")]

    def rate_limit(self) -> tuple[int, float]:
        url = f"{API}/rate_limit"
        response = self._open(url, self._headers(url))
        try:
            data = json.loads(response.read(65536).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubError("malformed rate limit response") from exc
        finally:
            _close(response)
        core = (data.get("resources") or {}).get("core") or data.get("rate") or {}
        return int(core.get("remaining", 0)), float(core.get("reset", 0))

    def fetch_small(self, url: str, max_bytes: int = 65536) -> bytes:
        """GET a small file (e.g. a checksum list) into memory."""
        response = self._open(url, self._headers(url, accept="application/octet-stream"))
        try:
            data = response.read(max_bytes + 1)
        finally:
            _close(response)
        if len(data) > max_bytes:
            raise GitHubError("file is larger than expected")
        return data

    # ------------------------------------------------------------ download
    def download(self, url: str, dest: str, max_bytes: int, progress=None) -> tuple[int, str]:
        """Stream ``url`` to ``dest``; returns (size, sha256). Partial files are removed."""
        # "*/*": the API tarball endpoint answers 415 to application/octet-stream
        # (found against live GitHub); asset download URLs accept anything.
        headers = self._headers(url, accept="*/*")
        response = self._open(url, headers)
        part = dest + ".part"
        digest = hashlib.sha256()
        size = 0
        try:
            length = int((response.headers or {}).get("Content-Length") or 0)
            if length and length > max_bytes:
                raise GitHubError(f"download is {length // 1048576} MB, over the limit")
            with open(part, "wb") as out:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise GitHubError("download exceeds the size limit")
                    digest.update(chunk)
                    out.write(chunk)
                    if progress:
                        progress(size, length)
            if length and size != length:
                raise GitHubError(f"incomplete download ({size} of {length} bytes)")
            os.replace(part, dest)
        except (OSError, socket.timeout) as exc:
            _remove(part)
            raise OfflineError(f"download interrupted: {exc}") from exc
        except BaseException:
            _remove(part)
            raise
        finally:
            _close(response)
        return size, digest.hexdigest()


def pick_asset(release: Release, app_id: str | None) -> Asset | None:
    """Prefer an official package asset; None means use the source tarball."""
    archives = [a for a in release.assets
                if a.name.lower().endswith(ARCHIVE_SUFFIXES) and a.url]
    if not archives:
        return None
    if app_id:
        for asset in archives:
            if asset.name.lower().startswith(f"{app_id}-{release.version}".lower()):
                return asset
        for asset in archives:
            if app_id.lower() in asset.name.lower():
                return asset
    for asset in archives:
        if "whisplay" in asset.name.lower() or "mfruit" in asset.name.lower():
            return asset
    return archives[0] if len(archives) == 1 else None


def checksum_asset(release: Release, asset: Asset) -> Asset | None:
    for candidate in release.assets:
        name = candidate.name.lower()
        if name in (f"{asset.name.lower()}.sha256", f"{asset.name.lower()}.sha256sum"):
            return candidate
    for candidate in release.assets:
        if candidate.name.lower() in CHECKSUM_NAMES:
            return candidate
    return None


def _short(url: str) -> str:
    return urllib.parse.urlsplit(url).path[:80]


def _close(response) -> None:
    close = getattr(response, "close", None)
    if close:
        try:
            close()
        except OSError:
            pass


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("Cannot remove %s: %s", path, exc)
