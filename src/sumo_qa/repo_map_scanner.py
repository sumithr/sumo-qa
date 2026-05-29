# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic local scanner for the QA-native repo-map artifact (issue #155 slice 2).

``scan_repo(root, *, generator_version) -> RepoMap`` walks a repository,
classifies files into the first-slice node vocabulary, fingerprints with
SHA-256, infers minimal ``likely_tests`` edges by name convention, extracts
top-level commands from ``pyproject.toml`` and ``package.json``, and reports
skipped or unsupported files via warnings.

Determinism contract: on the same repo state, the structural fields
(nodes / edges / commands / warnings) are byte-stable. File order is
sorted; edges and commands are sorted by stable keys; only
``project.generated_at`` varies between runs (that's the documented
freshness signal, not a determinism gap).

Slice 2 deliberately stays narrow: only ``likely_tests`` edges are inferred.
``imports`` and ``configured_by`` edges are deferred until #156 needs them.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

if sys.version_info >= (3, 11):  # pragma: no cover -- version-gated import: only one
    import tomllib  # branch runs per interpreter, so exclude both from the src cov gate
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

from sumo_qa.repo_map_models import (
    SCHEMA_VERSION,
    CommandKind,
    EdgeConfidence,
    NodeType,
    RepoMap,
    RepoMapCommand,
    RepoMapEdge,
    RepoMapNode,
    RepoMapProject,
    RepoMapWarning,
)

_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "build",
        ".tox",
        "mutants",
        ".sumo-qa",
    }
)

_BINARY_EXTS: Final[frozenset[str]] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".whl",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".jar",
        ".class",
    }
)

_LANGUAGE_BY_EXT: Final[dict[str, str]] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".tf": "hcl",
}

_PROGRAMMING_LANGS: Final[frozenset[str]] = frozenset(
    {"python", "javascript", "typescript", "rust", "go", "ruby", "java", "kotlin", "shell"}
)

_MANIFEST_NAMES: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "Cargo.toml",
        "Gemfile",
        "go.mod",
        "build.gradle",
        "pom.xml",
    }
)

