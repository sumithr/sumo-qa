# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ExternalSkillError(RuntimeError):
    """Base error for external skill operations."""


class NodeNotFoundError(ExternalSkillError):
    """Raised when the Skills CLI cannot run because npx is unavailable."""


class ExternalSkillCLIError(ExternalSkillError):
    """Raised when the Skills CLI exits non-zero."""


class ExternalSkillInstallConfirmationRequired(ExternalSkillError):
    """Raised when install is requested without an explicit confirmation flag."""


@dataclass(frozen=True)
class InstalledSkill:
    name: str
    path: Path
    agent: str
    scope: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "path": self.path.as_posix(),
            "agent": self.agent,
            "scope": self.scope,
        }


_DEFAULT_SOURCE = "https://github.com/vercel-labs/skills"
_VALID_SCOPES = {"auto", "project", "global"}
_SKILL_ROOTS = (
    (".codex", "skills", "codex"),
    (".claude", "skills", "claude-code"),
    (".agents", "skills", "agents"),
)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_READ_RAW_OUTPUT_HINT = (
    "Read `raw_output` as the user would in a terminal — one candidate per line, "
    "typically in the form `<owner>/<repo>@<skill>`. Don't pin to a specific shape; "
    "the Skills CLI output may evolve."
)


def search_external_skills(query: str, timeout: int = 30) -> dict[str, Any]:
    """Search the Skills CLI registry and return the cleaned CLI output verbatim."""
    if not query.strip():
        raise ValueError("query is required")
    command, stdout, stderr = _run_skills_cli(["find", query], timeout=timeout)
    return {
        "query": query,
        "command": command,
        "raw_output": _strip_ansi(stdout),
        "stderr": _strip_ansi(stderr),
        "hint": _READ_RAW_OUTPUT_HINT,
    }


def install_external_skill(
    skill: str,
    source: str = _DEFAULT_SOURCE,
    scope: str = "project",
    agent: str = "codex",
    confirmed: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """Install a skill through the Skills CLI after explicit confirmation."""
    skill = skill.strip()
    source = source.strip()
    agent = agent.strip() or "codex"
    if not confirmed:
        raise ExternalSkillInstallConfirmationRequired(
            "external skill install requires confirmed=True"
        )
    if not skill:
        raise ValueError("skill is required")
    if not source:
        raise ValueError("source is required")
    if scope not in {"project", "global"}:
        raise ValueError("scope must be 'project' or 'global'")

    args = ["add", source, "--skill", skill, "-a", agent, "-y"]
    if scope == "global":
        args.append("-g")
    command, stdout, stderr = _run_skills_cli(args, timeout=timeout)
    installed = check_external_skill_installed(skill, scope=scope)
    return {
        "skill": skill,
        "source": source,
        "scope": scope,
        "agent": agent,
        "command": command,
        "installed": installed,
        "raw_output": _strip_ansi(stdout),
        "stderr": _strip_ansi(stderr),
    }


def check_external_skill_installed(
    skill: str,
    scope: str = "auto",
    cwd: Path | None = None,
    home: Path | None = None,
) -> dict[str, str] | None:
    """Return the installed SKILL.md path for a skill, if present."""
    skill = skill.strip()
    if not skill:
        raise ValueError("skill is required")
    if scope not in _VALID_SCOPES:
        raise ValueError("scope must be 'auto', 'project', or 'global'")
    for installed in _iter_installed_skill_candidates(skill, scope, cwd, home):
        if installed.path.is_file():
            return installed.as_dict()
    return None


def execute_external_skill(
    skill: str,
    intent: str = "",
    scope: str = "auto",
    cwd: Path | None = None,
    home: Path | None = None,
) -> dict[str, str]:
    """Load an installed skill body and return the execution handoff payload."""
    installed = check_external_skill_installed(skill, scope, cwd, home)
    if installed is None:
        raise ExternalSkillError(f"external skill is not installed: {skill}")
    path = Path(installed["path"])
    body = path.read_text(encoding="utf-8")
    return {
        "skill": installed["name"],
        "path": path.as_posix(),
        "agent": installed["agent"],
        "scope": installed["scope"],
        "intent": intent,
        "skill_body": body,
        "execution_prompt": (
            "Follow the loaded SKILL.md exactly for this intent. Preserve sumo-qa's "
            "confirmation discipline for dependency installs and file writes."
        ),
    }


def hint_for_exception(exc: BaseException) -> str:
    """Map an exception to a one-line actionable hint for the host LLM."""
    if isinstance(exc, ExternalSkillInstallConfirmationRequired):
        return (
            "Confirm the user approved the install in this conversation, then retry "
            "with confirmed=true."
        )
    if isinstance(exc, NodeNotFoundError):
        return "Install Node.js (https://nodejs.org) so npx is on PATH, then retry."
    if isinstance(exc, ExternalSkillCLIError):
        return (
            "Inspect the Skills CLI error above. Retry once from a networked "
            "environment if it looks transient; otherwise surface and stop."
        )
    if isinstance(exc, ValueError):
        return "Check the tool arguments — the error message names the rejected value."
    if isinstance(exc, ExternalSkillError):
        return (
            "Surface the error above. If the skill is missing, install it first via "
            "sumo_qa_install_external_skill."
        )
    return "Surface the error above and stop."


def _run_skills_cli(args: list[str], timeout: int) -> tuple[list[str], str, str]:
    npx = shutil.which("npx")
    if not npx:
        raise NodeNotFoundError("npx not found on PATH")
    command = [npx, "--yes", "skills", *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExternalSkillCLIError(f"skills CLI timed out after {timeout}s") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise ExternalSkillCLIError(message or f"skills CLI exited {completed.returncode}")
    return command, completed.stdout, completed.stderr


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def _iter_installed_skill_candidates(
    skill: str,
    scope: str,
    cwd: Path | None,
    home: Path | None,
):
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    names = _candidate_skill_names(skill)
    if scope in {"auto", "project"}:
        for root, agent in _roots(cwd):
            yield from _candidate_paths(names, root, agent, "project")
    if scope in {"auto", "global"}:
        for root, agent in _roots(home):
            yield from _candidate_paths(names, root, agent, "global")


def _roots(base: Path):
    for first, second, agent in _SKILL_ROOTS:
        yield base / first / second, agent


def _candidate_paths(names: set[str], root: Path, agent: str, scope: str):
    for name in sorted(names):
        yield InstalledSkill(name=name, path=root / name / "SKILL.md", agent=agent, scope=scope)


def _candidate_skill_names(skill: str) -> set[str]:
    return {
        skill,
        skill.replace("_", "-"),
        skill.replace("-", "_"),
    }
