# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
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
# Source forms the pinned CLI strips '#<commit>' from (skills@1.7.0
# looksLikeGitSource / parseSource); anything else would silently drop the pin.
_SHORTHAND_SOURCE_RE = re.compile(r"([A-Za-z0-9][\w.-]*/[\w.-]+?)(?:@([\w.-]+))?")
_GITHUB_REPO_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+?(?:\.git)?/?")
# No userinfo on https (a token would be written into the lock) and none with
# a password on ssh; no '#' or whitespace anywhere.
_GIT_URL_RE = re.compile(
    r"https://[^\s#@/]+/[^\s#@]+\.git|ssh://(?:[^\s#@:/]+@)?[^\s#@/]+/[^\s#@]+\.git"
    r"|git@[\w.-]+:[^\s#]+"
)
# skills@1.7.0 SOURCE_ALIASES: shorthands the CLI rewrites before cloning.
# Re-check against the CLI source whenever the pin moves.
_CLI_SOURCE_ALIASES = {
    "coinbase/agentWallet": "coinbase/agentic-wallet-skills",
    "vercel-labs/vercel-skills": "vercel-labs/agent-skills",
}
# Skill names reach the CLI argv and filesystem paths: no leading '-' (a
# flag), '.' or space, no '*' (a wildcard), no separators (a path). Inner
# spaces are fine: the CLI's --skill takes a frontmatter name. Agent names are
# the CLI's fixed identifiers.
_SKILL_NAME_RE = re.compile(r"[^\s.*/\\-][^*/\\\x00-\x1f]*")
_AGENT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_LOCK_WAIT_SECONDS = 10.0
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
    _check_name(skill, "skill", _SKILL_NAME_RE)
    _check_name(agent, "agent", _AGENT_NAME_RE)

    source_base, remote_url, requested_ref, named_skill = _parse_source(source)
    if named_skill is not None and named_skill != skill:
        raise ValueError(f"source names skill {named_skill!r} but skill is {skill!r}")
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    lock_base = cwd if scope == "project" else home
    _read_lock(lock_base)  # fail fast on an unreadable lock, before the CLI runs
    resolved_ref = _resolve_commit(remote_url, requested_ref, timeout)
    before = _folder_identities(skill, scope, cwd, home)

    args = ["add", f"{source_base}#{resolved_ref}", "--skill", skill, "-a", agent, "-y"]
    if scope == "global":
        args.append("-g")
    command, stdout, stderr = _run_skills_cli(args, timeout=timeout, cwd=cwd)
    written = _written_folders(skill, scope, before, _folder_identities(skill, scope, cwd, home))
    installed_at = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "skill": skill,
            "source": source_base,
            "requested_ref": requested_ref,
            "resolved_ref": resolved_ref,
            "content_digest": skill_content_digest(location.path.parent),
            "agent": agent,
            "scope": scope,
            "path": location.path.parent.relative_to(lock_base).as_posix(),
            "installed_at": installed_at,
            "installer": skills_cli_identity(),
        }
        for location in written
    ]
    _record_in_lock(lock_base, records)
    installed = written[0].as_dict()
    provenance = records[0]
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
    _check_name(skill, "skill", _SKILL_NAME_RE)
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
    # Read the body once, before verifying, and check those exact bytes against
    # the verified walk so a swap in between cannot hand over unverified text.
    body_bytes = _read_skill_body(path)
    provenance = _verify_provenance(
        path, cwd if installed["scope"] == "project" else home, body_bytes
    )
    body = body_bytes.decode("utf-8")
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
            "does not match, or provenance could not be recorded. Reinstall it via "
            "sumo_qa_install_external_skill once the user confirms. If the error says "
            "the provenance lock (.sumo-qa/external-skills.lock.json) is unreadable, "
            "ask the user to repair or remove that file first; removing it drops every "
            "record."
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
    return _digest_of(_content_entries(Path(folder)))


