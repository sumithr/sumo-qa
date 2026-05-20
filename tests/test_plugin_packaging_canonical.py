# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for plugin_packaging.canonical.load — the single read path for pyproject.toml.

Covers:
  T1 — Reads name/version/description/license from [project]
  T2 — Reads author from [project.authors][0]
  T3 — Reads homepage/repository from [project.urls]
  T4 — Reads display_name and keywords from [tool.sumo-qa.plugin]
  T5 — Reads MCP spec from [tool.sumo-qa.plugin.mcp]
  T6 — Reads hooks list from [[tool.sumo-qa.plugin.hooks]]
  T7 — Missing overlay falls back to inferred defaults
  T8 — Missing required [project] field raises CanonicalLoadError
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugin_packaging import canonical


def _write_pyproject(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_reads_project_metadata(tmp_path: Path) -> None:
    """T1-T5 — Shared metadata flows from [project] / [project.urls] and overlay."""
    pyproj = _write_pyproject(
        tmp_path / "pyproject.toml",
        """\
[project]
name = "sumo-qa"
version = "9.9.9"
description = "Test description"
license = "Apache-2.0"
authors = [{ name = "Test Author", email = "a@b.test" }]

[project.urls]
Homepage = "https://example.test/home"
Repository = "https://example.test/repo"

[tool.sumo-qa.plugin]
display_name = "Sumo QA"
keywords = ["qa", "tdd"]

[tool.sumo-qa.plugin.mcp]
server_name = "sumo-qa"
command = "sumo-qa"
transport = "stdio"
args = []
""",
    )
    plugin = canonical.load(pyproj)
    assert plugin.name == "sumo-qa"
    assert plugin.version == "9.9.9"
    assert plugin.description == "Test description"
    assert plugin.license == "Apache-2.0"
    assert plugin.author == {"name": "Test Author", "email": "a@b.test"}
    assert plugin.homepage == "https://example.test/home"
    assert plugin.repository == "https://example.test/repo"
    assert plugin.display_name == "Sumo QA"
    assert plugin.keywords == ("qa", "tdd")
    assert plugin.mcp.server_name == "sumo-qa"
    assert plugin.mcp.command == "sumo-qa"
    assert plugin.mcp.transport == "stdio"
    assert plugin.mcp.args == ()


def test_reads_hook_overlay(tmp_path: Path) -> None:
    """T6 — Hooks declared in [[tool.sumo-qa.plugin.hooks]] are parsed."""
    pyproj = _write_pyproject(
        tmp_path / "pyproject.toml",
        """\
[project]
name = "sumo-qa"
version = "0.0.1"
description = "x"
license = "Apache-2.0"

[tool.sumo-qa.plugin]
display_name = "Sumo QA"

[tool.sumo-qa.plugin.mcp]
server_name = "sumo-qa"
command = "sumo-qa"

[[tool.sumo-qa.plugin.hooks]]
event = "SessionStart"
script = "session-start"
trigger = "startup|clear|compact"
""",
    )
    plugin = canonical.load(pyproj)
    assert len(plugin.hooks) == 1
    hook = plugin.hooks[0]
    assert hook.event == "SessionStart"
    assert hook.script == "session-start"
    assert hook.trigger == "startup|clear|compact"


def test_no_overlay_falls_back(tmp_path: Path) -> None:
    """T7 — Missing [tool.sumo-qa.plugin] header still loads with display_name=name."""
    pyproj = _write_pyproject(
        tmp_path / "pyproject.toml",
        """\
[project]
name = "sumo-qa"
version = "0.0.1"
description = "x"
license = "Apache-2.0"

[tool.sumo-qa.plugin.mcp]
server_name = "sumo-qa"
command = "sumo-qa"
""",
    )
    plugin = canonical.load(pyproj)
    assert plugin.display_name == "sumo-qa"
    assert plugin.keywords == ()
    assert plugin.hooks == ()


def test_missing_project_field_raises(tmp_path: Path) -> None:
    """T8 — Missing required [project] field raises with a clear message."""
    pyproj = _write_pyproject(
        tmp_path / "pyproject.toml",
        """\
[project]
name = "sumo-qa"
# version missing
description = "x"
license = "Apache-2.0"

[tool.sumo-qa.plugin.mcp]
server_name = "sumo-qa"
command = "sumo-qa"
""",
    )
    with pytest.raises(canonical.CanonicalLoadError, match="version"):
        canonical.load(pyproj)
