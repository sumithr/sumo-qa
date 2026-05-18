# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sumo_qa import external_skills as ext
from sumo_qa import server as sumo_server


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["npx", "--yes", "skills"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_search_external_skills_strips_ansi_and_returns_raw_output(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _completed(
            stdout="\x1b[38;5;145mowner/repo@my-skill\x1b[0m  42 installs\n",
            stderr="\x1b[31mwarning: thing\x1b[0m\n",
        )

    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(ext.subprocess, "run", fake_run)

    result = ext.search_external_skills("python type checking")

    assert result["command"] == ["/bin/npx", "--yes", "skills", "find", "python type checking"]
    assert result["raw_output"] == "owner/repo@my-skill  42 installs\n"
    assert result["stderr"] == "warning: thing\n"
    assert "raw_output" in result["hint"]
    assert calls[0][1]["timeout"] == 30


def test_search_external_skills_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query is required"):
        ext.search_external_skills(" ")


def test_run_skills_cli_requires_npx(monkeypatch) -> None:
    monkeypatch.setattr(ext.shutil, "which", lambda name: None)

    with pytest.raises(ext.NodeNotFoundError, match="npx not found"):
        ext.search_external_skills("playwright")


def test_run_skills_cli_wraps_timeout(monkeypatch) -> None:
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ext.subprocess, "run", fake_run)

    with pytest.raises(ext.ExternalSkillCLIError, match="timed out"):
        ext.search_external_skills("playwright")


def test_run_skills_cli_wraps_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        ext.subprocess,
        "run",
        lambda *args, **kwargs: _completed(stderr="registry unavailable", returncode=1),
    )

    with pytest.raises(ext.ExternalSkillCLIError, match="registry unavailable"):
        ext.search_external_skills("playwright")


def test_run_skills_cli_falls_back_to_stdout_then_returncode(monkeypatch) -> None:
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        ext.subprocess,
        "run",
        lambda *args, **kwargs: _completed(stdout="stdout message", returncode=2),
    )
    with pytest.raises(ext.ExternalSkillCLIError, match="stdout message"):
        ext.search_external_skills("anything")

    monkeypatch.setattr(
        ext.subprocess,
        "run",
        lambda *args, **kwargs: _completed(returncode=3),
    )
    with pytest.raises(ext.ExternalSkillCLIError, match="skills CLI exited 3"):
        ext.search_external_skills("anything")


def test_install_external_skill_requires_confirmation() -> None:
    with pytest.raises(ext.ExternalSkillInstallConfirmationRequired):
        ext.install_external_skill(skill="find-skills", confirmed=False)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"skill": " ", "confirmed": True}, "skill is required"),
        ({"skill": "find-skills", "source": " ", "confirmed": True}, "source is required"),
        (
            {"skill": "find-skills", "scope": "team", "confirmed": True},
            "scope must be 'project' or 'global'",
        ),
    ],
)
def test_install_external_skill_validates_inputs(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        ext.install_external_skill(**kwargs)


def test_install_external_skill_runs_project_install(monkeypatch) -> None:
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return _completed(stdout="installed")

    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(ext.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ext,
        "check_external_skill_installed",
        lambda skill, scope: {"name": skill, "path": "/tmp/SKILL.md"},
    )

    result = ext.install_external_skill(
        skill="find-skills",
        source="vercel-labs/skills",
        scope="project",
        agent="codex",
        confirmed=True,
    )

    assert commands == [
        [
            "/bin/npx",
            "--yes",
            "skills",
            "add",
            "vercel-labs/skills",
            "--skill",
            "find-skills",
            "-a",
            "codex",
            "-y",
        ]
    ]
    assert result["installed"]["path"] == "/tmp/SKILL.md"


def test_install_external_skill_runs_global_install(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        ext.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or _completed(stdout="installed"),
    )
    monkeypatch.setattr(ext, "check_external_skill_installed", lambda skill, scope: None)

    result = ext.install_external_skill(skill="find-skills", scope="global", confirmed=True)

    assert commands[0][-1] == "-g"
    assert result["installed"] is None


def test_install_external_skill_defaults_agent_when_blank(monkeypatch) -> None:
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        ext.subprocess, "run", lambda *args, **kwargs: _completed(stdout="installed")
    )
    monkeypatch.setattr(ext, "check_external_skill_installed", lambda skill, scope: None)

    result = ext.install_external_skill(
        skill="find-skills", confirmed=True, agent="   ", scope="project"
    )
    assert result["agent"] == "codex"


