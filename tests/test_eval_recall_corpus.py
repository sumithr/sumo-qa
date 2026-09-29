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

import re
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


# Path-like tokens, so `README.md` inside `docs/README.md` is not the root README.
_PATH_TOKEN = re.compile(r"[\w.-]+(?:/[\w.-]+)*")


def _shows_path(context: str, path: str) -> bool:
    # `a/<path>` and `b/<path>` are the path in a `diff --git` header.
    wanted = {path, f"a/{path}", f"b/{path}"}
    return any(token.rstrip(".") in wanted for token in _PATH_TOKEN.findall(context))


def test_shows_path_needs_the_whole_path_not_a_substring():
    assert _shows_path("diff --git a/README.md b/README.md", "README.md")
    assert not _shows_path('see docs/README.md and "README.mdx"', "README.md")
    assert not _shows_path("scripts/install.sh", "install.sh")


def test_the_corpus_holds_at_least_twenty_cases_and_a_control():
    assert len(CASES) >= 20
    assert CONTROLS


@pytest.mark.parametrize("case", CASES, ids=lambda t: t["description"][:60])
def test_every_case_is_scorable(case):
    meta = case["metadata"]
    assert meta["category"] in CATEGORIES
    assert meta["split"] in {"train", "held-out"}
    assert meta.get("ledger_issue") or meta.get("source_comment"), "no source recorded"
    context = _unwrapped(case["vars"]["ground_truth_context"])
    assert _shows_path(context, meta["expected_file"]), "the reviewer never sees the defect file"
    assert case["vars"]["expected_finding"].strip()


@pytest.mark.parametrize("control", CONTROLS, ids=lambda t: t["description"][:60])
def test_every_control_is_outside_both_splits(control):
    assert control["metadata"]["split"] == "control"
    assert "expected_file" not in control["metadata"]


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
