# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic local scanner for the QA-native repo-map artifact (issue #155 slice 2).

``scan_repo(root, *, generator_version) -> RepoMap`` walks a repository,
classifies files into the first-slice node vocabulary, fingerprints with
SHA-256, infers ``likely_tests`` edges (language-agnostically — see below),
extracts top-level commands from ``pyproject.toml`` and ``package.json``, and
reports skipped or unsupported files via warnings.

``likely_tests`` edges come from two signals so the mapping is not tied to a
fixed filename-suffix table (#266): a usage/import signal (a test file's
import statements name a source stem — robust across languages and naming
conventions; only import-style lines are read, so an incidental mention can't
fabricate an edge), and a name-convention signal covering snake_case
(``test_x`` / ``x_test``),
dotted JS/TS (``x.test`` / ``x.spec``), and CamelCase families
(``FooTest`` / ``FooTests`` / ``FooSpec`` / ``FooIT`` / ``FooITCase`` —
Kotlin/Java/Scala/Swift). A pair found by both signals is a single
corroborated edge.

Determinism contract: on the same repo state, the structural fields
(nodes / edges / commands / warnings) are byte-stable. File order is
sorted; edges and commands are sorted by stable keys; only
``project.generated_at`` varies between runs (that's the documented
freshness signal, not a determinism gap).

Only ``likely_tests`` edges are inferred here. First-class ``imports`` /
``configured_by`` edges (a full parsed import graph, e.g. via tree-sitter)
are deferred to #212; the usage signal below is a lightweight token-reference
heuristic, not a resolved import graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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

# CamelCase test-naming families (Kotlin/Java/Scala/Swift): FooTest, FooTests,
# FooSpec, FooIT, FooITCase. The non-greedy base captures the source stem.
# ITCase precedes IT so the longer suffix wins at the same anchor.
_CAMEL_TEST_RE: Final = re.compile(r"^(?P<base>.+?)(Tests?|Spec|ITCase|IT)$")

# Identifier token: what a usage reference looks like in source text.
_IDENT_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# The usage signal only reads identifiers off import-style lines, NOT arbitrary
# code/comments — an incidental mention of a common-word stem (`order`,
# `config`) in a comment or local variable must not fabricate a test→source
# edge that would then clear a genuinely-uncovered source off the risk surface.
# These patterns target real import/require statements across common languages
# while avoiding prose collisions (bare `use`/`from`/`using` are constrained by
# a following `::`, an `import` keyword, or a trailing `;`).
_IMPORT_LINE_RES: Final = (
    re.compile(r"^\s*import\b"),  # py / js / ts / java / kotlin / scala / go
    re.compile(r"^\s*from\s+\S+\s+import\b"),  # py: from X import Y
    re.compile(r"^\s*#\s*include\b"),  # c / c++
    re.compile(r"^\s*use\s+\S+::"),  # rust: use a::b
    re.compile(r"^\s*using\s+[A-Za-z_][\w.]*\s*;"),  # c#: using System.X;
    re.compile(r"\brequire(?:_relative)?\s*\(?\s*['\"]"),  # node/ruby require('x') / require 'x'
    re.compile(r"\bimport\s*\(\s*['\"]"),  # js dynamic import('x')
)

# A source stem must be at least this long to be a reliable usage token —
# single/double-char stems (a, io) are too common and would over-link.
_MIN_USAGE_STEM_LEN: Final = 3

# Cap per-test-file content read for the usage signal (bounded, deterministic).
_MAX_TEST_READ_BYTES: Final = 1_000_000


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

    edges = _infer_likely_tests_edges(nodes, root_path)
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
            # `git ls-files` lists tracked paths even after they're deleted in
            # the working tree (before the deletion is committed). The repo-map
            # describes the CURRENT tree, so drop entries that no longer exist
            # on disk — otherwise they'd become nodes with fingerprint=None and
            # point consumers at stale files.
            tracked = [
                rel
                for raw in result.stdout.split(b"\0")
                if raw
                for rel in (raw.decode("utf-8"),)
                if (root / rel).is_file()
            ]
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
    # A CamelCase suffix (FooTest / FooSpec / FooIT) is NOT classified as a test
    # on the name alone: a production class under src/main whose name happens to
    # end in Test/Spec/IT (e.g. ExperimentTest.kt in an A/B-testing domain) would
    # be misclassified, dropping a changed source off the risk surface — a
    # false-negative worse than a missed test (codex review, PR #277). Kotlin/
    # Java/Scala tests live under src/test and are caught by the path check
    # above; the CamelCase→source-stem mapping for those lives in
    # _normalise_test_stem (edge inference on files already classified as tests).
    return False


def _camelcase_test_base(stem: str) -> str | None:
    """The source stem a CamelCase test stem targets, or None.

    ``FooTest`` / ``FooTests`` / ``FooSpec`` / ``FooIT`` / ``FooITCase`` ->
    ``Foo``. Guards against acronym / ordinary-word false positives
    (``HTTP``, ``Commit``, ``Manifest``) by requiring the base to end in a
    lowercase letter or digit — a real CamelCase prefix does, a bare acronym
    suffix does not."""
    match = _CAMEL_TEST_RE.match(stem)
    if match is None:
        return None
    base = match.group("base")
    if not base or not (base[-1].islower() or base[-1].isdigit()):
        return None
    return base


