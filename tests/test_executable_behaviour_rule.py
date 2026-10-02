# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The executable-behaviour rule is stated once and referenced, never restated (issue #761).

Routing (`sumo-qa-deciding-approach`) and review (`sumo-qa-reviewing-before-merge`)
both decide whether a changed file is runtime. Each used to key on path or file
type in its own words, so the two drifted apart. The rule now lives once in the
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
# replaced). Any of them outside the catalogue is a restatement or a paraphrase.
RULE_FRAGMENTS = (
    "whatever its path",
    "follows it as instructions",
    "executes, imports",
    "something executes",
    "not path prefix",
    "behaviour, not path",
    "regardless of path",
)
# The rule's name as a reference: not a fragment of a longer hyphenated word,
# not pluralised.
NAME_RE = re.compile(r"(?<![\w-])executable-behaviour rule(?![\w-])", re.IGNORECASE)


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
def test_a_recased_or_paraphrased_copy_is_caught(copy):
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


@pytest.mark.parametrize(
    "text", ["non-executable-behaviour rule", "executable-behaviour rules", "the behaviour rule"]
)
def test_the_name_check_rejects_a_mere_substring(text):
    assert not NAME_RE.search(text)
