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
    # The entry shape is public contract; no test read e["level"] before, so
    # the "level"-key mutants survived (kills
    # x__index_catalogue_entries__mutmut_38/39).
    entry = next(e for e in entries if e["id"] == "api_contract_change")
    assert set(entry) == {"id", "heading", "level", "text", "summary"}
    assert entry["level"] == 2


def test_list_catalogue_entries_techniques_includes_named_techniques():
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("techniques")}
    for canonical in [
        "equivalence-partitioning",
        "boundary-value-analysis",
        "decision-tables",
        "mutation-testing",
        # Headings ending in ')' make the trailing strip("-") load-bearing:
        # strip(None) would leave "...-coverage-" / "...-inspection-" ids
        # (kills x__entry_slugify__mutmut_4).
        "mc-dc-modified-condition-decision-coverage",
        "review-walkthrough-technical-review-inspection",
    ]:
        assert canonical in ids, f"missing technique entry id {canonical!r}"


def test_list_catalogue_entries_unknown_catalogue_raises():
    # match pins the offending id in the KeyError payload (kills
    # x_list_catalogue_entries__mutmut_2's KeyError(None)).
    with pytest.raises(KeyError, match="not_a_catalogue"):
        knowledge_loaders.list_catalogue_entries("not_a_catalogue")


# --- grouper headings are not hollow addressable entries -------------------
#
# techniques.md groups its leaf techniques under level-2 category headings
# (## Black-box, ## Mutation, …) that are immediately followed by a deeper
# (###) heading with no prose body between. Such groupers must NOT be indexed
# as addressable catalogue entries: they would otherwise resolve to a hollow,
# blank-summary, near-empty-body entry that is still marked canonical (a
# citable husk). Only the leaf techniques carry real content.

# Decision table: heading-shape -> indexed-as-entry?
#   level-2 grouper, next heading is deeper, no prose between -> NO
#   level-3 leaf with prose body                              -> YES


def test_techniques_compact_summaries_are_all_non_empty():
    # Every compact-entry summary across ALL FOUR catalogues must be real
    # prose — a blank summary is the tell-tale of a hollow grouper leaking
    # into the index, or of the summary walk returning the blank line after
    # the heading. Catalogues whose entries put a blank line before the prose
    # (principles) are the discriminating case (kills
    # x__first_prose_line__mutmut_3's and-to-or, which returns "" there).
    for cat in CATALOGUES:
        compact = knowledge_loaders.load_catalogue(cat, format="compact")
        blank = [e["id"] for e in compact["entries"] if not e["summary"].strip()]
        assert blank == [], f"{cat} compact entries with empty summaries: {blank}"


def test_techniques_category_groupers_are_not_hollow_entries():
    # The category groupers must either be absent from the entry set, or (if a
    # caller asks for them by name) resolve to the real technique body — never
    # to a hollow "## Mutation\n\n" husk marked canonical.
    grouper_names = ["mutation", "black-box", "white-box-structural", "experience-based"]
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("techniques")}
    for name in grouper_names:
        if name in ids:
            entry = knowledge_loaders.load_catalogue_entry("techniques", name=name)
            assert entry.get("summary", "").strip() or entry["text"].strip().count("\n"), (
                f"grouper {name!r} resolved to a hollow entry: {entry!r}"
            )
            assert name not in ids, f"grouper {name!r} should not be an addressable hollow entry"


# --- single-entry retrieval (full) -----------------------------------------


def test_load_entry_by_slug_returns_canonical_verbatim_text():
    result = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract_change")
    # Full key-set + heading: no test read "heading" off the full envelope
    # (kills x_load_catalogue_entry__mutmut_80/81).
    assert set(result) == {"catalogue", "id", "heading", "format", "canonical", "text"}
    assert result["catalogue"] == "classifications"
    assert result["id"] == "api_contract_change"
    assert result["heading"] == "api_contract_change"
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
    # Exact message: "error" in result also passes for a None/mangled message
    # (kills x_load_catalogue_entry__mutmut_25/29/30).
    assert result["error"] == "name is required."
    assert "available_entries" in result
    assert "tdd-scaffold" in result["available_entries"]