_INFRA_NAMES: Final[frozenset[str]] = frozenset(
    {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
)

_CI_FILENAMES: Final[frozenset[str]] = frozenset(
    {"Jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml"}
)


def scan_repo(root: Path | str, *, generator_version: str) -> RepoMap:
    """Walk ``root`` and produce a deterministic :class:`RepoMap`."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise ValueError(f"scan_repo root must be a directory: {root_path!s}")

    files = _list_files(root_path)
    nodes: list[RepoMapNode] = []
    warnings: list[RepoMapWarning] = []

    for rel in files:
        abs_path = root_path / rel
        node = _file_to_node(rel, abs_path, warnings)
        if node is not None:
            nodes.append(node)

    edges = _infer_likely_tests_edges(nodes)
    commands = _extract_commands(root_path)
    git_commit = _detect_git_commit(root_path)

    return RepoMap(
        schema_version=SCHEMA_VERSION,
        project=RepoMapProject(
            root=str(root_path),
            name=root_path.name,
            git_commit=git_commit,
            generated_at=datetime.now(timezone.utc),
            generator_version=generator_version,
        ),
        nodes=nodes,
        edges=edges,
        commands=commands,
        warnings=warnings,
    )


def _list_files(root: Path) -> list[str]:
    """Repo-relative paths in sorted order. Prefers ``git ls-files``; falls
    back to a manual walk that excludes known cache/vendored directories.

    Two safety nets prevent leaking an outer git repo's tracked files when
    ``root`` happens to sit beneath one (the classic case: a temp dir under
    ``/var/folders/...`` while the parent process inherits ``GIT_DIR`` from
    something like pre-commit's stash). First, every git invocation strips
    ``GIT_*`` from the env so an inherited ``GIT_DIR``/``GIT_WORK_TREE``
    can't override ``--git-dir``/``cwd``. Second, ``rev-parse
    --show-toplevel`` must resolve to ``root`` itself — if git's discovery
    walks up and finds an ancestor repo, the toplevel won't match and we
    fall back to the manual walk."""
    git_env = _git_env()
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            env=git_env,
        )
        repo_root = Path(toplevel.stdout.decode("utf-8").strip()).resolve()
        if repo_root == root.resolve():
            result = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z"],
                capture_output=True,
                check=True,
                env=git_env,
            )
            tracked = [p.decode("utf-8") for p in result.stdout.split(b"\0") if p]
            if tracked:
                return sorted(tracked)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    paths: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        paths.append(p.relative_to(root).as_posix())
    return sorted(paths)


def _file_to_node(rel: str, abs_path: Path, warnings: list[RepoMapWarning]) -> RepoMapNode | None:
    ext = abs_path.suffix.lower()
    if ext in _BINARY_EXTS:
        warnings.append(
            RepoMapWarning(
                kind="skipped_file",
                message=f"binary extension {ext} skipped",
                path=rel,
            )
        )
        return None

    node_type = _classify(Path(rel))
    if node_type is None:
        warnings.append(
            RepoMapWarning(
                kind="unsupported_language",
                message=f"no classification for {rel}",
                path=rel,
            )
        )
        return None

    return RepoMapNode(
        id=f"file:{rel}",
        type=node_type,
        path=rel,
        language=_LANGUAGE_BY_EXT.get(ext),
        fingerprint=_fingerprint(abs_path),
    )


def _classify(rel: Path) -> NodeType | None:
    parts = rel.parts
    name = rel.name
    ext = rel.suffix.lower()

    if name in _INFRA_NAMES or ext == ".tf":
        return "infrastructure"

    if len(parts) >= 3 and parts[0] == ".github" and parts[1] == "workflows":
        return "ci_workflow"
    if name in _CI_FILENAMES:
        return "ci_workflow"

    if name in _MANIFEST_NAMES:
        return "manifest"

    if "migrations" in parts or name == "schema.sql" or ext == ".sql":
        return "migration_schema"

    if "fixtures" in parts or "__fixtures__" in parts:
        return "fixture"

    if _looks_like_test(rel):
        return "test_file"

    if ext in (".md", ".rst") or (parts and parts[0] == "docs"):
        return "docs"

    if ext in (".yaml", ".yml", ".json", ".toml"):
        return "config"

    if _LANGUAGE_BY_EXT.get(ext) in _PROGRAMMING_LANGS:
        return "source_file"

    return None


def _looks_like_test(rel: Path) -> bool:
    parts = rel.parts
    stem = rel.stem
    if "tests" in parts or "test" in parts:
        return True
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    if stem.endswith(".test") or stem.endswith(".spec"):
        return True
    return False


def _fingerprint(abs_path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with abs_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()


def _infer_likely_tests_edges(nodes: list[RepoMapNode]) -> list[RepoMapEdge]:
    sources_by_stem: dict[str, list[RepoMapNode]] = {}
    for node in nodes:
        if node.type == "source_file":
            sources_by_stem.setdefault(Path(node.path).stem, []).append(node)

    edges: list[RepoMapEdge] = []
    for node in nodes:
        if node.type != "test_file":
            continue
        test_stem = Path(node.path).stem
        target_stem = test_stem
        if target_stem.startswith("test_"):
            target_stem = target_stem.removeprefix("test_")
        elif target_stem.endswith("_test"):
            target_stem = target_stem.removesuffix("_test")

        candidates = sources_by_stem.get(target_stem, [])
        confidence: EdgeConfidence = "high" if len(candidates) == 1 else "medium"
        for source in candidates:
            edges.append(
                RepoMapEdge(
                    source=node.id,
                    target=source.id,
                    type="likely_tests",
                    confidence=confidence,
                    reason=f"name convention: {test_stem} -> {target_stem}",
                )
            )
    return sorted(edges, key=lambda e: (e.source, e.target))


def _extract_commands(root: Path) -> list[RepoMapCommand]:
    commands: list[RepoMapCommand] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        commands.extend(_pyproject_commands(pyproject))
    package_json = root / "package.json"
    if package_json.is_file():
        commands.extend(_package_json_commands(package_json))
    return sorted(commands, key=lambda c: (c.source, c.name))


def _pyproject_commands(path: Path) -> list[RepoMapCommand]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    scripts = data.get("project", {}).get("scripts", {}) or {}
    return [
        RepoMapCommand(name=str(name), kind="other", source="pyproject.toml", raw=str(target))
        for name, target in scripts.items()
    ]


def _package_json_commands(path: Path) -> list[RepoMapCommand]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = data.get("scripts", {}) or {}
    return [
        RepoMapCommand(
            name=str(name),
            kind=_guess_command_kind(str(name)),
            source="package.json",
            raw=str(raw),
        )
        for name, raw in scripts.items()
    ]


def _guess_command_kind(name: str) -> CommandKind:
    n = name.lower()
    if "test" in n:
        return "test"
    if "lint" in n:
        return "lint"
    if "format" in n or "fmt" in n:
        return "format"
    if "build" in n or "compile" in n:
        return "build"
    return "other"


def _detect_git_commit(root: Path) -> str | None:
    git_env = _git_env()
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            env=git_env,
        )
        repo_root = Path(toplevel.stdout.decode("utf-8").strip()).resolve()
        if repo_root != root.resolve():
            return None
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            env=git_env,
        )
        return result.stdout.decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_env() -> dict[str, str]:
    """Return os.environ stripped of ``GIT_*`` vars. Inherited ``GIT_DIR``/
    ``GIT_WORK_TREE`` from a parent process (notably pre-commit's stash
    mechanism) otherwise overrides ``--git-dir`` and ``cwd``, making
    ``git ls-files`` from a temp dir leak the outer repo's tracked files."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
