# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sumo_qa.ingest import _write_atomic


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
# Install sources are validated here and cloned by sumo-qa itself; the Skills
# CLI only ever receives the local checkout, so its own URL parsing (which can
# drop or reinterpret a ref) never applies. No credentials, query strings,
# whitespace, or '..' segments.
_SEGMENT = r"[A-Za-z0-9._~-]+"
_REPO_PATH = rf"{_SEGMENT}(?:/{_SEGMENT})*/?"
_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
_URL_SOURCE_RE = re.compile(
    rf"https://{_HOST}(?::\d+)?/{_REPO_PATH}"
    rf"|ssh://(?:[A-Za-z0-9._-]+@)?{_HOST}(?::\d+)?/{_REPO_PATH}"
    rf"|git@{_HOST}:{_REPO_PATH}"
)
_SHORTHAND_SOURCE_RE = re.compile(r"([A-Za-z0-9][\w.-]*)/([\w.-]+?)(?:\.git)?(?:@([\w.-]+))?")
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_DOT_SEGMENT_RE = re.compile(r"(?:^|[/:])\.{1,2}(?:/|$)")
_GIT_ALLOWED_PROTOCOLS = "https:ssh:file"
# Skill names reach the CLI argv and filesystem paths: letters, digits, '.',
# '_', '-' and inner spaces (the CLI's --skill takes a frontmatter name), and
# never a leading '-' (a flag) or '.', a wildcard, a separator, or a drive.
_SKILL_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 ._-]*[A-Za-z0-9._-])?")
_AGENT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Long enough for another install's CLI run (its default timeout) to finish.
_LOCK_WAIT_SECONDS = 150.0
_NO_RECORD = object()  # distinct from a present-but-null (malformed) record
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

    sumo-qa clones the source and checks out the resolved commit itself, then
    hands the CLI only that local checkout, so the installed bytes come from
    exactly the recorded commit. Each folder the install wrote is digested and
    recorded in the scope's provenance lock for ``execute_external_skill``.
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

    remote_url, requested_ref, named_skill = _parse_source(source)
    if named_skill is not None and named_skill != skill:
        raise ValueError(f"source names skill {named_skill!r} but skill is {skill!r}")
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    lock_base = cwd if scope == "project" else home
    _read_lock(lock_base)  # fail fast on an unreadable lock, before any fetch
    workdir, checkout, resolved_ref = _checkout_commit(remote_url, requested_ref, timeout)
    try:
        _check_checkout_links(checkout)
        # One guard around snapshot, CLI run, digest, and record: concurrent
        # installs can neither interleave their writes nor lose records.
        with _lock_guard(lock_base):
            before = _folder_identities(skill, scope, cwd, home)
            before_entries = {folder: _entry_identity(folder) for folder in before}
            args = ["add", str(checkout), "--skill", skill, "-a", agent, "-y"]
            if scope == "global":
                args.append("-g")
            command, stdout, stderr = _run_skills_cli(args, timeout=timeout, cwd=cwd)
            after = _folder_identities(skill, scope, cwd, home)
            written = _written_folders(skill, scope, before, after)
            try:
                records = _provenance_records(
                    written, remote_url, requested_ref, resolved_ref, skill, agent, scope, lock_base
                )
                _merge_into_lock(lock_base, records)
            except BaseException:
                # Never leave an install behind that runs as "unrecorded", but
                # keep entries the CLI did not replace (a user's alias link).
                replaced = [
                    location.path.parent
                    for location in written
                    if before_entries.get(location.path.parent)
                    != _entry_identity(location.path.parent)
                ]
                for folder in replaced:
                    _remove_install(folder)
                raise
    finally:
        _remove_tree(workdir)
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
    if scope not in _VALID_SCOPES:
        raise ValueError("scope must be 'auto', 'project', or 'global'")
    # Search one scope at a time, holding only that scope's install lock while
    # locating, reading, and verifying: an install cannot be mid-way (or rolled
    # back) under the read, and a project skill never touches the home lock.
    for each_scope in ("project", "global") if scope == "auto" else (scope,):
        lock_base = cwd if each_scope == "project" else home
        has_lock = (lock_base / _LOCK_RELPATH).parent.is_dir()
        with _lock_guard(lock_base) if has_lock else nullcontext():
            installed = check_external_skill_installed(skill, each_scope, cwd, home)
            if installed is not None:
                path = Path(installed["path"])
                body_bytes = _read_skill_body(path)
                provenance = _verify_provenance(path, lock_base, body_bytes)
                break
    else:
        raise ExternalSkillError(f"external skill is not installed: {skill}")
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
            "Check network access and that the source is a git repository whose "
            "#ref exists (a branch, tag, or full commit SHA)."
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


