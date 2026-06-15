# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Token-budget regression for the progressive skill-loading surface (#286,
epic #137 PR2). Complements:

* ``test_skill_md_token_budget.py`` — per-root-SKILL.md ceilings (the 3000
  global, with documented per-skill exceptions).
* ``test_token_weight_regression.py`` — catalogue-loader per-call / per-flow
  budgets plus the cumulative repeated-skill-load session budget.

This module owns the budgets that exist *because* the partial loader exists:

1. Every lazy skill module (``skills/<skill>/modules/*.md``) stays under a
   global 1500 approx-token ceiling. No modules ship today; the test guards
   the ceiling the moment the first module lands so a fat module cannot slip
   in unmeasured.
2. The all-skill manifest. TWO distinct artifacts, two distinct budgets
   (#306 inverted which one ships by default):
   * the SHIPPED DEFAULT — what ``sumo_qa_list_skill_manifests`` returns with
     no args (detail="compact"): per-skill metadata WITHOUT the section/module
     index arrays — stays under 2,500 approx tokens. This is the slice a host
     holds to route across all skills at once, and the artifact hosts truly
     fetch by default;
   * the explicit ``detail="full_index"`` opt-in (the whole index WITH every
     skill's ``sections[]`` and ``modules[]`` arrays, serialized exactly as the
     server emits it) stays under a separate, larger ceiling. It is no longer
     the shipped default, but the guard still matters so section/module-index
     bloat stays measured even though hosts no longer pay it by default.
3. For the heaviest skills, manifest + the routing-minimal required sections
   (frontmatter + Iron Law + Flow — the gate/route slice a host needs before
   it executes the body) stays at least 50% below that skill's full-body
   token count. This is the cumulative-cost win the loader exists to deliver.

Technique: boundary value analysis — every assertion pins a value against a
budget ceiling, the boundary where a regression first shows. Estimator is the
shared chars/4 approximation (``skill_manifest._approx_tokens``), so all four
budget suites are directly comparable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumo_qa import skill_manifest as sm
from sumo_qa.skill_manifest import _approx_tokens, list_skill_manifests, load_skill_context

SKILLS_DIR = Path(__file__).parent.parent / "skills"

# --------------------------------------------------------------------------
# Budgets (approx tokens, chars/4). Conservative ceilings with a small cushion.
# --------------------------------------------------------------------------

MODULE_TOKEN_BUDGET = 1500  # epic #137: skill modules stay under a smaller global budget
# Budget for the SHIPPED DEFAULT payload — what ``sumo_qa_list_skill_manifests``
# now returns with no args (detail="compact", #306): per-skill metadata WITHOUT
# the section/module index arrays. This is the cheap all-skill routing slice a
# host fetches to choose a skill. Measured at ~2,176 approx tokens; #150's
# sixteenth skill (sumo-qa-triaging-test-failures) raised it to ~2,545, so the
# budget moves to 2,650 — each new skill legitimately adds one description to the
# routing slice; the guard keeps that growth measured, not forbidden. #409's
# sumo-qa-measuring-coverage (the seventeenth skill) raised it to ~2,692, so the
# budget moves to 2,720.
COMPACT_MANIFEST_TOKEN_BUDGET = 2720  # epic #137 / #306: shipped compact default under 2,720
# Ceiling for the explicit ``detail="full_index"`` payload: the FULL index WITH
# every skill's sections[]/modules[] arrays, serialized exactly as ``server.py``
# emits it (json.dumps(..., ensure_ascii=False, indent=2)). Measured today at
# ~11,219 approx tokens; ceiling set with headroom so future section/module
# -index bloat trips this guard rather than slipping through unmeasured. Since
# #306 this is an OPT-IN payload (not the shipped default), but the guard still
# matters so all-skill index bloat stays measured. #150's sixteenth skill
# (sumo-qa-triaging-test-failures) raised it to ~13,033, so the ceiling moves to
# 13,500 — a new skill legitimately adds its section index to the full opt-in.
# #409's sumo-qa-measuring-coverage plus #282's security-relevance index entries
# raised it to ~13,806 on the merged tree, so the ceiling moves to 14,100.
FULL_INDEX_TOKEN_CEILING = 14100
HEAVY_SKILL_FULL_FLOOR = 2500  # a skill is "heavy" once its full body exceeds this
PARTIAL_LOAD_SAVING_FLOOR = 0.50  # manifest + routing-minimal sections >= 50% below full

# Headings whose section is part of the routing-minimal slice a host loads to
# route/gate before executing the body. Matched case-insensitively as a
# substring of the heading text (so "The Iron Law", "Process Flow" match).
# Deliberately EXCLUDES the bulky operational sections (Checklist, Red Flags,
# verdict tables) — those are the body a host defers until execution, which is
# exactly where the cumulative-cost saving comes from.
_ROUTING_MINIMAL_TERMS = ("frontmatter", "iron law", "flow")


def _is_routing_minimal(section: dict) -> bool:
    lowered = section["heading"].lower()
    return any(term in lowered for term in _ROUTING_MINIMAL_TERMS)


def _shipped_default_payload() -> str:
    """The exact string the shipped ``sumo_qa_list_skill_manifests`` MCP tool
    returns with no args. Since #306 that is the COMPACT routing slice
    (detail="compact") — per-skill metadata WITHOUT the section/module index
    arrays. The server serializes it with
    ``json.dumps(..., ensure_ascii=False, indent=2)``; this mirrors that
    serialization byte-for-byte so the guard measures the real artifact a host
    fetches, not a re-projected approximation of it. The per-skill section
    index is fetched via ``mode='manifest'`` only once a skill is chosen, never
    all at once."""
    return json.dumps(list_skill_manifests(), ensure_ascii=False, indent=2)


def _full_index_payload() -> str:
    """The exact string ``sumo_qa_list_skill_manifests`` returns for the
    explicit ``detail="full_index"`` opt-in: the FULL index WITH every skill's
    ``sections[]``/``modules[]`` arrays, serialized as the server emits it. Not
    the shipped default since #306, but still guarded so index bloat is
    measured."""
    return json.dumps(list_skill_manifests(detail="full_index"), ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# 1. Module token ceiling
# --------------------------------------------------------------------------

MODULE_PATHS = sorted(SKILLS_DIR.glob("*/modules/*.md"))


@pytest.mark.parametrize(
    "module_path", MODULE_PATHS, ids=lambda p: f"{p.parent.parent.name}/{p.name}"
)
def test_skill_module_stays_under_token_budget(module_path):
    """Each lazy skill module stays under the 1500 approx-token ceiling. A
    module that grows past it should be split, not silently bloat the lazy
    branch it backs."""
    tokens = _approx_tokens(module_path.read_text(encoding="utf-8"))
    assert tokens <= MODULE_TOKEN_BUDGET, (
        f"{module_path.parent.parent.name}/modules/{module_path.name} is "
        f"~{tokens} tokens (>{MODULE_TOKEN_BUDGET}); split the module or "
        f"justify the budget — modules back a lazy branch and must stay light."
    )


def test_module_budget_is_enforced_via_the_index(tmp_path, monkeypatch):
    """Guard that the ceiling is wired to the manifest index, not only the
    glob above — so a module discovered through ``_index_modules`` is also
    measured. Builds a fake skill with one over-budget module and asserts the
    index's estimated_tokens exceeds the ceiling (the signal the parametrized
    test fires on for a real module)."""
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    fat = "x" * (MODULE_TOKEN_BUDGET * 4 + 8)  # > budget after chars/4
    skill_dir.joinpath("modules", "fat.md").write_text(fat, encoding="utf-8")
    modules = sm._index_modules(skill_dir)
    assert modules[0]["estimated_tokens"] > MODULE_TOKEN_BUDGET


# --------------------------------------------------------------------------
# 2. All-skill manifest budgets — TWO artifacts:
#    (a) the compact routing projection (under 2,500), and
#    (b) the shipped full-index tool output (under the larger full-index
#        ceiling). (b) is what hosts actually fetch.
# --------------------------------------------------------------------------


def test_shipped_default_output_stays_under_compact_budget():
    """The SHIPPED DEFAULT payload — what ``sumo_qa_list_skill_manifests``
    returns with no args (detail="compact" since #306) — stays under 2,500
    approx tokens so a host can hold every skill's routing metadata at once
    without paying a full-body-per-skill tax. This IS the artifact hosts fetch
    by default; the section index for a single skill is fetched per-skill via
    ``mode='manifest'`` only once a skill is chosen, never all at once."""
    tokens = _approx_tokens(_shipped_default_payload())
    assert tokens <= COMPACT_MANIFEST_TOKEN_BUDGET, (
        f"shipped default sumo_qa_list_skill_manifests output is ~{tokens} "
        f"tokens (>{COMPACT_MANIFEST_TOKEN_BUDGET}); trim skill descriptions or "
        f"the metadata shape — the shipped routing slice must not carry "
        f"section/module index arrays."
    )


def test_full_index_opt_in_stays_under_full_index_ceiling():
    """Guard the explicit ``detail="full_index"`` payload: the FULL index WITH
    every skill's sections[]/modules[] arrays, serialized as the server emits
    it. Since #306 this is an opt-in, not the shipped default — but the guard
    still matters so all-skill section/module-index bloat stays measured even
    though hosts no longer pay it by default. Ceiling carries ~16% headroom
    over today's measured size so genuine bloat trips it, normal drift does
    not."""
    tokens = _approx_tokens(_full_index_payload())
    assert tokens <= FULL_INDEX_TOKEN_CEILING, (
        f"detail='full_index' sumo_qa_list_skill_manifests output is ~{tokens} "
        f"tokens (>{FULL_INDEX_TOKEN_CEILING}); the full-index payload has "
        f"bloated. Trim section/module index entries or raise the ceiling "
        f"deliberately with a fresh measurement — do not let the index grow "
        f"unmeasured."
    )


def test_shipped_default_is_lighter_than_the_full_index():
    """The compact default holds its budget only because per-skill section/
    module index arrays are NOT in it. Lock that: the default is strictly
    lighter than the full_index opt-in, and the full index is the heavier
    artifact — proving the projection is what keeps the default in budget, not
    that the index happens to be small."""
    compact = _approx_tokens(_shipped_default_payload())
    full = _approx_tokens(_full_index_payload())
    assert compact < full
    assert compact <= COMPACT_MANIFEST_TOKEN_BUDGET


# --------------------------------------------------------------------------
# 3. Heavy-skill partial-load saving (>= 50% below full body)
# --------------------------------------------------------------------------


def _heavy_skills() -> list[str]:
    out = list_skill_manifests()
    return [
        m["skill_name"]
        for m in out["skills"]
        if m["estimated_tokens_full"] > HEAVY_SKILL_FULL_FLOOR
    ]


def test_there_is_at_least_one_heavy_skill():
    """The >=50% saving claim is only meaningful if a heavy skill exists to
    make it about. If every skill shrank below the floor this test flags that
    the floor needs revisiting rather than letting the saving test vacuously
    pass over an empty set."""
    assert _heavy_skills(), (
        f"no skill exceeds the heavy floor ({HEAVY_SKILL_FULL_FLOOR} tokens); "
        f"revisit HEAVY_SKILL_FULL_FLOOR so the partial-load saving test has a subject."
    )


@pytest.mark.parametrize("skill_name", _heavy_skills())
def test_partial_load_is_at_least_half_the_full_body_for_heavy_skills(skill_name):
    """Loading manifest + the routing-minimal required sections for a heavy
    skill costs at least 50% fewer tokens than its full body. This is the
    cumulative-cost win: a host routes/gates on the light slice and defers the
    operational body until it actually executes the skill."""
    manifest = load_skill_context(skill_name, "manifest")
    full_tokens = manifest["estimated_tokens_full"]
    manifest_tokens = _approx_tokens(json.dumps(manifest))

    routing = [s for s in manifest["sections"] if _is_routing_minimal(s)]
    assert routing, f"{skill_name} exposes no routing-minimal section (frontmatter/Iron Law/Flow)"
    section_tokens = sum(
        _approx_tokens(load_skill_context(skill_name, "section", section=s["id"])["content"])
        for s in routing
    )

    partial_total = manifest_tokens + section_tokens
    saving = (full_tokens - partial_total) / full_tokens
    assert saving >= PARTIAL_LOAD_SAVING_FLOOR, (
        f"{skill_name}: manifest + routing-minimal sections is ~{partial_total} "
        f"tokens vs ~{full_tokens} full ({saving:.0%} below); must be "
        f">={PARTIAL_LOAD_SAVING_FLOOR:.0%} below for the partial-load win to hold."
    )
