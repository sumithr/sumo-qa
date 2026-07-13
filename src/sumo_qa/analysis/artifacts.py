# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Consume #147 coverage / mutation artifacts as analysis signals (#212, AC#5).

REUSES the #147 model layer (:mod:`sumo_qa.coverage_models`) — it does NOT
redefine the artifact shape. ``load_coverage_signal`` / ``load_mutation_signal``
read the conventional ``.sumo-qa`` files and return the scorecard signal plus an
optional fallback:

* an ABSENT file is a clean ``(None, None)`` — the dimension is simply not
  measured, never an error (issue #212: coverage/mutation ignored cleanly when
  absent);
* a PRESENT-but-malformed file is ``(None, invalid_artifact fallback)`` so a
  broken artifact is SURFACED, not silently dropped.

The relative paths mirror :mod:`sumo_qa.report_builder` so this layer reads the
exact files #147's writer produces.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from sumo_qa.analysis.contracts import AnalysisFallback
from sumo_qa.coverage_models import (
    CoverageArtifact,
    CoverageArtifactError,
    MutationArtifact,
    MutationArtifactError,
    load_coverage_artifact,
    load_mutation_artifact,
)
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal

COVERAGE_RELPATH = ".sumo-qa/coverage.json"
MUTATION_RELPATH = ".sumo-qa/mutation.json"


def _first_line(exc: Exception) -> str:
    """Collapse an exception to its first line (envelope errors carry their
    ``[kind]`` prefix there; multi-line pydantic dumps get truncated)."""
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else exc.__class__.__name__


def _load_artifact(
    root: Path | str,
    relpath: str,
    loader: Callable[[dict], CoverageArtifact | MutationArtifact],
    error_type: type[CoverageArtifactError] | type[MutationArtifactError],
) -> tuple[CoverageArtifact | MutationArtifact | None, AnalysisFallback | None]:
    """Read + validate one ``.sumo-qa`` artifact, mapping each failure mode to an
    honest outcome: absent file -> ``(None, None)``; unparseable/non-object JSON
    or loader rejection -> ``(None, invalid_artifact fallback)``. Never raises."""
    target = Path(root) / relpath
    if not target.is_file():
        return None, None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, AnalysisFallback(
            status="invalid_artifact", subject=relpath, message=_first_line(exc)
        )
    if not isinstance(data, dict):
        return None, AnalysisFallback(
            status="invalid_artifact",
            subject=relpath,
            message="artifact root is not a JSON object",
        )
    try:
        artifact = loader(data)
    except error_type as exc:
        return None, AnalysisFallback(
            status="invalid_artifact", subject=relpath, message=_first_line(exc)
        )
    return artifact, None


def load_coverage_signal(
    root: Path | str,
) -> tuple[CoverageSignal | None, AnalysisFallback | None]:
    """The coverage signal from ``root/.sumo-qa/coverage.json`` (#147 reuse)."""
    artifact, fallback = _load_artifact(
        root, COVERAGE_RELPATH, load_coverage_artifact, CoverageArtifactError
    )
    if artifact is None:
        return None, fallback
    assert isinstance(artifact, CoverageArtifact)  # narrow for type-checkers
    return artifact.to_signal(), None


def load_mutation_signal(
    root: Path | str,
) -> tuple[MutationSignal | None, AnalysisFallback | None]:
    """The mutation signal from ``root/.sumo-qa/mutation.json`` (#147 reuse)."""
    artifact, fallback = _load_artifact(
        root, MUTATION_RELPATH, load_mutation_artifact, MutationArtifactError
    )
    if artifact is None:
        return None, fallback
    assert isinstance(artifact, MutationArtifact)  # narrow for type-checkers
    return artifact.to_signal(), None
