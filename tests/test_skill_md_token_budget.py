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
    "sumo-qa-answering-testing-question": 2510,  # post-cut 2390 (was 2989, -20%)
    "sumo-qa-creating-test-plan": 1990,  # post-cut 1895 (was 2141, -11.5%)
    "sumo-qa-deciding-approach": 3060,  # +#188 catalogue-responsibilities section (lazy-load contract). Measured ~2983 post-#188; cushion ~2.6%. Net runtime context tax drops because the router no longer pre-loads principles + the chain explicitly delegates loads downstream.
    "sumo-qa-executing-qa-rollout": 1960,  # post-cut 1863 (was 2109, -11.7%)
    "sumo-qa-finding-test-data": 1580,  # post-cut 1508 (was 1754, -14.0%)
    "sumo-qa-finishing-qa-work": 1920,  # post-cut 1829 (was 2039, -10.3%)
    "sumo-qa-implementing-with-tdd": 2840,  # post-cut 2708 (was 3385, -20%)
    "sumo-qa-planning-qa-rollout": 2680,  # post-cut 2555 (was 2801, -8.8%)
    "sumo-qa-preparing-for-work": 2420,  # +#98 surface-signal rule (post-cut 2032 -> ~2301); cushion ~5%
    "sumo-qa-reviewing-before-merge": 3030,  # post-cut 2888 (was 4586, -37%)
    "sumo-qa-strategising": 2500,  # post-cut 2380 (was 2626, -9.4%)
    "sumo-qa-strengthening-tests": 2630,  # post-cut 2501 (was 2747, -9.0%)
    "sumo-qa-suggesting-external-skill": 2580,  # post-cut 2459 (was 3085, -20%)
    "using-sumo-qa": 2910,  # post-cut 2778 (was 3477, -20%)
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