def _normalise_test_stem(test_stem: str) -> str | None:
    """Map a test file's stem to the source stem it conventionally targets, or
    None when the stem matches no known convention.

    Covers snake_case (``test_x`` / ``x_test``), dotted JS/TS
    (``x.test`` / ``x.spec``), and CamelCase families. ``Path.stem`` strips only
    the last suffix, so a JS ``foo.test.ts`` arrives here as ``foo.test``."""
    if test_stem.endswith(".test"):
        return test_stem[: -len(".test")] or None
    if test_stem.endswith(".spec"):
        return test_stem[: -len(".spec")] or None
    if test_stem.startswith("test_"):
        return test_stem[len("test_") :] or None
    if test_stem.endswith("_test"):
        return test_stem[: -len("_test")] or None
    return _camelcase_test_base(test_stem)


def _referenced_source_stems(abs_path: Path, source_stems: frozenset[str]) -> set[str]:
    """Source stems a test file IMPORTS — the language-agnostic usage signal.

    A test that imports a source symbol (``import com.x.Money``,
    ``from src.checkout_flow import run``) is exercising it regardless of the
    test's filename. Identifiers are read ONLY from import-style lines
    (:data:`_IMPORT_LINE_RES`), never arbitrary code/comments: an incidental
    mention of a common-word stem (``order``, ``config``) in a comment or local
    must not fabricate an edge that would clear a genuinely-uncovered source off
    the risk surface. Only stems of at least ``_MIN_USAGE_STEM_LEN`` chars are
    considered. Reads at most ``_MAX_TEST_READ_BYTES``; an unreadable file
    yields no references rather than raising."""
    candidates = {s for s in source_stems if len(s) >= _MIN_USAGE_STEM_LEN}
    if not candidates:
        return set()
    try:
        text = abs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    tokens: set[str] = set()
    for line in text[:_MAX_TEST_READ_BYTES].splitlines():
        if any(pattern.search(line) for pattern in _IMPORT_LINE_RES):
            tokens.update(_IDENT_RE.findall(line))
    return candidates & tokens


def _fingerprint(abs_path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with abs_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()


def _infer_likely_tests_edges(nodes: list[RepoMapNode], root_path: Path) -> list[RepoMapEdge]:
    """Infer ``likely_tests`` edges from two language-agnostic signals (#266).

    For each test file: a name-convention signal (snake_case / dotted JS-TS /
    CamelCase, via :func:`_normalise_test_stem`) and a usage signal (the test's
    content references a source stem, via :func:`_referenced_source_stems`). A
    pair found by both collapses to one corroborated edge. Confidence is
    ``high`` for a unique name match or a name+usage corroboration, ``medium``
    for an ambiguous-name-only or usage-only match. Output is sorted for
    determinism."""
    sources_by_stem: dict[str, list[RepoMapNode]] = {}
    source_by_id: dict[str, RepoMapNode] = {}
    for node in nodes:
        if node.type == "source_file":
            sources_by_stem.setdefault(Path(node.path).stem, []).append(node)
            source_by_id[node.id] = node
    source_stems = frozenset(sources_by_stem)

    # (test_id, source_id) -> edge, so a pair found by both signals is one edge.
    edges_by_pair: dict[tuple[str, str], RepoMapEdge] = {}

    for node in nodes:
        if node.type != "test_file":
            continue
        test_stem = Path(node.path).stem

        name_target = _normalise_test_stem(test_stem)
        name_sources = sources_by_stem.get(name_target, []) if name_target else []
        name_is_unique = len(name_sources) == 1
        usage_stems = _referenced_source_stems(root_path / node.path, source_stems)

        # source_id -> set of signals ("name", "usage") that found it.
        signals: dict[str, set[str]] = {}
        for source in name_sources:
            signals.setdefault(source.id, set()).add("name")
        for stem in usage_stems:
            for source in sources_by_stem.get(stem, []):
                signals.setdefault(source.id, set()).add("usage")

        for source_id, sigs in signals.items():
            has_name = "name" in sigs
            has_usage = "usage" in sigs
            confidence: EdgeConfidence
            if has_name and (name_is_unique or has_usage):
                confidence = "high"
            else:
                confidence = "medium"
            reasons: list[str] = []
            if has_name:
                reasons.append(f"name convention: {test_stem} -> {name_target}")
            if has_usage:
                reasons.append(f"usage: references {Path(source_by_id[source_id].path).stem}")
            edges_by_pair[(node.id, source_id)] = RepoMapEdge(
                source=node.id,
                target=source_id,
                type="likely_tests",
                confidence=confidence,
                reason="; ".join(reasons),
            )
    return sorted(edges_by_pair.values(), key=lambda e: (e.source, e.target))


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