def test_load_entry_unknown_catalogue_returns_error_envelope():
    result = knowledge_loaders.load_catalogue_entry("not_a_catalogue", name="x")
    # The message must NAME the offending catalogue — actionable envelope
    # (kills x_load_catalogue_entry__mutmut_4's message -> None).
    assert "not_a_catalogue" in result["error"]
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
    # Envelope key-set + catalogue identity (kills x_load_catalogue__mutmut_41/42).
    assert set(compact) == {"catalogue", "format", "canonical", "entries"}
    assert compact["catalogue"] == "classifications"
    assert compact["canonical"] is False
    assert compact["format"] == "compact"


def test_load_catalogue_defaults_to_full():
    """Omitting `format` is the same call as `format="full"`.

    Kills the `"full"` default-value mutants on load_catalogue: a mutated
    default ("XXfullXX" / "FULL") is an unknown format, so the zero-format
    call would return the error envelope instead of the canonical text.
    """
    default = knowledge_loaders.load_catalogue("classifications")
    assert default == knowledge_loaders.load_catalogue("classifications", format="full")
    assert default["format"] == "full"
    assert default["canonical"] is True


def test_load_catalogue_entry_defaults_to_full():
    """Same contract for the single-entry loader's `format` default."""
    default = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract_change")
    assert default == knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change", format="full"
    )
    assert default["format"] == "full"
    assert default["canonical"] is True


def test_full_catalogue_via_new_loader_is_canonical_and_verbatim():
    # Decision table: (format=full) -> canonical=True, text byte-equal to the
    # backward-compatible loader.
    full = knowledge_loaders.load_catalogue("classifications", format="full")
    # Envelope key-set + catalogue identity (kills x_load_catalogue__mutmut_24/25).
    assert set(full) == {"catalogue", "format", "canonical", "text"}
    assert full["catalogue"] == "classifications"
    assert full["canonical"] is True
    assert full["format"] == "full"
    assert full["text"] == knowledge_loaders.sumo_qa_load_classifications()


def test_compact_entry_is_shorter_than_full_entry():
    full_entry = knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change"
    )
    compact = knowledge_loaders.load_catalogue("classifications", format="compact")
    compact_entry = next(e for e in compact["entries"] if e["id"] == "api_contract_change")
    # Entries-list item key-set + heading value: no test read "heading" off
    # the compact list items (kills x_load_catalogue__mutmut_56/57).
    assert set(compact_entry) == {"id", "heading", "summary", "canonical"}
    assert compact_entry["heading"] == "api_contract_change"
    assert len(compact_entry["summary"]) < len(full_entry["text"])
    assert compact_entry.get("canonical") is False


def test_load_entry_compact_format_marks_non_canonical():
    # Decision table: single-entry (format=compact) -> canonical=False.
    result = knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change", format="compact"
    )
    # Full key-set + identity values: no test read catalogue/id/heading off
    # the compact single-entry envelope, so those dict-key mutants survived
    # (kills x_load_catalogue_entry__mutmut_53/54/55/56/59/60).
    assert set(result) == {"catalogue", "id", "heading", "format", "canonical", "text"}
    assert result["catalogue"] == "classifications"
    assert result["id"] == "api_contract_change"
    assert result["heading"] == "api_contract_change"
    assert result["format"] == "compact"
    assert result["canonical"] is False
    # Compact single-entry stays shorter than the full verbatim entry.
    full = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract_change")
    assert len(result["text"]) <= len(full["text"])


def test_load_catalogue_unknown_format_returns_error_envelope():
    result = knowledge_loaders.load_catalogue("classifications", format="bogus")
    # Message names the offending format (kills x_load_catalogue__mutmut_10).
    assert "bogus" in result["error"]
    assert "available_formats" in result
    assert set(result["available_formats"]) == {"full", "compact"}


def test_load_catalogue_unknown_catalogue_returns_error_envelope():
    result = knowledge_loaders.load_catalogue("not_a_catalogue", format="full")
    # Message names the offending catalogue (kills x_load_catalogue__mutmut_4).
    assert "not_a_catalogue" in result["error"]
    assert "available_catalogues" in result
    assert set(result["available_catalogues"]) == set(CATALOGUES)


