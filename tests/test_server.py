from sumo_qa.server import build_mcp_server


def test_builds_mcp_server_with_registered_tools() -> None:
    server = build_mcp_server()

    assert type(server).__name__ == "FastMCP"


def test_registers_all_qa_tools() -> None:
    server = build_mcp_server()

    tool_names = set(server._tool_manager._tools.keys())

    assert tool_names == {
        "sumo_qa_prepare_for_work",
        "sumo_qa_review_local_change",
        "sumo_qa_answer_testing_question",
        "sumo_qa_create_test_plan",
        "sumo_qa_scaffold_tests",
        "sumo_qa_decide_approach",
        "sumo_qa_explain_test_data_requirements",
        "sumo_qa_find_test_data",
        "sumo_qa_validate_test_data",
        "sumo_qa_register_known_good_test_data",
    }


def test_registers_natural_language_prompts() -> None:
    server = build_mcp_server()

    prompt_names = set(server._prompt_manager._prompts.keys())

    assert prompt_names == {
        "sumo_qa_review_my_changes",
        "sumo_qa_plan_for_work",
        "sumo_qa_test_plan_for_work",
        "sumo_qa_scaffold_tests_for_work",
        "sumo_qa_what_approach",
        "sumo_qa_how_do_i_test",
        "sumo_qa_find_data",
        "sumo_qa_explain_data_needs",
        "sumo_qa_validate_data",
    }


def test_tool_descriptions_advertise_natural_language_triggers() -> None:
    server = build_mcp_server()
    tools = server._tool_manager._tools

    review = tools["sumo_qa_review_local_change"].description
    assert "review my changes" in review.lower()
    assert "is this safe to merge" in review.lower()

    answer = tools["sumo_qa_answer_testing_question"].description
    assert "how do i test" in answer.lower()

    prepare = tools["sumo_qa_prepare_for_work"].description
    assert "plan qa for this" in prepare.lower()

    find_data = tools["sumo_qa_find_test_data"].description
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
        "use the sumo_qa_",
        "use the sumo_qa_prepare_for_work",
        "use the sumo_qa_review_local_change",
        "use the sumo_qa_answer_testing_question",
        "use the sumo_qa_find_test_data",
        "use the sumo_qa_validate_test_data",
        "use the sumo_qa_explain_test_data_requirements",
    ]

    async def collect_bodies() -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for name in server._prompt_manager._prompts:
            sample_args = {
                "sumo_qa_review_my_changes": {"scope": ""},
                "sumo_qa_plan_for_work": {"work_item": "x"},
                "sumo_qa_test_plan_for_work": {"work_item": "x", "scope_size": "medium"},
                "sumo_qa_scaffold_tests_for_work": {"work_item": "x", "target_path": ""},
                "sumo_qa_what_approach": {"intent": "x", "target_path": ""},
                "sumo_qa_how_do_i_test": {"thing": "x"},
                "sumo_qa_find_data": {"scenario": "x"},
                "sumo_qa_explain_data_needs": {"scenario": "x"},
                "sumo_qa_validate_data": {"entry_id_or_entry": "x"},
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


def test_every_tool_advertises_an_output_schema() -> None:
    """MCP best practice: tools should advertise an `outputSchema` so hosts
    can render structured output without reverse-engineering it from a
    sample response.

    The schema is sourced from the canonical Pydantic response model in
    `sumo_qa.models` / `sumo_qa.tdm_models` and surfaced via FastMCP's
    Tool wrapper. The advertised shape may include fields the slimmed
    runtime payload omits — that's intentional; the schema describes the
    full vocabulary of what the tool can return.
    """
    server = build_mcp_server()
    tools = server._tool_manager._tools

    for name, tool in tools.items():
        schema = tool.output_schema
        assert schema is not None, f"tool {name!r} missing outputSchema"
        assert isinstance(schema, dict)
        assert "properties" in schema or "$ref" in schema or schema.get("type") == "object", (
            f"tool {name!r} outputSchema lacks an object-shaped declaration"
        )


def test_every_tool_output_schema_round_trips_through_list_tools() -> None:
    """`list_tools()` is what the MCP client actually sees over the wire.

    Confirm the wrapper-level outputSchema we set propagates to the
    protocol-level `Tool.outputSchema` field.
    """
    import asyncio

    server = build_mcp_server()
    listed = asyncio.run(server.list_tools())
    by_name = {t.name: t for t in listed}
    assert len(by_name) == 10
    for name, mcp_tool in by_name.items():
        assert mcp_tool.outputSchema is not None, (
            f"tool {name!r} did not surface outputSchema in list_tools()"
        )


def test_response_format_json_default_returns_dict() -> None:
    """Default response_format=json keeps the structured payload intact."""
    import asyncio

    server = build_mcp_server()
    fn = server._tool_manager._tools["sumo_qa_decide_approach"].fn
    result = asyncio.run(fn(intent_text="add a tiny helper", target_paths=[]))

    assert isinstance(result, dict)
    assert result.get("tool") == "sumo_qa_decide_approach"
    assert "recommended_approach" in result
    assert "format" not in result, "json default must not wrap in markdown envelope"


def test_response_format_markdown_returns_text() -> None:
    """response_format='markdown' wraps the response in a render-ready envelope."""
    import asyncio

    server = build_mcp_server()
    fn = server._tool_manager._tools["sumo_qa_decide_approach"].fn
    result = asyncio.run(
        fn(intent_text="add a tiny helper", target_paths=[], response_format="markdown")
    )

    assert isinstance(result, dict)
    assert result.get("format") == "markdown"
    assert isinstance(result.get("content"), str)
    assert result["content"].strip(), "markdown content must be non-empty"


def test_response_format_markdown_falls_back_for_unknown_tool_payloads() -> None:
    """For tools whose payload `render_response` doesn't know, the markdown
    branch falls back to a JSON code block instead of crashing."""
    server = build_mcp_server()
    # qa_find_test_data isn't covered by render_response; falls back.
    fn = server._tool_manager._tools["sumo_qa_find_test_data"].fn
    result = fn(environment="integration", domain="fulfilment", response_format="markdown")

    assert isinstance(result, dict)
    assert result.get("format") == "markdown"
    assert isinstance(result.get("content"), str)
    assert "```json" in result["content"], (
        "fallback rendering should embed the payload as a JSON code block"
    )


def test_every_tool_accepts_response_format_parameter() -> None:
    """Each tool's input schema declares the `response_format` parameter so
    hosts can advertise the rendering choice in their UI."""
    server = build_mcp_server()
    tools = server._tool_manager._tools
    for name, tool in tools.items():
        params = tool.parameters or {}
        properties = params.get("properties") or {}
        assert "response_format" in properties, (
            f"tool {name!r} does not advertise the response_format parameter"
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
