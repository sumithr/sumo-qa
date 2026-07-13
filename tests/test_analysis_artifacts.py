# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for #147 coverage/mutation artifact consumption (issue #212 AC#5)."""

from __future__ import annotations

import json
from pathlib import Path

from sumo_qa.analysis.artifacts import (
    _first_line,
    load_coverage_signal,
    load_mutation_signal,
)


def _write(root: Path, relpath: str, payload: object) -> None:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    target.write_text(text, encoding="utf-8")


def test_absent_coverage_is_clean_none_none(tmp_path):
    signal, fallback = load_coverage_signal(tmp_path)
    assert signal is None
    assert fallback is None


def test_valid_coverage_maps_to_a_signal(tmp_path):
    _write(
        tmp_path,
        ".sumo-qa/coverage.json",
        {
            "schema_version": "1.0",
            "generated_at": "2026-07-02T00:00:00Z",
            "source_tool": "pytest-cov",
            "line_percent": 88.5,
            "freshness": "fresh",
        },
    )
    signal, fallback = load_coverage_signal(tmp_path)
    assert fallback is None
    assert signal is not None
    assert signal.line_percent == 88.5
    assert signal.freshness == "fresh"


def test_unparseable_coverage_json_is_an_invalid_artifact(tmp_path):
    _write(tmp_path, ".sumo-qa/coverage.json", "{not json")
    signal, fallback = load_coverage_signal(tmp_path)
    assert signal is None
    assert fallback is not None
    assert fallback.status == "invalid_artifact"


def test_non_object_coverage_json_is_an_invalid_artifact(tmp_path):
    _write(tmp_path, ".sumo-qa/coverage.json", [1, 2, 3])
    signal, fallback = load_coverage_signal(tmp_path)
    assert signal is None
    assert fallback is not None
    assert "not a JSON object" in fallback.message


def test_schema_mismatch_coverage_is_an_invalid_artifact(tmp_path):
    _write(
        tmp_path,
        ".sumo-qa/coverage.json",
        {"schema_version": "9.9", "generated_at": "x", "source_tool": "y"},
    )
    signal, fallback = load_coverage_signal(tmp_path)
    assert signal is None
    assert fallback is not None
    assert fallback.status == "invalid_artifact"


def test_absent_mutation_is_clean_none_none(tmp_path):
    signal, fallback = load_mutation_signal(tmp_path)
    assert signal is None
    assert fallback is None


def test_valid_mutation_maps_to_a_signal(tmp_path):
    _write(
        tmp_path,
        ".sumo-qa/mutation.json",
        {
            "schema_version": "1.0",
            "generated_at": "2026-07-02T00:00:00Z",
            "source_tool": "mutmut",
            "survivors": 3,
            "killed": 40,
            "freshness": "fresh",
        },
    )
    signal, fallback = load_mutation_signal(tmp_path)
    assert fallback is None
    assert signal is not None
    assert signal.survivors == 3
    assert signal.killed == 40


def test_invalid_mutation_artifact_is_surfaced(tmp_path):
    _write(tmp_path, ".sumo-qa/mutation.json", {"schema_version": "2.0"})
    signal, fallback = load_mutation_signal(tmp_path)
    assert signal is None
    assert fallback is not None
    assert fallback.status == "invalid_artifact"


def test_first_line_takes_the_first_line_of_a_multiline_message():
    exc = ValueError("first line\nsecond line")
    assert _first_line(exc) == "first line"


def test_first_line_falls_back_to_the_class_name_for_an_empty_message():
    assert _first_line(ValueError("")) == "ValueError"
