# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Schema models for the structured QA-artifact export (issue #148).

The export is a *deterministic projection* of already-structured QA state — test
cases the host LLM has already identified — into a small set of documented,
machine-readable shapes (versioned JSON, a markdown table, optional CSV). It is
NOT a test-management system, NOT a live integration with any external vendor,
and NOT a default response shape: markdown prose stays the human-facing output
unless the user explicitly asks to export.

No inference lives here. This module only locks the SHAPE of an exportable test
case so a deterministic helper can validate it and a formatter can render it.
Every field is supplied by the host; nothing is derived from repo context by this
code.

A ``QaTestCase`` carries exactly the fields the issue's acceptance criteria
require:

* ``id``                — a stable id WITHIN this export (e.g. ``TC1``); the key a
                          downstream import/script anchors on. Cross-session
                          identity is deliberately out of scope until a
                          persistence feature exists.
* ``title``             — a one-line human title for the case.
* ``preconditions``     — ordered setup steps that must hold before the checks run
                          (may be empty).
* ``steps``             — ordered actions / checks the case performs (may be
                          empty for a pure-assertion case).
* ``expected_result``   — the observable outcome that distinguishes pass from
                          fail.
* ``linked_risk_id``    — optional link to a risk id in a companion risk ledger
                          (issue #144). Absence is fine — not every case traces to
                          a single recorded risk.
* ``priority``          — one of four DISTINCT levels (see ``Priority``).
* ``evidence_status``   — one of the five risk-ledger evidence states, reused
                          verbatim (see ``ledger_models.EvidenceStatus``) so the
                          export and the ledger speak the same vocabulary.

Reusing the ledger's ``EvidenceStatus`` (issue #144) rather than minting a parallel
enum keeps the two structured surfaces consistent: a case exported as ``planned``
means the same thing as a ledger row marked ``planned``.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sumo_qa.ledger_models import EvidenceStatus

#: Versioned from the start (acceptance criterion). A consumer keys on this to
#: detect a schema it cannot read; ``load_test_case_export`` rejects a present
#: mismatch up front with a clear message.
EXPORT_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

#: Test-case priority. Four distinct levels, highest-first by convention. Named,
#: not numeric, so an export is self-describing without a legend.
Priority = Literal[
    "critical",
    "high",
    "medium",
    "low",
]


class QaTestCase(BaseModel):
    """One exportable QA test case — a structured record the host fills in.

    Pure shape: no inference. ``preconditions`` and ``steps`` are ordered lists
    (empty is valid); ``evidence_status`` reuses the risk-ledger vocabulary so a
    case and a ledger row mean the same thing by the same word.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Stable id WITHIN this export (e.g. 'TC1'). Not a cross-session id."
    )
    title: str = Field(description="One-line human title for the test case.")
    preconditions: list[str] = Field(
        default_factory=list,
        description="Ordered setup steps that must hold before the checks run (may be empty).",
    )
    steps: list[str] = Field(
        default_factory=list,
        description="Ordered actions/checks the case performs (may be empty for a pure assertion).",
    )
    expected_result: str = Field(
        description="The observable outcome that distinguishes pass from fail."
    )
    linked_risk_id: str | None = Field(
        default=None,
        description=(
            "Optional link to a risk id in a companion risk ledger (#144). Absence "
            "is fine — not every case traces to a single recorded risk."
        ),
    )
    priority: Priority
    evidence_status: EvidenceStatus

    @field_validator("id")
    @classmethod
    def _require_non_blank_id(cls, value: str) -> str:
        # A blank id can't anchor a stable row reference, so every projection
        # (JSON key, markdown row, CSV row) would be unreferenceable.
        if not value.strip():
            raise ValueError("test case id must be non-blank")
        return value

    @field_validator("title", "expected_result")
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        # title/expected_result are the two load-bearing human fields; a blank
        # one yields a meaningless exported row.
        if not value.strip():
            raise ValueError("must be non-blank")
        return value

    def is_flat(self) -> bool:
        """True when the case is a *flat* outline — at most one step/precondition.

        CSV export is documented as only suitable for flat test-case outlines; a
        case with multiple preconditions or steps would force a CSV cell to carry
        an ordered list, which CSV cannot represent without lossy flattening. This
        predicate lets the CSV formatter detect that case and refuse rather than
        silently collapse structure.
        """
        return len(self.preconditions) <= 1 and len(self.steps) <= 1


class QaTestCaseExport(BaseModel):
    """A versioned collection of exportable QA test cases.

    ``schema_version`` is required, not defaulted: a versioned artifact must carry
    its version explicitly so a producer that forgot to stamp the field can't
    sneak past validation. Python callers pass :data:`EXPORT_SCHEMA_VERSION`.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    title: str | None = Field(
        default=None,
        description="Optional human title for the whole export (e.g. the feature under test).",
    )
    test_cases: list[QaTestCase] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> QaTestCaseExport:
        # Case ids are the key every projection and any consumer keys on.
        # Duplicates would silently collapse two cases into one row.
        seen: set[str] = set()
        for case in self.test_cases:
            if case.id in seen:
                raise ValueError(f"duplicate test case id: {case.id!r}")
            seen.add(case.id)
        return self

    def is_flat(self) -> bool:
        """True when EVERY case is flat (CSV-exportable). Empty export is flat."""
        return all(case.is_flat() for case in self.test_cases)
