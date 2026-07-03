# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Parse a unified diff into changed line numbers per file (issue #212, AC#4).

The changed-symbol pass needs the NEW-side line numbers a diff touched.
``changed_lines_from_unified_diff`` reads ``git diff`` hunk headers
(``@@ -old +new @@``) and returns, per new-side path, the set of changed line
numbers the input :func:`sumo_qa.analysis.python_adapter.symbols_touching_lines`
maps onto symbol spans. Pure text parsing, no git invocation: the caller supplies
the diff text (e.g. from a ``git diff`` beside
:func:`sumo_qa.repo_map_impact.changed_files_from_git`).

An added (``+``) line carries its own new-side line number. A deletion (``-``)
has no new-side line of its own, but deleting logic inside a surviving function
is a real behavior change, so the CURRENT new-side position is recorded as the
"deletion seam" for that file (the counter is NOT advanced). Git's
zero-length-new-side hunk convention (``@@ -N,3 +M,0 @@`` puts ``M`` at the line
BEFORE the deletion) keeps that seam in or adjacent to the enclosing symbol, so a
pure deletion still attributes to a changed symbol instead of vanishing. A file
deleted outright (``+++ /dev/null``) contributes nothing.

Header detection is hunk-aware: an added content line can itself begin with
``+++ `` (the content ``++ x`` shown in the diff as ``+++ x``), which must NOT be
mistaken for the ``+++ b/path`` new-file header. A ``+++ `` line is read as a file
header only OUTSIDE a hunk; inside a hunk it is an added content line.
"""

from __future__ import annotations

import re

# ``+++ b/path`` (or ``+++ path``) names the new-side file; ``git`` prefixes with
# ``b/`` and may append a tab-separated timestamp, both stripped below. Consulted
# only OUTSIDE a hunk: inside a hunk ``+++ x`` is an added content line.
_NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.*?)(?:\t.*)?$")
# ``@@ -old[,len] +new[,len] @@``: capture the new-side start line.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# ``git`` file-section separator: it always begins a new file's header block and
# can never be hunk content (every content line carries a ``+``/``-``/`` ``/``\``
# prefix), so it definitively ends any hunk in progress and returns us to the
# header region where the following ``+++ `` line is the new-file header.
_DIFF_GIT_PREFIX = "diff --git "


def changed_lines_from_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """New-side changed line numbers per file path from a unified diff.

    Returns ``{path: {line, ...}}`` for every non-deleted file the diff touched:
    each added line's new-side number plus a deletion-seam line for each removed
    line (so removing logic inside a surviving symbol stays visible).
    Deterministic; empty when the diff changes nothing.
    """
    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    new_line = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith(_DIFF_GIT_PREFIX):
            # A new file section: leave any hunk and wait for its +++ header.
            in_hunk = False
            current_path = None
            continue
        hunk_match = _HUNK_RE.match(raw)
        if hunk_match is not None:
            new_line = int(hunk_match.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            # Header region (before the first hunk, or after a diff --git): the
            # only line we act on is the +++ new-file header.
            new_match = _NEW_FILE_RE.match(raw)
            if new_match is not None:
                path = new_match.group(1)
                # A file removed entirely has no new-side path to record against.
                current_path = None if path == "/dev/null" else path
            continue
        if current_path is None:
            continue  # inside a deleted (/dev/null) file: nothing to attribute
        if raw.startswith("+"):
            # An added line, including ``+++ x`` (content ``++ x``), which the
            # header region would have mis-read as a file switch.
            changed.setdefault(current_path, set()).add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            # A removed line has no new-side line of its own; the deletion sits
            # BETWEEN new-side lines (new_line - 1) and new_line. Record both
            # sides of that seam (without advancing): new_line alone points at
            # the next surviving line, which is the FOLLOWING symbol's def when
            # the deleted line was the last statement of a function. Attributing
            # both sides guarantees the enclosing symbol is touched, at the cost
            # of sometimes also flagging the neighbour (over-attribution beats
            # an invisible change for QA evidence).
            # Clamp to line 1: a zero-length new side at the start of a file
            # (git emits `@@ -1 +0,0 @@` for a -U0 first-line deletion) sets
            # new_line to 0, which no 1-based symbol span can match.
            lines = changed.setdefault(current_path, set())
            lines.add(max(new_line, 1))
            if new_line > 1:
                lines.add(new_line - 1)
        elif raw.startswith("\\"):
            # "\ No newline at end of file" is metadata, not a content line.
            continue
        else:
            # A context line (leading space) exists on both sides; advance the
            # new-side counter without recording it as changed.
            new_line += 1
    return changed
