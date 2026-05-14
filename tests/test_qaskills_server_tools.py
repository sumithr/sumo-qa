# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the qaskills / Node-install MCP tools.

Consent for installs is per-action (the suggesting skill asks `[y/N]`).
There is no global feature flag — these tools are always callable. The
tests verify subprocess plumbing, error envelopes, and that the install
tools land their effects in the right places.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from sumo_qa.server import build_mcp_server

_FIXTURES = Path(__file__).parent / "fixtures"


def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _get_tool(mcp, name: str):
    return mcp._tool_manager._tools[name].fn  # noqa: SLF001 — internal access in test


def test_search_tool_returns_raw_cleaned_text() -> None:
    fixture = (_FIXTURES / "qaskills_search_playwright.txt").read_text(encoding="utf-8")
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed(fixture)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_search_external_skills")(query="playwright")

    assert "output" in out
    assert "Playwright E2E Testing" in out["output"]
    assert "npx qaskills add playwright-e2e" in out["output"]
    # ANSI codes stripped before the LLM sees the text.
    assert "\x1b[" not in out["output"]


def test_info_tool_returns_raw_cleaned_text() -> None:
    fixture = (_FIXTURES / "qaskills_info_playwright_e2e.txt").read_text(encoding="utf-8")
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed(fixture)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_get_external_skill_info")(name="playwright-e2e")

    assert "output" in out
    assert "Quality Score: 92/100" in out["output"]
    assert "License: MIT" in out["output"]


def test_install_tool_surfaces_clean_error_when_node_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_install_external_skill")(name="playwright-e2e", scope="global")
    assert out["isError"] is True
    assert "Node" in out["error"]["actionable_hint"]


def test_install_tool_rejects_invalid_scope() -> None:
    mcp = build_mcp_server()
    out = _get_tool(mcp, "sumo_qa_install_external_skill")(name="x", scope="nowhere")
    assert out["isError"] is True
    assert "global" in out["error"]["actionable_hint"]


def test_check_installed_tool_returns_location(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skill_dir = tmp_path / ".claude" / "skills" / "axe-accessibility"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: axe-accessibility\n---\n", encoding="utf-8")

    mcp = build_mcp_server()
    out = _get_tool(mcp, "sumo_qa_check_external_skill_installed")(name="axe-accessibility")

    assert out["installed"] is True
    assert out["scope"] == "global"


def test_check_installed_tool_returns_false_when_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    mcp = build_mcp_server()
    out = _get_tool(mcp, "sumo_qa_check_external_skill_installed")(name="not-here")
    assert out["installed"] is False


def test_load_registry_tool_returns_publishers() -> None:
    mcp = build_mcp_server()
    out = _get_tool(mcp, "sumo_qa_load_external_skills_registry")()
    assert "trusted_publishers" in out
    assert "blocked_publishers" in out


def test_check_node_available_returns_true_when_npx_present() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_check_node_available")()
    assert out["available"] is True


def test_check_node_available_returns_false_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_check_node_available")()
    assert out["available"] is False


def test_detect_node_installer_returns_brew_on_darwin() -> None:
    with patch("sumo_qa.node_install.sys.platform", "darwin"), \
         patch("sumo_qa.node_install.shutil.which", side_effect=lambda cmd: "/opt/homebrew/bin/brew" if cmd == "brew" else None):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_detect_node_installer")()
    assert out["installer"] == "brew"
    assert out["command"] == ["brew", "install", "node"]
    assert out["needs_sudo"] is False


def test_detect_node_installer_returns_none_when_nothing_detected() -> None:
    with patch("sumo_qa.node_install.sys.platform", "haiku"), \
         patch("sumo_qa.node_install.shutil.which", return_value=None):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_detect_node_installer")()
    assert out["installer"] is None
    assert "no supported" in out["reason"].lower() or "no installer" in out["reason"].lower()


def test_install_node_runs_detected_installer() -> None:
    with patch("sumo_qa.node_install.sys.platform", "darwin"), \
         patch("sumo_qa.node_install.shutil.which", side_effect=lambda cmd: "/opt/homebrew/bin/brew" if cmd == "brew" else None), \
         patch("sumo_qa.node_install.subprocess.run", return_value=_completed(stdout="installed")):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_install_node")()
    assert out["installed"] is True


def test_install_node_returns_no_installer_when_none_detected() -> None:
    with patch("sumo_qa.node_install.sys.platform", "haiku"), \
         patch("sumo_qa.node_install.shutil.which", return_value=None):
        mcp = build_mcp_server()
        out = _get_tool(mcp, "sumo_qa_install_node")()
    assert out["installed"] is False
    assert "no installer" in out["reason"].lower() or "detected" in out["reason"].lower()
