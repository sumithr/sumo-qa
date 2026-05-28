# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.repo_map_models — the first-slice repo-map schema."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sumo_qa.repo_map_models import (
    SCHEMA_VERSION,
    RepoMap,
    RepoMapCommand,
    RepoMapEdge,
    RepoMapNode,
    RepoMapProject,
    RepoMapWarning,
)


@pytest.fixture
def project() -> RepoMapProject:
    return RepoMapProject(
        root="/repo",
        name="example",
        git_commit="abc123",
        generated_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        generator_version="sumo-qa 0.16.0",
    )


def test_schema_version_constant_is_one_dot_zero():
    assert SCHEMA_VERSION == "1.0"


def test_repo_map_round_trip_preserves_fields(project: RepoMapProject):
    original = RepoMap(
        schema_version=SCHEMA_VERSION,
        project=project,
        nodes=[
            RepoMapNode(id="file:src/app.py", type="source_file", path="src/app.py"),
        ],
        edges=[
            RepoMapEdge(
                source="file:tests/test_app.py",
                target="file:src/app.py",
                type="likely_tests",
                confidence="medium",
                reason="path/name convention",
            ),
        ],
        commands=[RepoMapCommand(name="pytest", kind="test", source="pyproject.toml")],
        warnings=[RepoMapWarning(kind="skipped_file", message="binary skipped", path="bin/x")],
    )
    rebuilt = RepoMap.model_validate(original.model_dump(mode="json"))
    assert rebuilt == original
    assert rebuilt.schema_version == "1.0"


def test_repo_map_defaults_collections_to_empty(project: RepoMapProject):
    minimal = RepoMap(schema_version=SCHEMA_VERSION, project=project)
    assert minimal.nodes == []
    assert minimal.edges == []
    assert minimal.commands == []
    assert minimal.warnings == []


def test_repo_map_requires_explicit_schema_version(project: RepoMapProject):
    # Missing schema_version on a JSON payload must NOT silently default —
    # a versioned artifact has to carry its version stamp explicitly so
    # producers that forgot to stamp the field can't sneak past validation.
    with pytest.raises(ValidationError):
        RepoMap.model_validate({"project": project.model_dump(mode="json")})


def test_repo_map_rejects_unknown_top_level_field(project: RepoMapProject):
    with pytest.raises(ValidationError):
        RepoMap.model_validate(
            {
                "schema_version": "1.0",
                "project": project.model_dump(mode="json"),
                "nodes": [],
                "edges": [],
                "rogue_top_level": True,
            }
        )


def test_repo_map_rejects_drifted_schema_version(project: RepoMapProject):
    with pytest.raises(ValidationError):
        RepoMap.model_validate(
            {
                "schema_version": "2.0",
                "project": project.model_dump(mode="json"),
                "nodes": [],
                "edges": [],
            }
        )


def test_project_requires_generated_at_and_generator_version():
    with pytest.raises(ValidationError) as excinfo:
        RepoMapProject(root="/repo")  # type: ignore[call-arg]
    msg = str(excinfo.value)
    assert "generated_at" in msg
    assert "generator_version" in msg


def test_project_rejects_unknown_field():
    with pytest.raises(ValidationError):
        RepoMapProject(
            root="/repo",
            generated_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            generator_version="x",
            rogue="hi",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "node_type",
    [
        "source_file",
        "test_file",
        "docs",
        "config",
        "ci_workflow",
        "manifest",
        "fixture",
        "migration_schema",
        "infrastructure",
    ],
)
def test_node_accepts_first_slice_types(node_type: str):
    RepoMapNode(id=f"file:x.{node_type}", type=node_type, path="x")


def test_node_rejects_out_of_catalogue_type():
    with pytest.raises(ValidationError):
        RepoMapNode(id="file:x", type="something_invented", path="x")  # type: ignore[arg-type]


def test_node_rejects_unknown_field():
    with pytest.raises(ValidationError):
        RepoMapNode(id="file:x", type="source_file", path="x", rogue=True)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "edge_type",
    ["likely_tests", "imports", "configured_by"],
)
def test_edge_accepts_first_slice_types(edge_type: str):
    RepoMapEdge(source="a", target="b", type=edge_type, confidence="low", reason="r")


