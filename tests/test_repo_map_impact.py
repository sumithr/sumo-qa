# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the slice-4 diff-impact core (issue #156)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumo_qa.repo_map_models import DiffImpact, ImpactNode


def test_impact_node_minimal_shape():
    n = ImpactNode(id="file:src/a.py", type="source_file", path="src/a.py", has_mapped_tests=True)
    assert n.has_mapped_tests is True
    assert n.path == "src/a.py"


def test_impact_node_forbids_extra():
    with pytest.raises(ValidationError):
        ImpactNode(id="x", type="source_file", path="x", has_mapped_tests=False, bogus=1)


def test_diff_impact_defaults_are_empty_lists():
    d = DiffImpact()
    assert d.changed_nodes == []
    assert d.affected_nodes == []
    assert d.related_tests == []
    assert d.unmapped_files == []
    assert d.risk_surface == []
    assert d.suggested_inspections == []
    assert d.warnings == []
