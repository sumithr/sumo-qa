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
    "sumo-qa-preparing-for-work": 2894,  # +#98 surface-signal rule AND +#156 repo-map query wiring in step 3 (prefer .sumo-qa/repo-map.json via sumo_qa_query_repo_map, fall back to reading files) AND +#144 optional planning-only risk-to-test ledger appendix in step 8 (project named risks + proposed checks into sumo_qa_format_risk_ledger, all rows evidence_status=planned, no code change / no test run) AND +#149 optional host-neutral context-bundle input in step 3 (prefer a supplied bundle via sumo_qa_format_context_bundle to seed scope + constraints, fall back to reading files/ticket directly, treat stale/unknown/absent test/CI facts as stale; no GitHub/network dependency). Merged measured ~2838; cushion ~2%.
    "sumo-qa-reviewing-before-merge": 9244,  # +#264 acceptance-criteria coverage: step-9 AC-coverage rule (each host-supplied criterion checked vs diff + fresh tests, classified MET/UNMET/UNVERIFIED with a cited anchor; host-neutral — host supplies the criteria, the skill never fetches an issue / calls gh; graceful explicit fallback when none supplied — no fabrication, no silent skip), step-10(d) SAFE-blocker on any UNMET/UNVERIFIED AC mirroring the uncovered-risk rule, an AC-coverage appendix that REUSES the existing sumo_qa_format_risk_ledger schema (no new tool/structure — one row per criterion, uncovered_blocker_count enforces the gate), three Red-Flags rows. +#264-review-fix: per-criterion AC output made MANDATORY (not verdict-conditional) — Verdict-format item 7 now requires one classified+anchored AC line per supplied criterion incl. MET ones on the all-MET SAFE path; step-9 mandate + appendix de-conditionalised. Measured ~8468 (#264 review-fix-2: UNVERIFIED→planned-only ledger mapping aligned with docs/RISK-LEDGER.md); cushion ~1.9% (was 8330 over measured ~8093). MERGED #266 + #187 (origin/main) + #149 (this branch). +#266 mapping-gap narration in step 1 (diff-impact accelerator persists a repo-map on first run via persisted_map_path; a bare risk surface is never "no repo-map / not scanned"; probable_mapping_gap reads as a missed-convention mapping gap not zero coverage). +#187 UNPROVEN-escalation: technique-keyed failure-mode hints in step 6, the 2b verdict-discipline extension (every UNPROVEN row emits a prescribed discriminating-input line or a failure-mode-named acknowledged deferral; both SAFE-blockers), boundary-anchor wording, step-10 two-pass split note, three Red-Flags rows. Builds on +#236 adversarial discovery pass + #156 repo-map wiring + #144 ledger appendix. PLUS +#149 optional host-neutral context-bundle input in step 1 (prefer a supplied bundle via sumo_qa_format_context_bundle as a head-start, fall back to direct repo inspection; three rules — stale/unknown/absent evidence is never the verdict source, bundle-vs-local conflicts are called out not silently resolved, the bundle never replaces the diff read; no GitHub/network dependency). Merged measured ~7214; cushion ~2%. Largest single skill — carries the heaviest review surface plus the independent-discovery pass and the UNPROVEN-escalation discipline. +#264 review-fix-3: sharpened the MET vs UNVERIFIED boundary so the discriminator is WHICH behaviour the fresh test asserts (not whether every nuance is proven) — amended MET/UNVERIFIED bullets, added a worked MET-vs-UNVERIFIED contrast + a Red-Flags row against over-firing UNVERIFIED; fixes the AC-UNMET eval case where an asserted-stated-behaviour AC was wrongly downgraded. Measured ~9063; ceiling 9244, cushion ~2%.
    "sumo-qa-strategising": 2732,  # +#156 repo-map wiring: step-1 accelerator (sumo_qa_scan_repo / sumo_qa_query_repo_map as inventory aid) + step-9 final-turn output guard that restores the strategising eval to 1/1 after the wiring diluted the output-economy rule's salience. Merged measured ~2679; cushion ~2%.
    "sumo-qa-strengthening-tests": 2630,  # post-cut 2501 (was 2747, -9.0%)
    "sumo-qa-suggesting-external-skill": 2870,  # +#216 step-6 reproducibility re-assertion over the external skill_body (sumo-qa's repo-pinned + CI-reproducible setup standard OVERRIDES the returned skill_body, not just confirmation discipline; translate any brew/`-g`/system-pip skill_body instruction to its repo-pinned equivalent + CI mirror) plus the matching Red-Flags row. Measured ~2810; cushion ~2%.
    "using-sumo-qa": 3565,  # +#216 repo-pinned + CI-reproducible tool-setup as a HARD requirement in "Setting up the recommended tool" (both: exact pinned version + committed lockfile/manifest/pinned pre-commit hook — not a floating range/`latest`, written by RUNNING the install command not hand-editing — AND a CI step running that SAME repo-pinned binary, plus an explicit confirm-before-install inline gate) + a ban on machine-level/global installs for repo test tooling (brew, `npm -g`, system pip), with a matching Red-Flags row. Measured ~3493; cushion ~2%.
}


