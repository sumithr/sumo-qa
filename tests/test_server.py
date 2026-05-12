from sumo_qa.server import build_mcp_server


# Phase 4 slimmed surface: 4 test-data tools + 7 knowledge loaders = 11 atomic tools.
# Phase 5 follow-up: each of the 10 SKILL.md files is also registered as an MCP
# tool (in addition to its MCP prompt) so hosts whose slash menus surface tools
# but not prompts (IntelliJ AI Assistant, VS Code + Copilot) can invoke skills.
# Total registered tools: 11 atomic + 10 skill = 21.
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
    "sumo_qa_load_specialty_tools",
    "sumo_qa_load_standards",
    "sumo_qa_load_rules",
}

# Skills registered as MCP tools (parallel to their MCP-prompt registration).
# Names match the skill directory with `-` -> `_`.
_SKILL_TOOL_NAMES = {
    "using_sumo_qa",
    "qa_deciding_approach",
    "qa_preparing_for_work",
    "qa_creating_test_plan",
    "qa_implementing_with_tdd",
    "qa_reviewing_before_merge",
    "qa_strengthening_tests",
    "qa_finding_test_data",
    "qa_answering_testing_question",
    "sumo_qa_strategising",
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
    """The 7 sumo_qa_load_* tools must appear in the server's tool list."""
    server = build_mcp_server()
    tool_names = set(server._tool_manager._tools.keys())
    for name in _KNOWLEDGE_LOADER_TOOL_NAMES:
        assert name in tool_names, f"Missing tool: {name}"
