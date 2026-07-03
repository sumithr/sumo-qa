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
        "-old_removed = 1",  # removed: no new-side line
        " keep = 2",  # context -> new line 4
        "\\ No newline at end of file",  # metadata, ignored
    ]
)


def test_only_added_lines_are_recorded_with_new_side_numbers():
    changed = changed_lines_from_unified_diff(_DIFF)
    assert changed == {"pkg/mod.py": {2, 3}}


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


def test_empty_diff_is_empty():
    assert changed_lines_from_unified_diff("") == {}
