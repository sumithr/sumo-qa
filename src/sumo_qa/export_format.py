# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic export of a validated QA-test-case set (issue #148).

Pure formatting — NO inference, NO file IO. Given an already-validated
:class:`QaTestCaseExport`, render it into one of three documented, machine-
readable shapes:

* ``json``     — a versioned, key-sorted JSON document (the schema is versioned
                 from the start). Stable key order + no float content ⇒
                 byte-for-byte deterministic, so it can be snapshot-tested and
                 diffed.
* ``markdown`` — a markdown table. This is the DEFAULT human-facing shape; the
                 export tool emits it unless another format is explicitly named.
* ``csv``      — OPTIONAL, and only valid for a *flat* outline (every case has at
                 most one precondition and one step). A nested case would force a
                 CSV cell to carry an ordered list, which CSV cannot represent
                 without lossy flattening, so ``export_test_cases`` refuses CSV
                 for a non-flat export with a clear message rather than silently
                 collapsing structure.

The set of formats is documented and host-neutral: there is no dependency on any
single external test-management vendor, and an invalid format request fails with
an explicit supported-format message. ``json`` and ``csv`` use only the Python
standard library (``json`` / ``csv``) — no new mandatory install dependency.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Final

from sumo_qa.export_models import QaTestCase, QaTestCaseExport

#: The export formats this build supports, in a stable documented order. The
#: validator (``export_test_cases``) refuses anything outside this set with a
#: message listing exactly these names.
SUPPORTED_FORMATS: Final[tuple[str, ...]] = ("json", "markdown", "csv")

#: The flat columns a CSV row carries, in a stable documented order. Ordered
#: lists (preconditions/steps) collapse to their single element on the flat path
#: (a flat case has at most one of each); ``linked_risk_id`` renders empty when
#: absent.
_CSV_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "title",
    "precondition",
    "step",
    "expected_result",
    "linked_risk_id",
    "priority",
    "evidence_status",
)


class UnsupportedExportFormat(ValueError):
    """Raised for a format string outside :data:`SUPPORTED_FORMATS`.

    Carries the offending value and a message listing the supported formats so
    the caller can surface the acceptance criterion's clear supported-format
    error verbatim.
    """

    def __init__(self, requested: str) -> None:
        self.requested = requested
        super().__init__(
            f"unsupported export format {requested!r}; "
            f"supported formats are: {', '.join(SUPPORTED_FORMATS)}"
        )


class CsvRequiresFlatExport(ValueError):
    """Raised when CSV is requested for a non-flat export.

    CSV only models flat test-case outlines (one precondition + one step per
    case); a nested case would lose its ordered structure in a single cell.
    """

    def __init__(self, offending_ids: list[str]) -> None:
        self.offending_ids = offending_ids
        joined = ", ".join(offending_ids)
        super().__init__(
            "csv export is only supported for flat test-case outlines (at most one "
            "precondition and one step per case); these cases are not flat: "
            f"{joined}. Export as json or markdown to keep the ordered structure."
        )


def _escape_cell(value: str) -> str:
    # A literal pipe in a field would create a phantom table column; escape it so
    # the markdown table stays well-formed. Any line/paragraph/vertical separator
    # would break the row entirely and let arbitrary markdown be injected on a
    # fresh line, so collapse the full class to a single space first. Mirrors the
    # risk-ledger formatter's separator handling.
    flattened = re.sub(r"[\r\n\x0b\x0c\x1c\x1d\x1e\x85  ]+", " ", value)
    return flattened.replace("|", "\\|")


def _join_ordered(items: list[str]) -> str:
    # Render an ordered list inside a single markdown cell as "1. a; 2. b" so the
    # ordering survives the flattening to one cell. An empty list renders as "—".
    if not items:
        return "—"
    return "; ".join(f"{i}. {_escape_cell(item)}" for i, item in enumerate(items, start=1))


def _case_to_dict(case: QaTestCase) -> dict:
    # Explicit, stable field order for the JSON projection — the same field set
    # the schema documents. (json.dumps(sort_keys=True) also sorts, so this dict's
    # insertion order is belt-and-braces; the sorted dump is the determinism
    # guarantee.) linked_risk_id is always present (null when absent) so the JSON
    # shape is uniform across cases.
    return {
        "id": case.id,
        "title": case.title,
        "preconditions": list(case.preconditions),
        "steps": list(case.steps),
        "expected_result": case.expected_result,
        "linked_risk_id": case.linked_risk_id,
        "priority": case.priority,
        "evidence_status": case.evidence_status,
    }


def export_json(export: QaTestCaseExport) -> str:
    """Render the export as a versioned, key-sorted JSON document.

    Deterministic: ``sort_keys=True`` fixes key order regardless of dict
    insertion order, and the payload carries only strings/lists/null, so the
    output is byte-for-byte stable and snapshot-testable. The trailing newline
    matches the repo's other JSON artifacts.
    """
    payload = {
        "schema_version": export.schema_version,
        "title": export.title,
        "test_cases": [_case_to_dict(case) for case in export.test_cases],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def export_markdown(export: QaTestCaseExport) -> str:
    """Render the export as a markdown table (the DEFAULT human-facing shape)."""
    if not export.test_cases:
        return "**QA test cases** — none recorded."

    header = (
        "| ID | Title | Preconditions | Steps / checks | Expected result | "
        "Risk | Priority | Evidence |"
    )
    rule = "|---|---|---|---|---|---|---|---|"
    title_line = (
        f"**QA test cases — {_escape_cell(export.title)}**" if export.title else "**QA test cases**"
    )
    lines = [title_line, "", header, rule]
    for case in export.test_cases:
        cells = [
            _escape_cell(case.id),
            _escape_cell(case.title),
            _join_ordered(case.preconditions),
            _join_ordered(case.steps),
            _escape_cell(case.expected_result),
            _escape_cell(case.linked_risk_id) if case.linked_risk_id else "—",
            case.priority,
            case.evidence_status,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def export_csv(export: QaTestCaseExport) -> str:
    """Render a FLAT export as CSV. Refuses a non-flat export.

    Uses the stdlib ``csv`` writer with ``\\r\\n`` line terminator forced to
    ``\\n`` for deterministic, OS-independent output. The header row is always
    emitted (even for an empty export) so a consumer can read the columns.
    """
    if not export.is_flat():
        offending = [case.id for case in export.test_cases if not case.is_flat()]
        raise CsvRequiresFlatExport(offending)

    buffer = io.StringIO()
    # lineterminator="\n" so the output is identical on every platform (the
    # default "\r\n" would make snapshots platform-dependent).
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for case in export.test_cases:
        writer.writerow(
            [
                case.id,
                case.title,
                case.preconditions[0] if case.preconditions else "",
                case.steps[0] if case.steps else "",
                case.expected_result,
                case.linked_risk_id or "",
                case.priority,
                case.evidence_status,
            ]
        )
    return buffer.getvalue()


def export_test_cases(export: QaTestCaseExport, fmt: str) -> str:
    """Render the export in ``fmt`` — one of :data:`SUPPORTED_FORMATS`.

    Raises :class:`UnsupportedExportFormat` for any other format string (the
    clear supported-format error), and :class:`CsvRequiresFlatExport` when CSV is
    requested for a non-flat export. Side-effect free — returns a string; never
    writes a file.
    """
    if fmt == "json":
        return export_json(export)
    if fmt == "markdown":
        return export_markdown(export)
    if fmt == "csv":
        return export_csv(export)
    raise UnsupportedExportFormat(fmt)
