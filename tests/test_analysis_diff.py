# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for unified-diff -> changed-line parsing (issue #212 AC#4)."""

from __future__ import annotations

from sumo_qa.analysis.diff import changed_lines_from_unified_diff

_DIFF = "\n".join(
    [
        "diff --git a/pkg/mod.py b/pkg/mod.py",  # preamble before first +++
        "index 111..222 100644",
        "--- a/pkg/mod.py",
        "+++ b/pkg/mod.py",
        "@@ -1,3 +1,5 @@",
        " import os",  # context -> new line 1
        "+def added():",  # new line 2
        "+    return 1",  # new line 3
        "-old_removed = 1",  # removed: deletion seam at the current new line 4
        " keep = 2",  # context -> new line 4
        "\\ No newline at end of file",  # metadata, ignored
    ]
)


def test_added_lines_and_the_deletion_seam_are_recorded():
    # The two added lines carry new-side numbers; the removed line records the
    # deletion seam (the current new-side position) so it is not invisible.
    changed = changed_lines_from_unified_diff(_DIFF)
    assert changed == {"pkg/mod.py": {2, 3, 4}}


def test_pure_deletion_inside_a_function_records_the_seam_line():
    # A diff that ONLY deletes a line inside a body must still report a changed
    # line inside the enclosing function; the pre-fix parser returned {}.
    diff = "\n".join(
        [
            "diff --git a/pkg/mod.py b/pkg/mod.py",
            "--- a/pkg/mod.py",
            "+++ b/pkg/mod.py",
            "@@ -1,4 +1,3 @@",
            " def keep(x):",  # context -> new line 1
            "     a = x + 1",  # context -> new line 2
            "-    b = a * 2",  # removed: deletion seam at the current new line 3
            "     return a",  # context -> new line 3
        ]
    )
    # The deletion sits between new-side lines 2 and 3; both seam sides are
    # recorded and both sit inside `keep` (new-side lines 1-3).
    assert changed_lines_from_unified_diff(diff) == {"pkg/mod.py": {2, 3}}


def test_first_line_deletion_with_zero_length_new_side_clamps_to_line_one():
    # `git diff -U0` deleting a file's FIRST line emits `@@ -1 +0,0 @@`, so the
    # new-side counter is 0 — a line no 1-based symbol span can match. The seam
    # must clamp to line 1 so a top-of-file deletion (e.g. a decorator above
    # `def f():`) stays visible; the pre-clamp parser recorded {0}.
    diff = "\n".join(
        [
            "diff --git a/pkg/mod.py b/pkg/mod.py",
            "--- a/pkg/mod.py",
            "+++ b/pkg/mod.py",
            "@@ -1 +0,0 @@",
            "-@decorator",
        ]
    )
    assert changed_lines_from_unified_diff(diff) == {"pkg/mod.py": {1}}


def test_deleting_the_last_statement_of_a_function_touches_that_function():
    # Boundary case: deleting the LAST statement of `f` immediately before
    # `def g():`. The next new-side line (3) is g's def line, so a seam that
    # records only the next line attributes the change to `g` and misses `f`
    # entirely. Recording BOTH seam sides guarantees line 2 (inside `f`) is
    # flagged; the neighbour over-attribution on line 3 is accepted.
    from sumo_qa.analysis.python_adapter import extract_symbols, symbols_touching_lines

    diff = "\n".join(
        [
            "diff --git a/pkg/mod.py b/pkg/mod.py",
            "--- a/pkg/mod.py",
            "+++ b/pkg/mod.py",
            "@@ -1,4 +1,3 @@",
            " def f():",  # context -> new line 1
            "     x()",  # context -> new line 2
            "-    y()",  # removed: seam between new lines 2 and 3
            " def g():",  # context -> new line 3
        ]
    )
    changed = changed_lines_from_unified_diff(diff)
    assert changed == {"pkg/mod.py": {2, 3}}

    new_source = b"def f():\n    x()\ndef g():\n    pass\n"
    symbols = extract_symbols(new_source)
    touched = {s.qualname for s in symbols_touching_lines(symbols, changed["pkg/mod.py"])}
    assert "f" in touched  # the pre-fix seam ({3} only) attributed the change to g alone


def test_added_content_line_beginning_with_plus_plus_is_not_a_file_header():
    # An added line whose content is `++ x` shows in the diff as `+++ x` and
    # matches the file-header regex; inside a hunk it must be an added line of
    # the current file, not a switch to a file named `x`.
    diff = "\n".join(
        [
            "+++ b/pkg/mod.py",
            "@@ -1,1 +1,2 @@",
            " existing = 0",  # context -> new line 1
            "+++ x",  # added content line (content `++ x`) -> new line 2
        ]
    )
    assert changed_lines_from_unified_diff(diff) == {"pkg/mod.py": {2}}


def test_deleted_file_contributes_nothing():
    diff = "\n".join(
        [
            "--- a/gone.py",
            "+++ /dev/null",
            "@@ -1,2 +0,0 @@",
            "-def gone():",
            "-    return 0",
        ]
    )
    assert changed_lines_from_unified_diff(diff) == {}


def test_new_side_path_without_b_prefix_is_handled():
    diff = "\n".join(
        [
            "+++ plain/path.py",
            "@@ -0,0 +1,1 @@",
            "+first = 1",
        ]
    )
    assert changed_lines_from_unified_diff(diff) == {"plain/path.py": {1}}


def test_second_hunk_resets_the_new_side_counter():
    diff = "\n".join(
        [
            "+++ b/a.py",
            "@@ -1,1 +1,1 @@",
            "+top = 1",
            "@@ -10,1 +20,2 @@",
            " ctx = 2",  # new line 20 (context)
            "+bottom = 3",  # new line 21
        ]
    )
    assert changed_lines_from_unified_diff(diff) == {"a.py": {1, 21}}


def test_plain_multi_file_diff_attributes_each_file_and_exits_each_hunk():
    # A non-git multi-file unified diff (e.g. `diff -u` / `difflib.unified_diff`)
    # repeats the ---/+++ headers WITHOUT `diff --git` separators. The parser
    # tracks each hunk's declared line budget (an omitted `,len` defaults to 1),
    # so it leaves the first file's hunk once that budget is spent and the second
    # file's header block is read as a header, not content. Without it, the
    # second file's ---/+++ lines are swallowed as deleted/added content under the
    # first path and its changes bleed into the wrong file (the pre-fix parser
    # returned {"first.py": {1, 2}} and dropped second.py entirely).
    diff = "\n".join(
        [
            "--- a/first.py",
            "+++ b/first.py",
            "@@ -1 +1 @@",  # both lengths omitted -> default 1 old / 1 new
            "-was = 1",  # removed: deletion seam at new line 1
            "+now = 1",  # added -> new line 1
            "--- a/second.py",
            "+++ b/second.py",
            "@@ -0,0 +1 @@",  # new length omitted -> default 1
            "+added = 2",  # added -> new line 1
        ]
    )
    assert changed_lines_from_unified_diff(diff) == {
        "first.py": {1},
        "second.py": {1},
    }


def test_empty_diff_is_empty():
    assert changed_lines_from_unified_diff("") == {}
