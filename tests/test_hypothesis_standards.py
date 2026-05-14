# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sumo_qa.standards import StandardsEngine, StandardsEvaluation

ROOT = Path(__file__).resolve().parents[1]
_STANDARDS_PATH = ROOT / "standards" / "packs"


def _engine() -> StandardsEngine:
    return StandardsEngine.from_directory(_STANDARDS_PATH)


def _known_workflows() -> list[str]:
    """All workflow strings declared in any check across all loaded packs."""
    engine = _engine()
    workflows: set[str] = set()
    for pack in engine._packs:
        for check in pack.checks:
            workflows.update(check.applies_to)
    return sorted(workflows)


# ---------------------------------------------------------------------------
# Test 1 — known workflows yield at least one matched check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow", _known_workflows())
def test_known_workflow_has_applicable_checks(workflow: str) -> None:
    """Every workflow string declared in a pack must produce ≥1 matched check."""
    result = _engine().evaluate(workflow)
    assert isinstance(result, StandardsEvaluation)
    assert result.checks, f"Known workflow {workflow!r} should have at least one applicable check"


# ---------------------------------------------------------------------------
# Test 2 — evaluate is total: never raises, never returns None
# ---------------------------------------------------------------------------


@given(workflow=st.text(min_size=1, max_size=50))
def test_evaluate_is_total_over_arbitrary_strings(workflow: str) -> None:
    """evaluate() must return a StandardsEvaluation for any non-empty string."""
    result = _engine().evaluate(workflow)
    assert isinstance(result, StandardsEvaluation)


# ---------------------------------------------------------------------------
# Test 3 — evaluate is deterministic for the same engine instance
# ---------------------------------------------------------------------------


@given(workflow=st.text(min_size=1, max_size=50))
def test_evaluate_is_deterministic(workflow: str) -> None:
    """Two consecutive calls on the same engine with the same input must agree."""
    engine = _engine()
    first = engine.evaluate(workflow)
    second = engine.evaluate(workflow)
    assert first == second


# ---------------------------------------------------------------------------
# Test 4 — workflow field in result always echoes the input
# ---------------------------------------------------------------------------


@given(workflow=st.text(min_size=1, max_size=50))
def test_evaluate_echoes_workflow_field(workflow: str) -> None:
    """The `workflow` field in the returned StandardsEvaluation must equal the input."""
    result = _engine().evaluate(workflow)
    assert result.workflow == workflow
