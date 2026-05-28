# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.repo_map_validation — load + actionable error envelope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumo_qa.repo_map_models import RepoMap
from sumo_qa.repo_map_validation import RepoMapValidationError, load_repo_map

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "repo_map" / "repo-map.example.json"


def _valid_payload() -> dict:
    return {
        "schema_version": "1.0",
        "project": {
            "root": "/repo",
            "name": "example",
            "generated_at": "2026-05-28T00:00:00+00:00",
            "generator_version": "sumo-qa 0.16.0",
        },
        "nodes": [
            {"id": "file:src/app.py", "type": "source_file", "path": "src/app.py"},
        ],
        "edges": [],
        "commands": [],
        "warnings": [],
    }


def test_load_dict_returns_repo_map():
    repo_map = load_repo_map(_valid_payload())
    assert isinstance(repo_map, RepoMap)
    assert repo_map.schema_version == "1.0"
    assert repo_map.nodes[0].path == "src/app.py"


def test_load_path_returns_repo_map(tmp_path: Path):
    path = tmp_path / "repo-map.json"
    path.write_text(json.dumps(_valid_payload()), encoding="utf-8")
    repo_map = load_repo_map(path)
    assert repo_map.project.root == "/repo"


def test_load_str_path_is_accepted(tmp_path: Path):
    path = tmp_path / "repo-map.json"
    path.write_text(json.dumps(_valid_payload()), encoding="utf-8")
    repo_map = load_repo_map(str(path))
    assert repo_map.project.root == "/repo"


def test_load_missing_file_raises_io_error(tmp_path: Path):
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(tmp_path / "does-not-exist.json")
    assert excinfo.value.kind == "io_error"
    assert excinfo.value.source is not None


def test_load_malformed_json_raises_actionable_error(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(path)
    assert excinfo.value.kind == "malformed_json"
    assert "line" in str(excinfo.value)
    assert excinfo.value.source == str(path)


def test_load_drifted_schema_version_raises_stale_kind():
    payload = _valid_payload()
    payload["schema_version"] = "2.0"
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "schema_version_mismatch"
    assert excinfo.value.path == "/schema_version"
    assert "2.0" in str(excinfo.value)


def test_load_missing_required_field_raises_field_named_error():
    payload = _valid_payload()
    del payload["project"]["generated_at"]
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "missing_field"
    assert "generated_at" in excinfo.value.path


def test_load_unknown_field_raises_unknown_field_error():
    payload = _valid_payload()
    payload["project"]["rogue"] = "x"
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "unknown_field"
    assert "rogue" in excinfo.value.path


def test_load_out_of_catalogue_node_type_raises_vocab_error():
    payload = _valid_payload()
    payload["nodes"][0]["type"] = "not_in_catalogue"
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "vocab_error"


def test_load_wrong_collection_type_raises_type_error():
    payload = _valid_payload()
    payload["nodes"] = {"this": "should be a list"}
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "type_error"


def test_load_non_object_root_raises_type_error(tmp_path: Path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(path)
    assert excinfo.value.kind == "type_error"


def test_load_numeric_schema_version_does_not_short_circuit_as_mismatch():
    # Numeric 1.0 is a type problem, not a version-drift problem — the
    # pre-check is restricted to strings so Pydantic categorises this clearly.
    payload = _valid_payload()
    payload["schema_version"] = 1.0
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind != "schema_version_mismatch"


def test_load_null_schema_version_falls_through_to_pydantic():
    payload = _valid_payload()
    payload["schema_version"] = None
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind != "schema_version_mismatch"


def test_load_naive_datetime_in_generated_at_raises_type_error():
    payload = _valid_payload()
    payload["project"]["generated_at"] = "2026-05-28T00:00:00"
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    # Custom validators surface as Pydantic's value_error, which we category
    # as type_error to keep the slice-1 kind taxonomy compact.
    assert excinfo.value.kind == "type_error"
    assert "/project/generated_at" in excinfo.value.path


def test_load_malformed_fingerprint_raises_type_error():
    payload = _valid_payload()
    payload["nodes"][0]["fingerprint"] = "md5:nope"
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "type_error"
    assert "fingerprint" in excinfo.value.path


def test_load_duplicate_node_id_raises_type_error():
    payload = _valid_payload()
    payload["nodes"].append(
        {"id": payload["nodes"][0]["id"], "type": "source_file", "path": "dup.py"}
    )
    with pytest.raises(RepoMapValidationError) as excinfo:
        load_repo_map(payload)
    assert excinfo.value.kind == "type_error"
    assert "duplicate node id" in str(excinfo.value)


def test_fixture_artifact_round_trips():
    repo_map = load_repo_map(FIXTURE_PATH)
    rebuilt = RepoMap.model_validate(repo_map.model_dump(mode="json"))
    assert rebuilt == repo_map


def test_repo_map_validation_error_str_includes_kind_and_path():
    err = RepoMapValidationError(
        kind="missing_field",
        message="Field required",
        path="/project/generated_at",
    )
    s = str(err)
    assert "[missing_field]" in s
    assert "/project/generated_at" in s
    assert "Field required" in s


def test_repo_map_validation_error_str_without_path_omits_at_clause():
    err = RepoMapValidationError(kind="io_error", message="no such file")
    s = str(err)
    assert "[io_error]" in s
    assert " at " not in s
