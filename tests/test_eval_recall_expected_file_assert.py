# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/recall-expected-file.js``
(issue #754).

The review-recall corpus scores a case as caught on file plus defect, never on
wording. This assert is the file half: the review must name the file that
carries the defect (``metadata.expected_file``), by its repo path or its file
name. The llm-rubric judge owns the defect half. It runs under node, the
promptfoo runtime, so these tests execute the real file the eval loads.

Technique: *equivalence partitioning* over how a review can refer to the
file (full path, path with a line suffix, bare file name, a different file,
a file whose name only contains the expected name) plus the control class
with no expected file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSERT_PATH = REPO_ROOT / "tests" / "evals" / "promptfoo" / "asserts" / "recall-expected-file.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)"
)


def _grade(output: str, metadata: dict) -> dict:
    script = (
        "const check = require(process.argv[1]);"
        "const [output, metadata] = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(check(output, {test: {metadata}})));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(ASSERT_PATH)],
        input=json.dumps([output, metadata]),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


EXPECTED = {"expected_file": "tests/evals/promptfoo/run-eval.sh"}


@pytest.mark.parametrize(
    "output",
    [
        "Risk 1: dry-run parse in tests/evals/promptfoo/run-eval.sh:96 accepts 0",
        "The case arm at `run-eval.sh:96` treats any value as a dry run.",
        "**run-eval.sh** enables the dry run for `false`.",
    ],
)
def test_naming_the_file_by_path_or_name_passes(output):
    assert _grade(output, EXPECTED)["pass"] is True


@pytest.mark.parametrize(
    "output",
    [
        "Risk 1: run_baseline.py ignores error fields. SAFE TO MERGE.",
        "The wrapper old-run-eval.shim is fine.",
        "my-run-eval.sh is a different script.",
        "",
    ],
)
def test_not_naming_the_file_fails(output):
    result = _grade(output, EXPECTED)
    assert result["pass"] is False
    assert "run-eval.sh" in result["reason"]


def test_a_case_without_an_expected_file_is_not_checked():
    result = _grade("SAFE TO MERGE", {"category": "control"})
    assert result["pass"] is True