def test_check_external_skill_installed_finds_project_and_global_paths(tmp_path: Path) -> None:
    project_skill = tmp_path / ".codex" / "skills" / "mypy-type-checking" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text("# Mypy skill", encoding="utf-8")
    home = tmp_path / "home"
    global_skill = home / ".claude" / "skills" / "find-skills" / "SKILL.md"
    global_skill.parent.mkdir(parents=True)
    global_skill.write_text("# Find skills", encoding="utf-8")

    project = ext.check_external_skill_installed("mypy_type_checking", cwd=tmp_path, home=home)
    global_result = ext.check_external_skill_installed(
        "find-skills", scope="global", cwd=tmp_path, home=home
    )

    assert project == {
        "name": "mypy-type-checking",
        "path": str(project_skill),
        "agent": "codex",
        "scope": "project",
    }
    assert global_result["path"] == str(global_skill)
    assert ext.check_external_skill_installed("missing", cwd=tmp_path, home=home) is None


@pytest.mark.parametrize(
    ("skill", "scope", "message"),
    [
        (" ", "auto", "skill is required"),
        ("find-skills", "workspace", "scope must be 'auto', 'project', or 'global'"),
    ],
)
def test_check_external_skill_installed_validates_inputs(skill, scope, message) -> None:
    with pytest.raises(ValueError, match=message):
        ext.check_external_skill_installed(skill, scope=scope)


def test_execute_external_skill_returns_handoff_payload(tmp_path: Path) -> None:
    skill_path = tmp_path / ".codex" / "skills" / "mypy-type-checking" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nname: mypy-type-checking\n---\n# Body", encoding="utf-8")

    result = ext.execute_external_skill(
        "mypy-type-checking",
        intent="add type checking",
        cwd=tmp_path,
        home=tmp_path / "home",
    )

    assert result["skill_body"].endswith("# Body")
    assert result["intent"] == "add type checking"
    assert "Follow the loaded SKILL.md" in result["execution_prompt"]


def test_execute_external_skill_requires_installed_skill(tmp_path: Path) -> None:
    with pytest.raises(ext.ExternalSkillError, match="not installed"):
        ext.execute_external_skill("missing", cwd=tmp_path, home=tmp_path / "home")


def test_installed_skill_as_dict_round_trip() -> None:
    installed = ext.InstalledSkill(
        name="x", path=Path("/tmp/SKILL.md"), agent="codex", scope="project"
    )
    assert installed.as_dict() == {
        "name": "x",
        "path": "/tmp/SKILL.md",
        "agent": "codex",
        "scope": "project",
    }


def test_strip_ansi_removes_color_and_cursor_sequences() -> None:
    text = "\x1b[38;5;145mname\x1b[0m\n\x1b[?25hcursor"
    assert ext._strip_ansi(text) == "name\ncursor"


@pytest.mark.parametrize(
    ("exception", "expected_keyword"),
    [
        (ext.ExternalSkillInstallConfirmationRequired("x"), "confirmed=true"),
        (ext.NodeNotFoundError("x"), "Node.js"),
        (ext.ExternalSkillCLIError("x"), "Skills CLI error"),
        (ValueError("x"), "tool arguments"),
        (ext.ExternalSkillError("x"), "install it first"),
        (RuntimeError("x"), "Surface the error"),
    ],
)
def test_hint_for_exception_routes_by_type(exception, expected_keyword) -> None:
    hint = ext.hint_for_exception(exception)
    assert expected_keyword in hint


