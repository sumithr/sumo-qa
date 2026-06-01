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
    "sumo-qa-creating-test-plan": 2055,  # +#144 optional risk-to-test ledger appendix in step 12 (project the confirmed risk→technique table into sumo_qa_format_risk_ledger; planned/accepted residual rows). Measured ~2010; cushion ~2%.
    "sumo-qa-deciding-approach": 3060,  # +#188 catalogue-responsibilities section (lazy-load contract). Measured ~2983 post-#188; cushion ~2.6%. Net runtime context tax drops because the router no longer pre-loads principles + the chain explicitly delegates loads downstream.
    "sumo-qa-executing-qa-rollout": 1960,  # post-cut 1863 (was 2109, -11.7%)
    "sumo-qa-finding-test-data": 1580,  # post-cut 1508 (was 1754, -14.0%)
    "sumo-qa-finishing-qa-work": 1990,  # +#144 optional risk-to-test ledger render in step 3 (project the risk-to-test map into sumo_qa_format_risk_ledger; passing/failing/planned/stale/accepted_residual states). Measured ~1947; cushion ~2%.
    "sumo-qa-implementing-with-tdd": 3200,  # +#85 expected-value derivation check — post-cut 2708 → ~3177 after adding the third discriminator-check axis to step 3 (assertion expected-value vs input+domain rule, complementing the existing tautology + setup-discriminator checks), matching Red-Flags row, and Bad/contrast example for recalled-vs-derived expected values. Closes the leap-year boundary eval FAIL → PASS (delta +1/-1 on the implementing-with-tdd promptfoo baseline). Cushion ~0.7%.
    "sumo-qa-planning-qa-rollout": 2680,  # post-cut 2555 (was 2801, -8.8%)
    "sumo-qa-preparing-for-work": 2685,  # +#98 surface-signal rule AND +#156 repo-map query wiring in step 3 (prefer .sumo-qa/repo-map.json via sumo_qa_query_repo_map, fall back to reading files) AND +#144 optional planning-only risk-to-test ledger appendix in step 8 (project named risks + proposed checks into sumo_qa_format_risk_ledger, all rows evidence_status=planned, no code change / no test run). Merged measured ~2628; cushion ~2%.
    "sumo-qa-reviewing-before-merge": 5560,  # +#161 one-line reasoning-effort reminder (merge-safety review = high-stakes → strongest available reasoning, no model/provider names, no hidden reasoning) → measured ~5446. +#236 mandatory adversarial discovery pass (step 4: an 11-probe signal->defect-class sweep BEFORE the risk list, the "discovery hit = NAMED RISK -> UNCOVERED -> NOT SAFE" verdict-conversion rule, the change-rule label-leak guard) AND +#156 repo-map wiring (step-1 sumo_qa_analyze_diff_impact accelerator as input aid NOT coverage evidence, step-9 sumo_qa_query_repo_map re-anchor, 2a inventory-drift worked contrast) AND +#144 optional structured risk-to-test ledger appendix in step 10 (project the named risks + coverage map into sumo_qa_format_risk_ledger BELOW the prose verdict; uncovered_blocker_count must be 0 before SAFE; markdown-first preserved; the table shape + columns + a worked uncovered-blocker row pinned so the candidate emits the markdown table not JSON — closes the reviewing-before-merge-ledger eval FAIL->PASS). Merged measured ~5237; cushion ~2%. Largest single skill — carries the heaviest review surface plus the independent-discovery pass.
    "sumo-qa-strategising": 2830,  # +#161 one-line reasoning-effort reminder (repo-wide strategy = high-stakes → strongest available reasoning, no model/provider names, no hidden reasoning) → measured ~2772. +#156 repo-map wiring: step-1 accelerator (sumo_qa_scan_repo / sumo_qa_query_repo_map as inventory aid) + step-9 final-turn output guard that restores the strategising eval to 1/1 after the wiring diluted the output-economy rule's salience. Merged measured ~2679; cushion ~2%.
    "sumo-qa-strengthening-tests": 2630,  # post-cut 2501 (was 2747, -9.0%)
    "sumo-qa-suggesting-external-skill": 2580,  # post-cut 2459 (was 3085, -20%)
    "using-sumo-qa": 3135,  # +#161 host-neutral "Reasoning effort" global-discipline block (inherited by every sub-skill: prefer strongest AVAILABLE reasoning for high-stakes QA, highest practical reasoning-effort setting if exposed, no model/provider/control names, never expose hidden reasoning). Measured ~3069; cushion ~2%.
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
