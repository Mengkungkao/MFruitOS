"""Download verification and safe archive extraction.

Archives from the internet are untrusted. Extraction rejects absolute paths,
``..`` traversal, links that escape the destination, device files and FIFOs,
and enforces file-count and size limits. Set-uid/set-gid bits and
group/other write permissions are stripped.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import stat
import tarfile
import zipfile

log = logging.getLogger("mfruitos.updater.verifier")

MAX_FILES = 20000
MAX_TOTAL_BYTES = 600 * 1024 * 1024


class VerificationError(Exception):
    pass


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output (``<hex>  <name>``) or a bare hash."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if match:
            result[os.path.basename(match.group(2).strip())] = match.group(1).lower()
        elif re.match(r"^[0-9a-fA-F]{64}$", line):
            result[""] = line.lower()
    return result


def expected_from_digest(digest: str) -> str | None:
    if digest.lower().startswith("sha256:") and len(digest) == 71:
        return digest[7:].lower()
    return None


def verify_sha256(actual: str, expected: str) -> None:
    if actual.lower() != expected.lower():
        raise VerificationError("checksum mismatch: the download is corrupt or was tampered with")


def _check_name(name: str) -> str:
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise VerificationError(f"archive contains an absolute path: {name!r}")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise VerificationError(f"archive contains a path traversal: {name!r}")
    if "\x00" in name:
        raise VerificationError("archive contains a NUL in a file name")
    return "/".join(parts)


def _inside(dest: str, relative: str) -> str:
    target = os.path.realpath(os.path.join(dest, relative))
    root = os.path.realpath(dest)
    if target != root and os.path.commonpath([root, target]) != root:
        raise VerificationError(f"archive entry escapes the destination: {relative!r}")
    return target


def _safe_mode(mode: int, is_dir: bool) -> int:
    mode &= 0o755
    if is_dir:
        mode |= 0o700
    else:
        mode |= 0o600
    return mode


def safe_extract(archive: str, dest: str) -> str:
    """Extract ``archive`` into (new, empty) ``dest``; return the package root.

    A single top-level directory (as in GitHub source tarballs) is unwrapped.
    """
    os.makedirs(dest, exist_ok=True)
    lower = archive.lower()
    if lower.endswith(".zip") or zipfile.is_zipfile(archive):
        _extract_zip(archive, dest)
    else:
        try:
            _extract_tar(archive, dest)
        except tarfile.TarError as exc:
            raise VerificationError(f"not a valid archive: {exc}") from exc
    entries = [e for e in os.listdir(dest) if e not in ("pax_global_header",)]
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])) \
            and not os.path.islink(os.path.join(dest, entries[0])):
        return os.path.join(dest, entries[0])
    return dest


def _extract_tar(archive: str, dest: str) -> None:
    total = 0
    count = 0
    links: list[tuple[str, str]] = []
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            count += 1
            if count > MAX_FILES:
                raise VerificationError("archive has too many files")
            if member.name in ("pax_global_header",) or member.type == tarfile.XGLTYPE:
                continue
            name = _check_name(member.name)
            if not name:
                continue
            target = _inside(dest, name)
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                os.chmod(target, _safe_mode(member.mode, True))
            elif member.isfile():
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise VerificationError("archive is too large when extracted")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise VerificationError(f"cannot read {name!r}")
                with source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
                os.chmod(target, _safe_mode(member.mode, False))
            elif member.issym() or member.islnk():
                links.append((name, member.linkname if member.issym() else "\0hard:" + member.linkname))
            else:
                raise VerificationError(f"archive contains a special file: {name!r}")
    for name, link in links:
        _make_link(dest, name, link)


def _make_link(dest: str, name: str, link: str) -> None:
    target = _inside(dest, name)
    if link.startswith("\0hard:"):
        source_rel = _check_name(link[6:])
        source = _inside(dest, source_rel)
        if not os.path.isfile(source):
            raise VerificationError(f"hard link to missing file: {name!r}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        return
    if os.path.isabs(link):
        raise VerificationError(f"absolute symlink in archive: {name!r} -> {link!r}")
    resolved = os.path.normpath(os.path.join(os.path.dirname(name), link))
    if resolved.startswith("..") or os.path.isabs(resolved):
        raise VerificationError(f"symlink escapes the package: {name!r} -> {link!r}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.symlink(link, target)


def _extract_zip(archive: str, dest: str) -> None:
    total = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_FILES:
                raise VerificationError("archive has too many files")
            for info in infos:
                name = _check_name(info.filename)
                if not name:
                    continue
                target = _inside(dest, name)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise VerificationError(f"symlinks are not allowed in zip packages: {name!r}")
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise VerificationError("archive is too large when extracted")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
                os.chmod(target, _safe_mode(mode or 0o644, False))
    except zipfile.BadZipFile as exc:
        raise VerificationError(f"not a valid zip archive: {exc}") from exc
