# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Fail if an em-dash or en-dash appears in user-facing markdown PROSE.

The em-dash (`—`) reads as an AI-slop tell in shipped documentation; the
standing rule is that no user-facing prose carries one. This gate enforces
that on the documentation set (README, DEMO, AGENTS, docs/*.md) so a stray
dash fails the commit and CI instead of reaching a reader. The en-dash
(`–`) is caught too; replace numeric ranges like `3-7` with a hyphen.

Fenced code blocks (``` and ~~~) are SKIPPED on purpose: they hold literal
example commands, sample tool output, and config snippets where a dash may be
real and must match what the tool actually emits. Everything else, including
markdown tables and headings, is treated as prose and checked.

Usage::

    python scripts/check_no_em_dashes.py [FILE ...]

With no FILE arguments the default documentation set is scanned (so CI can
call it bare); pre-commit passes the changed markdown files explicitly. Exit
code is 1 (with `file:line` for every hit) when any dash is found, 0 otherwise.
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

# Em-dash (U+2014) and en-dash (U+2013). The ordinary hyphen-minus is fine.
EM_DASH = "—"
EN_DASH = "–"
_DASHES = (EM_DASH, EN_DASH)
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Scanned when no explicit files are passed. Top-level docs/ only; nested
# trees (e.g. docs/superpowers/) are local-only and not user-facing.
DEFAULT_GLOBS = ("README.md", "DEMO.md", "AGENTS.md", "docs/*.md")


def prose_hits(text: str) -> list[tuple[int, str, str]]:
    """Return ``(line_number, dash_char, stripped_line)`` for every em/en-dash
    in prose, skipping fenced code blocks."""
    hits: list[tuple[int, str, str]] = []
    in_fence = False
    for line_no, line in enumerate(text.split("\n"), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for ch in _DASHES:
            if ch in line:
                hits.append((line_no, ch, line.strip()))
                break
    return hits


def _resolve_files(args: list[str]) -> list[Path]:
    if args:
        return [Path(a) for a in args]
    files: list[Path] = []
    for pattern in DEFAULT_GLOBS:
        files.extend(sorted(Path(p) for p in glob.glob(pattern)))
    return files


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:]) if argv is None else list(argv)
    files = _resolve_files(args)
    if not files:
        print("check_no_em_dashes: no markdown files to check")
        return 0

    failures: list[tuple[Path, int, str, str]] = []
    for md in files:
        if not md.exists():
            print(f"check_no_em_dashes: SKIP {md} (does not exist)", file=sys.stderr)
            continue
        for line_no, ch, line in prose_hits(md.read_text(encoding="utf-8")):
            failures.append((md, line_no, ch, line))

    if failures:
        for md, line_no, ch, line in failures:
            name = "em-dash" if ch == EM_DASH else "en-dash"
            print(f"{md}:{line_no}: {name} in prose -> {line}", file=sys.stderr)
        print(
            f"\n{len(failures)} em/en-dash(es) found in user-facing prose. "
            "Replace each with the punctuation the context needs (a colon to "
            "introduce, parentheses for an aside, a semicolon or period to join "
            "clauses, or a hyphen for a numeric range). Fenced code blocks are "
            "exempt.",
            file=sys.stderr,
        )
        return 1

    print(f"check_no_em_dashes: {len(files)} file(s) scanned, no em/en-dashes in prose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