def _check_link_stays_inside(  # pragma: no cover -- POSIX only
    path: Path, root_real: str, inside_is_error: bool = False
) -> None:
    target = os.path.realpath(path)
    if (os.path.commonpath([root_real, target]) == root_real) == inside_is_error:
        raise ExternalSkillProvenanceError(
            f"{path} links to {target}, outside the pinned content; it cannot be pinned"
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
            f"{kind} name {value!r} must start with a letter or digit and use only "
            "letters, digits, '.', '_', '-' (and inner spaces for a skill)"
        )


def _parse_source(source: str) -> tuple[str, str | None, str | None]:
    """Split an install source into (git remote URL, requested ref, named skill)."""
    base, has_ref, ref = source.partition("#")
    if has_ref and not (_REF_RE.fullmatch(ref) and ".." not in ref):
        raise ValueError(f"source ref {ref!r} is not a branch, tag, or commit name")
    shorthand = _SHORTHAND_SOURCE_RE.fullmatch(base)
    if shorthand:
        remote = f"https://github.com/{shorthand[1]}/{shorthand[2]}.git"
        return remote, ref or None, shorthand[3]
    if _URL_SOURCE_RE.fullmatch(base) and not _DOT_SEGMENT_RE.search(base):
        return base, ref or None, None
    raise ValueError(
        "source must be owner/repo[@skill], an https:// or ssh:// git URL, or "
        "git@host:path, without credentials or a query string"
    )


def _checkout_commit(remote_url: str, ref: str | None, timeout: int) -> tuple[Path, Path, str]:
    """Clone ``remote_url`` and check out ``ref`` (default HEAD) detached.

    Returns (temporary folder to remove, checkout, full commit SHA).
    """
    git = shutil.which("git")
    if not git:
        raise GitNotFoundError("git not found on PATH")
    workdir = Path(tempfile.mkdtemp(prefix="sumo-qa-skill-"))
    checkout = workdir / "checkout"
    try:
        _run_git(
            [git, "clone", "--no-checkout", "--filter=blob:none", "--quiet", "--"]
            + [remote_url, str(checkout)],
            timeout,
        )
        commit = _rev_parse_commit(git, checkout, ref, timeout)
        _run_git([git, "-C", str(checkout), "checkout", "--quiet", "--detach", commit], timeout)
    except BaseException:
        _remove_tree(workdir)
        raise
    return workdir, checkout, commit


def _provenance_records(
    written: list[InstalledSkill],
    remote_url: str,
    requested_ref: str | None,
    resolved_ref: str,
    skill: str,
    agent: str,
    scope: str,
    lock_base: Path,
) -> list[dict[str, Any]]:
    installed_at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "skill": skill,
            "source": remote_url,
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


def _check_checkout_links(checkout: Path) -> None:
    """Refuse a checkout whose links reach bytes outside the commit.

    The CLI copies a local source by dereferencing links, so a link out of
    the checkout, or into its .git folder, would install bytes no commit holds.
    """
    root_real = os.path.realpath(checkout)
    git_real = os.path.join(root_real, ".git")
    for dirpath, dirnames, filenames in os.walk(checkout):
        current = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not (current == checkout and d == ".git")]
        for name in [*dirnames, *filenames]:
            path = current / name
            if path.is_symlink():  # pragma: no cover -- platform-conditional (POSIX only)
                _check_link_stays_inside(path, root_real)
                _check_link_stays_inside(path, git_real, inside_is_error=True)


