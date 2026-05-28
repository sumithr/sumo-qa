# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.repo_map_scanner — slice-2 deterministic local walker."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sumo_qa.repo_map_models import RepoMap
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_validation import load_repo_map


def _git_init(path: Path) -> None:
    """Create a minimal git repo so scan_repo's git-ls-files path is exercised."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


def _git_add_and_commit(path: Path) -> str:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init", "--no-gpg-sign"],
        cwd=path,
        check=True,
    )
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, check=True)
    return result.stdout.decode().strip()


def _make_file(root: Path, rel: str, content: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------- Argument validation ----------


def test_scan_repo_rejects_non_directory(tmp_path: Path):
    f = tmp_path / "not-a-dir"
    f.write_text("x")
    with pytest.raises(ValueError, match="must be a directory"):
        scan_repo(f, generator_version="t")


def test_scan_repo_rejects_missing_path(tmp_path: Path):
    with pytest.raises(ValueError, match="must be a directory"):
        scan_repo(tmp_path / "nope", generator_version="t")


# ---------- Smoke: produces a valid RepoMap ----------


def test_scan_repo_returns_validated_repo_map(tmp_path: Path):
    _make_file(tmp_path, "README.md", "# x")
    repo_map = scan_repo(tmp_path, generator_version="sumo-qa-test")
    assert isinstance(repo_map, RepoMap)
    assert repo_map.schema_version == "1.0"
    assert repo_map.project.generator_version == "sumo-qa-test"
    assert repo_map.project.root == str(tmp_path.resolve())
    assert repo_map.project.generated_at.tzinfo is not None


def test_scan_repo_dumps_then_loads_through_validation(tmp_path: Path):
    _make_file(tmp_path, "README.md", "# x")
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    _make_file(tmp_path, "tests/test_app.py", "def test_x():\n    pass\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    rebuilt = load_repo_map(repo_map.model_dump(mode="json"))
    assert rebuilt == repo_map


# ---------- Determinism ----------


def test_scan_repo_is_deterministic_across_invocations(tmp_path: Path):
    _make_file(tmp_path, "src/a.py", "x\n")
    _make_file(tmp_path, "src/b.py", "y\n")
    _make_file(tmp_path, "tests/test_a.py", "pass\n")
    first = scan_repo(tmp_path, generator_version="t")
    second = scan_repo(tmp_path, generator_version="t")
    # generated_at varies; everything else must match.
    assert [n.model_dump() for n in first.nodes] == [n.model_dump() for n in second.nodes]
    assert [e.model_dump() for e in first.edges] == [e.model_dump() for e in second.edges]
    assert [c.model_dump() for c in first.commands] == [c.model_dump() for c in second.commands]


def test_scan_repo_orders_nodes_by_path(tmp_path: Path):
    _make_file(tmp_path, "z/last.py", "x\n")
    _make_file(tmp_path, "a/first.py", "x\n")
    _make_file(tmp_path, "m/middle.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    paths = [n.path for n in repo_map.nodes]
    assert paths == sorted(paths)


# ---------- git ls-files vs fallback walk ----------


def test_scan_repo_uses_git_ls_files_when_available(tmp_path: Path):
    _git_init(tmp_path)
    _make_file(tmp_path, "tracked.py", "x\n")
    _make_file(tmp_path, "ignored.py", "x\n")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    sha = _git_add_and_commit(tmp_path)

    repo_map = scan_repo(tmp_path, generator_version="t")
    paths = {n.path for n in repo_map.nodes}
    assert "tracked.py" in paths
    assert "ignored.py" not in paths  # gitignored, not tracked
    assert repo_map.project.git_commit == sha


def test_scan_repo_falls_back_to_walk_outside_git(tmp_path: Path):
    _make_file(tmp_path, "a.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert {n.path for n in repo_map.nodes} == {"a.py"}
    assert repo_map.project.git_commit is None


def test_fallback_walk_skips_known_caches(tmp_path: Path):
    _make_file(tmp_path, "src/app.py", "x\n")
    _make_file(tmp_path, "__pycache__/cache.pyc", "x\n")
    _make_file(tmp_path, "node_modules/dep/index.js", "x\n")
    _make_file(tmp_path, ".venv/lib/site.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    paths = {n.path for n in repo_map.nodes}
    assert "src/app.py" in paths
    assert not any("__pycache__" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any(".venv" in p for p in paths)


# ---------- Classification ----------


@pytest.mark.parametrize(
    "rel,expected_type",
    [
        ("src/app.py", "source_file"),
        ("lib/widget.ts", "source_file"),
        ("tests/test_app.py", "test_file"),
        ("tests/app_test.py", "test_file"),
        ("src/foo.test.ts", "test_file"),
        ("README.md", "docs"),
        ("docs/guide.md", "docs"),
        ("pyproject.toml", "manifest"),
        ("package.json", "manifest"),
        (".github/workflows/ci.yml", "ci_workflow"),
        ("tests/fixtures/sample.json", "fixture"),
        ("migrations/0001_init.sql", "migration_schema"),
        ("db/schema.sql", "migration_schema"),
        ("Dockerfile", "infrastructure"),
        ("infra/main.tf", "infrastructure"),
        ("config.yaml", "config"),
    ],
)
def test_classify_each_first_slice_kind(tmp_path: Path, rel: str, expected_type: str):
    _make_file(tmp_path, rel, "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    matching = [n for n in repo_map.nodes if n.path == rel]
    assert len(matching) == 1, f"expected one node for {rel}, got {repo_map.nodes}"
    assert matching[0].type == expected_type


@pytest.mark.parametrize("name", ["Jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml"])
def test_ci_workflow_by_filename_at_root(tmp_path: Path, name: str):
    _make_file(tmp_path, name, "pipeline:\n  - x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    matching = [n for n in repo_map.nodes if n.path == name]
    assert len(matching) == 1
    assert matching[0].type == "ci_workflow"


def test_test_file_prefix_outside_tests_directory(tmp_path: Path):
    # A test_ prefix in an unrelated directory should still classify as test_file,
    # exercising the second branch of _looks_like_test (not the parts check).
    _make_file(tmp_path, "scripts/test_helper.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    matching = [n for n in repo_map.nodes if n.path == "scripts/test_helper.py"]
    assert len(matching) == 1
    assert matching[0].type == "test_file"


def test_unclassifiable_file_surfaces_warning(tmp_path: Path):
    _make_file(tmp_path, "something.xyz", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert not any(n.path == "something.xyz" for n in repo_map.nodes)
    assert any(
        w.kind == "unsupported_language" and w.path == "something.xyz" for w in repo_map.warnings
    )


def test_binary_extension_skipped_with_warning(tmp_path: Path):
    _make_file(tmp_path, "logo.png", "PNGDATA")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert not any(n.path == "logo.png" for n in repo_map.nodes)
    assert any(
        w.kind == "skipped_file" and w.path == "logo.png" and "binary" in w.message
        for w in repo_map.warnings
    )


# ---------- Language detection ----------


def test_language_set_on_known_extensions(tmp_path: Path):
    _make_file(tmp_path, "src/x.py", "x\n")
    _make_file(tmp_path, "src/y.ts", "x\n")
    _make_file(tmp_path, "config.yaml", "x: 1\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    lang = {n.path: n.language for n in repo_map.nodes}
    assert lang["src/x.py"] == "python"
    assert lang["src/y.ts"] == "typescript"
    assert lang["config.yaml"] == "yaml"


# ---------- Fingerprinting ----------


def test_fingerprint_is_canonical_sha256(tmp_path: Path):
    _make_file(tmp_path, "src/app.py", "deterministic\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    node = next(n for n in repo_map.nodes if n.path == "src/app.py")
    # SHA-256 of "deterministic\n" — locks the fingerprint shape and content.
    assert node.fingerprint == (
        "sha256:d7db64ea975b7b358e3d68dcbc82437869a410a29b9da7de119c422abf61c3d0"
    )


def test_fingerprint_returns_none_on_read_error(tmp_path: Path):
    # Test the internal helper directly: a path that can't be opened (no such
    # file) must return None rather than raising — keeps scan_repo robust on
    # races between ls-files enumeration and per-file read.
    from sumo_qa.repo_map_scanner import _fingerprint

    assert _fingerprint(tmp_path / "vanished.py") is None


def test_fingerprint_changes_with_content(tmp_path: Path):
    _make_file(tmp_path, "src/a.py", "one\n")
    first = scan_repo(tmp_path, generator_version="t")
    _make_file(tmp_path, "src/a.py", "two\n")
    second = scan_repo(tmp_path, generator_version="t")
    fps_first = {n.path: n.fingerprint for n in first.nodes}
    fps_second = {n.path: n.fingerprint for n in second.nodes}
    assert fps_first["src/a.py"] != fps_second["src/a.py"]


# ---------- Likely-tests edge inference ----------


def test_likely_tests_edge_high_confidence_for_unique_match(tmp_path: Path):
    _make_file(tmp_path, "src/payments.py", "x\n")
    _make_file(tmp_path, "tests/test_payments.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    edges = [e for e in repo_map.edges if e.type == "likely_tests"]
    assert len(edges) == 1
    assert edges[0].source == "file:tests/test_payments.py"
    assert edges[0].target == "file:src/payments.py"
    assert edges[0].confidence == "high"


def test_likely_tests_edge_medium_confidence_when_ambiguous(tmp_path: Path):
    # Two source files share the same stem; the matcher can't pick one.
    _make_file(tmp_path, "src/widget.py", "x\n")
    _make_file(tmp_path, "lib/widget.py", "x\n")
    _make_file(tmp_path, "tests/test_widget.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    edges = [e for e in repo_map.edges if e.type == "likely_tests"]
    assert len(edges) == 2
    assert all(e.confidence == "medium" for e in edges)


def test_likely_tests_edge_handles_underscore_suffix(tmp_path: Path):
    _make_file(tmp_path, "src/widget.py", "x\n")
    _make_file(tmp_path, "tests/widget_test.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    edges = [e for e in repo_map.edges if e.type == "likely_tests"]
    assert len(edges) == 1
    assert edges[0].target == "file:src/widget.py"


def test_no_edge_when_test_has_no_source_match(tmp_path: Path):
    _make_file(tmp_path, "tests/test_orphan.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert not any(e.type == "likely_tests" for e in repo_map.edges)


def test_edges_are_sorted_deterministically(tmp_path: Path):
    _make_file(tmp_path, "src/a.py", "x\n")
    _make_file(tmp_path, "src/b.py", "x\n")
    _make_file(tmp_path, "tests/test_b.py", "x\n")
    _make_file(tmp_path, "tests/test_a.py", "x\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    edges = repo_map.edges
    assert edges == sorted(edges, key=lambda e: (e.source, e.target))


# ---------- Command extraction ----------


def test_extract_commands_from_pyproject_scripts(tmp_path: Path):
    _make_file(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "x"\nversion = "1"\n\n[project.scripts]\nfoo = "x:main"\n',
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    cmds = {c.name: c for c in repo_map.commands}
    assert "foo" in cmds
    assert cmds["foo"].source == "pyproject.toml"
    assert cmds["foo"].raw == "x:main"


def test_extract_commands_from_package_json_scripts(tmp_path: Path):
    _make_file(
        tmp_path,
        "package.json",
        json.dumps({"name": "x", "scripts": {"test": "vitest", "lint": "eslint ."}}),
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    by_name = {c.name: c for c in repo_map.commands}
    assert by_name["test"].kind == "test"
    assert by_name["lint"].kind == "lint"
    assert by_name["test"].source == "package.json"


def test_package_json_kind_guess_covers_known_verbs(tmp_path: Path):
    scripts = {
        "test": "x",
        "lint": "x",
        "format": "x",
        "build": "x",
        "deploy": "x",  # falls back to "other"
    }
    _make_file(tmp_path, "package.json", json.dumps({"scripts": scripts}))
    repo_map = scan_repo(tmp_path, generator_version="t")
    by_name = {c.name: c.kind for c in repo_map.commands}
    assert by_name["test"] == "test"
    assert by_name["lint"] == "lint"
    assert by_name["format"] == "format"
    assert by_name["build"] == "build"
    assert by_name["deploy"] == "other"


def test_pyproject_with_no_scripts_yields_no_commands(tmp_path: Path):
    _make_file(tmp_path, "pyproject.toml", '[project]\nname = "x"\nversion = "1"\n')
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert repo_map.commands == []


def test_malformed_pyproject_does_not_crash(tmp_path: Path):
    _make_file(tmp_path, "pyproject.toml", "this is not toml = = =\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert repo_map.commands == []


def test_malformed_package_json_does_not_crash(tmp_path: Path):
    _make_file(tmp_path, "package.json", "{not json")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert repo_map.commands == []


def test_commands_are_sorted_deterministically(tmp_path: Path):
    _make_file(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "x"\nversion = "1"\n\n[project.scripts]\nzeta = "x:m"\nalpha = "y:m"\n',
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    names = [c.name for c in repo_map.commands]
    assert names == sorted(names)
