# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from sumo_qa.server import build_mcp_server

# Phase 4 slimmed surface: 4 test-data tools + 6 knowledge loaders = 10 atomic tools.
# Phase 5 follow-up: each SKILL.md is also registered as an MCP tool
# (in addition to its MCP prompt) so hosts whose slash menus surface tools but
# not prompts (IntelliJ AI Assistant, VS Code + Copilot) can invoke skills.
# Chain-polish pass added 3 more skills (planning / executing / finishing).
# Task 8: sumo-qa-suggesting-external-skill added.
# External-skill lifecycle restored as thin MCP tools; Node installer helpers remain deleted.
# Task 72: sumo_qa_load_specialty_tools removed (catalogue → discovery rule).
# Total registered tools: 14 atomic + 14 skill = 28.
_TEST_DATA_TOOL_NAMES = {
    "sumo_qa_explain_test_data_requirements",
    "sumo_qa_find_test_data",
    "sumo_qa_validate_test_data",
    "sumo_qa_register_known_good_test_data",
}

_KNOWLEDGE_LOADER_TOOL_NAMES = {
    "sumo_qa_load_classifications",
    "sumo_qa_load_approaches",
    "sumo_qa_load_principles",
    "sumo_qa_load_techniques",
    "sumo_qa_load_standards",
    "sumo_qa_load_rules",
}

_EXTERNAL_SKILL_TOOL_NAMES = {
    "sumo_qa_search_external_skills",
    "sumo_qa_check_external_skill_installed",
    "sumo_qa_install_external_skill",
    "sumo_qa_execute_external_skill",
}

# Skills registered as MCP tools (parallel to their MCP-prompt registration).
# Names match the skill directory with `-` -> `_`.
_SKILL_TOOL_NAMES = {
    "using_sumo_qa",
    "sumo_qa_deciding_approach",
    "sumo_qa_preparing_for_work",
    "sumo_qa_creating_test_plan",
    "sumo_qa_implementing_with_tdd",
    "sumo_qa_reviewing_before_merge",
    "sumo_qa_strengthening_tests",
    "sumo_qa_finding_test_data",
    "sumo_qa_answering_testing_question",
    "sumo_qa_strategising",
    # Chain-polish pass: planning + executing + finishing skills.
    "sumo_qa_planning_qa_rollout",
    "sumo_qa_executing_qa_rollout",
    "sumo_qa_finishing_qa_work",
    # Task 8: external-skill suggestion.
    "sumo_qa_suggesting_external_skill",
}

# Heavy tools that MUST NOT be registered after Phase 4. The skills now drive
# this work via SKILL.md prompts + the knowledge_loader tools.
_HEAVY_TOOL_NAMES_DELETED = {
    "sumo_qa_prepare_for_work",
    "sumo_qa_review_local_change",
    "sumo_qa_answer_testing_question",
    "sumo_qa_create_test_plan",
    "sumo_qa_scaffold_tests",
    "sumo_qa_decide_approach",
    "sumo_qa_get_external_skill_info",
    "sumo_qa_load_external_skills_registry",
    "sumo_qa_check_node_available",
    "sumo_qa_detect_node_installer",
    "sumo_qa_install_node",
}


def test_builds_mcp_server_with_registered_tools() -> None:
    server = build_mcp_server()

    assert type(server).__name__ == "FastMCP"


def test_registers_only_test_data_knowledge_and_skill_tools() -> None:
    server = build_mcp_server()

    tool_names = set(server._tool_manager._tools.keys())

    assert tool_names == (
        _TEST_DATA_TOOL_NAMES
        | _KNOWLEDGE_LOADER_TOOL_NAMES
        | _EXTERNAL_SKILL_TOOL_NAMES
        | _SKILL_TOOL_NAMES
    )


def test_skills_registered_as_tools_only() -> None:
    """Each SKILL.md is registered as an MCP tool, NOT as a prompt.

    Single delivery channel rationale: MCP tools are surfaced in the
    slash menu by Claude Code, IntelliJ AI Assistant, and VS Code +
    Copilot — registering as tools alone gives identical slash-menu
    behavior across hosts. Registering as both creates duplicate
    entries in Claude Code and is the confusion this design avoids."""
    server = build_mcp_server()
    tool_names = set(server._tool_manager._tools.keys())
    prompt_names = set(server._prompt_manager._prompts.keys())

    assert _SKILL_TOOL_NAMES.issubset(tool_names), (
        f"Missing skill tools: {_SKILL_TOOL_NAMES - tool_names}"
    )
    assert _SKILL_TOOL_NAMES.isdisjoint(prompt_names), (
        f"Skill names leaked into prompts: {_SKILL_TOOL_NAMES & prompt_names}"
    )