def test_load_entry_unknown_format_returns_error_envelope():
    result = knowledge_loaders.load_catalogue_entry(
        "classifications", name="api_contract_change", format="bogus"
    )
    # Message names the offending format (kills x_load_catalogue_entry__mutmut_10).
    assert "bogus" in result["error"]
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
    entries = knowledge_loaders.list_catalogue_entries("classifications")
    ids = {e["id"] for e in entries}
    assert ids == {"real_entry", "second_entry"}
    assert "not_a_heading_inside_fence" not in ids
    # Entry text must stop at the NEXT heading (kills the end-boundary
    # off-by-one x__index_catalogue_entries__mutmut_23, which runs the
    # penultimate entry's text to EOF and swallows the last entry).
    real_entry = next(e for e in entries if e["id"] == "real_entry")
    assert "## second_entry" not in real_entry["text"]


def test_leaf_entry_with_no_prose_body_has_empty_summary(tmp_path, monkeypatch):
    # A genuine leaf entry (no deeper heading follows, so NOT a grouper) whose
    # body holds only blank lines has no prose line — its summary is the empty
    # string. Exercises the no-prose-found branch of the summary builder.
    cat = tmp_path / "approaches.md"
    cat.write_text(
        "# Title\n\n## first\nReal prose.\n\n## trailing_blank\n\n\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(tmp_path))
    entries = knowledge_loaders.list_catalogue_entries("approaches")
    summaries = {e["id"]: e["summary"] for e in entries}
    assert summaries == {"first": "Real prose.", "trailing_blank": ""}


# --- FIX 1: missing/unreadable catalogue file -> error envelope, never raises -


def test_load_catalogue_entry_missing_file_returns_error_envelope(tmp_path, monkeypatch):
    # Contract: load_catalogue_entry NEVER raises. A QA_KNOWLEDGE_PATH that
    # points at a directory holding no catalogue file (so the underlying
    # read_text would raise FileNotFoundError) must surface as an error
    # envelope, not a leaked FileNotFoundError.
    missing_dir = tmp_path / "no_such_dir"
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(missing_dir))
    result = knowledge_loaders.load_catalogue_entry("classifications", name="api_contract_change")
    assert isinstance(result, dict)
    # Message content: names the catalogue (repr-quoted PREFIX, not a bare
    # substring — the OS error's file path also contains "classifications",
    # so a substring check passes even when the catalogue arg is dropped)
    # AND carries the OS error detail (kills
    # x__missing_catalogue_error__mutmut_1's message -> None and the
    # dropped-argument mutants on the load_catalogue_entry call site).
    assert result["error"].startswith("Catalogue 'classifications' could not be read")
    # The exception detail is asserted via the missing PATH (our own
    # fixture dir name) rather than the OS strerror: POSIX renders
    # "No such file or directory" but Windows renders "[WinError 3] The
    # system cannot find the path specified", and test.yml runs this
    # suite on windows-latest. The path is present on every OS and
    # absent when the exception argument is dropped.
    assert "no_such_dir" in result["error"]
    assert "available_catalogues" in result
    assert set(result["available_catalogues"]) == set(CATALOGUES)
    assert "text" not in result


def test_load_catalogue_full_missing_file_returns_error_envelope(tmp_path, monkeypatch):
    # The full-format path goes straight through _read(); it must also honour
    # the never-raises contract when the catalogue file is missing/unreadable.
    missing_dir = tmp_path / "no_such_dir"
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(missing_dir))
    result = knowledge_loaders.load_catalogue("classifications", format="full")
    assert isinstance(result, dict)
    # Full-branch envelope call arguments stay intact — repr-quoted prefix,
    # not a bare substring (the OS error's path contains "classifications"
    # too), kills both dropped-argument mutants on this call site.
    assert result["error"].startswith("Catalogue 'classifications' could not be read")
    # The exception detail is asserted via the missing PATH (our own
    # fixture dir name) rather than the OS strerror: POSIX renders
    # "No such file or directory" but Windows renders "[WinError 3] The
    # system cannot find the path specified", and test.yml runs this
    # suite on windows-latest. The path is present on every OS and
    # absent when the exception argument is dropped.
    assert "no_such_dir" in result["error"]
    assert "available_catalogues" in result
    assert set(result["available_catalogues"]) == set(CATALOGUES)
    assert "text" not in result


