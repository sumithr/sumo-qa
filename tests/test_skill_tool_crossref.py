# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""T6 — Skill ↔ MCP-tool cross-reference test.

Guards against R-SKILLDRIFT: a SKILL.md body references a sumo_qa_* tool that
no longer exists (deletion / rename drift), or a registered MCP tool has no
SKILL.md reference (dead tool).

Regex note: the tighter pattern `[a-z0-9]` at the end (rather than `[a-z0-9_]`)
intentionally avoids matching the bare glob `sumo_qa_load_*` that appears in the
deciding-approach frontmatter description — only fully-formed tool names are flagged.
"""

from __future__ import annotations

import re
from pathlib import Path

from sumo_qa import server as sumo_server

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

# Matches any `sumo_qa_*` token.  Trailing `[a-z0-9]` (not `_`) prevents the
# bare glob `sumo_qa_load_*` (ending in `_`) from being treated as a tool ref.
_TOOL_REF_RE = re.compile(r"\bsumo_qa_[a-z][a-z0-9_]*[a-z0-9]\b")


def _registered_tool_names() -> set[str]:
    mcp = sumo_server.build_mcp_server()
    return set(mcp._tool_manager._tools.keys())


def _skill_bodies() -> dict[str, str]:
    """Map skill name → full SKILL.md body."""
    return {
        d.name: (d / "SKILL.md").read_text(encoding="utf-8")
        for d in sorted(SKILLS_DIR.iterdir())
        if d.is_dir() and (d / "SKILL.md").is_file()
    }


def _find_dead_refs(skill_bodies: dict[str, str], registered: set[str]) -> dict[str, set[str]]:
    """For each skill, return the set of sumo_qa_* refs that aren't registered."""
    dead: dict[str, set[str]] = {}
    for skill_name, body in skill_bodies.items():
        refs = set(_TOOL_REF_RE.findall(body))
        missing = refs - registered
        if missing:
            dead[skill_name] = missing
    return dead


def _find_orphan_tools(
    skill_bodies: dict[str, str], registered: set[str], whitelist: set[str]
) -> set[str]:
    """Return registered tool names that no SKILL body references (excluding whitelist)."""
    all_refs: set[str] = set()
    for body in skill_bodies.values():
        all_refs.update(_TOOL_REF_RE.findall(body))
    return registered - all_refs - whitelist


def test_no_dead_skill_to_tool_refs() -> None:
    """Forward: every sumo_qa_* ref in any SKILL.md must be a registered MCP tool."""
    bodies = _skill_bodies()
    registered = _registered_tool_names()
    dead = _find_dead_refs(bodies, registered)
    assert not dead, f"SKILL bodies reference nonexistent tools: {dead}"


# Standalone, description-discoverable utility tools that deliberately sit
# OUTSIDE the QA-routing skill chain. `sumo_qa_ingest_knowledge_pack` is a
# knowledge-management action ("add this to the knowledge base"), not a QA
# intent — routing it through `using-sumo-qa` would violate that skill's Iron
# Law (no work before `sumo-qa-deciding-approach`). `sumo_qa_capabilities` is a
# pure discovery tool ("what can sumo-qa do?") — it answers, it does not route a
# QA intent, so it is deliberately not the target of any SKILL body. The agent
# discovers and calls both from their tool descriptions, so neither needs a
# SKILL.md cross-reference.
#
# `sumo_qa_list_skill_manifests` and `sumo_qa_load_skill_context` (#285) are
# read-only progressive-loading tools a host discovers from their descriptions
# to fetch a slice of a skill instead of the full body. They are NOT routed via
# the QA-routing skill chain, so they have no SKILL.md cross-reference either.
#
# `sumo_qa_load_catalogue_entry` (#287, epic #137 Lever 4) is the same shape: a
# read-only progressive-loading tool a host discovers from its description to
# fetch one catalogue entry or a compact catalogue form instead of the full
# catalogue. The skills cite the full-text `sumo_qa_load_*` loaders for
# canonical wording; the compact loader is a navigation aid, not skill-routed.
_STANDALONE_UTILITY_TOOLS = {
    "sumo_qa_ingest_knowledge_pack",
    "sumo_qa_capabilities",
    "sumo_qa_list_skill_manifests",
    "sumo_qa_load_skill_context",
    "sumo_qa_load_catalogue_entry",
    # QA-artifact export (#148) is opt-in and deliberately NOT wired into any
    # default skill flow — markdown prose stays the human-facing output unless
    # the user explicitly asks to export, and the token-budget guard
    # (test_export_token_budget.py) pins that no SKILL.md references it. So it is
    # a standalone utility, not cross-referenced from a skill body.
    "sumo_qa_export_test_cases",
    # Local QA report (#157) is the same shape as export: opt-in artifact
    # plumbing the user explicitly asks for ("generate the QA report"), not a
    # step in any default skill reasoning flow. The host discovers it from its
    # tool description; the CLI mirror is `sumo-qa report`.
    "sumo_qa_generate_qa_report",
}
# #156 wired the repo-map tools into the skill chain: `sumo_qa_analyze_diff_impact`
# and `sumo_qa_query_repo_map` are referenced from `sumo-qa-reviewing-before-merge`,
# `sumo_qa_query_repo_map` also from `sumo-qa-preparing-for-work`, and
# `sumo_qa_scan_repo` + `sumo_qa_query_repo_map` from `sumo-qa-strategising`, so
# none of the three sit in the standalone-utility whitelist any more.


def test_no_orphan_registered_tools() -> None:
    """Reverse: every registered MCP tool must appear in at least one SKILL.md body.

    Per-skill content tools (one per skill directory, derived as
    `dir.name.replace('-', '_')`) are whitelisted — they return the SKILL.md
    body itself and don't need to be cross-referenced inside other SKILL bodies.
    Standalone utility tools (`_STANDALONE_UTILITY_TOOLS`) are whitelisted too.
    """
    bodies = _skill_bodies()
    registered = _registered_tool_names()
    whitelist = {
        d.name.replace("-", "_") for d in SKILLS_DIR.iterdir() if d.is_dir()
    } | _STANDALONE_UTILITY_TOOLS
    orphans = _find_orphan_tools(bodies, registered, whitelist)
    assert not orphans, f"Registered MCP tools with no SKILL reference: {orphans}"


def test_helpers_catch_synthetic_drift() -> None:
    """Self-test: prove the helpers actually flag drift on known-bad inputs."""
    synthetic_bodies = {
        "fake-skill": (
            "Body that calls `sumo_qa_does_not_exist` and `sumo_qa_load_classifications`."
        ),
    }
    synthetic_registered = {"sumo_qa_load_classifications", "sumo_qa_orphan_tool"}

    dead = _find_dead_refs(synthetic_bodies, synthetic_registered)
    assert dead == {"fake-skill": {"sumo_qa_does_not_exist"}}, (
        f"Dead-ref helper should flag the bad ref; got {dead}"
    )

    orphans = _find_orphan_tools(synthetic_bodies, synthetic_registered, whitelist=set())
    assert orphans == {"sumo_qa_orphan_tool"}, (
        f"Orphan-tool helper should flag the unreferenced tool; got {orphans}"
    )