def test_no_heavy_tools_leak_after_phase_4_deletion() -> None:
    """Defensive guard: the 6 heavy reasoning tools were deleted in Phase 4.
    If any of them re-appear in the registered surface a future change is
    accidentally re-introducing the heavy single-shot path."""
    server = build_mcp_server()
    tool_names = set(server._tool_manager._tools.keys())
    leaked = tool_names & _HEAVY_TOOL_NAMES_DELETED
    assert not leaked, f"Heavy tools leaked back into the registered surface: {leaked}"


def test_tool_descriptions_advertise_natural_language_triggers() -> None:
    server = build_mcp_server()
    tools = server._tool_manager._tools

    find_data = tools["sumo_qa_find_test_data"].description
    assert "find me test data" in find_data.lower()


def test_tool_descriptions_avoid_directive_language() -> None:
    """Tool descriptions must NOT contain instructions aimed at the model.

    Directive phrases like 'Use this when...' look like prompt-injection to
    defensive hosts (e.g. IntelliJ AI Assistant). Descriptions should be
    declarative ('Returns ...', 'Generates ...') with natural-language triggers
    framed as facts about the tool, not instructions to the caller.
    """
    server = build_mcp_server()
    forbidden_phrases = [
        "use this when",
        "use this before",
        "use this if",
        "you must",
        "you should",
        "ignore previous",
    ]
    for name, tool in server._tool_manager._tools.items():
        description = (tool.description or "").lower()
        for phrase in forbidden_phrases:
            assert phrase not in description, (
                f"tool {name!r} description contains directive phrase {phrase!r}; "
                "rewrite as a declarative description of what the tool returns."
            )


def test_knowledge_loader_tools_are_registered():
    """The 6 sumo_qa_load_* tools must appear in the server's tool list."""
    server = build_mcp_server()
    tool_names = set(server._tool_manager._tools.keys())
    for name in _KNOWLEDGE_LOADER_TOOL_NAMES:
        assert name in tool_names, f"Missing tool: {name}"


def _tool_text(result) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(getattr(item, "text", str(item)) for item in result)
    return getattr(result, "text", str(result))


def test_filtered_knowledge_loader_args_are_forwarded_via_server_call_tool() -> None:
    """The MCP-facing wrappers must pass classification filters through."""
    import asyncio

    server = build_mcp_server()

    async def run() -> tuple[str, str]:
        standards = await server.call_tool(
            "sumo_qa_load_standards",
            {"classification": "api_contract_change, business_logic_change"},
        )
        rules = await server.call_tool(
            "sumo_qa_load_rules", {"classification": "frontend_change config_change"}
        )
        return _tool_text(standards), _tool_text(rules)

    standards_text, rules_text = asyncio.run(run())

    assert "QA Shift-Left Core Standards" in standards_text
    assert "ISTQB-Aligned Senior QA Standards" not in standards_text
    assert "frontend_change:" in rules_text
    assert "config_change:" in rules_text
    assert "ui_only_change:" not in rules_text
    assert "configuration_change:" not in rules_text


# ---------------------------------------------------------------------------
# __main__ module import (covers sumo_qa/__main__.py:2)
# ---------------------------------------------------------------------------


def test_main_module_imports_without_error() -> None:
    """Importing sumo_qa.__main__ must not raise — it just wires main()."""
    import importlib

    mod = importlib.import_module("sumo_qa.__main__")
    assert hasattr(mod, "main")


# ---------------------------------------------------------------------------
# Tool bodies — call the registered MCP tools directly via the server so the
# nested function bodies inside build_mcp_server() are executed.
# ---------------------------------------------------------------------------


def test_tool_bodies_are_reachable_via_server_call_tool() -> None:
    """Calling each test-data tool via the server exercises the inner function
    bodies that are registered at build time but not called by structural tests."""
    import asyncio
    from pathlib import Path

    from sumo_qa.tdm_catalogue import TestDataCatalogue
    from sumo_qa.tools import QAShiftLeftService

    service = QAShiftLeftService(
        test_data_catalogue=TestDataCatalogue(
            Path(__file__).resolve().parent / "fixtures" / "test_data"
        )
    )
    server = build_mcp_server(service=service)

    async def run_tools() -> list:
        results = []
        # sumo_qa_explain_test_data_requirements (lines 125-138)
        r = await server.call_tool(
            "sumo_qa_explain_test_data_requirements", {"question": "what data for login?"}
        )
        results.append(r)
        # sumo_qa_find_test_data (lines 181-208)
        r = await server.call_tool(
            "sumo_qa_find_test_data", {"environment": "integration", "domain": "auth"}
        )
        results.append(r)
        # sumo_qa_validate_test_data (lines 225-237)
        r = await server.call_tool(
            "sumo_qa_validate_test_data", {"entry_id": "auth-locked-account-001"}
        )
        results.append(r)
        # sumo_qa_load_classifications (line 276)
        r = await server.call_tool("sumo_qa_load_classifications", {})
        results.append(r)
        # sumo_qa_load_approaches (line 282)
        r = await server.call_tool("sumo_qa_load_approaches", {})
        results.append(r)
        # sumo_qa_load_principles (line 288)
        r = await server.call_tool("sumo_qa_load_principles", {})
        results.append(r)
        # sumo_qa_load_techniques (line 295)
        r = await server.call_tool("sumo_qa_load_techniques", {})
        results.append(r)
        # sumo_qa_load_standards (line 312)
        r = await server.call_tool("sumo_qa_load_standards", {})
        results.append(r)
        # sumo_qa_load_rules (line 318)
        r = await server.call_tool("sumo_qa_load_rules", {})
        results.append(r)
        return results

    results = asyncio.run(run_tools())
    assert len(results) == 9