def _invoke_tool(mcp, name: str, **kwargs):
    return mcp._tool_manager._tools[name].fn(**kwargs)


def test_external_skill_server_tools_success(monkeypatch) -> None:
    monkeypatch.setattr(sumo_server, "_search_external_skills", lambda query: {"query": query})
    monkeypatch.setattr(
        sumo_server,
        "_check_external_skill_installed",
        lambda skill, scope="auto": {"name": skill, "scope": scope},
    )
    monkeypatch.setattr(
        sumo_server,
        "_install_external_skill",
        lambda **kwargs: {"skill": kwargs["skill"], "confirmed": kwargs["confirmed"]},
    )
    monkeypatch.setattr(
        sumo_server,
        "_execute_external_skill",
        lambda **kwargs: {"skill": kwargs["skill"], "intent": kwargs["intent"]},
    )
    mcp = sumo_server.build_mcp_server()

    assert _invoke_tool(mcp, "sumo_qa_search_external_skills", query="mypy")["query"] == "mypy"
    assert (
        _invoke_tool(mcp, "sumo_qa_check_external_skill_installed", skill="mypy")["name"] == "mypy"
    )
    assert (
        _invoke_tool(mcp, "sumo_qa_install_external_skill", skill="mypy", confirmed=True)[
            "confirmed"
        ]
        is True
    )
    assert (
        _invoke_tool(mcp, "sumo_qa_execute_external_skill", skill="mypy", intent="check")["intent"]
        == "check"
    )


def test_external_skill_server_tools_route_hint_by_exception_type(monkeypatch) -> None:
    monkeypatch.setattr(
        sumo_server,
        "_search_external_skills",
        lambda query: (_ for _ in ()).throw(ext.NodeNotFoundError("npx missing")),
    )
    monkeypatch.setattr(
        sumo_server,
        "_check_external_skill_installed",
        lambda skill, scope="auto": (_ for _ in ()).throw(ValueError("bad scope")),
    )
    monkeypatch.setattr(
        sumo_server,
        "_install_external_skill",
        lambda **kwargs: (_ for _ in ()).throw(
            ext.ExternalSkillInstallConfirmationRequired("nope")
        ),
    )
    monkeypatch.setattr(
        sumo_server,
        "_execute_external_skill",
        lambda **kwargs: (_ for _ in ()).throw(ext.ExternalSkillError("not installed")),
    )
    mcp = sumo_server.build_mcp_server()

    search = _invoke_tool(mcp, "sumo_qa_search_external_skills", query="mypy")
    check = _invoke_tool(mcp, "sumo_qa_check_external_skill_installed", skill="mypy")
    install = _invoke_tool(mcp, "sumo_qa_install_external_skill", skill="mypy")
    execute = _invoke_tool(mcp, "sumo_qa_execute_external_skill", skill="mypy")

    assert "Node.js" in search["error"]["actionable_hint"]
    assert "tool arguments" in check["error"]["actionable_hint"]
    assert "confirmed=true" in install["error"]["actionable_hint"]
    assert "install it first" in execute["error"]["actionable_hint"]


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not installed")
def test_search_external_skills_real_cli_smoke() -> None:
    """End-to-end smoke against the real Skills CLI.

    Asserts only on shape contracts the MCP guarantees — keys present,
    raw_output is non-empty text, ANSI stripped. Does NOT assert on the CLI's
    specific output format (the whole point of dropping the parser is so format
    drift in the upstream CLI does not break this flow).
    """
    result = ext.search_external_skills("mypy")
    assert set(result) >= {"query", "command", "raw_output", "stderr", "hint"}
    assert isinstance(result["raw_output"], str) and result["raw_output"]
    assert "\x1b" not in result["raw_output"]
    assert "\x1b" not in result["stderr"]