def test_edge_rejects_out_of_catalogue_type():
    with pytest.raises(ValidationError):
        RepoMapEdge(
            source="a",
            target="b",
            type="some_other_link",  # type: ignore[arg-type]
            confidence="low",
            reason="r",
        )


def test_edge_rejects_deferred_command_runs_type():
    # command_runs is deliberately deferred to slice 2 — see EdgeType definition.
    with pytest.raises(ValidationError):
        RepoMapEdge(
            source="a",
            target="b",
            type="command_runs",  # type: ignore[arg-type]
            confidence="low",
            reason="r",
        )


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_edge_accepts_known_confidence_levels(confidence: str):
    RepoMapEdge(source="a", target="b", type="imports", confidence=confidence, reason="r")


def test_edge_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        RepoMapEdge(
            source="a",
            target="b",
            type="imports",
            confidence="absolute",  # type: ignore[arg-type]
            reason="r",
        )


@pytest.mark.parametrize("kind", ["test", "build", "lint", "format", "ci_job", "other"])
def test_command_accepts_first_slice_kinds(kind: str):
    RepoMapCommand(name=f"{kind}-cmd", kind=kind, source="pyproject.toml")


def test_command_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        RepoMapCommand(
            name="x",
            kind="deploy",  # type: ignore[arg-type]
            source="pyproject.toml",
        )


@pytest.mark.parametrize(
    "kind",
    ["skipped_file", "unsupported_language", "stale", "schema_drift", "other"],
)
def test_warning_accepts_first_slice_kinds(kind: str):
    RepoMapWarning(kind=kind, message="...")


def test_warning_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        RepoMapWarning(
            kind="weird_thing",  # type: ignore[arg-type]
            message="...",
        )


def test_warning_optional_path_round_trips():
    w = RepoMapWarning(kind="skipped_file", message="binary", path="bin/x")
    assert w.path == "bin/x"


def test_project_rejects_naive_datetime():
    with pytest.raises(ValidationError) as excinfo:
        RepoMapProject(
            root="/repo",
            generated_at=datetime(2026, 5, 28),
            generator_version="x",
        )
    assert "timezone-aware" in str(excinfo.value)


def test_project_accepts_non_utc_aware_datetime():
    from datetime import timedelta

    bst = timezone(timedelta(hours=1))
    project = RepoMapProject(
        root="/repo",
        generated_at=datetime(2026, 5, 28, 10, 0, 0, tzinfo=bst),
        generator_version="x",
    )
    assert project.generated_at.tzinfo is not None


def test_node_accepts_canonical_sha256_fingerprint():
    node = RepoMapNode(
        id="file:x",
        type="source_file",
        path="x",
        fingerprint="sha256:" + "0" * 64,
    )
    assert node.fingerprint is not None


def test_node_accepts_none_fingerprint():
    node = RepoMapNode(id="file:x", type="source_file", path="x", fingerprint=None)
    assert node.fingerprint is None


@pytest.mark.parametrize(
    "bad_fingerprint",
    [
        "md5:" + "a" * 32,
        "sha256:short",
        "sha256:" + "Z" * 64,
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "0" * 64,
    ],
)
def test_node_rejects_malformed_fingerprint(bad_fingerprint: str):
    with pytest.raises(ValidationError):
        RepoMapNode(id="file:x", type="source_file", path="x", fingerprint=bad_fingerprint)


def test_repo_map_rejects_duplicate_node_ids(project: RepoMapProject):
    with pytest.raises(ValidationError) as excinfo:
        RepoMap(
            schema_version=SCHEMA_VERSION,
            project=project,
            nodes=[
                RepoMapNode(id="file:dup", type="source_file", path="a"),
                RepoMapNode(id="file:dup", type="source_file", path="b"),
            ],
        )
    assert "duplicate node id" in str(excinfo.value)


def test_node_rejects_fingerprint_with_trailing_newline():
    # re.match with `$` would accept the newline; fullmatch closes the gap.
    with pytest.raises(ValidationError):
        RepoMapNode(
            id="file:x",
            type="source_file",
            path="x",
            fingerprint="sha256:" + "0" * 64 + "\n",
        )
