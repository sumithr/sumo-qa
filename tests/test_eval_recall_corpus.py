# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Corpus contract for ``skill-reviewing-before-merge-recall.yaml`` (issue #754).

The recall corpus is only a measurement if every case can be scored the same
way: a ledger category and a split for ``recall.py``, an expected file the
file-anchor assert can look for in the diff the reviewer saw, and a held-out
case in every category a fix issue (#755-#759) will be judged on. A case whose
diff carries template syntax must be wrapped in a nunjucks raw block: promptfoo
renders var values, so an unwrapped ``{% endfor %}`` crashes the case and an
unwrapped ``{{ name }}`` whose names are all defined is silently substituted.

Technique: *checklist-based testing* over every case, plus *boundary value
analysis* on the corpus-size and held-out-per-category minimums.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "tests" / "evals" / "promptfoo" / "skill-reviewing-before-merge-recall.yaml"
CATEGORIES = {
    "null-empty-boundary",
    "contract-vs-implementation",
    "doc-or-comment-drift",
    "external-surface",
    "config-or-dependency",
    "state-or-ordering",
    "security",
    "test-adequacy",
    "eval-validity",
    "other",
}
# Categories promoted to their own fix issue on the ledger (#752 -> #755-#759).
PROMOTED = {
    "contract-vs-implementation",
    "test-adequacy",
    "external-surface",
    "doc-or-comment-drift",
    "eval-validity",
}
TEMPLATE = re.compile(r"\{\{|\{%|\{#")

TESTS = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["tests"]
CASES = [t for t in TESTS if t["metadata"]["category"] != "control"]
CONTROLS = [t for t in TESTS if t["metadata"]["category"] == "control"]


def _unwrapped(value: str) -> str:
    return value.removeprefix("{% raw %}").removesuffix("{% endraw %}")


ASSERT_PATH = REPO_ROOT / "tests" / "evals" / "promptfoo" / "asserts" / "recall-expected-file.js"


def _file_anchor_passes(pairs: list[tuple[str, str]]) -> list[bool]:
    """Run the scorer's own file check (the JS the eval loads) on each
    (text, expected_file) pair, so the corpus is held to the rule it is scored by."""
    script = (
        "const check = require(process.argv[1]);"
        "const pairs = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(pairs.map(([t, f]) =>"
        " check(t, {test: {metadata: {expected_file: f}}}).pass)));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(ASSERT_PATH)],
        input=json.dumps(pairs),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _git_has(spec: str) -> bool | None:
    """True/False when git can answer; None when the object is not in this clone."""
    sha = spec.split(":", 1)[0]
    if subprocess.run(
        ["git", "cat-file", "-e", sha], cwd=REPO_ROOT, capture_output=True
    ).returncode:
        return None
    return not subprocess.run(
        ["git", "cat-file", "-e", spec], cwd=REPO_ROOT, capture_output=True
    ).returncode


def test_the_corpus_holds_at_least_twenty_cases_and_a_control():
    assert len(CASES) >= 20
    assert CONTROLS


@pytest.mark.parametrize("case", CASES, ids=lambda t: t["description"][:60])
def test_every_case_is_scorable(case):
    meta = case["metadata"]
    assert meta["category"] in CATEGORIES
    assert meta["split"] in {"train", "held-out"}
    assert meta.get("ledger_issue") or meta.get("source_comment"), "no source recorded"
    assert meta.get("source_pr") is None or isinstance(meta["source_pr"], int)
    assert re.fullmatch(r"[0-9a-f]{7,40}", str(meta.get("defect_state"))), "no defect_state"
    assert case["vars"]["expected_finding"].strip()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)")
def test_every_case_shows_the_reviewer_its_defect_file():
    """The scorer's file check must be satisfiable from what the reviewer saw."""
    pairs = [
        (_unwrapped(c["vars"]["ground_truth_context"]), c["metadata"]["expected_file"])
        for c in CASES
    ]
    hidden = [
        c["description"] for c, ok in zip(CASES, _file_anchor_passes(pairs), strict=True) if not ok
    ]
    assert not hidden


def test_every_defect_state_holds_its_defect_file_when_the_clone_has_it():
    """`git show <defect_state>:<expected_file>` reproduces the defective file.
    PR-branch commits are absent from a shallow CI clone; those are checked
    wherever the objects exist (a maintainer clone) and skipped otherwise."""
    results = [
        _git_has(f"{c['metadata']['defect_state']}:{c['metadata']['expected_file']}") for c in CASES
    ]
    if all(r is None for r in results):
        pytest.skip("no defect_state commit is in this clone")
    missing = [c["description"] for c, r in zip(CASES, results, strict=True) if r is False]
    assert not missing


@pytest.mark.parametrize("control", CONTROLS, ids=lambda t: t["description"][:60])
def test_every_control_is_outside_both_splits(control):
    assert control["metadata"]["split"] == "control"
    assert "expected_file" not in control["metadata"]
    assert isinstance(control["metadata"].get("source_pr"), int)
    assert re.fullmatch(r"[0-9a-f]{7,40}", str(control["metadata"].get("pr_head")))


@pytest.mark.parametrize("category", sorted(PROMOTED))
def test_every_promoted_category_holds_out_a_case(category):
    splits = [c["metadata"]["split"] for c in CASES if c["metadata"]["category"] == category]
    assert "held-out" in splits and "train" in splits, splits


def test_descriptions_are_unique_because_recall_keys_cases_by_them():
    names = [t["description"] for t in TESTS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t["description"][:60])
def test_template_syntax_in_a_var_is_raw_wrapped(test):
    for name, value in test["vars"].items():
        if isinstance(value, str) and TEMPLATE.search(value):
            assert value.startswith("{% raw %}") and value.endswith("{% endraw %}"), name
            assert "{% endraw %}" not in value[len("{% raw %}") : -len("{% endraw %}")], name
