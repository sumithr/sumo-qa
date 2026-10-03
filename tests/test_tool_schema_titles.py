# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The emitted tools/list must carry no auto-generated ``title`` keys.

Pydantic emits a Title-Cased echo of every field name ("Base Ref",
"Artifact Path") plus a ``<model>Arguments`` title per input model. Those
titles carry zero information for the host LLM — JSON-schema validators key
on ``properties``/``type``/``required``, not ``title`` — yet measured across
the full always-on tools/list they cost ~3.3k approx tokens, paid on EVERY
turn the server is connected. ``build_mcp_server`` strips them position-aware:
the annotation ``title`` on schema objects is removed, while title-named
properties/definitions and data (``default``/``const``/``enum``/``examples``)
are preserved. This test pins that no annotation title survives on the real
served input schemas (the surface ``tools/list`` returns); output schemas are
not served. It also pins that every served description is free of docstring
indentation, so tools/list is identical on every supported Python.
"""

from __future__ import annotations

import asyncio
import inspect

from sumo_qa.server import _slim_tool_schemas, _strip_schema_titles, build_mcp_server


def _count_annotation_titles(node: object) -> int:
    """Count ``title`` keys on every dict reached, independent of the stripper.

    Deliberately over-counts on unknown keywords so a future generator keyword
    carrying a title fails the served-list test. It does not descend into
    data-valued keywords, and for name-map keywords it skips the map's own keys
    (identifiers, e.g. a property called ``title``) and walks only the values.
    """
    if isinstance(node, list):
        return sum(_count_annotation_titles(v) for v in node)
    if not isinstance(node, dict):
        return 0
    total = int("title" in node)
    for key, value in node.items():
        if key in _DATA_KEYWORDS:
            continue
        if key in _NAME_MAP_KEYWORDS and isinstance(value, dict):
            total += sum(_count_annotation_titles(v) for v in value.values())
        else:
            total += _count_annotation_titles(value)
    return total


_DATA_KEYWORDS = {"default", "const", "enum", "examples", "discriminator"}
_NAME_MAP_KEYWORDS = {
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
    "dependencies",
    "dependentRequired",
}


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


def test_annotation_detector_counts_unknown_keywords() -> None:
    assert _count_annotation_titles({"x-vendor": {"title": "T"}}) == 1


def test_strip_dependencies_and_content_schema() -> None:
    schema = {
        "dependencies": {"title": {"title": "D", "type": "string"}, "a": ["b"]},
        "contentSchema": {"title": "C", "type": "object"},
    }
    assert _strip_schema_titles(schema) == {
        "dependencies": {"title": {"type": "string"}, "a": ["b"]},
        "contentSchema": {"type": "object"},
    }


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


def test_served_tool_descriptions_carry_no_docstring_indentation() -> None:
    # Python 3.13+ strips docstring indentation at compile time and earlier
    # versions keep it; a served description must already be cleandoc-clean.
    tools = asyncio.run(build_mcp_server().list_tools())
    indented = sorted(
        tool.name
        for tool in tools
        if tool.description and tool.description != inspect.cleandoc(tool.description)
    )
    assert not indented, f"tool descriptions still carry docstring indentation: {indented}"
