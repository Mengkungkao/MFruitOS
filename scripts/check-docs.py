#!/usr/bin/env python3
"""Check relative Markdown links and #anchors in the repository.

    python3 scripts/check-docs.py            # exit 1 and list broken links

External links (http, https, mailto) are not fetched. Links inside fenced code
blocks and inline code are ignored. Anchors use GitHub's heading slugs.
Standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def markdown_files() -> list[Path]:
    files = []
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        files += [Path(folder) / n for n in sorted(names) if n.endswith(".md")]
    return files


def visible_lines(text: str):
    """(line number, line) outside fenced code blocks, inline code removed."""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, re.sub(r"`[^`]*`", "", line)


def slug(heading: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)   # links -> their text
    text = text.replace("`", "").lower()
    text = re.sub(r"[^\w\- ]", "", text)                      # keeps letters, digits, _, -, space
    return text.replace(" ", "-")


def anchors(path: Path, cache: dict) -> set:
    if path not in cache:
        found, counts = set(), {}
        fenced = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if FENCE.match(line):
                fenced = not fenced
                continue
            match = None if fenced else HEADING.match(line)
            if match:
                base = slug(match.group(2))
                n = counts.get(base, 0)
                counts[base] = n + 1
                found.add(base if n == 0 else f"{base}-{n}")
        cache[path] = found
    return cache[path]


def check() -> list[str]:
    errors, cache = [], {}
    for md in markdown_files():
        text = md.read_text(encoding="utf-8")
        for number, line in visible_lines(text):
            for match in LINK.finditer(line):
                target = match.group(1) or match.group(2)
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    continue                                  # http:, https:, mailto:
                path_part, _, fragment = target.partition("#")
                where = f"{md.relative_to(ROOT)}:{number}"
                resolved = (md.parent / path_part).resolve() if path_part else md
                if not resolved.exists():
                    errors.append(f"{where}: missing target {target}")
                    continue
                if fragment and resolved.suffix == ".md" and fragment not in anchors(resolved, cache):
                    errors.append(f"{where}: no heading for #{fragment} in {resolved.relative_to(ROOT)}")
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"Documentation link check failed ({len(errors)} broken).", file=sys.stderr)
        return 1
    print("Documentation links OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
