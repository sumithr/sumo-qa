# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Canonical loader for sumo-qa plugin packaging.

Reads `pyproject.toml` once and returns an immutable `CanonicalPlugin`
object that every per-host template consumes. This is the only file in
the codebase that knows how `pyproject.toml` is structured.

Shared metadata (name, version, description, license, author, urls)
flows from `[project]` and `[project.urls]`. Plugin-specific overlay
lives under `[tool.sumo-qa.plugin]`. No field is duplicated.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path; covered by py3.10 CI matrix
    import tomli as tomllib


class CanonicalLoadError(ValueError):
    """Raised when `pyproject.toml` is missing a field the plugin needs."""


@dataclass(frozen=True)
class McpSpec:
    server_name: str
    command: str
    transport: str = "stdio"
    args: tuple[str, ...] = ()
    # Optional environment variables the host should set when spawning the
    # MCP server. Anthropic's Python-stdio MCP best practices recommend
    # PYTHONUNBUFFERED=1 so JSON-RPC responses aren't held in a Python
    # stdout buffer; round-tripped from [tool.sumo-qa.plugin.mcp.env].
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HookSpec:
    event: str
    script: str
    trigger: str = ""


@dataclass(frozen=True)
class CanonicalPlugin:
    name: str
    version: str
    description: str
    license: str
    author: dict
    homepage: str
    repository: str
    display_name: str
    keywords: tuple[str, ...]
    mcp: McpSpec
    hooks: tuple[HookSpec, ...]
    # Marketplace copy (issue #84). Optional so older overlays still load;
    # short_description is capped at 200 chars — the common marketplace
    # short-copy limit — and enforced in load().
    short_description: str = ""
    long_description: str = ""
    category: str = ""


_SHORT_DESCRIPTION_MAX = 200


def _require(data: dict, dotted_path: str) -> object:
    cursor: object = data
    for segment in dotted_path.split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            raise CanonicalLoadError(f"pyproject.toml missing required field: {dotted_path}")
        cursor = cursor[segment]
    return cursor


def load(pyproject_path: Path) -> CanonicalPlugin:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    name = str(_require(data, "project.name"))
    version = str(_require(data, "project.version"))
    description = str(_require(data, "project.description"))
    license_ = str(_require(data, "project.license"))

    authors = data.get("project", {}).get("authors") or []
    author = dict(authors[0]) if authors else {}

    urls = data.get("project", {}).get("urls") or {}
    homepage = str(urls.get("Homepage", ""))
    repository = str(urls.get("Repository", ""))

    overlay = data.get("tool", {}).get("sumo-qa", {}).get("plugin", {})
    display_name = str(overlay.get("display_name", name))
    keywords = tuple(overlay.get("keywords", ()))
    short_description = str(overlay.get("short_description", ""))
    long_description = str(overlay.get("long_description", ""))
    category = str(overlay.get("category", ""))
    if len(short_description) > _SHORT_DESCRIPTION_MAX:
        raise CanonicalLoadError(
            f"[tool.sumo-qa.plugin].short_description must be <= "
            f"{_SHORT_DESCRIPTION_MAX} characters, got {len(short_description)}"
        )

    mcp_raw = _require(data, "tool.sumo-qa.plugin.mcp")
    if not isinstance(mcp_raw, dict):
        raise CanonicalLoadError("[tool.sumo-qa.plugin.mcp] must be a table")
    env_raw = mcp_raw.get("env") or {}
    if not isinstance(env_raw, dict):
        raise CanonicalLoadError("[tool.sumo-qa.plugin.mcp.env] must be a table")
    mcp = McpSpec(
        server_name=str(_require({"mcp": mcp_raw}, "mcp.server_name")),
        command=str(_require({"mcp": mcp_raw}, "mcp.command")),
        transport=str(mcp_raw.get("transport", "stdio")),
        args=tuple(str(a) for a in mcp_raw.get("args", ())),
        env={str(k): str(v) for k, v in env_raw.items()},
    )

    hooks_raw = overlay.get("hooks", ()) or ()
    hooks = tuple(
        HookSpec(
            event=str(_require({"h": h}, "h.event")),
            script=str(_require({"h": h}, "h.script")),
            trigger=str(h.get("trigger", "")),
        )
        for h in hooks_raw
    )

    return CanonicalPlugin(
        name=name,
        version=version,
        description=description,
        license=license_,
        author=author,
        homepage=homepage,
        repository=repository,
        display_name=display_name,
        keywords=keywords,
        mcp=mcp,
        hooks=hooks,
        short_description=short_description,
        long_description=long_description,
        category=category,
    )
