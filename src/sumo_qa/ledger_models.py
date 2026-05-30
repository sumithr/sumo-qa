# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Schema models for the risk-to-test traceability ledger (issue #144).

The ledger is a *structured appendix* to sumo-qa's markdown-first verdict — NOT
a replacement for it. The host LLM identifies the risks (skills already require
this); this module only locks the shape of a row so a deterministic helper can
validate, store, or format it. No inference lives here: a ``RiskLedgerRow`` is a
record the host fills in, and every field is supplied, never derived from repo
context by this code.

A row carries the six fields the issue's acceptance criteria require:

* ``risk_id``        — stable WITHIN a single response or exported artifact
                       (cross-session identity is deliberately out of scope until
                       a later persistence feature exists).
* ``risk``           — the risk statement in plain English.
* ``source_anchor``  — where the risk lives (``file:line``, a domain term, …).
* ``test``           — the covering test id OR a planned check phrase.
* ``evidence_status``— one of five DISTINCT states (see ``EvidenceStatus``).
* ``residual``       — the residual decision (see ``ResidualDecision``).

``repo_map_node_id`` optionally links a row to a ``.sumo-qa/repo-map.json`` node
(issue #154 scope update). It is optional by design: a missing or stale repo-map
must NOT block ledger creation — it is simply weaker evidence when absent.

The five evidence states map 1:1 onto the acceptance criteria's required
distinctions:

* ``planned``            — "planned but not executed".
* ``passing``            — "executed and passing".
* ``failing``            — "executed and failing".
* ``stale``              — "stale evidence" (a prior pass that no longer reflects
                           the current code).
* ``accepted_residual``  — "accepted residual risk" (a deliberate decision not to
                           cover, distinct from an un-run check).
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LEDGER_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

EvidenceStatus = Literal[
    "planned",
    "passing",
    "failing",
    "stale",
    "accepted_residual",
]

ResidualDecision = Literal[
    "open",
    "accepted",
    "mitigated",
    "blocker",
]


class RiskLedgerRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(
        description="Stable id WITHIN this response/artifact (e.g. 'R1'). Not a cross-session id."
    )
    risk: str = Field(description="The risk statement in plain English.")
    source_anchor: str = Field(
        description="Where the risk lives — 'file:line', a domain term, a contract name."
    )
    test: str = Field(description="The covering test id OR a planned check phrase ('planned: …').")
    evidence_status: EvidenceStatus
    residual: ResidualDecision
    repo_map_node_id: str | None = Field(
        default=None,
        description=(
            "Optional link to a .sumo-qa/repo-map.json node id (#154). Absence is "
            "fine — a missing repo-map is weaker evidence, never a blocker."
        ),
    )

    @field_validator("risk_id")
    @classmethod
    def _require_non_blank_id(cls, value: str) -> str:
        # A blank id can't anchor a stable row reference inside the document, so
        # the markdown projection would emit an unreferenceable row.
        if not value.strip():
            raise ValueError("risk_id must be non-blank")
        return value

    def is_uncovered_blocker(self) -> bool:
        """True when this row is a high-risk gap that should block safe-to-merge.

        Deterministic: a row is an uncovered blocker iff its evidence is not
        demonstrably passing AND it has not been explicitly accepted as a
        residual. ``accepted_residual`` evidence (a deliberate non-coverage
        decision) is never a blocker; neither is a ``passing`` row.
        """
        if self.evidence_status == "passing":
            return False
        if self.evidence_status == "accepted_residual":
            return False
        return self.residual == "blocker"


class RiskLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `schema_version` is required, not defaulted: a versioned artifact must
    # carry its version explicitly so a producer that forgot to stamp the field
    # can't sneak past validation. Python callers pass LEDGER_SCHEMA_VERSION.
    schema_version: Literal["1.0"]
    rows: list[RiskLedgerRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_risk_ids(self) -> RiskLedger:
        # Risk ids are the lookup key the markdown projection and any consumer
        # key on. Duplicates would silently collapse two risks into one row.
        seen: set[str] = set()
        for row in self.rows:
            if row.risk_id in seen:
                raise ValueError(f"duplicate risk id: {row.risk_id!r}")
            seen.add(row.risk_id)
        return self