def _remove_tree(path: Path) -> None:
    """Remove a temporary tree, including git's read-only object files."""
    for dirpath, dirnames, filenames in os.walk(path):
        for name in [*dirnames, *filenames]:
            entry = os.path.join(dirpath, name)
            if not os.path.islink(entry):
                os.chmod(entry, stat.S_IRWXU)
    shutil.rmtree(path, ignore_errors=True)


def _entry_identity(path: Path) -> tuple[int, int]:
    """Identity of the directory entry itself (a link, not its target)."""
    stat_result = os.lstat(path)
    return stat_result.st_ino, stat_result.st_mtime_ns


def _remove_install(folder: Path) -> None:
    # An agent folder may be a link to the canonical copy: drop the link only.
    folder.unlink(missing_ok=True) if folder.is_symlink() else _remove_tree(folder)


def _rev_parse_commit(git: str, checkout: Path, ref: str | None, timeout: int) -> str:
    if ref is None:
        candidates = ["HEAD"]
    elif _COMMIT_SHA_RE.fullmatch(ref.lower()):
        candidates = [ref.lower()]
    else:
        # A tag before a same-named branch; a branch through its remote ref.
        candidates = [f"refs/tags/{ref}", f"refs/remotes/origin/{ref}"]
    for candidate in candidates:
        completed = _run_git(
            [git, "-C", str(checkout), "rev-parse", "--verify", "--quiet", "--end-of-options"]
            + [f"{candidate}^{{commit}}"],
            timeout,
            check=False,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()
    raise SourceResolutionError(f"ref {ref or 'HEAD'!r} not found in the cloned source")


def _run_git(
    command: list[str], timeout: int, check: bool = True
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        # Blocks ext:: and other command-running transports.
        "GIT_ALLOW_PROTOCOL": _GIT_ALLOWED_PROTOCOLS,
    }
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceResolutionError(f"git timed out after {timeout}s") from exc
    if check and completed.returncode != 0:
        raise SourceResolutionError(f"git failed: {completed.stderr.strip()}")
    return completed


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


@contextmanager
def _lock_guard(base: Path) -> Iterator[None]:
    """Hold an OS advisory lock on the scope's guard file.

    The OS releases it when the descriptor closes, including when the process
    dies, so a crashed install never leaves a stale guard behind.
    """
    path = base / _LOCK_RELPATH
    if path.parent.is_symlink():
        raise ExternalSkillProvenanceError(f"refusing to use {path.parent}: it is a symlink")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o666)
    except OSError as exc:
        raise ExternalSkillProvenanceError(f"could not lock {path}: {exc}") from exc
    try:
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise ExternalSkillProvenanceError(
                    f"provenance lock {path} is busy: another install is still running"
                )
            time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _try_lock(fd: int) -> bool:
    if os.name == "nt":  # pragma: no cover -- platform-conditional (Windows only)
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    else:  # pragma: no cover -- platform-conditional (POSIX only)
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _merge_into_lock(base: Path, records: list[dict[str, Any]]) -> None:
    """Merge records into the lock; the caller holds ``_lock_guard``."""
    lock = _read_lock(base)
    for record in records:
        lock["skills"][record["path"]] = record
    path = base / _LOCK_RELPATH
    # Keep a rewritten lock's permissions; a new one follows the folder's
    # (umask-derived) mode rather than the 0600 staging file's.
    source = path if path.exists() else path.parent
    mode = source.stat().st_mode & 0o666
    try:
        _write_atomic(path, json.dumps(lock, indent=2, sort_keys=True) + "\n")
        os.chmod(path, mode)
    except OSError as exc:
        raise ExternalSkillProvenanceError(
            f"could not write provenance lock {path}: {exc}"
        ) from exc


def _verify_provenance(skill_md: Path, lock_base: Path, body: bytes) -> dict[str, Any]:
    folder = skill_md.parent
    key, record = _find_record(folder, lock_base)
    if record is _NO_RECORD:
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
    return key, _NO_RECORD


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