def test_tool_body_register_known_good_via_server(tmp_path) -> None:
    """sumo_qa_register_known_good_test_data body (lines 253-264)."""
    import asyncio

    from sumo_qa.tdm_catalogue import TestDataCatalogue
    from sumo_qa.tools import QAShiftLeftService

    service = QAShiftLeftService(test_data_catalogue=TestDataCatalogue(tmp_path / "test_data"))
    server = build_mcp_server(service=service)

    async def run():
        return await server.call_tool(
            "sumo_qa_register_known_good_test_data",
            {
                "entry": {
                    "id": "auth-server-test-001",
                    "environment": "integration",
                    "domain": "auth",
                    "scenario_tags": ["active_account"],
                    "known_valid_for": ["login flow"],
                    "owner": "qa",
                    "confidence": "medium",
                    "source": "qa-curated",
                }
            },
        )

    result = asyncio.run(run())
    assert result is not None


def test_tool_body_error_envelope_on_explain_failure() -> None:
    """Exception path in sumo_qa_explain_test_data_requirements body (line 128)."""
    import asyncio
    from unittest.mock import MagicMock

    async def run():
        # Build a server with a broken service to exercise the exception envelope path.
        broken_service = MagicMock()
        broken_service.qa_explain_test_data_requirements.side_effect = RuntimeError("broken")
        s = build_mcp_server(service=broken_service)
        return await s.call_tool("sumo_qa_explain_test_data_requirements", {"question": "x"})

    result = asyncio.run(run())
    assert result is not None


def test_tool_body_error_envelope_on_find_failure() -> None:
    """Exception path in sumo_qa_find_test_data body (line 193)."""
    import asyncio
    from unittest.mock import MagicMock

    broken_service = MagicMock()
    broken_service.qa_find_test_data.side_effect = RuntimeError("broken find")
    server = build_mcp_server(service=broken_service)

    async def run():
        return await server.call_tool("sumo_qa_find_test_data", {})

    result = asyncio.run(run())
    assert result is not None


def test_tool_body_error_envelope_on_validate_failure() -> None:
    """Exception path in sumo_qa_validate_test_data body (line 228)."""
    import asyncio
    from unittest.mock import MagicMock

    broken_service = MagicMock()
    broken_service.qa_validate_test_data.side_effect = RuntimeError("broken validate")
    server = build_mcp_server(service=broken_service)

    async def run():
        return await server.call_tool("sumo_qa_validate_test_data", {})

    result = asyncio.run(run())
    assert result is not None


def test_tool_body_error_envelope_on_register_failure() -> None:
    """Exception path in sumo_qa_register_known_good_test_data body (line 256)."""
    import asyncio
    from unittest.mock import MagicMock

    broken_service = MagicMock()
    broken_service.qa_register_known_good_test_data.side_effect = RuntimeError("broken register")
    server = build_mcp_server(service=broken_service)

    async def run():
        return await server.call_tool(
            "sumo_qa_register_known_good_test_data", {"entry": {"id": "x"}}
        )

    result = asyncio.run(run())
    assert result is not None


def test_main_function_runs_server() -> None:
    """server.main() calls build_mcp_server().run() — covers line 326."""
    from unittest.mock import MagicMock, patch

    mock_server = MagicMock()
    with patch("sumo_qa.server.build_mcp_server", return_value=mock_server):
        from sumo_qa.server import main

        main()

    mock_server.run.assert_called_once()


def test_build_mcp_server_raises_when_mcp_not_installed() -> None:
    """ImportError path in build_mcp_server() (lines 73-74)."""
    import sys
    from unittest.mock import patch

    with patch.dict(sys.modules, {"mcp.server.fastmcp": None, "mcp.types": None}):
        import pytest

        with pytest.raises((RuntimeError, ImportError)):
            build_mcp_server()
