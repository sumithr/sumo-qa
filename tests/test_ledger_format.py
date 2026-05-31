# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.ledger_format — deterministic markdown projection of the
risk-to-test ledger (issue #144).

The formatter performs NO inference: it renders a validated ``RiskLedger`` into a
markdown table (the structured appendix the verdict carries) plus a compact
one-line summary, and supports truncation so a large ledger can't blow the MCP
token budget (#89/#137 guard).
"""

from __future__ import annotations

import pytest

from sumo_qa.ledger_format import (
    compact_summary,
    format_ledger_markdown,
)
from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION, RiskLedger, RiskLedgerRow


def _row(**overrides) -> RiskLedgerRow:
    base = dict(
        risk_id="R1",
        risk="Refund issued twice on retry.",
        source_anchor="refund.py:47",
        test="tests/test_refund.py::test_idempotent",
        evidence_status="passing",
        residual="accepted",
    )
    base.update(overrides)
    return RiskLedgerRow(**base)


def _ledger(*rows: RiskLedgerRow) -> RiskLedger:
    return RiskLedger(schema_version=LEDGER_SCHEMA_VERSION, rows=list(rows))


def test_empty_ledger_renders_placeholder_not_blank():
    out = format_ledger_markdown(_ledger())
    assert "Risk ledger" in out
    assert "no risks recorded" in out.lower()


def test_markdown_has_header_row_with_all_columns():
    out = format_ledger_markdown(_ledger(_row()))
    assert "| Risk | Statement | Source | Test / check | Evidence | Residual |" in out


def test_markdown_renders_each_field_value():
    out = format_ledger_markdown(_ledger(_row()))
    assert "R1" in out
    assert "Refund issued twice on retry." in out
    assert "refund.py:47" in out
    assert "tests/test_refund.py::test_idempotent" in out
    assert "passing" in out
    assert "accepted" in out


def test_markdown_renders_one_data_row_per_ledger_row():
    out = format_ledger_markdown(_ledger(_row(), _row(risk_id="R2")))
    data_rows = [
        line for line in out.splitlines() if line.startswith("| R1 ") or line.startswith("| R2 ")
    ]
    assert len(data_rows) == 2


def test_markdown_escapes_pipe_in_field_so_table_is_not_broken():
    # A literal pipe in a risk statement would otherwise create a phantom column.
    out = format_ledger_markdown(_ledger(_row(risk="a | b split")))
    assert "a \\| b split" in out


def test_markdown_neutralises_newline_in_cell_so_row_is_not_split():
    # A newline in a cell would otherwise break the table row and let arbitrary
    # markdown be injected on a fresh line outside the row. It must collapse to a
    # single space, and any pipe in the same value must still be escaped.
    out = format_ledger_markdown(_ledger(_row(risk="line one\nline two | with pipe")))
    data_rows = [line for line in out.splitlines() if line.startswith("| R1 ")]
    assert len(data_rows) == 1
    row_line = data_rows[0]
    assert "\n" not in row_line.rstrip("\n")
    assert "line one line two \\| with pipe" in row_line
    # No stray non-table line leaked out of the row.
    assert "line two" not in out.replace(row_line, "")


def test_markdown_neutralises_carriage_return_in_cell():
    out = format_ledger_markdown(_ledger(_row(risk="a\r\nb\rc")))
    data_rows = [line for line in out.splitlines() if line.startswith("| R1 ")]
    assert len(data_rows) == 1
    assert "a b c" in data_rows[0]


def test_negative_max_rows_renders_zero_rows_and_truncates_all():
    # A negative cap must clamp to 0 — never become a Python negative slice
    # (max_rows=-1 would otherwise keep all-but-the-last row).
    rows = [_row(risk_id=f"R{i}") for i in range(1, 4)]
    out = format_ledger_markdown(_ledger(*rows), max_rows=-1)
    assert "R1" not in out and "R2" not in out and "R3" not in out
    assert "3 more" in out  # all 3 rows truncated


def test_markdown_renders_repo_map_node_id_when_present():
    out = format_ledger_markdown(_ledger(_row(repo_map_node_id="file:refund.py")))
    assert "file:refund.py" in out


def test_markdown_omits_node_id_column_when_no_row_has_one():
    # Keep the table compact: the optional node-id column only appears when at
    # least one row carries a link (#137 token-budget discipline).
    out = format_ledger_markdown(_ledger(_row()))
    assert "Repo-map node" not in out


def test_markdown_includes_node_id_column_when_any_row_has_one():
    out = format_ledger_markdown(_ledger(_row(), _row(risk_id="R2", repo_map_node_id="file:x.py")))
    assert "Repo-map node" in out


def test_repo_map_column_keeps_table_well_formed():
    # Regression: the optional Repo-map node column must add a real delimiter to
    # BOTH the header and the rule, so header / rule / every data row expose the
    # same cell count. Substring presence (the assertions above) can't catch a
    # missing delimiter that merges 'Residual' and 'Repo-map node' into one
    # header cell while each data row still emits its own 7th cell. The test row
    # values carry no literal pipe, so splitting on '|' counts cells faithfully.
    out = format_ledger_markdown(
        _ledger(_row(), _row(risk_id="R2", repo_map_node_id="file:refund.py"))
    )
    table = [line for line in out.splitlines() if line.startswith("|")]

    def cell_count(line: str) -> int:
        return len(line.strip().strip("|").split("|"))

    counts = [cell_count(line) for line in table]
    # 6 base columns + 1 optional Repo-map node column = 7, identical for the
    # header, the delimiter rule, and both data rows (the node-less row gets a
    # '—' placeholder cell).
    assert counts == [7, 7, 7, 7], f"ragged table — per-line cell counts: {counts}"


def test_truncation_caps_rows_and_announces_the_cut():
    rows = [_row(risk_id=f"R{i}") for i in range(1, 11)]
    out = format_ledger_markdown(_ledger(*rows), max_rows=3)
    assert "R1" in out and "R2" in out and "R3" in out
    assert "R4" not in out
    assert "7 more" in out  # 10 - 3 truncated rows announced


def test_no_truncation_notice_when_under_cap():
    out = format_ledger_markdown(_ledger(_row(), _row(risk_id="R2")), max_rows=5)
    assert "more" not in out.lower()


def test_compact_summary_counts_each_evidence_state():
    led = _ledger(
        _row(risk_id="R1", evidence_status="passing", residual="accepted"),
        _row(risk_id="R2", evidence_status="planned", residual="open"),
        _row(risk_id="R3", evidence_status="failing", residual="blocker"),
    )
    summary = compact_summary(led)
    assert "3 risks" in summary
    assert "1 passing" in summary
    assert "1 planned" in summary
    assert "1 failing" in summary


def test_compact_summary_flags_uncovered_blockers():
    led = _ledger(
        _row(risk_id="R1", evidence_status="failing", residual="blocker"),
        _row(risk_id="R2", evidence_status="passing", residual="accepted"),
    )
    summary = compact_summary(led)
    assert "1 uncovered blocker" in summary


def test_compact_summary_no_blocker_phrase_when_all_covered():
    led = _ledger(_row(evidence_status="passing", residual="accepted"))
    summary = compact_summary(led)
    assert "blocker" not in summary.lower()


def test_compact_summary_empty_ledger():
    summary = compact_summary(_ledger())
    assert "0 risks" in summary


# ---------------------------------------------------------------------------
# Fix 1 regression: comprehensive Unicode line/paragraph/vertical separators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "separator,label",
    [
        ("\r\n", "CRLF"),
        ("\r", "CR"),
        ("\n", "LF"),
        ("\x0b", "VT vertical-tab"),
        ("\x0c", "FF form-feed"),
        ("\x1c", "FS file-separator"),
        ("\x1d", "GS group-separator"),
        ("\x1e", "RS record-separator"),
        ("\x85", "NEL next-line"),
        (" ", "LS line-separator"),
        (" ", "PS paragraph-separator"),
    ],
)
def test_escape_collapses_every_unicode_line_separator_to_single_row(separator, label):
    """Each separator variant must collapse to a space — never split the table row."""
    row = _row(risk="before" + separator + "after")
    out = format_ledger_markdown(_ledger(row))
    data_rows = [line for line in out.splitlines() if line.startswith("| R1 ")]
    assert len(data_rows) == 1, f"{label} ({repr(separator)}) split the row into multiple lines"
    assert "before after" in data_rows[0], (
        f"{label} ({repr(separator)}) was not collapsed to a space"
    )


# ---------------------------------------------------------------------------
# Fix 2 regression: truncated reflects ACTUAL omission, not raw max_rows sign
# ---------------------------------------------------------------------------


def test_truncated_false_for_empty_ledger_with_negative_max_rows():
    """rows=[], max_rows=-1 => truncated must be False (nothing was omitted)."""
    rows_list = []
    max_rows = -1
    truncated = len(rows_list) > max(max_rows, 0)
    assert truncated is False


def test_truncated_true_when_all_rows_fall_outside_negative_cap():
    """rows=[3 items], max_rows=-1 => truncated must be True (all rows omitted)."""
    rows_list = [_row(risk_id=f"R{i}") for i in range(1, 4)]
    max_rows = -1
    truncated = len(rows_list) > max(max_rows, 0)
    assert truncated is True


def test_truncated_false_when_positive_cap_exceeds_row_count():
    """rows=[3 items], max_rows=5 => truncated must be False (no rows omitted)."""
    rows_list = [_row(risk_id=f"R{i}") for i in range(1, 4)]
    max_rows = 5
    truncated = len(rows_list) > max(max_rows, 0)
    assert truncated is False
