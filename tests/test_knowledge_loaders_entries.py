# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the per-entry / compact catalogue loaders (issue #287, epic #137
Lever 4).

The full-text catalogue loaders (`sumo_qa_load_classifications` etc.) stay
backward-compatible and are covered by `test_knowledge_loaders.py`. These
tests cover the new single-entry and compact-form retrieval:

  * single-entry retrieval by name (slug or verbatim heading);
  * unknown-name returns an actionable error envelope listing valid names;
  * compact form covers exactly the same entry set as full;
  * compact output is marked non-canonical (`canonical=false`); full entry
    text stays canonical (verbatim).

Risks (grounded in sumo_qa_load_techniques):
  * equivalence partitioning — entry-found vs entry-absent classes; probe
    substring confusion (a partial name must not match a longer entry).
  * decision tables — (catalogue x format) -> canonical flag combinations.
"""

from __future__ import annotations

import pytest

from sumo_qa import knowledge_loaders

CATALOGUES = ["classifications", "approaches", "principles", "techniques"]


# --- entry index -----------------------------------------------------------


def test_list_catalogue_entries_classifications_has_ten():
    entries = knowledge_loaders.list_catalogue_entries("classifications")
    ids = {e["id"] for e in entries}
    for canonical in [
        "api_contract_change",
        "business_logic_change",
        "security_change",
        "performance_change",
        "frontend_change",
        "infrastructure_change",
        "test_change",
        "docs_change",
        "config_change",
        "data_migration",
    ]:
        assert canonical in ids, f"missing classification entry id {canonical!r}"


def test_list_catalogue_entries_techniques_includes_named_techniques():
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("techniques")}
    for canonical in [
        "equivalence-partitioning",
        "boundary-value-analysis",
        "decision-tables",
        "mutation-testing",
    ]:
        assert canonical in ids, f"missing technique entry id {canonical!r}"


def test_list_catalogue_entries_unknown_catalogue_raises():
    with pytest.raises(KeyError):
        knowledge_loaders.list_catalogue_entries("not_a_catalogue")


# --- single-entry retrieval (full) -----------------------------------------


def test_load_entry_by_slug_returns_canonical_verbatim_text():
    result = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract_change")
    assert result["catalogue"] == "classifications"
    assert result["id"] == "api_contract_change"
    assert result["format"] == "full"
    assert result["canonical"] is True
    # Verbatim: the entry text is a substring of the full catalogue.
    full = knowledge_loaders.sumo_qa_load_classifications()
    assert result["text"] in full
    assert result["text"].startswith("## api_contract_change")
    # Body of THIS entry is present, not the next one.
    assert "downstream" in result["text"]
    assert "## business_logic_change" not in result["text"]


def test_load_entry_by_verbatim_heading_matches_slug():
    by_heading = knowledge_loaders.load_catalogue_entry(
        "techniques", name="equivalence partitioning"
    )
    by_slug = knowledge_loaders.load_catalogue_entry("techniques", name="equivalence-partitioning")
    assert by_heading["id"] == "equivalence-partitioning"
    assert by_heading["text"] == by_slug["text"]


def test_load_entry_matching_is_case_insensitive_on_heading():
    result = knowledge_loaders.load_catalogue_entry("approaches", name="TDD-Scaffold")
    assert result["id"] == "tdd-scaffold"


# --- unknown name -> actionable error envelope -----------------------------


def test_load_entry_unknown_name_returns_error_envelope_with_choices():
    result = knowledge_loaders.load_catalogue_entry("classifications", name="no_such_entry")
    assert "error" in result
    assert "no_such_entry" in result["error"]
    assert "available_entries" in result
    assert "api_contract_change" in result["available_entries"]
    assert "text" not in result


def test_load_entry_missing_name_returns_error_envelope():
    result = knowledge_loaders.load_catalogue_entry("approaches", name=None)
    assert "error" in result
    assert "available_entries" in result
    assert "tdd-scaffold" in result["available_entries"]


def test_load_entry_unknown_catalogue_returns_error_envelope():
    result = knowledge_loaders.load_catalogue_entry("not_a_catalogue", name="x")
    assert "error" in result
    assert "available_catalogues" in result
    assert set(result["available_catalogues"]) == set(CATALOGUES)


def test_load_entry_substring_does_not_match_longer_entry():
    # Equivalence partitioning, substring-confusion failure mode: a partial
    # name must NOT match a longer entry's id.
    result = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract")
    assert "error" in result, "partial name should not resolve to api_contract_change"


# --- compact form ----------------------------------------------------------


def test_compact_entry_set_equals_full_entry_set():
    # Equivalence partitioning: compact and full describe the SAME entries,
    # only verbosity differs. No entry dropped or invented.
    for cat in CATALOGUES:
        full_ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries(cat)}
        compact = knowledge_loaders.load_catalogue(cat, format="compact")
        compact_ids = {e["id"] for e in compact["entries"]}
        assert compact_ids == full_ids, f"{cat}: compact entry set drifted from full"


def test_compact_catalogue_is_marked_non_canonical():
    # Decision table: (format=compact) -> canonical=False.
    compact = knowledge_loaders.load_catalogue("classifications", format="compact")
    assert compact["canonical"] is False
    assert compact["format"] == "compact"


def test_full_catalogue_via_new_loader_is_canonical_and_verbatim():
    # Decision table: (format=full) -> canonical=True, text byte-equal to the
    # backward-compatible loader.
    full = knowledge_loaders.load_catalogue("classifications", format="full")
    assert full["canonical"] is True
    assert full["format"] == "full"
    assert full["text"] == knowledge_loaders.sumo_qa_load_classifications()


def test_compact_entry_is_shorter_than_full_entry():
    full_entry = knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change"
    )
    compact = knowledge_loaders.load_catalogue("classifications", format="compact")
    compact_entry = next(e for e in compact["entries"] if e["id"] == "api_contract_change")
    assert len(compact_entry["summary"]) < len(full_entry["text"])
    assert compact_entry.get("canonical") is False


def test_load_entry_compact_format_marks_non_canonical():
    # Decision table: single-entry (format=compact) -> canonical=False.
    result = knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change", format="compact"
    )
    assert result["format"] == "compact"
    assert result["canonical"] is False
    # Compact single-entry stays shorter than the full verbatim entry.
    full = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract_change")
    assert len(result["text"]) <= len(full["text"])


def test_load_catalogue_unknown_format_returns_error_envelope():
    result = knowledge_loaders.load_catalogue("classifications", format="bogus")
    assert "error" in result
    assert "available_formats" in result
    assert set(result["available_formats"]) == {"full", "compact"}


def test_load_catalogue_unknown_catalogue_returns_error_envelope():
    result = knowledge_loaders.load_catalogue("not_a_catalogue", format="full")
    assert "error" in result
    assert "available_catalogues" in result
    assert set(result["available_catalogues"]) == set(CATALOGUES)


def test_load_entry_unknown_format_returns_error_envelope():
    result = knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change", format="bogus"
    )
    assert "error" in result
    assert set(result["available_formats"]) == {"full", "compact"}


def test_entry_index_ignores_headings_inside_fenced_code_blocks(tmp_path, monkeypatch):
    # A '#' line inside a ``` fence is markdown code, not an entry heading, and
    # must not be indexed. Exercises the fence-tracking branch in the indexer.
    cat = tmp_path / "classifications.md"
    cat.write_text(
        "# Title\n\n"
        "## real_entry\n"
        "Body line.\n\n"
        "```python\n"
        "# not_a_heading_inside_fence\n"
        "x = 1\n"
        "```\n\n"
        "## second_entry\n"
        "More body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(tmp_path))
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("classifications")}
    assert ids == {"real_entry", "second_entry"}
    assert "not_a_heading_inside_fence" not in ids


def test_full_loaders_backward_compatible_zero_arg():
    # Regression guard: the existing zero-arg loaders are untouched.
    for fn, marker in [
        (knowledge_loaders.sumo_qa_load_classifications, "api_contract_change"),
        (knowledge_loaders.sumo_qa_load_approaches, "tdd-scaffold"),
        (knowledge_loaders.sumo_qa_load_principles, "ISTQB"),
        (knowledge_loaders.sumo_qa_load_techniques, "equivalence partitioning"),
    ]:
        text = fn()
        assert marker in text
