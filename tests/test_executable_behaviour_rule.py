# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The executable-behaviour rule is stated once and referenced, never restated (issue #761).

Routing (`sumo-qa-deciding-approach`) and review (`sumo-qa-reviewing-before-merge`)
both decide whether a changed file is runtime. Each used to key on path or file
type in its own words, so the two drifted apart. The rule now lives once in the
classifications catalogue, which both skills load, and every place that applies
it names it instead of rewording it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RULE = "a file is runtime when something executes, imports, or follows it as instructions"
NAME = "executable-behaviour rule"


def test_rule_is_stated_once_in_the_classifications_catalogue():
    hits = sorted(
        path.relative_to(ROOT).as_posix()
        for top in ("skills", "knowledge")
        for path in (ROOT / top).rglob("*.md")
        if RULE in " ".join(path.read_text(encoding="utf-8").split())
    )
    assert hits == ["knowledge/classifications.md"]


@pytest.mark.parametrize(
    "rel",
    [
        "knowledge/classifications.md",
        "skills/sumo-qa-deciding-approach/SKILL.md",
        "skills/sumo-qa-reviewing-before-merge/modules/runtime-scope.md",
        "skills/sumo-qa-reviewing-before-merge/modules/test-only-diff.md",
    ],
)
def test_routing_and_review_reference_the_rule_by_name(rel):
    assert NAME in (ROOT / rel).read_text(encoding="utf-8")
