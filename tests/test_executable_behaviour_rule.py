# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The executable-behaviour rule is stated once and referenced, never restated (issue #761).

Routing (`sumo-qa-deciding-approach`) and review (`sumo-qa-reviewing-before-merge`)
both decide whether a changed file is runtime. The rule lives once in the
classifications catalogue, which both skills load, and every place that applies
it names it instead of rewording it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOME = "knowledge/classifications.md"

# Distinctive fragments of the rule's wording (and of the path-keyed wording it
# replaced). Any of them outside the catalogue is a near-verbatim restatement;
# a true paraphrase in new words is not caught here.
RULE_FRAGMENTS = (
    "whatever its path",
    "follows it as instructions",
    "executes, imports",
    "something executes",
    "not path prefix",
    "behaviour, not path",
    "regardless of path",
    "no `app/`/`src/`/`lib/` runtime file",
    "no `app`/`src`/`lib` runtime file",
)
# The rule's name as a reference, across a line wrap: not a fragment of a
# longer hyphenated word, not pluralised.
NAME_RE = re.compile(r"(?<![\w-])executable-behaviour\s+rule(?![\w-])", re.IGNORECASE)


def _normalised(text: str) -> str:
    return " ".join(text.split()).lower()


def restatements(texts: dict[str, str]) -> list[str]:
    """Each `path: fragment` where a file other than the catalogue carries a
    fragment of the rule's wording, case- and whitespace-insensitively."""
    return sorted(
        f"{rel}: {fragment}"
        for rel, text in texts.items()
        if rel != HOME
        for fragment in RULE_FRAGMENTS
        if fragment in _normalised(text)
    )


def _shipped_texts() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for top in ("skills", "knowledge")
        for path in (ROOT / top).rglob("*.md")
    }


def test_rule_is_stated_in_the_classifications_catalogue():
    text = _normalised((ROOT / HOME).read_text(encoding="utf-8"))
    assert all(fragment in text for fragment in RULE_FRAGMENTS[:4])


def test_rule_is_not_restated_outside_the_catalogue():
    assert restatements(_shipped_texts()) == []


@pytest.mark.parametrize(
    "copy",
    [
        "A FILE IS RUNTIME WHEN SOMETHING EXECUTES, IMPORTS, OR FOLLOWS IT AS INSTRUCTIONS.",
        "Treat it as runtime if an agent\nfollows it as instructions, whatever its path.",
        "Decide by executable behaviour, not path prefix.",
    ],
)
def test_a_recased_or_rewrapped_copy_of_a_fragment_is_caught(copy):
    """A near-verbatim copy carrying a rule fragment is caught whatever its case
    or line wrapping. A paraphrase in new words is out of scope."""
    assert restatements({"skills/x/SKILL.md": copy})


@pytest.mark.parametrize(
    "rel",
    [
        HOME,
        "skills/sumo-qa-deciding-approach/SKILL.md",
        "skills/sumo-qa-reviewing-before-merge/SKILL.md",
        "skills/sumo-qa-reviewing-before-merge/modules/runtime-scope.md",
        "skills/sumo-qa-reviewing-before-merge/modules/test-only-diff.md",
    ],
)
def test_routing_and_review_reference_the_rule_by_name(rel):
    assert NAME_RE.search((ROOT / rel).read_text(encoding="utf-8"))


def test_the_name_check_survives_a_line_wrap():
    assert NAME_RE.search("by the executable-behaviour\n   rule, never path")


@pytest.mark.parametrize(
    "text", ["non-executable-behaviour rule", "executable-behaviour rules", "the behaviour rule"]
)
def test_the_name_check_rejects_a_mere_substring(text):
    assert not NAME_RE.search(text)


@pytest.mark.parametrize(
    ("rel", "clause"),
    [
        # Ordinary tests and inert prose keep the lighter handling (#761).
        (
            HOME,
            "Ordinary test functions, fixtures and genuinely inert prose keep their "
            "current lighter handling",
        ),
        # A changed command or step in a followed procedure is runtime; prose is not (#746).
        (
            HOME,
            "In a followed procedure, a changed command or step is runtime; a prose-only "
            "edit is not.",
        ),
        # Executable test infrastructure is not test_change (#447, #667).
        (HOME, "parser, grader, reporter, transform) is `infrastructure_change`"),
        # A helper-only test diff still loads test-only-diff, by behaviour not path.
        (
            "skills/sumo-qa-reviewing-before-merge/SKILL.md",
            "| `test-only-diff` | only test code changed, by the executable-behaviour rule |",
        ),
    ],
)
def test_the_rule_edges_are_pinned(rel, clause):
    assert _normalised(clause) in _normalised((ROOT / rel).read_text(encoding="utf-8"))