def _content_entries(root: Path) -> dict[tuple[str, str], str]:
    """Map each ``(kind, relative path)`` under ``root`` to its content.

    ``kind`` is ``file`` (value: SHA-256 of its bytes) or ``link`` (value: the
    link target). A symlink inside the folder is pinned by its target and not
    followed; the bytes it reaches are hashed at their own path. A link
    leaving the folder, or anything that is not a regular file, cannot be
    pinned and is refused.
    """
    root_real = os.path.realpath(root)
    entries: dict[tuple[str, str], str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        for name in [*dirnames, *filenames]:
            path = current / name
            relpath = path.relative_to(root).as_posix()
            if path.is_symlink():  # pragma: no cover -- platform-conditional (POSIX only)
                _check_link_stays_inside(path, root_real)
                entries[("link", relpath)] = os.readlink(path)
            elif name in filenames:
                entries[("file", relpath)] = _hash_regular_file(path)
    return entries


def _check_link_stays_inside(path: Path, root_real: str) -> None:  # pragma: no cover -- POSIX only
    target = os.path.realpath(path)
    if os.path.commonpath([root_real, target]) != root_real:
        raise ExternalSkillProvenanceError(
            f"{path} links outside the skill folder ({target}); that content cannot be pinned"
        )


def _hash_regular_file(path: Path) -> str:
    try:
        if not path.is_file():  # pragma: no cover -- platform-conditional (POSIX only)
            raise ExternalSkillProvenanceError(f"{path} is not a regular file; refusing to read it")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ExternalSkillProvenanceError(f"could not read {path}: {exc}") from exc


def _digest_of(entries: dict[tuple[str, str], str]) -> str:
    # JSON framing: no name or link target can shift bytes between fields.
    items = sorted([kind, relpath, value] for (kind, relpath), value in entries.items())
    encoded = json.dumps(items, ensure_ascii=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _read_skill_body(path: Path) -> bytes:
    return path.read_bytes()


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


def _check_name(value: str, kind: str, pattern: re.Pattern[str]) -> None:
    if not pattern.fullmatch(value):
        raise ValueError(
            f"{kind} name {value!r} must not start with '-', '.' or a space, and must "
            "not contain '*', '/' or '\\'"
        )


def _parse_source(source: str) -> tuple[str, str, str | None, str | None]:
    """Split an install source into (CLI source, git remote URL, ref, named skill)."""
    base, has_ref, ref = source.partition("#")
    if has_ref and not ref:
        raise ValueError("source ref after '#' is empty")
    if "/tree/" in base or "/blob/" in base:
        raise ValueError("source must be a repository URL; pass a folder's ref as '#<ref>'")
    shorthand = _SHORTHAND_SOURCE_RE.fullmatch(base)
    if shorthand and not shorthand[1].endswith(".git"):
        repo = _CLI_SOURCE_ALIASES.get(shorthand[1], shorthand[1])
        return repo, f"https://github.com/{repo}.git", ref or None, shorthand[2]
    if _GITHUB_REPO_URL_RE.fullmatch(base) or _GIT_URL_RE.fullmatch(base):
        return base, base, ref or None, None
    raise ValueError(
        "source must be owner/repo[@skill], https://github.com/owner/repo, or a git "
        "URL ending in .git (https:// or ssh://) or git@host:path, so the install can "
        "be pinned to a commit"
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
            # An annotated tag's commit is only listed when its peeled name is
            # asked for explicitly; a plain pattern lists the tag object alone.
            [git, "ls-remote", "--", remote_url, wanted, f"{wanted}^{{}}"],
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
    # ls-remote matches ref-name suffixes, so pick exact names only, the
    # peeled (^{}) tag entry first: it names the commit, not the tag object.
    for name in (f"refs/tags/{wanted}^{{}}", f"refs/tags/{wanted}", f"refs/heads/{wanted}", wanted):
        if name in refs:
            return refs[name]
    raise SourceResolutionError(f"ref {wanted!r} not found in {remote_url}")


def _folder_identities(
    skill: str, scope: str, cwd: Path, home: Path
) -> dict[Path, tuple[InstalledSkill, tuple[int, int]]]:
    """Every existing copy of ``skill`` in ``scope`` with its folder identity.

    The pinned CLI deletes and recreates the folder on every install
    (cleanAndCreateDirectory), so a new inode or mtime marks a folder it wrote.
    """
    # Keyed by (root, inode): name variants that reach one folder (on a
    # case-insensitive filesystem) count once, under the first spelling tried,
    # which is the CLI's own.
    found: dict[tuple[Path, int], tuple[InstalledSkill, tuple[int, int]]] = {}
    for candidate in _iter_installed_skill_candidates(skill, scope, cwd, home):
        if candidate.path.is_file():
            stat = candidate.path.parent.stat()
            found.setdefault(
                (candidate.path.parent.parent, stat.st_ino),
                (candidate, (stat.st_ino, stat.st_mtime_ns)),
            )
    return {location.path.parent: (location, identity) for location, identity in found.values()}


def _written_folders(
    skill: str,
    scope: str,
    before: dict[Path, tuple[InstalledSkill, tuple[int, int]]],
    after: dict[Path, tuple[InstalledSkill, tuple[int, int]]],
) -> list[InstalledSkill]:
    """The copies this install created or rewrote.

    A copy it did not touch is never returned, even when it is the only one
    found: recording it would vouch for bytes this install never wrote.
    """
    written = [
        location
        for folder, (location, identity) in after.items()
        if before.get(folder, (None, None))[1] != identity
    ]
    if not written:
        raise ExternalSkillProvenanceError(
            f"installed skill {skill!r} not found among the {scope} skill folders this "
            "install wrote; provenance was not recorded"
        )
    return written


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


def _record_in_lock(base: Path, records: list[dict[str, Any]]) -> None:
    """Merge records into the lock under an exclusive guard file, re-reading
    it inside the guard so concurrent installs keep each other's records."""
    path = base / _LOCK_RELPATH
    guard = path.with_name(path.name + ".lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _acquire_guard(guard)
    except OSError as exc:
        raise ExternalSkillProvenanceError(f"could not lock {path}: {exc}") from exc
    try:
        lock = _read_lock(base)
        for record in records:
            lock["skills"][record["path"]] = record
        _replace_lock_file(path, json.dumps(lock, indent=2, sort_keys=True) + "\n")
    finally:
        guard.unlink()


def _acquire_guard(guard: Path) -> None:
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while True:
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ExternalSkillProvenanceError(
                    f"provenance lock is busy ({guard} exists); if no install is "
                    "running, remove that file and retry"
                ) from None
            time.sleep(0.02)


def _replace_lock_file(path: Path, content: str) -> None:
    # The previous lock's permissions carry over (mkstemp creates 0600).
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, staging = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, mode)
        os.replace(staging, path)
    except OSError as exc:
        Path(staging).unlink(missing_ok=True)
        raise ExternalSkillProvenanceError(
            f"could not write provenance lock {path}: {exc}"
        ) from exc


def _verify_provenance(skill_md: Path, lock_base: Path, body: bytes) -> dict[str, Any]:
    folder = skill_md.parent
    key, record = _find_record(folder, lock_base)
    if record is None:
        return {"status": "unrecorded"}
    resolved_ref = record.get("resolved_ref") if isinstance(record, dict) else None
    if not isinstance(resolved_ref, str) or not _COMMIT_SHA_RE.fullmatch(resolved_ref):
        raise ExternalSkillProvenanceError(
            f"recorded resolved ref {resolved_ref!r} for {key} is not an immutable commit SHA"
        )
    entries = _content_entries(folder)
    actual = _digest_of(entries)
    if actual != record.get("content_digest"):
        raise ExternalSkillProvenanceError(
            f"content digest mismatch for {key}: recorded "
            f"{record.get('content_digest')}, installed {actual}"
        )
    # The bytes handed over are those of SKILL.md's real file, which may sit
    # behind an in-folder link; the CLI also keeps any case of the name.
    real_relpath = Path(
        os.path.relpath(os.path.realpath(skill_md), os.path.realpath(folder))
    ).as_posix()
    body_entry = entries.get(("file", real_relpath)) or next(
        (
            value
            for (kind, relpath), value in entries.items()
            if kind == "file" and relpath.lower() == real_relpath.lower()
        ),
        None,
    )
    if hashlib.sha256(body).hexdigest() != body_entry:
        raise ExternalSkillProvenanceError(
            f"{key}/SKILL.md changed while it was being verified; not executing it"
        )
    return {"status": "verified", **record}


def _find_record(folder: Path, lock_base: Path) -> tuple[str, Any]:
    """The lock record for ``folder``, matched by the folder on disk.

    Matching by path spelling alone would let a case or symlink variant of the
    name miss the record and run the skill as unrecorded.
    """
    skills = _read_lock(lock_base)["skills"]
    key = os.path.relpath(folder, lock_base).replace(os.sep, "/")
    if key in skills:
        return key, skills[key]
    for recorded_key, record in skills.items():
        recorded = lock_base / recorded_key
        if recorded.exists() and os.path.samefile(recorded, folder):
            return recorded_key, record
    return key, None


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


def _candidate_paths(names: list[str], root: Path, agent: str, scope: str):
    for name in names:
        yield InstalledSkill(name=name, path=root / name / "SKILL.md", agent=agent, scope=scope)


def _candidate_skill_names(skill: str) -> list[str]:
    variants = [
        # skills@1.7.0 sanitizeName(): the folder the CLI actually writes.
        re.sub(r"[^a-z0-9._]+", "-", skill.lower()).strip(".-"),
        skill,
        skill.replace("_", "-"),
        skill.replace("-", "_"),
    ]
    return list(dict.fromkeys(variants))
