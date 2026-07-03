# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Parse a unified diff into changed line numbers per file (issue #212, AC#4).

The changed-symbol pass needs the NEW-side line numbers a diff touched.
``changed_lines_from_unified_diff`` reads ``git diff`` hunk headers
(``@@ -old +new @@``) and returns, per new-side path, the set of added/modified
line numbers — the input :func:`sumo_qa.analysis.python_adapter.symbols_touching_lines`
maps onto symbol spans. Pure text parsing, no git invocation: the caller supplies
the diff text (e.g. from a ``git diff`` beside
:func:`sumo_qa.repo_map_impact.changed_files_from_git`).

Only ADDED lines (``+``) carry a new-side line number, so only they are recorded
— a pure deletion has no new-side line to attribute to a symbol. A file deleted
outright (``+++ /dev/null``) contributes nothing.
"""

from __future__ import annotations

import re

# ``+++ b/path`` (or ``+++ path``) names the new-side file; ``git`` prefixes with
# ``b/`` and may append a tab-separated timestamp, both stripped below.
_NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.*?)(?:\t.*)?$")
# ``@@ -old[,len] +new[,len] @@`` — capture the new-side start line.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines_from_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """New-side changed line numbers per file path from a unified diff.

    Returns ``{path: {line, ...}}`` for every non-deleted file with at least one
    added line. Deterministic; empty when the diff adds nothing.
    """
    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    new_line = 0
    for raw in diff_text.splitlines():
        new_match = _NEW_FILE_RE.match(raw)
        if new_match is not None:
            path = new_match.group(1)
            # A file removed entirely has no new-side path to record against.
            current_path = None if path == "/dev/null" else path
            continue
        hunk_match = _HUNK_RE.match(raw)
        if hunk_match is not None:
            new_line = int(hunk_match.group(1))
            continue
        if current_path is None:
            continue  # header/preamble lines before the first file are ignored
        if raw.startswith("+"):
            changed.setdefault(current_path, set()).add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            # Removed line: old side only, the new-side counter does not advance.
            continue
        elif raw.startswith("\\"):
            # "\ No newline at end of file" is metadata, not a content line.
            continue
        else:
            # A context line (leading space) exists on both sides; advance the
            # new-side counter without recording it as changed.
            new_line += 1
    return changed
