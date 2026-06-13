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

# Dash characters that read as an em-dash-style slop tell. The ordinary
# hyphen-minus (U+002D) is fine; these are the wide/look-alike dashes:
#   U+2014 em-dash, U+2013 en-dash, U+2015 horizontal bar (em-dash look-alike),
#   U+2012 figure dash.
DASH_NAMES = {
    "—": "em-dash",
    "–": "en-dash",
    "―": "horizontal bar",
    "‒": "figure dash",
}
EM_DASH = "—"
EN_DASH = "–"

# A fenced-code delimiter is a run of >=3 backticks or tildes, indented 0-3
# spaces (CommonMark; 4+ spaces is an indented code block, not a fence).
_FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<rest>.*)$")

# Scanned when no explicit files are passed. Top-level docs/ only; nested
# trees (e.g. docs/superpowers/) are local-only and not user-facing.
DEFAULT_GLOBS = ("README.md", "DEMO.md", "AGENTS.md", "docs/*.md")


def prose_hits(text: str) -> list[tuple[int, str, str]]:
    """Return ``(line_number, dash_char, stripped_line)`` for every wide dash
    in prose, skipping fenced code blocks.

    The fence state machine follows CommonMark: a fence opens on a run of >=3
    backticks or tildes (indent 0-3); it closes only on a later line using the
    SAME character, a run at least as long, and no trailing content. A shorter
    or different-character delimiter inside the block is content, not a close,
    so mixed/nested-looking delimiters can't prematurely flip the state."""
    hits: list[tuple[int, str, str]] = []
    fence: tuple[str, int] | None = None  # (char, length) while inside a fence
    for line_no, line in enumerate(text.split("\n"), start=1):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group("marker")
            char, length = marker[0], len(marker)
            if fence is None:
                # Opening fence (an info string may follow, e.g. ```python).
                fence = (char, length)
            else:
                open_char, open_len = fence
                closes = char == open_char and length >= open_len and m.group("rest").strip() == ""
                if closes:
                    fence = None
            # A delimiter line is never prose, whether it opened, closed, or
            # is a non-closing run inside the block.
            continue
        if fence is not None:
            continue
        for ch, _name in DASH_NAMES.items():
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
            name = DASH_NAMES.get(ch, "wide dash")
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
