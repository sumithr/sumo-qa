# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Hypothesis property tests for sumo_qa.knowledge_loaders.

Covers invariants that happy-path unit tests cannot pin:
  - Every no-arg loader returns non-empty markdown starting with '#'.
  - Both filter loaders are total over arbitrary string inputs (never raise).
  - Passing None explicitly equals calling with no argument.
  - Filtered output is always a subset (length) of unfiltered output.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sumo_qa import knowledge_loaders as kl

NO_ARG_LOADERS = [
    kl.sumo_qa_load_classifications,
    kl.sumo_qa_load_approaches,
    kl.sumo_qa_load_principles,
    kl.sumo_qa_load_techniques,
]


@pytest.mark.parametrize("loader", NO_ARG_LOADERS, ids=lambda f: f.__name__)
def test_no_arg_loader_returns_non_empty_markdown(loader) -> None:
    """Each no-arg loader must return a non-empty str starting with '#'."""
    result = loader()
    assert isinstance(result, str)
    assert len(result) > 0
    assert result.lstrip().startswith("#"), (
        f"{loader.__name__} should return markdown starting with #, got: {result[:80]!r}"
    )


@given(classification=st.text(min_size=0, max_size=50))
@settings(max_examples=100)
def test_load_standards_is_total_over_arbitrary_strings(classification: str) -> None:
    """sumo_qa_load_standards must never raise for any string input."""
    result = kl.sumo_qa_load_standards(classification)
    assert isinstance(result, str)


@given(classification=st.text(min_size=0, max_size=50))
@settings(max_examples=100)
def test_load_rules_is_total_over_arbitrary_strings(classification: str) -> None:
    """sumo_qa_load_rules must never raise for any string input."""
    result = kl.sumo_qa_load_rules(classification)
    assert isinstance(result, str)


def test_none_classification_equals_no_arg_for_standards() -> None:
    """Explicit None must produce the same output as calling with no argument."""
    assert kl.sumo_qa_load_standards(None) == kl.sumo_qa_load_standards()


def test_none_classification_equals_no_arg_for_rules() -> None:
    """Explicit None must produce the same output as calling with no argument."""
    assert kl.sumo_qa_load_rules(None) == kl.sumo_qa_load_rules()


@given(classification=st.text(min_size=1, max_size=50))
@settings(max_examples=100)
def test_load_standards_filtered_length_le_unfiltered(classification: str) -> None:
    """Filtered standards output must never be longer than the full catalogue."""
    unfiltered = kl.sumo_qa_load_standards()
    filtered = kl.sumo_qa_load_standards(classification)
    assert len(filtered) <= len(unfiltered)
