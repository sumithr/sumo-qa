# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Canonical MCP tool registry and the profiles derived from it (#806).

Every tool the server registers has exactly one entry in ``TOOLS``: its
capability group, whether it belongs to the compact ``core`` profile, whether it
is open-world, and the optional integration it needs. The public profiles are
derived from this tuple, never hand-listed: ``full`` is every entry, ``core`` is
the entries marked ``core``. ``server.build_mcp_server`` resolves the profile
from ``SUMO_QA_MCP_PROFILE`` before registering anything, then removes the tools
outside it; a registered tool with no entry here warns on stderr and is
served under ``full`` only, and tests/test_tool_registry.py fails on it.

Core covers every advertised workflow: the entry router and every workflow
skill, plus each tool a core skill names (pinned by tests/test_tool_registry.py)
and ``sumo_qa_capabilities`` for discovery. The external-skill workflow body is
core so the router never points at a missing tool, but the open-world and
external-skill tools it drives (search, check, install, execute) are not: under
``core`` that workflow's tool is in ``tools/list``, and its entry declares ``requires`` on that
group, so calling it (or loading it through ``sumo_qa_load_skill_context``)
returns ``unavailable_capability``'s activation path instead of the skill body.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

PROFILE_ENV = "SUMO_QA_MCP_PROFILE"
PROFILES = ("core", "full")
DEFAULT_PROFILE = "full"
GROUPS = ("workflow", "test_design", "analysis", "execution_evidence", "specialist", "external")
ACTIVATION = f"{PROFILE_ENV}=full"


@dataclass(frozen=True)
class ToolMeta:
    name: str
    group: str
    core: bool
    open_world: bool = False
    integration: str | None = None
    # The group a core workflow cannot run without; a profile that leaves the
    # group out serves the activation path in place of the workflow.
    requires: str | None = None


def _core(group: str, *names: str) -> tuple[ToolMeta, ...]:
    return tuple(ToolMeta(name, group, core=True) for name in names)


TOOLS: tuple[ToolMeta, ...] = (
    *_core(
        "workflow",
        "using_sumo_qa",
        "sumo_qa_deciding_approach",
        "sumo_qa_answering_testing_question",
        "sumo_qa_closing_qa_gaps",
        "sumo_qa_creating_test_plan",
        "sumo_qa_executing_qa_rollout",
        "sumo_qa_finding_test_data",
        "sumo_qa_finishing_qa_work",
        "sumo_qa_implementing_with_tdd",
        "sumo_qa_measuring_coverage",
        "sumo_qa_planning_qa_rollout",
        "sumo_qa_preparing_for_work",
        "sumo_qa_reviewing_before_merge",
        "sumo_qa_security_testing",
        "sumo_qa_strategising",
        "sumo_qa_strengthening_tests",
        "sumo_qa_triaging_test_failures",
        "sumo_qa_capabilities",
        "sumo_qa_load_skill_context",
    ),
    *_core(
        "test_design",
        "sumo_qa_load_classifications",
        "sumo_qa_load_approaches",
        "sumo_qa_load_principles",
        "sumo_qa_load_techniques",
        "sumo_qa_load_standards",
        "sumo_qa_load_rules",
        "sumo_qa_explain_test_data_requirements",
        "sumo_qa_find_test_data",
        "sumo_qa_validate_test_data",
        "sumo_qa_register_known_good_test_data",
    ),
    *_core(
        "analysis",
        "sumo_qa_scan_repo",
        "sumo_qa_analyze_diff_impact",
        "sumo_qa_query_repo_map",
    ),
    *_core(
        "execution_evidence",
        "sumo_qa_format_risk_ledger",
        "sumo_qa_format_context_bundle",
        "sumo_qa_format_qa_scorecard",
        "sumo_qa_generate_qa_report",
        "sumo_qa_record_coverage",
        "sumo_qa_record_mutation",
        "sumo_qa_capture_review_feedback",
    ),
    ToolMeta("sumo_qa_suggesting_external_skill", "workflow", core=True, requires="external"),
    ToolMeta("sumo_qa_load_catalogue_entry", "specialist", core=False),
    ToolMeta("sumo_qa_list_skill_manifests", "specialist", core=False),
    ToolMeta("sumo_qa_export_test_cases", "specialist", core=False),
    ToolMeta("sumo_qa_ingest_knowledge_pack", "specialist", core=False),
    ToolMeta(
        "sumo_qa_search_external_skills",
        "external",
        core=False,
        open_world=True,
        integration="skills-cli",
    ),
    ToolMeta("sumo_qa_check_external_skill_installed", "external", core=False),
    ToolMeta(
        "sumo_qa_install_external_skill",
        "external",
        core=False,
        open_world=True,
        integration="skills-cli",
    ),
    ToolMeta("sumo_qa_execute_external_skill", "external", core=False),
)


def _invalid(value: str) -> ValueError:
    return ValueError(
        f"{PROFILE_ENV}={value!r} is not a valid MCP tool profile; "
        f"expected one of: {', '.join(PROFILES)}"
    )


def resolve_profile(env: Mapping[str, str] | None = None) -> str:
    """Return the profile named by ``SUMO_QA_MCP_PROFILE`` in ``env`` (default:
    the process env); unset or empty means ``full``. Any other value raises: it
    is never coerced."""
    value = (os.environ if env is None else env).get(PROFILE_ENV) or DEFAULT_PROFILE
    if value not in PROFILES:
        raise _invalid(value)
    return value


def resolve_profile_or_exit() -> str:
    """``resolve_profile`` for an entry point: a bad value exits with one line,
    never a traceback."""
    try:
        return resolve_profile()
    except ValueError as exc:
        raise SystemExit(f"sumo-qa: {exc}") from None


def profile_tool_names(profile: str) -> frozenset[str]:
    """The tool names a profile exposes, derived from ``TOOLS``."""
    if profile not in PROFILES:
        raise _invalid(profile)
    return frozenset(t.name for t in TOOLS if profile == "full" or t.core)


def group_availability(profile: str) -> tuple[list[str], list[str]]:
    """``(enabled, unavailable)`` groups for ``profile``, in ``GROUPS`` order:
    a group is enabled when the profile serves any of its tools and unavailable
    when it leaves any of them out."""
    served = profile_tool_names(profile)
    enabled = [g for g in GROUPS if any(t.group == g and t.name in served for t in TOOLS)]
    unavailable = [g for g in GROUPS if any(t.group == g and t.name not in served for t in TOOLS)]
    return enabled, unavailable


def unavailable_capability(name: str, profile: str | None = None) -> str | None:
    """The activation path for workflow ``name`` (tool or skill spelling) when
    ``profile`` (default: the configured one) leaves out the group it
    ``requires``; ``None`` when it can run."""
    meta = next((t for t in TOOLS if t.name == name.replace("-", "_")), None)
    if meta is None or meta.requires is None:
        return None
    profile = profile or resolve_profile()
    if meta.requires not in group_availability(profile)[1]:
        return None
    return (
        f"capability unavailable in {profile} profile\n"
        f"required group: {meta.requires}\n"
        f"activate: {ACTIVATION}\n"
        "Set it in the sumo-qa MCP server's env and restart the host. Tell the "
        "user this step needs it; do not substitute another tool or answer from memory."
    )
