from sumo_qa.server import build_mcp_server


def test_builds_mcp_server_with_registered_tools() -> None:
    server = build_mcp_server()

    assert type(server).__name__ == "FastMCP"


def test_registers_all_qa_tools() -> None:
    server = build_mcp_server()

    tool_names = set(server._tool_manager._tools.keys())

    assert tool_names == {
        "qa_prepare_for_work",
        "qa_review_local_change",
        "qa_answer_testing_question",
        "qa_create_test_plan",
        "qa_scaffold_tests",
        "qa_decide_approach",
        "qa_explain_test_data_requirements",
        "qa_find_test_data",
        "qa_validate_test_data",
        "qa_register_known_good_test_data",
    }


def test_registers_natural_language_prompts() -> None:
    server = build_mcp_server()

    prompt_names = set(server._prompt_manager._prompts.keys())

    assert prompt_names == {
        "qa_review_my_changes",
        "qa_plan_for_work",
        "qa_test_plan_for_work",
        "qa_scaffold_tests_for_work",
        "qa_what_approach",
        "qa_how_do_i_test",
        "qa_find_data",
        "qa_explain_data_needs",
        "qa_validate_data",
    }


def test_tool_descriptions_advertise_natural_language_triggers() -> None:
    server = build_mcp_server()
    tools = server._tool_manager._tools

    review = tools["qa_review_local_change"].description
    assert "review my changes" in review.lower()
    assert "is this safe to merge" in review.lower()

    answer = tools["qa_answer_testing_question"].description
    assert "how do i test" in answer.lower()

    prepare = tools["qa_prepare_for_work"].description
    assert "plan qa for this" in prepare.lower()

    find_data = tools["qa_find_test_data"].description
    assert "find me test data" in find_data.lower()


def test_prompt_bodies_do_not_instruct_the_model_to_call_tools() -> None:
    """MCP prompt bodies render as user messages.

    Phrases like 'Use the qa_X tool' inside a user message look like
    prompt-injection to defensive hosts (IntelliJ AI Assistant flagged ours).
    The model already knows what tools exist; the prompt body should read like
    something a real user would type.
    """
    import asyncio

    server = build_mcp_server()
    forbidden_substrings = [
        "use the qa_",
        "use the qa_prepare_for_work",
        "use the qa_review_local_change",
        "use the qa_answer_testing_question",
        "use the qa_find_test_data",
        "use the qa_validate_test_data",
        "use the qa_explain_test_data_requirements",
    ]

    async def collect_bodies() -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for name in server._prompt_manager._prompts:
            sample_args = {
                "qa_review_my_changes": {"scope": ""},
                "qa_plan_for_work": {"work_item": "x"},
                "qa_test_plan_for_work": {"work_item": "x", "scope_size": "medium"},
                "qa_scaffold_tests_for_work": {"work_item": "x", "target_path": ""},
                "qa_what_approach": {"intent": "x", "target_path": ""},
                "qa_how_do_i_test": {"thing": "x"},
                "qa_find_data": {"scenario": "x"},
                "qa_explain_data_needs": {"scenario": "x"},
                "qa_validate_data": {"entry_id_or_entry": "x"},
            }[name]
            rendered = await server.get_prompt(name, sample_args)
            for message in rendered.messages:
                text = getattr(message.content, "text", "") or ""
                results.append((name, text))
        return results

    bodies = asyncio.run(collect_bodies())
    for name, text in bodies:
        lowered = text.lower()
        for phrase in forbidden_substrings:
            assert phrase not in lowered, (
                f"prompt {name!r} body contains directive phrase {phrase!r}; "
                "rewrite as a plain user-style message without naming tools."
            )


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
