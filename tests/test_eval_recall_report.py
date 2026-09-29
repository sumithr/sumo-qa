# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/recall.py`` (issue #754).

The recall reporter turns promptfoo reports of the review-recall corpus
(``skill-reviewing-before-merge-recall.yaml``) into the numbers the corpus
exists for: recall overall, per ledger category and per train / held-out split,
per run, with the mean and the run-to-run spread across several reports.

Techniques: *decision tables* over a result's (caught / missed) x (category) x
(split) cells, so each bucket's numerator and denominator are pinned
independently; *equivalence partitioning* over the result kinds (graded
case, negative control, provider error, case with missing metadata); and
*error guessing* on the failure the #651 class names: an errored result must
never be scored as a miss.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tests" / "evals" / "promptfoo" / "recall.py"


def _load():
    spec = importlib.util.spec_from_file_location("recall_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(desc: str, category: str, split: str, caught: bool, **extra) -> dict:
    result = {
        "description": desc,
        "success": caught,
        "failureReason": 0 if caught else 1,
        "gradingResult": {"pass": caught, "reason": "graded"},
        "testCase": {
            "description": desc,
            "metadata": {"category": category, "split": split, "ledger_issue": 1},
        },
    }
    result.update(extra)
    return result


def _report(tmp_path: Path, name: str, results: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps({"results": {"results": results, "stats": {"errors": 0}}}),
        encoding="utf-8",
    )
    return path


def _one_run(tmp_path: Path) -> Path:
    return _report(
        tmp_path,
        "run1.json",
        [
            _result("a1", "external-surface", "train", True),
            _result("a2", "external-surface", "train", False),
            _result("a3", "external-surface", "held-out", True),
            _result("b1", "test-adequacy", "train", False),
            _result("b2", "test-adequacy", "held-out", False),
            _result("c1", "control", "control", True),
        ],
    )


def test_single_run_recall_overall_per_category_and_per_split(tmp_path):
    recall = _load()
    summary = recall.summarise([_one_run(tmp_path)])

    run = summary["runs"][0]
    # Five recall cases (the control is not one); two caught.
    assert (run["overall"]["caught"], run["overall"]["total"]) == (2, 5)
    assert run["categories"]["external-surface"] == {"caught": 2, "total": 3}
    assert run["categories"]["test-adequacy"] == {"caught": 0, "total": 2}
    assert run["splits"]["train"] == {"caught": 1, "total": 3}
    assert run["splits"]["held-out"] == {"caught": 1, "total": 2}


def test_negative_controls_are_scored_apart_from_recall(tmp_path):
    recall = _load()
    path = _report(
        tmp_path,
        "run.json",
        [
            _result("a1", "external-surface", "train", True),
            _result("c1", "control", "control", True),
            _result("c2", "control", "control", False),
        ],
    )
    run = recall.summarise([path])["runs"][0]

    assert "control" not in run["categories"]
    assert (run["overall"]["caught"], run["overall"]["total"]) == (1, 1)
    # A control "passes" when the review stayed quiet; a failed control is a false alarm.
    assert run["controls"] == {"passed": 1, "total": 2}


def test_several_runs_report_mean_and_spread_of_overall_recall(tmp_path):
    recall = _load()
    first = _report(
        tmp_path,
        "r1.json",
        [_result("a1", "x", "train", True), _result("a2", "x", "train", True)],
    )
    second = _report(
        tmp_path,
        "r2.json",
        [_result("a1", "x", "train", True), _result("a2", "x", "train", False)],
    )
    summary = recall.summarise([first, second])

    assert [r["overall"]["recall"] for r in summary["runs"]] == [1.0, 0.5]
    assert summary["mean_recall"] == pytest.approx(0.75)
    assert summary["spread"] == pytest.approx(0.5)
    # Per case: caught in how many of the runs.
    assert summary["cases"]["a1"] == {"caught": 2, "runs": 2, "category": "x", "split": "train"}
    assert summary["cases"]["a2"] == {"caught": 1, "runs": 2, "category": "x", "split": "train"}


def test_repeat_rows_inside_one_report_are_separate_runs(tmp_path):
    recall = _load()
    # promptfoo --repeat 2 writes each case twice into the same report; the
    # k-th row of a case is its k-th run.
    path = _report(
        tmp_path,
        "rep.json",
        [
            _result("a1", "x", "train", True),
            _result("a2", "x", "train", True),
            _result("a1", "x", "train", False),
            _result("a2", "x", "train", True),
        ],
    )
    summary = recall.summarise([path])

    assert [r["overall"]["recall"] for r in summary["runs"]] == [1.0, 0.5]
    assert summary["spread"] == pytest.approx(0.5)


def test_an_errored_result_is_refused_not_scored_as_a_miss(tmp_path):
    recall = _load()
    path = _report(
        tmp_path,
        "err.json",
        [
            _result("a1", "x", "train", True),
            _result("a2", "x", "train", False, failureReason=2, error="usage limit"),
        ],
    )
    with pytest.raises(recall.ReportError, match="a2"):
        recall.summarise([path])


def test_an_assertion_failure_with_error_text_is_a_miss_not_an_error(tmp_path):
    recall = _load()
    # Real promptfoo shape for a graded miss: failureReason 1 (ASSERT) and the
    # judge's reason copied into `error`. Only failureReason 2 is a provider error.
    missed = _result("a1", "x", "train", False, error="A: NOT FOUND ... Verdict: FAIL")
    path = _report(tmp_path, "miss.json", [missed, _result("a2", "x", "train", True)])
    run = recall.summarise([path])["runs"][0]
    assert (run["overall"]["caught"], run["overall"]["total"]) == (1, 2)


def test_a_judge_error_is_refused_not_scored_as_a_miss(tmp_path):
    recall = _load()
    judged = _result("a1", "x", "train", False)
    judged["gradingResult"]["componentResults"] = [
        {"pass": False, "metadata": {"graderError": True}}
    ]
    path = _report(tmp_path, "judge.json", [judged])
    with pytest.raises(recall.ReportError, match="a1"):
        recall.summarise([path])


@pytest.mark.parametrize("missing", ["category", "split"])
def test_a_case_without_category_or_split_is_refused(tmp_path, missing):
    recall = _load()
    result = _result("a1", "x", "train", True)
    del result["testCase"]["metadata"][missing]
    path = _report(tmp_path, "meta.json", [result])
    with pytest.raises(recall.ReportError, match=missing):
        recall.summarise([path])


def test_a_report_with_no_results_is_refused(tmp_path):
    recall = _load()
    path = _report(tmp_path, "empty.json", [])
    with pytest.raises(recall.ReportError, match="no results"):
        recall.summarise([path])


def test_cli_prints_the_recall_table_and_exits_zero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(_one_run(tmp_path))],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "overall recall: 2/5 (40%)" in proc.stdout
    assert "external-surface: 2/3 (67%)" in proc.stdout
    assert "held-out: 1/2 (50%)" in proc.stdout
    assert "controls passed: 1/1" in proc.stdout


def test_cli_exits_two_on_an_unusable_report(tmp_path):
    path = _report(tmp_path, "empty.json", [])
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 2
    assert "no results" in proc.stderr


def test_no_reports_is_refused_not_a_division_by_zero():
    recall = _load()
    with pytest.raises(recall.ReportError, match="no reports"):
        recall.summarise([])
