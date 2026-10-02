# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The tool registry is the single source of each tool's capability metadata;
the core/full profiles are derived from it (#806).

Techniques: equivalence partitioning over the profile config value (unset,
empty, each valid profile, unknown, a case/whitespace variant of a valid one),
and a cross-check of the registry against the live in-process registration and
the advertised workflow skills."""

from __future__ import annotations

import re

import pytest

from sumo_qa import server, skill_prompts
from sumo_qa.capabilities import _CORE_WORKFLOWS
from sumo_qa.tool_registry import (
    GROUPS,
    PROFILE_ENV,
    PROFILES,
    TOOLS,
    profile_tool_names,
    resolve_profile,
)

_BY_NAME = {t.name: t for t in TOOLS}


def _live_names(server_obj) -> list[str]:
    return [t.name for t in server_obj._tool_manager.list_tools()]


@pytest.fixture
def full_server(monkeypatch):
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    return server.build_mcp_server()


def test_exactly_core_and_full_are_public_profiles() -> None:
    assert PROFILES == ("core", "full")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "full"), ("", "full"), ("full", "full"), ("core", "core")],
)
def test_resolve_profile_valid_values(monkeypatch, value, expected) -> None:
    if value is None:
        monkeypatch.delenv(PROFILE_ENV, raising=False)
    else:
        monkeypatch.setenv(PROFILE_ENV, value)
    assert resolve_profile() == expected


@pytest.mark.parametrize("value", ["bogus", "CORE", " core", "minimal"])
def test_resolve_profile_rejects_unknown_values_without_coercion(monkeypatch, value) -> None:
    monkeypatch.setenv(PROFILE_ENV, value)
    with pytest.raises(ValueError) as exc:
        resolve_profile()
    message = str(exc.value)
    assert f"{PROFILE_ENV}={value!r}" in message
    assert "core, full" in message


def test_profile_tool_names_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="'bogus'"):
        profile_tool_names("bogus")


def test_registry_names_are_unique_and_groups_known() -> None:
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))
    assert {t.group for t in TOOLS} <= set(GROUPS)


def test_every_registered_tool_has_metadata_and_no_metadata_is_stale(full_server) -> None:
    assert set(_live_names(full_server)) == set(_BY_NAME)


def test_tool_registered_without_metadata_fails_the_build() -> None:
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("t")
    mcp.tool(name="sumo_qa_unlisted")(lambda: "x")
    with pytest.raises(ValueError, match="sumo_qa_unlisted"):
        server._apply_profile(mcp, "full")


def test_full_profile_is_every_registry_tool_and_core_is_a_strict_subset() -> None:
    full = profile_tool_names("full")
    core = profile_tool_names("core")
    assert full == set(_BY_NAME)
    assert core == {t.name for t in TOOLS if t.core}
    assert core < full


def test_external_and_open_world_tools_are_absent_from_core() -> None:
    core = profile_tool_names("core")
    external = {t.name for t in TOOLS if t.group == "external" or t.open_world}
    assert external, "registry marks no external/open-world tool"
    assert not core & external


def test_open_world_flag_matches_the_tool_annotation(full_server) -> None:
    for tool in full_server._tool_manager.list_tools():
        hint = bool(tool.annotations and tool.annotations.open_world_hint)
        assert _BY_NAME[tool.name].open_world is hint, tool.name


def test_core_build_registers_exactly_the_core_tools_in_full_order(
    monkeypatch, full_server
) -> None:
    monkeypatch.setenv(PROFILE_ENV, "core")
    core_names = _live_names(server.build_mcp_server())
    core = profile_tool_names("core")
    assert set(core_names) == core
    assert core_names == [n for n in _live_names(full_server) if n in core]


def test_unknown_profile_fails_the_build(monkeypatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "bogus")
    with pytest.raises(ValueError, match="'bogus'"):
        server.build_mcp_server()


def test_main_exits_with_a_clear_message_on_unknown_profile(monkeypatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "bogus")
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert str(exc.value) == (
        f"sumo-qa: {PROFILE_ENV}='bogus' is not a valid MCP tool profile; "
        "expected one of: core, full"
    )


def test_every_advertised_workflow_entry_is_core_unless_external() -> None:
    for _workflow, _prompt, skill, _outcome in _CORE_WORKFLOWS:
        meta = _BY_NAME[skill.replace("-", "_")]
        assert meta.core or meta.group == "external", skill


def test_core_skills_only_name_core_tools() -> None:
    """A core skill must not send the host to a tool the core profile lacks."""
    skills_dir = skill_prompts._skills_dir()
    core = profile_tool_names("core")
    for skill_dir in sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()):
        if skill_dir.name.replace("-", "_") not in core:
            continue
        text = "\n".join(p.read_text(encoding="utf-8") for p in skill_dir.rglob("*.md"))
        named = set(re.findall(r"\b(?:sumo_qa_[a-z_]+|using_sumo_qa)\b", text)) & set(_BY_NAME)
        assert named <= core, f"{skill_dir.name} names non-core tools: {sorted(named - core)}"
