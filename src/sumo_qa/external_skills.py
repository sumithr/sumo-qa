# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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


class SkillsCLIVersionError(ExternalSkillCLIError):
    """Raised when the Skills CLI pin is not exact or the CLI reports another version."""


class GitNotFoundError(ExternalSkillError):
    """Raised when git is unavailable to resolve an install source to a commit."""


class SourceResolutionError(ExternalSkillError):
    """Raised when an install source ref cannot be resolved to a commit."""


class ExternalSkillProvenanceError(ExternalSkillError):
    """Raised when an installed skill's provenance cannot be recorded or verified."""


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


# The Skills CLI every subprocess runs. An exact version only: npx would
# otherwise resolve whatever the registry serves as newest. Moving the pin is
# a reviewed dependency change (docs/DEVELOPMENT.md, "Skills CLI pin").
SKILLS_CLI_PACKAGE = "skills"
SKILLS_CLI_VERSION = "1.7.0"
_EXACT_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
# npx paths whose CLI already reported the pinned version this process.
_VERIFIED_CLI_PATHS: set[str] = set()

_DEFAULT_SOURCE = "https://github.com/vercel-labs/skills"
_REMOTE_SOURCE_PREFIXES = ("https://", "ssh://", "git@", "file://")
_GITHUB_SHORTHAND_RE = re.compile(r"[A-Za-z0-9][\w.-]*/[\w.-]+")
_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_LOCK_RELPATH = Path(".sumo-qa") / "external-skills.lock.json"
_LOCK_SCHEMA_VERSION = 1
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
        "cli": skills_cli_identity(),
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
    cwd: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Install a skill through the pinned Skills CLI after explicit confirmation.

    The source is resolved to a commit first and the CLI installs exactly that
    commit; the installed folder's digest is then recorded in the scope's
    provenance lock so ``execute_external_skill`` can verify it later.
    """
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

    source_base, remote_url, requested_ref = _parse_source(source)
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    lock_base = cwd if scope == "project" else home
    lock = _read_lock(lock_base)
    resolved_ref = _resolve_commit(remote_url, requested_ref, timeout)

    args = ["add", f"{source_base}#{resolved_ref}", "--skill", skill, "-a", agent, "-y"]
    if scope == "global":
        args.append("-g")
    command, stdout, stderr = _run_skills_cli(args, timeout=timeout, cwd=cwd)
    installed = check_external_skill_installed(skill, scope=scope, cwd=cwd, home=home)
    if installed is None:
        raise ExternalSkillProvenanceError(
            f"installed skill {skill!r} not found in the {scope} skill folders; "
            "provenance was not recorded"
        )
    folder = Path(installed["path"]).parent
    key = folder.relative_to(lock_base).as_posix()
    provenance = {
        "skill": skill,
        "source": source_base,
        "requested_ref": requested_ref,
        "resolved_ref": resolved_ref,
        "content_digest": skill_content_digest(folder),
        "agent": agent,
        "scope": scope,
        "path": key,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "installer": skills_cli_identity(),
    }
    lock["skills"][key] = provenance
    _write_lock(lock_base, lock)
    return {
        "skill": skill,
        "source": source,
        "scope": scope,
        "agent": agent,
        "cli": skills_cli_identity(),
        "command": command,
        "installed": installed,
        "provenance": provenance,
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
) -> dict[str, Any]:
    """Load an installed skill body and return the execution handoff payload.

    A skill recorded at install time must still match its recorded commit and
    content digest, or execution is blocked. A skill with no record (installed
    outside sumo-qa) is reported as ``unrecorded``.
    """
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    installed = check_external_skill_installed(skill, scope, cwd, home)
    if installed is None:
        raise ExternalSkillError(f"external skill is not installed: {skill}")
    path = Path(installed["path"])
    provenance = _verify_provenance(path.parent, cwd if installed["scope"] == "project" else home)
    body = path.read_text(encoding="utf-8")
    return {
        "skill": installed["name"],
        "path": path.as_posix(),
        "agent": installed["agent"],
        "scope": installed["scope"],
        "intent": intent,
        "provenance": provenance,
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
    if isinstance(exc, SkillsCLIVersionError):
        return (
            f"The Skills CLI did not match the pinned {_cli_spec()}. Check for an npx "
            "shim or npm config overriding the package; never retry with an unpinned "
            "CLI. Moving the pin is a reviewed change to SKILLS_CLI_VERSION."
        )
    if isinstance(exc, NodeNotFoundError):
        return "Install Node.js (https://nodejs.org) so npx is on PATH, then retry."
    if isinstance(exc, ExternalSkillCLIError):
        return (
            "Inspect the Skills CLI error above. Retry once from a networked "
            "environment if it looks transient; otherwise surface and stop."
        )
    if isinstance(exc, GitNotFoundError):
        return (
            "Install git (https://git-scm.com) so the install source can be resolved "
            "to a commit, then retry."
        )
    if isinstance(exc, SourceResolutionError):
        return (
            "Check network access and that the source URL and #ref exist. A full "
            "40-character commit SHA as #ref skips remote resolution."
        )
    if isinstance(exc, ExternalSkillProvenanceError):
        return (
            "Do not execute this skill: its installed content or provenance record "
            "does not match. Reinstall it via sumo_qa_install_external_skill once "
            "the user confirms."
        )
    if isinstance(exc, ValueError):
        return "Check the tool arguments — the error message names the rejected value."
    if isinstance(exc, ExternalSkillError):
        return (
            "Surface the error above. If the skill is missing, install it first via "
            "sumo_qa_install_external_skill."
        )
    return "Surface the error above and stop."


def skills_cli_identity() -> dict[str, str]:
    """The exact Skills CLI package every subprocess runs."""
    return {
        "package": SKILLS_CLI_PACKAGE,
        "version": SKILLS_CLI_VERSION,
        "spec": _cli_spec(),
    }


def build_skills_cli_command(npx: str, args: Sequence[str]) -> list[str]:
    """Build the argv for one pinned Skills CLI call; the only place argv is built."""
    if not _EXACT_VERSION_RE.fullmatch(SKILLS_CLI_VERSION):
        raise SkillsCLIVersionError(
            f"Skills CLI pin {SKILLS_CLI_VERSION!r} is not an exact version; "
            "refusing to let npx resolve a floating one"
        )
    return [npx, "--yes", _cli_spec(), *args]


def skill_content_digest(folder: Path) -> str:
    """SHA-256 over every file path and file content under an installed skill."""
    root = Path(folder)
    entries: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        for name in dirnames:
            path = current / name
            # os.walk does not descend into a symlinked folder; record its
            # target so retargeting it changes the digest.
            target = os.readlink(path) if path.is_symlink() else ""
            entries.append((path.relative_to(root).as_posix() + "/", target))
        for name in filenames:
            path = current / name
            content = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append((path.relative_to(root).as_posix(), content))
    digest = hashlib.sha256()
    for relpath, value in sorted(entries):
        digest.update(f"{relpath}\0{value}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def _cli_spec() -> str:
    return f"{SKILLS_CLI_PACKAGE}@{SKILLS_CLI_VERSION}"


def _run_skills_cli(
    args: list[str], timeout: int, cwd: Path | None = None
) -> tuple[list[str], str, str]:
    npx = shutil.which("npx")
    if not npx:
        raise NodeNotFoundError("npx not found on PATH")
    _ensure_pinned_cli(npx, timeout)
    command = build_skills_cli_command(npx, args)
    stdout, stderr = _run_cli_process(command, timeout, cwd)
    return command, stdout, stderr


def _ensure_pinned_cli(npx: str, timeout: int) -> None:
    probe_key = f"{npx}|{_cli_spec()}"
    if probe_key in _VERIFIED_CLI_PATHS:
        return
    stdout, _ = _run_cli_process(build_skills_cli_command(npx, ["--version"]), timeout, None)
    reported = stdout.strip()
    if reported != SKILLS_CLI_VERSION:
        raise SkillsCLIVersionError(
            f"expected {_cli_spec()} but the Skills CLI reported {reported or 'no version'}"
        )
    _VERIFIED_CLI_PATHS.add(probe_key)


def _run_cli_process(command: list[str], timeout: int, cwd: Path | None) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExternalSkillCLIError(f"skills CLI timed out after {timeout}s") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise ExternalSkillCLIError(message or f"skills CLI exited {completed.returncode}")
    return completed.stdout, completed.stderr


def _parse_source(source: str) -> tuple[str, str, str | None]:
    """Split an install source into (CLI source, git remote URL, requested ref)."""
    base, has_ref, ref = source.partition("#")
    if has_ref and not ref:
        raise ValueError("source ref after '#' is empty")
    if "/tree/" in base or "/blob/" in base:
        raise ValueError("source must be a repository URL; pass a folder's ref as '#<ref>'")
    if base.startswith(_REMOTE_SOURCE_PREFIXES):
        return base, base, ref or None
    if _GITHUB_SHORTHAND_RE.fullmatch(base):
        return base, f"https://github.com/{base}.git", ref or None
    raise ValueError(
        "source must be a git URL (https://, ssh://, git@, file://) or owner/repo "
        "shorthand so the install can be pinned to a commit"
    )


def _resolve_commit(remote_url: str, ref: str | None, timeout: int) -> str:
    """Resolve a ref (default HEAD) to the full commit SHA it points at now."""
    if ref and _COMMIT_SHA_RE.fullmatch(ref.lower()):
        return ref.lower()
    git = shutil.which("git")
    if not git:
        raise GitNotFoundError("git not found on PATH")
    wanted = ref or "HEAD"
    try:
        completed = subprocess.run(
            [git, "ls-remote", "--", remote_url, wanted],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceResolutionError(
            f"resolving {remote_url}#{wanted} timed out after {timeout}s"
        ) from exc
    if completed.returncode != 0:
        raise SourceResolutionError(
            f"could not resolve {remote_url}#{wanted}: {completed.stderr.strip()}"
        )
    refs: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        sha, _, name = line.partition("\t")
        refs[name.strip()] = sha.strip()
    # ls-remote matches ref-name suffixes, so pick exact names only; an
    # annotated tag's peeled entry (^{}) names the commit, not the tag object.
    for name in (f"refs/tags/{wanted}^{{}}", f"refs/tags/{wanted}", f"refs/heads/{wanted}", wanted):
        if name in refs:
            return refs[name]
    raise SourceResolutionError(f"ref {wanted!r} not found in {remote_url}")


def _read_lock(base: Path) -> dict[str, Any]:
    path = base / _LOCK_RELPATH
    if not path.exists():
        return {"schema_version": _LOCK_SCHEMA_VERSION, "skills": {}}
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExternalSkillProvenanceError(f"provenance lock {path} is unreadable: {exc}") from exc
    if (
        not isinstance(lock, dict)
        or lock.get("schema_version") != _LOCK_SCHEMA_VERSION
        or not isinstance(lock.get("skills"), dict)
    ):
        raise ExternalSkillProvenanceError(
            f"provenance lock {path} is unreadable: unsupported shape or schema_version"
        )
    return lock


def _write_lock(base: Path, lock: dict[str, Any]) -> None:
    path = base / _LOCK_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staging, path)


def _verify_provenance(folder: Path, lock_base: Path) -> dict[str, Any]:
    key = folder.relative_to(lock_base).as_posix()
    record = _read_lock(lock_base)["skills"].get(key)
    if record is None:
        return {"status": "unrecorded"}
    resolved_ref = record.get("resolved_ref") if isinstance(record, dict) else None
    if not isinstance(resolved_ref, str) or not _COMMIT_SHA_RE.fullmatch(resolved_ref):
        raise ExternalSkillProvenanceError(
            f"recorded resolved ref {resolved_ref!r} for {key} is not an immutable commit SHA"
        )
    actual = skill_content_digest(folder)
    if actual != record.get("content_digest"):
        raise ExternalSkillProvenanceError(
            f"content digest mismatch for {key}: recorded "
            f"{record.get('content_digest')}, installed {actual}"
        )
    return {"status": "verified", **record}


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
