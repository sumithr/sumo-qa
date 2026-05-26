# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SKILL.md token-weight regression — separate from the catalogue-loader
budget in test_token_weight_regression.py (which covers sumo_qa_load_*
output). Every skills/*/SKILL.md is loaded into the host LLM context when
its skill activates, so its size is a direct, per-activation token cost.

Budgets are measured (chars/4) plus a small cushion. A skill that grows past
its ceiling fails here; a NEW skill with no budget entry also fails, forcing
an explicit budget decision rather than silent drift.
"""

from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILL_PATHS = sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _approx_tokens(text: str) -> int:
    """Approximate token count: length / 4, rounded up. Same estimator as
    test_token_weight_regression.py so the two budgets are comparable."""
    return (len(text) + 3) // 4


# Per-skill ceilings in approx-tokens (chars/4). Tranche skills carry post-cut
# measured size + cushion; untouched skills carry current measured size +
# cushion so this test guards the status quo.
SKILL_TOKEN_BUDGETS = {
    # measured 2026-05-26 (post-#82); cut skills tighten their entry as the
    # compression lands. Cushion ~5% above measured.
    "sumo-qa-answering-testing-question": 3140,  # measured 2989
    "sumo-qa-creating-test-plan": 2230,  # measured 2119
    "sumo-qa-deciding-approach": 3650,  # measured 3470
    "sumo-qa-executing-qa-rollout": 2200,  # measured 2094
    "sumo-qa-finding-test-data": 1830,  # measured 1740
    "sumo-qa-finishing-qa-work": 2130,  # measured 2025
    "sumo-qa-implementing-with-tdd": 2840,  # post-cut 2708 (was 3385, -20%)
    "sumo-qa-planning-qa-rollout": 2920,  # measured 2776
    "sumo-qa-preparing-for-work": 2380,  # measured 2266
    "sumo-qa-reviewing-before-merge": 3030,  # post-cut 2888 (was 4586, -37%)
    "sumo-qa-strategising": 2740,  # measured 2602
    "sumo-qa-strengthening-tests": 2870,  # measured 2724
    "sumo-qa-suggesting-external-skill": 3240,  # measured 3085
    "using-sumo-qa": 3660,  # measured 3477
}


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_md_stays_under_token_budget(skill_path):
    name = skill_path.parent.name
    assert name in SKILL_TOKEN_BUDGETS, (
        f"{name} has no entry in SKILL_TOKEN_BUDGETS. Add one (measured "
        f"chars/4 + small cushion) so SKILL.md size cannot drift silently."
    )
    tokens = _approx_tokens(skill_path.read_text(encoding="utf-8"))
    budget = SKILL_TOKEN_BUDGETS[name]
    assert tokens <= budget, (
        f"{name} SKILL.md is ~{tokens} tokens (>{budget}). Compress the body "
        f"or justify a budget bump; do not raise the ceiling to paper over bloat."
    )