# The global root-SKILL.md ceiling (epic #137). A root body may exceed it ONLY
# with a deliberately documented exception — recorded as a per-skill entry in
# SKILL_TOKEN_BUDGETS above whose inline comment justifies the size. Skills at
# or below the global ceiling need no special justification.
GLOBAL_ROOT_SKILL_TOKEN_BUDGET = 3000

# Roots permitted above the global ceiling, each with the reason it carries
# more than the budget. Keep this list short and justified — it is the
# "deliberate exception is documented" escape hatch, not a place to park drift.
# (Epic #137 also tracks splitting the heaviest of these into lazy modules; until
# that lands these stay documented exceptions rather than silent overflows.)
DOCUMENTED_ROOT_BUDGET_EXCEPTIONS = {
    "sumo-qa-reviewing-before-merge": "heaviest review surface — adversarial discovery + UNPROVEN escalation + coverage ledger; epic #137 tracks splitting deep behaviour into lazy modules.",
    "using-sumo-qa": "entry router carries the full global discipline every sub-skill inherits (knowledge authority, output economy, shared host-neutral vocabulary).",
    "sumo-qa-implementing-with-tdd": "carries the full red→green discipline incl. the expected-value derivation discriminator (#85) with worked examples.",
    "sumo-qa-deciding-approach": "router + removability gate + catalogue lazy-load contract; net runtime context drops because it no longer pre-loads principles.",
}


def test_documented_exceptions_are_the_only_roots_over_the_global_budget():
    """Every root SKILL.md is at or below the 3000 global ceiling UNLESS it is
    a documented exception. A new root that drifts above 3000 without an entry
    in DOCUMENTED_ROOT_BUDGET_EXCEPTIONS fails here, forcing a deliberate
    decision (compress, split into a lazy module, or document why)."""
    over = {}
    for skill_path in SKILL_PATHS:
        name = skill_path.parent.name
        tokens = _approx_tokens(skill_path.read_text(encoding="utf-8"))
        if tokens > GLOBAL_ROOT_SKILL_TOKEN_BUDGET:
            over[name] = tokens
    undocumented = {n: t for n, t in over.items() if n not in DOCUMENTED_ROOT_BUDGET_EXCEPTIONS}
    assert not undocumented, (
        f"root SKILL.md over the {GLOBAL_ROOT_SKILL_TOKEN_BUDGET}-token global "
        f"budget without a documented exception: {undocumented}. Compress it, "
        f"split deep behaviour into a lazy module, or add a justified entry to "
        f"DOCUMENTED_ROOT_BUDGET_EXCEPTIONS."
    )


def test_documented_exception_list_has_no_stale_entries():
    """An exception entry whose skill has since dropped under the global
    ceiling (e.g. after a module split) is stale and must be removed so the
    list keeps meaning what it says."""
    stale = []
    for name, _reason in DOCUMENTED_ROOT_BUDGET_EXCEPTIONS.items():
        path = SKILLS_DIR / name / "SKILL.md"
        if not path.is_file():
            stale.append(f"{name} (no such skill)")
            continue
        tokens = _approx_tokens(path.read_text(encoding="utf-8"))
        if tokens <= GLOBAL_ROOT_SKILL_TOKEN_BUDGET:
            stale.append(f"{name} (~{tokens} now under {GLOBAL_ROOT_SKILL_TOKEN_BUDGET})")
    assert not stale, f"documented root-budget exceptions are stale and should be removed: {stale}"


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