def test_load_catalogue_compact_missing_file_returns_error_envelope(tmp_path, monkeypatch):
    # The compact-format path goes through list_catalogue_entries() -> _read().
    missing_dir = tmp_path / "no_such_dir"
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(missing_dir))
    result = knowledge_loaders.load_catalogue("classifications", format="compact")
    assert isinstance(result, dict)
    # Compact-branch envelope call arguments stay intact — repr-quoted
    # prefix for the same path-substring reason as the full branch; kills
    # both dropped-argument mutants on this call site.
    assert result["error"].startswith("Catalogue 'classifications' could not be read")
    # The exception detail is asserted via the missing PATH (our own
    # fixture dir name) rather than the OS strerror: POSIX renders
    # "No such file or directory" but Windows renders "[WinError 3] The
    # system cannot find the path specified", and test.yml runs this
    # suite on windows-latest. The path is present on every OS and
    # absent when the exception argument is dropped.
    assert "no_such_dir" in result["error"]
    assert "available_catalogues" in result
    assert "entries" not in result


# --- FIX 2: CommonMark-correct fence tracking ------------------------------


def test_outer_4tick_fence_wrapping_inner_3tick_block_hides_fake_heading(tmp_path, monkeypatch):
    # A 4-backtick fence may legally contain a 3-backtick run as literal
    # content. A length-blind fence tracker closes on the inner ``` and then
    # treats text after it as outside the block — wrongly indexing a fake
    # heading that lives inside the (still-open) outer code block.
    cat = tmp_path / "classifications.md"
    cat.write_text(
        "# Title\n\n"
        "## real_entry\n"
        "Body line.\n\n"
        "````markdown\n"
        "```\n"
        "## Fake heading inside the block\n"
        "```\n"
        "````\n\n"
        "## second_entry\n"
        "More body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(tmp_path))
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("classifications")}
    assert ids == {"real_entry", "second_entry"}
    assert "fake-heading-inside-the-block" not in ids


def test_closing_fence_with_trailing_info_string_is_not_a_close(tmp_path, monkeypatch):
    # CommonMark: a CLOSING fence may have only whitespace after the fence run.
    # A line like ```bash INSIDE a 3-backtick block carries an info string, so
    # it is content (an attempted opener), NOT a valid close. A length-blind,
    # trailing-blind tracker closes on it and then wrongly indexes the
    # following ## line as a real entry.
    cat = tmp_path / "classifications.md"
    cat.write_text(
        "# Title\n\n"
        "## real_entry\n"
        "Body line.\n\n"
        "```\n"
        "```bash\n"
        "## Fake heading inside the block\n"
        "```\n\n"
        "## second_entry\n"
        "More body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(tmp_path))
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("classifications")}
    assert ids == {"real_entry", "second_entry"}
    assert "fake-heading-inside-the-block" not in ids


def test_indented_4space_backticks_are_not_a_fence(tmp_path, monkeypatch):
    # CommonMark: a line indented >= 4 spaces is an indented code block, not a
    # fence marker. The indented ``` must NOT open a fence — so the real
    # heading that follows must still be indexed as an entry.
    cat = tmp_path / "classifications.md"
    cat.write_text(
        "# Title\n\n"
        "## real_entry\n"
        "Body line.\n\n"
        "    ```\n"
        "    indented code, not a fence\n\n"
        "## second_entry\n"
        "More body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(tmp_path))
    ids = {e["id"] for e in knowledge_loaders.list_catalogue_entries("classifications")}
    assert "real_entry" in ids
    assert "second_entry" in ids, (
        "an indented (>=4 space) ``` must not open a fence that swallows the next heading"
    )


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
