# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the persisted coverage/mutation artifact models + validation."""

from __future__ import annotations

import pytest

from sumo_qa.coverage_models import (
    CoverageArtifact,
    CoverageArtifactError,
    MutationArtifact,
    MutationArtifactError,
    load_coverage_artifact,
    load_mutation_artifact,
)


def test_coverage_artifact_maps_to_signal() -> None:
    art = load_coverage_artifact(
        {
            "schema_version": "1.0",
            "generated_at": "2026-06-12T18:46:00Z",
            "source_tool": "pytest-cov",
            "line_percent": 100.0,
            "freshness": "fresh",
            "detail": "changed-file gaps: none",
        }
    )
    assert isinstance(art, CoverageArtifact)
    sig = art.to_signal()
    assert sig.line_percent == 100.0
    assert sig.freshness == "fresh"
    assert sig.detail == "changed-file gaps: none"
    assert sig.has_measurement() is True


def test_coverage_measurementless_signal_collapses() -> None:
    art = load_coverage_artifact(
        {
            "schema_version": "1.0",
            "generated_at": "2026-06-12T18:46:00Z",
            "source_tool": "pytest-cov",
            "freshness": "fresh",
        }
    )
    # No line_percent supplied: the mapped signal carries no measurement.
    assert art.line_percent is None
    assert art.to_signal().has_measurement() is False


def test_coverage_default_freshness_is_unknown() -> None:
    art = load_coverage_artifact({"schema_version": "1.0", "generated_at": "x", "source_tool": "x"})
    assert art.freshness == "unknown"


def test_coverage_percent_out_of_range_rejected() -> None:
    with pytest.raises(CoverageArtifactError) as exc:
        load_coverage_artifact(
            {
                "schema_version": "1.0",
                "generated_at": "2026-06-12T18:46:00Z",
                "source_tool": "x",
                "line_percent": 101.0,
                "freshness": "fresh",
            }
        )
    assert exc.value.kind == "value_error"
    assert exc.value.path == "line_percent"


def test_coverage_schema_version_mismatch() -> None:
    with pytest.raises(CoverageArtifactError) as exc:
        load_coverage_artifact(
            {
                "schema_version": "2.0",
                "generated_at": "x",
                "source_tool": "x",
                "freshness": "fresh",
            }
        )
    assert exc.value.kind == "schema_version_mismatch"
    assert exc.value.path == "/schema_version"


def test_coverage_missing_required_field() -> None:
    with pytest.raises(CoverageArtifactError) as exc:
        load_coverage_artifact({"schema_version": "1.0", "source_tool": "x"})
    assert exc.value.kind == "missing_field"
    assert exc.value.path == "generated_at"


def test_coverage_extra_field_rejected() -> None:
    with pytest.raises(CoverageArtifactError) as exc:
        load_coverage_artifact(
            {
                "schema_version": "1.0",
                "generated_at": "x",
                "source_tool": "x",
                "freshness": "fresh",
                "bogus": 1,
            }
        )
    assert exc.value.kind == "unknown_field"


def test_coverage_bad_freshness_vocab() -> None:
    with pytest.raises(CoverageArtifactError) as exc:
        load_coverage_artifact(
            {
                "schema_version": "1.0",
                "generated_at": "x",
                "source_tool": "x",
                "freshness": "very-fresh",
            }
        )
    assert exc.value.kind == "vocab_error"
    assert exc.value.path == "freshness"


def test_mutation_artifact_maps_to_signal() -> None:
    art = load_mutation_artifact(
        {
            "schema_version": "1.0",
            "generated_at": "2026-06-12T18:46:00Z",
            "source_tool": "mutmut",
            "survivors": 2,
            "killed": 145,
            "freshness": "fresh",
            "detail": "survivors in scorecard_models",
        }
    )
    assert isinstance(art, MutationArtifact)
    sig = art.to_signal()
    assert (sig.survivors, sig.killed) == (2, 145)
    assert sig.freshness == "fresh"
    # The detail must map through — a dropped/None detail loses the survivor
    # location the report surfaces.
    assert sig.detail == "survivors in scorecard_models"
    assert sig.has_measurement() is True


def test_mutation_measurementless_signal_collapses() -> None:
    art = load_mutation_artifact(
        {
            "schema_version": "1.0",
            "generated_at": "x",
            "source_tool": "mutmut",
            "freshness": "fresh",
        }
    )
    assert art.to_signal().has_measurement() is False


def test_mutation_negative_count_rejected() -> None:
    with pytest.raises(MutationArtifactError) as exc:
        load_mutation_artifact(
            {
                "schema_version": "1.0",
                "generated_at": "x",
                "source_tool": "x",
                "survivors": -1,
                "freshness": "fresh",
            }
        )
    assert exc.value.kind == "value_error"
    assert exc.value.path == "survivors"
    # The underlying validator message must survive into the error, not be
    # dropped — the host reads it to know WHY the artifact was rejected.
    assert "non-negative" in exc.value.message


def test_mutation_schema_version_mismatch_int() -> None:
    # A non-string version is still a mismatch, not a confusing type error.
    with pytest.raises(MutationArtifactError) as exc:
        load_mutation_artifact({"schema_version": 2, "generated_at": "x", "source_tool": "x"})
    assert exc.value.kind == "schema_version_mismatch"
    # The mismatch message names both the found and expected versions.
    assert "schema_version is 2" in exc.value.message
    assert "this build expects" in exc.value.message


def test_coverage_wrong_type_classified_as_type_error() -> None:
    # A non-numeric line_percent fails Pydantic type parsing (not the range
    # validator), exercising the _classify default branch.
    with pytest.raises(CoverageArtifactError) as exc:
        load_coverage_artifact(
            {
                "schema_version": "1.0",
                "generated_at": "x",
                "source_tool": "x",
                "line_percent": "not-a-number",
                "freshness": "fresh",
            }
        )
    assert exc.value.kind == "type_error"
    assert exc.value.path == "line_percent"


def test_artifact_error_formats_kind_path_and_message() -> None:
    # The error string is what the MCP envelope surfaces; assert every part
    # (kind, the " at <path>" location, the message) so the construction can't
    # silently drop one and still "pass".
    err = CoverageArtifactError(kind="value_error", message="bad value", path="line_percent")
    assert err.kind == "value_error"
    assert err.message == "bad value"
    assert err.path == "line_percent"
    assert str(err) == "[value_error] at line_percent: bad value"


def test_artifact_error_without_path_omits_location() -> None:
    # A path-less error renders no " at ..." segment — pins the empty-string
    # branch so a non-empty placeholder can't sneak in.
    err = MutationArtifactError(kind="type_error", message="boom", path=None)
    assert err.path is None
    assert str(err) == "[type_error]: boom"
    assert " at " not in str(err)
