# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.export_format — the deterministic export of a validated
QA-test-case set into JSON / markdown / CSV (issue #148).

The export MUST be deterministic (snapshot-tested), side-effect free (returns a
string, never touches disk), markdown-default, and honest about the CSV
flat-only constraint. An unsupported format fails with a clear supported-format
message. Free-text fields must survive separator/pipe injection in the markdown
table.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from sumo_qa.export_format import (
    SUPPORTED_FORMATS,
    CsvRequiresFlatExport,
    UnsupportedExportFormat,
    export_csv,
    export_json,
    export_markdown,
    export_test_cases,
)
from sumo_qa.export_models import EXPORT_SCHEMA_VERSION, QaTestCase, QaTestCaseExport


def _case(**overrides) -> QaTestCase:
    base = dict(
        id="TC1",
        title="Refund is idempotent across a retried request.",
        preconditions=["A charge exists with a known idempotency key."],
        steps=["POST the refund twice with the same idempotency key."],
        expected_result="The charge is refunded exactly once; the second call is a no-op.",
        priority="high",
        evidence_status="planned",
    )
    base.update(overrides)
    return QaTestCase(**base)


def _export(*cases, title=None) -> QaTestCaseExport:
    return QaTestCaseExport(
        schema_version=EXPORT_SCHEMA_VERSION, title=title, test_cases=list(cases)
    )


# --- deterministic snapshots -------------------------------------------------

# A fixed two-case export reused across the snapshot assertions. The values are
# chosen to exercise: an absent linked_risk_id, a present one, an empty
# precondition/step list, and the two priority + evidence vocabularies.
_SNAPSHOT_EXPORT = _export(
    _case(
        id="TC1",
        linked_risk_id="R1",
        priority="critical",
        evidence_status="passing",
    ),
    _case(
        id="TC2",
        title="Webhook retry does not double-fire.",
        preconditions=[],
        steps=[],
        expected_result="Exactly one downstream event is emitted per source event.",
        priority="medium",
        evidence_status="planned",
    ),
    title="Billing refund + webhook",
)


_EXPECTED_JSON = """\
{
  "schema_version": "1.0",
  "test_cases": [
    {
      "evidence_status": "passing",
      "expected_result": "The charge is refunded exactly once; the second call is a no-op.",
      "id": "TC1",
      "linked_risk_id": "R1",
      "preconditions": [
        "A charge exists with a known idempotency key."
      ],
      "priority": "critical",
      "steps": [
        "POST the refund twice with the same idempotency key."
      ],
      "title": "Refund is idempotent across a retried request."
    },
    {
      "evidence_status": "planned",
      "expected_result": "Exactly one downstream event is emitted per source event.",
      "id": "TC2",
      "linked_risk_id": null,
      "preconditions": [],
      "priority": "medium",
      "steps": [],
      "title": "Webhook retry does not double-fire."
    }
  ],
  "title": "Billing refund + webhook"
}
"""


def test_json_export_is_byte_for_byte_stable():
    assert export_json(_SNAPSHOT_EXPORT) == _EXPECTED_JSON


def test_json_export_is_deterministic_across_calls():
    assert export_json(_SNAPSHOT_EXPORT) == export_json(_SNAPSHOT_EXPORT)


def test_json_export_parses_and_carries_schema_version():
    parsed = json.loads(export_json(_SNAPSHOT_EXPORT))
    assert parsed["schema_version"] == "1.0"
    assert [c["id"] for c in parsed["test_cases"]] == ["TC1", "TC2"]
    # linked_risk_id is always present (null when absent) so the JSON shape is
    # uniform across cases.
    assert parsed["test_cases"][1]["linked_risk_id"] is None


_EXPECTED_MARKDOWN = (
    "**QA test cases — Billing refund + webhook**\n"
    "\n"
    "| ID | Title | Preconditions | Steps / checks | Expected result | Risk | "
    "Priority | Evidence |\n"
    "|---|---|---|---|---|---|---|---|\n"
    "| TC1 | Refund is idempotent across a retried request. | 1. A charge exists "
    "with a known idempotency key. | 1. POST the refund twice with the same "
    "idempotency key. | The charge is refunded exactly once; the second call is a "
    "no-op. | R1 | critical | passing |\n"
    "| TC2 | Webhook retry does not double-fire. | — | — | Exactly one downstream "
    "event is emitted per source event. | — | medium | planned |"
)


def test_markdown_export_snapshot():
    assert export_markdown(_SNAPSHOT_EXPORT) == _EXPECTED_MARKDOWN


_EXPECTED_CSV = (
    "id,title,precondition,step,expected_result,linked_risk_id,priority,evidence_status\n"
    "TC1,Refund is idempotent across a retried request.,A charge exists with a "
    "known idempotency key.,POST the refund twice with the same idempotency key.,"
    "The charge is refunded exactly once; the second call is a no-op.,R1,critical,passing\n"
    "TC2,Webhook retry does not double-fire.,,,Exactly one downstream event is "
    "emitted per source event.,,medium,planned\n"
)


def test_csv_export_snapshot():
    assert export_csv(_SNAPSHOT_EXPORT) == _EXPECTED_CSV


def test_csv_export_round_trips_through_stdlib_reader():
    rows = list(csv.reader(io.StringIO(export_csv(_SNAPSHOT_EXPORT))))
    assert rows[0][0] == "id"
    assert rows[1][0] == "TC1"
    assert rows[2][5] == ""  # TC2 has no linked_risk_id


# --- markdown defaults / empties ---------------------------------------------


def test_markdown_is_the_default_format():
    out = export_test_cases(_SNAPSHOT_EXPORT, "markdown")
    assert out == _EXPECTED_MARKDOWN


def test_markdown_empty_export_placeholder():
    assert export_markdown(_export()) == "**QA test cases** — none recorded."


def test_markdown_without_title_omits_title_suffix():
    md = export_markdown(_export(_case()))
    assert md.startswith("**QA test cases**\n")
    assert "—" not in md.splitlines()[0]


# --- injection hardening (markdown table) ------------------------------------


def test_pipe_in_field_is_escaped():
    md = export_markdown(_export(_case(title="cost | tax")))
    assert r"cost \| tax" in md


def test_newline_in_field_is_flattened():
    md = export_markdown(_export(_case(expected_result="line one\n## Injected\nline two")))
    body_line = next(line for line in md.splitlines() if line.startswith("| TC1"))
    assert "## Injected" in body_line
    assert "\n" not in body_line


# --- format gating -----------------------------------------------------------


def test_supported_formats_are_the_documented_three():
    assert SUPPORTED_FORMATS == ("json", "markdown", "csv")


@pytest.mark.parametrize("fmt", ["json", "markdown", "csv"])
def test_each_supported_format_dispatches(fmt):
    out = export_test_cases(_export(_case()), fmt)
    assert isinstance(out, str) and out


def test_unsupported_format_raises_with_supported_list():
    with pytest.raises(UnsupportedExportFormat) as exc:
        export_test_cases(_export(_case()), "xml")
    msg = str(exc.value)
    assert "unsupported export format 'xml'" in msg
    assert "json" in msg and "markdown" in msg and "csv" in msg


def test_csv_refuses_a_nested_export_naming_offenders():
    nested = _export(
        _case(id="TC1"),
        _case(id="TC2", steps=["a", "b"]),
    )
    with pytest.raises(CsvRequiresFlatExport) as exc:
        export_test_cases(nested, "csv")
    assert exc.value.offending_ids == ["TC2"]
    assert "flat test-case outlines" in str(exc.value)


def test_csv_allows_a_flat_export():
    flat = _export(_case(id="TC1"), _case(id="TC2"))
    out = export_test_cases(flat, "csv")
    assert out.startswith("id,title,")


def test_csv_empty_export_emits_header_only():
    out = export_csv(_export())
    assert out == (
        "id,title,precondition,step,expected_result,linked_risk_id,priority,evidence_status\n"
    )


# --- side-effect freedom -----------------------------------------------------


def test_export_writes_no_file(tmp_path, monkeypatch):
    # The export is documented as side-effect free: it returns text and never
    # writes to disk. cd into an empty tmp dir and assert nothing is created.
    monkeypatch.chdir(tmp_path)
    for fmt in SUPPORTED_FORMATS:
        export_test_cases(_export(_case()), fmt)
    assert list(tmp_path.iterdir()) == []
