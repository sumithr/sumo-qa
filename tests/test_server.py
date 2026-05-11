from sumo_qa.server import build_mcp_server


# Phase 4 slimmed surface: 4 test-data tools + 7 knowledge loaders = 11 tools.
# The 6 heavy QA reasoning tools have been removed; that work is now driven
# by the host LLM via skill prompts and knowledge loaders.
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


def test_registers_only_test_data_and_knowledge_loader_tools() -> None:
    server = build_mcp_server()

    tool_names = set(server._tool_manager._tools.keys())

    assert tool_names == _TEST_DATA_TOOL_NAMES | _KNOWLEDGE_LOADER_TOOL_NAMES


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
