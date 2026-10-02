# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The emitted tools/list must carry no auto-generated ``title`` keys.

Pydantic emits a Title-Cased echo of every field name ("Base Ref",
"Artifact Path") plus a ``<model>Arguments`` title per input model. Those
titles carry zero information for the host LLM — JSON-schema validators key
on ``properties``/``type``/``required``, not ``title`` — yet measured across
the full always-on tools/list they cost ~3.3k approx tokens, paid on EVERY
turn the server is connected. ``build_mcp_server`` strips them; this test
pins that they stay gone for BOTH input and output schemas on the real
served ``MCPTool`` payload (the same surface ``tools/list`` returns).
"""

from __future__ import annotations

import asyncio

from sumo_qa.server import _slim_tool_schemas, _strip_schema_titles, build_mcp_server

# JSON Schema keywords whose value is a name -> schema map: the keys are
# identifiers (a property literally called ``title`` is legitimate), the values
# are schemas. Every other keyword holding a schema is listed in _SCHEMA_VALUED.
_NAME_MAPS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
_SCHEMA_VALUED = (
    "items",
    "prefixItems",
    "additionalItems",
    "additionalProperties",
    "unevaluatedItems",
    "unevaluatedProperties",
    "contains",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
    "allOf",
    "anyOf",
    "oneOf",
)


def _count_annotation_titles(schema: object) -> int:
    """Count ``title`` annotations by schema position.

    A ``title`` key is an annotation only when it sits on a schema object. A
    ``title`` that is a property / definition name, or a key inside
    ``default`` / ``const`` / ``enum`` / ``examples`` data, is not counted.
    """
    if isinstance(schema, list):
        return sum(_count_annotation_titles(s) for s in schema)
    if not isinstance(schema, dict):
        return 0
    total = int("title" in schema)
    for key, value in schema.items():
        if key in _NAME_MAPS and isinstance(value, dict):
            total += sum(_count_annotation_titles(s) for s in value.values())
        elif key in _SCHEMA_VALUED:
            total += _count_annotation_titles(value)
    return total


def test_served_tools_list_has_no_schema_titles() -> None:
    mcp = build_mcp_server()
    tools = asyncio.run(mcp.list_tools())
    assert tools, "expected a non-empty tools/list"

    offenders = {
        tool.name: (
            _count_annotation_titles(tool.input_schema or {}),
            _count_annotation_titles(tool.output_schema or {}),
        )
        for tool in tools
        if _count_annotation_titles(tool.input_schema or {})
        or _count_annotation_titles(tool.output_schema or {})
    }
    assert not offenders, (
        f"{len(offenders)} tool(s) still emit auto-generated schema `title` "
        f"keys (name -> (input_titles, output_titles)): {offenders}"
    )


def test_annotation_detector_ignores_title_named_identifiers() -> None:
    assert _count_annotation_titles({"properties": {"title": {"type": "string"}}}) == 0
    assert _count_annotation_titles({"properties": {"title": {"title": "Title"}}}) == 1
    assert _count_annotation_titles({"default": {"title": "x"}, "type": "object"}) == 0


def test_strip_minimum_discriminating_schema() -> None:
    schema = {
        "title": "ExampleArguments",
        "type": "object",
        "properties": {"title": {"title": "Title", "type": "string"}},
        "required": ["title"],
    }
    assert _strip_schema_titles(schema) == {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }


def test_strip_nested_model_property_named_title() -> None:
    schema = {
        "title": "Outer",
        "type": "object",
        "properties": {
            "item": {
                "title": "Item",
                "type": "object",
                "properties": {"title": {"title": "Title", "type": "string"}},
                "required": ["title"],
            },
            "items": {
                "title": "Items",
                "type": "array",
                "items": {"title": "Row", "properties": {"title": {"title": "T"}}},
            },
            "either": {"anyOf": [{"title": "A", "properties": {"title": {"type": "string"}}}]},
        },
    }
    assert _strip_schema_titles(schema) == {
        "type": "object",
        "properties": {
            "item": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
            "items": {
                "type": "array",
                "items": {"properties": {"title": {}}},
            },
            "either": {"anyOf": [{"properties": {"title": {"type": "string"}}}]},
        },
    }


def test_strip_keeps_title_named_definitions_and_patterns() -> None:
    schema = {
        "$defs": {"title": {"title": "Title", "type": "string"}},
        "definitions": {"title": {"title": "Legacy", "type": "integer"}},
        "patternProperties": {"title": {"title": "P", "type": "string"}},
        "properties": {"ref": {"$ref": "#/$defs/title"}},
    }
    assert _strip_schema_titles(schema) == {
        "$defs": {"title": {"type": "string"}},
        "definitions": {"title": {"type": "integer"}},
        "patternProperties": {"title": {"type": "string"}},
        "properties": {"ref": {"$ref": "#/$defs/title"}},
    }


def test_strip_leaves_user_data_untouched() -> None:
    schema = {
        "type": "object",
        "properties": {
            "doc": {
                "title": "Doc",
                "type": "object",
                "default": {"title": "My default", "nested": {"title": "x"}},
                "const": {"title": "c"},
                "enum": [{"title": "e"}],
                "examples": [{"title": "ex"}],
            }
        },
    }
    data = {k: v for k, v in schema["properties"]["doc"].items() if k != "title"}
    assert _strip_schema_titles(schema) == {"type": "object", "properties": {"doc": data}}


def test_served_tool_with_title_argument_survives_slimming() -> None:
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("t")

    @mcp.tool()
    def add_note(title: str, body: str = "") -> str:
        return title + body

    _slim_tool_schemas(mcp)
    (tool,) = asyncio.run(mcp.list_tools())
    schema = tool.input_schema
    assert set(schema["properties"]) == {"title", "body"}
    assert schema["required"] == ["title"]
    assert _count_annotation_titles(schema) == 0
    assert "title" not in schema["properties"]["title"]
    assert "title" not in schema


def test_served_tools_list_emits_no_output_schema() -> None:
    """No tool ships an ``outputSchema`` in the served ``tools/list``.

    MCPServer derives an ``outputSchema`` from each tool's return annotation —
    measured at ~18k approx tokens across this server, the single largest
    always-on surface. The host LLM reads the tool's text content, which is
    identical whether or not the schema is published (MCPServer computes the
    unstructured content unconditionally and only ADDS a ``structuredContent``
    block when a schema is present), so the schema is pure overhead.
    ``build_mcp_server`` drops it; this pins that it stays gone.
    """
    mcp = build_mcp_server()
    tools = asyncio.run(mcp.list_tools())
    assert tools, "expected a non-empty tools/list"

    with_output_schema = [tool.name for tool in tools if tool.output_schema is not None]
    assert not with_output_schema, (
        f"{len(with_output_schema)} tool(s) still ship an outputSchema in "
        f"tools/list: {with_output_schema}"
    )
