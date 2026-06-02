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
2. The all-skill manifest. TWO distinct artifacts, two distinct budgets:
   * the COMPACT ROUTING PROJECTION (per-skill metadata WITHOUT the
     section/module index arrays) stays under 2,500 approx tokens — this is
     the slice a host would hold to route across all skills at once;
   * the FULL-INDEX output the shipped ``sumo_qa_list_skill_manifests`` MCP
     tool actually returns (the whole index WITH every skill's ``sections[]``
     and ``modules[]`` arrays, serialized exactly as the server emits it)
     stays under a separate, larger ceiling. The shipped tool is the artifact
     hosts truly fetch, so it gets its own regression guard; without it,
     section/module-index bloat could balloon the real payload while the
     compact-projection budget stayed green.
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
# Budget for the COMPACT ROUTING PROJECTION only (per-skill metadata WITHOUT the
# section/module index arrays). This is NOT what the shipped MCP tool returns —
# see SHIPPED_MANIFEST_TOKEN_CEILING below for that.
COMPACT_MANIFEST_TOKEN_BUDGET = 2500  # epic #137: compact routing projection under 2,500
# Ceiling for the REAL payload the shipped ``sumo_qa_list_skill_manifests`` MCP
# tool returns: the FULL index WITH every skill's sections[]/modules[] arrays,
# serialized exactly as ``server.py`` emits it (json.dumps(..., ensure_ascii=
# False, indent=2)). Measured today at ~11,219 approx tokens; ceiling set with
# ~16% headroom so future section/module-index bloat trips this guard rather
# than slipping through unmeasured. This is the artifact hosts actually fetch,
# so it gets its own regression guard distinct from the compact-projection
# budget above (which a host would only realise by re-projecting the payload).
SHIPPED_MANIFEST_TOKEN_CEILING = 13000
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


def _compact_manifest_projection() -> str:
    """The routing projection a host fetches to choose a skill: per-skill
    metadata WITHOUT the section/module index arrays. This is the 'manifest
    output' the budget governs — the section index is fetched per-skill via
    ``mode='manifest'`` only once a skill is chosen, never all at once."""
    out = list_skill_manifests()
    compact = [
        {k: v for k, v in m.items() if k not in ("sections", "modules")} for m in out["skills"]
    ]
    return json.dumps(compact)


def _shipped_manifest_payload() -> str:
    """The exact string the shipped ``sumo_qa_list_skill_manifests`` MCP tool
    returns. The server serializes the FULL index (every skill's
    ``sections[]``/``modules[]`` arrays included) with
    ``json.dumps(..., ensure_ascii=False, indent=2)``; this mirrors that
    serialization byte-for-byte so the guard measures the real artifact a host
    fetches, not a re-projected approximation of it."""
    return json.dumps(list_skill_manifests(), ensure_ascii=False, indent=2)


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


def test_compact_routing_projection_stays_under_budget():
    """The COMPACT ROUTING PROJECTION (``_compact_manifest_projection`` —
    per-skill metadata WITHOUT the section/module index arrays) stays under
    2,500 approx tokens so a host could hold every skill's routing metadata at
    once without paying a full-body-per-skill tax.

    NOTE: this measures the compact projection, NOT the output of the shipped
    ``sumo_qa_list_skill_manifests`` MCP tool. The shipped tool returns the
    FULL index (sections[]/modules[] included) and is guarded separately by
    ``test_shipped_list_skill_manifests_output_stays_under_full_index_ceiling``.
    """
    tokens = _approx_tokens(_compact_manifest_projection())
    assert tokens <= COMPACT_MANIFEST_TOKEN_BUDGET, (
        f"compact routing projection is ~{tokens} tokens "
        f"(>{COMPACT_MANIFEST_TOKEN_BUDGET}); trim skill descriptions or the "
        f"metadata shape — the routing projection must not carry section/"
        f"module bodies."
    )


def test_shipped_list_skill_manifests_output_stays_under_full_index_ceiling():
    """Guard the REAL artifact hosts fetch: the exact string the shipped
    ``sumo_qa_list_skill_manifests`` MCP tool returns (the FULL index WITH
    every skill's sections[]/modules[] arrays, serialized as the server emits
    it). This is distinct from the compact-projection budget above — the
    shipped tool does NOT return the compact projection, so without this guard
    section/module-index bloat could balloon the payload hosts actually pay for
    while the compact budget stayed green. Ceiling carries ~16% headroom over
    today's measured size so genuine bloat trips it, normal drift does not."""
    tokens = _approx_tokens(_shipped_manifest_payload())
    assert tokens <= SHIPPED_MANIFEST_TOKEN_CEILING, (
        f"shipped sumo_qa_list_skill_manifests output is ~{tokens} tokens "
        f"(>{SHIPPED_MANIFEST_TOKEN_CEILING}); the full-index payload hosts "
        f"fetch has bloated. Trim section/module index entries or raise the "
        f"ceiling deliberately with a fresh measurement — do not let the real "
        f"artifact grow unmeasured behind the compact-projection budget."
    )


def test_manifest_excludes_section_and_module_bodies():
    """The manifest budget only holds because per-skill section/module index
    arrays are NOT in the all-skill routing projection. Lock that: the section
    index for a single skill is fetched via mode='manifest' once chosen."""
    out = list_skill_manifests()
    # The full index (with sections[]/modules[]) is deliberately heavier than
    # the compact projection — proving the projection is what keeps us in
    # budget, not that the index happens to be small.
    full = _approx_tokens(json.dumps(out))
    compact = _approx_tokens(_compact_manifest_projection())
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
