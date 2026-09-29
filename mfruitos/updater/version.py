"""Semantic version parsing and comparison (never compare versions as strings)."""

from __future__ import annotations

import functools
import re

_SEMVER = re.compile(
    r"^[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class InvalidVersion(ValueError):
    pass


@functools.total_ordering
class Version:
    """A semantic version. ``1.2`` is accepted and treated as ``1.2.0``."""

    __slots__ = ("major", "minor", "patch", "prerelease", "build")

    def __init__(self, major: int, minor: int, patch: int,
                 prerelease: tuple = (), build: str = ""):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.prerelease = prerelease
        self.build = build

    @classmethod
    def parse(cls, text: object) -> "Version":
        if not isinstance(text, str):
            raise InvalidVersion(f"not a version: {text!r}")
        match = _SEMVER.match(text.strip())
        if not match:
            raise InvalidVersion(f"not a semantic version: {text!r}")
        major, minor, patch, pre, build = match.groups()
        prerelease: tuple = ()
        if pre:
            parts = []
            for part in pre.split("."):
                if part.isdigit():
                    if len(part) > 1 and part.startswith("0"):
                        raise InvalidVersion(f"leading zero in prerelease: {text!r}")
                    parts.append(int(part))
                else:
                    parts.append(part)
            prerelease = tuple(parts)
        return cls(int(major), int(minor), int(patch or 0), prerelease, build or "")

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _key(self):
        # Releases sort after their prereleases; numeric identifiers sort
        # before alphanumeric ones (SemVer 2.0 §11).
        if not self.prerelease:
            pre_key = (1,)
        else:
            pre_key = (0,) + tuple((0, p, "") if isinstance(p, int) else (1, 0, p)
                                   for p in self.prerelease)
        return (self.major, self.minor, self.patch, pre_key)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(str(p) for p in self.prerelease)
        if self.build:
            text += "+" + self.build
        return text

    def __repr__(self):
        return f"Version('{self}')"


def parse_version(text: object) -> Version | None:
    """Parse a version or tag name; returns None if it is not semantic."""
    try:
        return Version.parse(text)
    except InvalidVersion:
        return None


def is_newer(candidate: str, installed: str) -> bool:
    """True if ``candidate`` is a strictly newer semantic version."""
    new = parse_version(candidate)
    old = parse_version(installed)
    if new is None:
        return False
    if old is None:
        return True
    return new > old


def sort_versions(texts, descending: bool = True) -> list[str]:
    parsed = [(parse_version(t), t) for t in texts]
    valid = [(v, t) for v, t in parsed if v is not None]
    valid.sort(key=lambda item: item[0], reverse=descending)
    return [t for _, t in valid]
