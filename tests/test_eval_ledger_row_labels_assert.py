# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/ledger-row-labels.js``
(issue #689).

The assert fails a reviewing-before-merge coverage-ledger row whose label
contradicts its own ``Fresh matching tests`` field (the "label follows the
row" rule pinned in the ``coverage-ledger`` module). It runs under node, the
promptfoo runtime, so these tests execute the real file the evals load.

Techniques: *equivalence partitioning* over the tests-field classes (listed /
NONE) crossed with the label classes (COVERED / UNPROVEN / UNCOVERED /
ignored), and *error guessing* over the markdown shapes the Claude candidate
has emitted (bold, backticks, table pipes, header tables). The negative cases
include rows the candidate really produced on the coverage-artifact corpus.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"
ASSERT_PATH = PROMPTFOO_DIR / "asserts" / "ledger-row-labels.js"
ASSERT_REF = "file://asserts/ledger-row-labels.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)"
)


def _grade(outputs: list[str]) -> list[dict]:
    script = (
        "const check = require(process.argv[1]);"
        "const outputs = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(outputs.map((o) => check(o))));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(ASSERT_PATH)],
        input=json.dumps(outputs),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _row(tests: str, coverage: str, risk: str = "Invalid Amount Guard") -> str:
    return (
        f"Risk: {risk} | Anchor: services/billing/refund.py:43-44 | "
        f"Required test path: tests/billing/ | Fresh matching tests: {tests} | Coverage: {coverage}"
    )


LISTED = "tests/billing/test_refund.py::test_refund_happy_path"

# Real rows the Claude candidate emitted on skill-reviewing-before-merge-coverage-artifact.yaml
# before this check existed; each contradicts its own tests field.
REAL_CONTRADICTIONS = [
    "Risk: Zero Amount Edge Case | Anchor: services/billing/refund.py:43 | Required test path: tests/billing/ | "
    "Fresh matching tests: tests/billing/test_refund.py::test_refund_happy_path | Coverage: UNCOVERED",
    "Risk: Undefined or unverified `bulk_discount()` function | Anchor: domain/pricing.py:2 | "
    "Required test path: tests/domain/test_pricing.py | "
    "Fresh matching tests: tests/domain/test_pricing.py::test_line_total_is_positive | Coverage: UNCOVERED",
    "Risk: Invalid Amount Validation Path Untested | Anchor: services/billing/refund.py:43-44 | "
    "Required test path: tests/billing/ | Fresh matching tests: test_refund_happy_path (positive amount only) | "
    "Coverage: UNCOVERED",
    "Risk: RefundAmountInvalid Exception Handling Unverified | Anchor: services/billing/refund.py:43 | "
    "Required test path: tests/billing/ | Fresh matching tests: NONE | Coverage: UNPROVEN",
]

# Real consistent rows from the same corpus, in the markdown shapes the candidate used.
REAL_CONSISTENT = [
    "**Risk: Invalid Amount Validation Branch Not Exercised | Anchor: services/billing/refund.py:43-44 | "
    "Required test path: tests/billing/ | Fresh matching tests: tests/billing/test_refund.py::test_refund_happy_path "
    "| Coverage: UNPROVEN**",
    "Risk 1: Multiplication operator not asserted | Anchor: `domain/pricing.py:2` | Required test path: "
    "`tests/domain/` | Fresh matching tests: `tests/domain/test_pricing.py::test_line_total_is_positive` | "
    "Coverage: **UNPROVEN**",
    "`Risk: Invalid Amount Rejection Path Untested | Anchor: services/billing/refund.py:43-44 | "
    "Required test path: tests/billing/ | Fresh matching tests: NONE | Coverage: UNCOVERED`",
]


@pytest.mark.parametrize("row", REAL_CONTRADICTIONS)
def test_real_contradicting_rows_fail_and_are_named(row):
    [result] = _grade([f"## Coverage ledger\n{row}\n\nNOT SAFE TO MERGE"])
    assert result["pass"] is False
    assert result["score"] == 0
    risk = row.split("|")[0].split(":", 1)[1].strip().replace("`", "")
    assert risk in result["reason"]


@pytest.mark.parametrize("row", REAL_CONSISTENT)
def test_real_consistent_rows_pass(row):
    [result] = _grade([row])
    assert result["pass"] is True, result["reason"]
    assert "1 ledger row(s) checked" in result["reason"]


@pytest.mark.parametrize(
    ("tests", "coverage", "passes"),
    [
        (LISTED, "COVERED (assert raises RefundAmountInvalid)", True),
        (LISTED, "UNPROVEN", True),
        (LISTED, "UNCOVERED", False),
        ("NONE", "UNCOVERED", True),
        ("NONE", "UNPROVEN", False),
        ("NONE", "COVERED", False),
        ("none (no test under tests/billing/)", "UNCOVERED", True),
        ("(none)", "UNPROVEN", False),
        ("", "UNPROVEN", False),
        ("-", "UNCOVERED", True),
        ("NONE", "N/A", True),
        ("NONE", "COVERED BY VERIFICATION", True),
        (LISTED, "DISCHARGED", True),
    ],
)
def test_label_follows_the_tests_field(tests, coverage, passes):
    [result] = _grade([_row(tests, coverage)])
    assert result["pass"] is passes, result["reason"]


@pytest.mark.parametrize(
    "tests",
    ["N/A", "n/a (no test under tests/billing/)", "nothing", "0 tests", "0 test", "not run"],
)
def test_empty_tests_field_spellings_read_as_none(tests):
    """A correct UNCOVERED row whose tests field says there is no test in
    other words passes; the same field labelled UNPROVEN fails."""
    [uncovered, unproven] = _grade([_row(tests, "UNCOVERED"), _row(tests, "UNPROVEN")])
    assert uncovered["pass"] is True, uncovered["reason"]
    assert unproven["pass"] is False, unproven["reason"]


@pytest.mark.parametrize(
    ("tests", "coverage", "passes"),
    [
        ("tests/parse/test_parse.py::test_parse[a|b]", "UNCOVERED", False),
        ("tests/parse/test_parse.py::test_parse[a|b]", "UNPROVEN", True),
        (
            "tests/parse/test_parse.py::test_parse[a|b], tests/parse/test_parse.py::test_x[|]",
            "UNCOVERED",
            False,
        ),
    ],
)
def test_test_id_containing_a_pipe_is_still_checked(tests, coverage, passes):
    """A parametrized pytest ID can carry `|`; the row must still be parsed and
    checked, never skipped as if it had no ledger row."""
    [result] = _grade([_row(tests, coverage)])
    assert result["pass"] is passes, result["reason"]
    if passes:
        assert "1 ledger row(s) checked" in result["reason"]


def test_integration_test_listed_for_a_module_risk_may_be_covered():
    """The coverage-ledger integration/e2e exception lists the admitted test in
    the tests field, so the row reads as a listed test, never NONE."""
    tests = "tests/integration/test_refund_flow.py::test_refund_rejects_zero_amount"
    [covered, uncovered] = _grade(
        [_row(tests, "COVERED (assert raises RefundAmountInvalid)"), _row(tests, "UNCOVERED")]
    )
    assert covered["pass"] is True, covered["reason"]
    assert uncovered["pass"] is False, uncovered["reason"]


def test_every_offending_row_is_named_and_consistent_rows_are_not():
    output = "\n".join(
        [
            _row(LISTED, "UNPROVEN", risk="Good Row"),
            _row(LISTED, "UNCOVERED", risk="Listed Yet Uncovered"),
            _row("NONE", "UNPROVEN", risk="None Yet Unproven"),
        ]
    )
    [result] = _grade([output])
    assert result["pass"] is False
    assert "Listed Yet Uncovered" in result["reason"]
    assert "None Yet Unproven" in result["reason"]
    assert "Good Row" not in result["reason"]


def test_table_pipes_around_an_inline_row_are_tolerated():
    [bad, good] = _grade(
        [
            f"| {_row(LISTED, 'UNCOVERED')} |",
            f"| {_row(LISTED, 'UNPROVEN')} |",
        ]
    )
    assert bad["pass"] is False
    assert good["pass"] is True


def test_header_table_ledger_is_checked():
    table = (
        "| Risk | Anchor | Fresh matching tests | Coverage |\n"
        "|---|:---:|---|---|\n"
        f"| Duplicate Charge | app/billing/checkout.py:12 | `{LISTED}` | **UNCOVERED** |\n"
        "| Session Bypass | app/auth/session.py:33 | NONE | UNCOVERED |\n"
        "\n"
        "| Other | table |\n"
        "|---|---|\n"
        "| NONE | UNPROVEN |\n"
    )
    [result] = _grade([table])
    assert result["pass"] is False
    assert "Duplicate Charge" in result["reason"]
    assert "Session Bypass" not in result["reason"]
    assert "Other" not in result["reason"]


def test_header_table_without_a_risk_column_still_names_the_row():
    table = "| Fresh matching tests | Coverage |\n|---|---|\n| NONE | UNPROVEN |\n"
    [result] = _grade([table])
    assert result["pass"] is False
    assert "Fresh matching tests: NONE | Coverage: UNPROVEN" in result["reason"]


def test_long_offending_row_is_truncated_in_the_reason():
    row = (
        "Anchor: x.py:1 | Fresh matching tests: " + "tests/a.py::t " * 20 + "| Coverage: UNCOVERED"
    )
    [result] = _grade([row])
    assert result["pass"] is False
    assert "..." in result["reason"]


@pytest.mark.parametrize(
    "output",
    [
        "",
        "SAFE TO MERGE: docs-only change, trivial-change exemption.",
        "External-contract anchor: a.py:3 | External source: gh | Real-output evidence: NONE | Coverage: UNPROVEN",
    ],
)
def test_output_without_path_keyed_ledger_rows_passes(output):
    [result] = _grade([output])
    assert result["pass"] is True
    assert "no COVERED/UNPROVEN/UNCOVERED ledger rows" in result["reason"]


def test_null_output_passes():
    script = (
        "const check = require(process.argv[1]); process.stdout.write(JSON.stringify(check(null)));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(ASSERT_PATH)], capture_output=True, encoding="utf-8", check=True
    )
    assert json.loads(proc.stdout)["pass"] is True


def _review_configs_loading_coverage_ledger() -> list[Path]:
    configs = []
    for path in sorted(PROMPTFOO_DIR.glob("skill-reviewing-before-merge*.yaml")):
        text = path.read_text(encoding="utf-8")
        declared = [
            line
            for line in text.splitlines()
            if "review_modules:" in line and "coverage-ledger" in line
        ]
        if declared:
            configs.append(path)
    return configs


def test_every_review_config_that_loads_the_ledger_wires_the_check():
    """A config whose skill slice can emit ledger rows must run the check in
    ``defaultTest.assert`` so it grades every seed and every ``.ab`` leg."""
    configs = _review_configs_loading_coverage_ledger()
    assert configs, "no reviewing-before-merge config loads coverage-ledger"
    missing = []
    for path in configs:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        asserts = config.get("defaultTest", {}).get("assert", [])
        if not any(a.get("type") == "javascript" and a.get("value") == ASSERT_REF for a in asserts):
            missing.append(path.name)
    assert not missing, f"configs loading coverage-ledger without {ASSERT_REF}: {missing}"
