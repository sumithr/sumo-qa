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

from sumo_qa.server import build_mcp_server


def _count_titles(node: object) -> int:
    """Count ``title`` keys anywhere in a JSON-schema-shaped object."""
    if isinstance(node, dict):
        return sum(int(k == "title") + _count_titles(v) for k, v in node.items())
    if isinstance(node, list):
        return sum(_count_titles(v) for v in node)
    return 0


def test_served_tools_list_has_no_schema_titles() -> None:
    mcp = build_mcp_server()
    tools = asyncio.run(mcp.list_tools())
    assert tools, "expected a non-empty tools/list"

    offenders = {
        tool.name: (
            _count_titles(tool.inputSchema or {}),
            _count_titles(tool.outputSchema or {}),
        )
        for tool in tools
        if _count_titles(tool.inputSchema or {}) or _count_titles(tool.outputSchema or {})
    }
    assert not offenders, (
        f"{len(offenders)} tool(s) still emit auto-generated schema `title` "
        f"keys (name -> (input_titles, output_titles)): {offenders}"
    )


def test_served_tools_list_emits_no_output_schema() -> None:
    """No tool ships an ``outputSchema`` in the served ``tools/list``.

    FastMCP derives an ``outputSchema`` from each tool's return annotation —
    measured at ~18k approx tokens across this server, the single largest
    always-on surface. The host LLM reads the tool's text content, which is
    identical whether or not the schema is published (FastMCP computes the
    unstructured content unconditionally and only ADDS a ``structuredContent``
    block when a schema is present), so the schema is pure overhead.
    ``build_mcp_server`` drops it; this pins that it stays gone.
    """
    mcp = build_mcp_server()
    tools = asyncio.run(mcp.list_tools())
    assert tools, "expected a non-empty tools/list"

    with_output_schema = [tool.name for tool in tools if tool.outputSchema is not None]
    assert not with_output_schema, (
        f"{len(with_output_schema)} tool(s) still ship an outputSchema in "
        f"tools/list: {with_output_schema}"
    )
