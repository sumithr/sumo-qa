# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Gate-evidence schema for host-LLM QA claims (issue #213).

An LLM cannot be relied on to follow a procedure or report execution
truthfully by instruction alone. This module gives a *lightweight,
deterministic* record for the gate claims a host LLM makes during a QA
workflow — "tests passed", "safe to merge", "risk covered", "catalogue
loaded", "gate blocked" — so an unsupported pass/safe claim can be CAUGHT by a
validator instead of trusted on faith.

It does NOT make the LLM deterministic and it does NOT observe every host-side
action on its own. It locks the SHAPE of a claim: a claim asserting an
execution outcome must cite the observed evidence that backs it, or mark itself
``unverified``. That is the honesty boundary the repo can point at — the model
is probabilistic, but a safety claim must carry evidence.

This is a standalone schema + helpers; it is deliberately NOT wired into the
MCP tool-output surface, so the existing ``isError`` envelope behaviour in
``server.py`` / ``server_schemas.py`` is untouched.

Statuses (``GateStatus``):

* ``passed``     — the gate ran and its check succeeded.
* ``failed``     — the gate ran and its check failed.
* ``skipped``    — the gate was deliberately not run (not applicable this turn).
* ``blocked``    — the gate could not run because a precondition/dependency failed.
* ``unverified`` — no evidence was observed; the honest "cannot claim" state.

Evidence source types (``EvidenceSource``) — where an observation came from:

* ``command``            — a shell command the host ran (its output is the proof).
* ``tool_call``          — a tool/function invocation and its returned result.
* ``file_read``          — reading a file's contents (a coverage report, a lockfile).
* ``user_fact``          — a fact the user asserted (product context the diff can't show).
* ``external_ci``        — an external CI / pipeline result.
* ``manual_observation`` — a human/agent observation not captured by the above.

Evidence rule (enforced at construction, mirroring the ledger schema's
validators): an evidence-backed status (``passed`` / ``failed`` / ``blocked``)
MUST cite at least one :class:`EvidenceItem`; ``unverified`` MUST cite none
(evidence would contradict the "unverified" label — use ``passed`` /
``failed`` / ``blocked`` instead); ``skipped`` may cite none.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GATE_EVIDENCE_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

GateStatus = Literal[
    "passed",
    "failed",
    "skipped",
    "blocked",
    "unverified",
]

EvidenceSource = Literal[
    "command",
    "tool_call",
    "file_read",
    "user_fact",
    "external_ci",
    "manual_observation",
]

# Statuses that assert an OBSERVED outcome and therefore require evidence. A
# frozenset (not a re-derived Literal) so the model validator and any caller
# branch on one authoritative definition.
EVIDENCE_REQUIRED_STATUSES: Final[frozenset[str]] = frozenset({"passed", "failed", "blocked"})


def status_requires_evidence(status: str) -> bool:
    """True when a claim of this status must cite at least one evidence item.

    Deterministic and side-effect free so the transcript-level validator and
    skill logic can branch on the same rule the model enforces.
    """
    return status in EVIDENCE_REQUIRED_STATUSES


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    detail: str = Field(
        description=(
            "What was observed — the command that ran, the tool invoked, the file "
            "read + what it showed, the user's stated fact, or the CI result."
        )
    )

    @field_validator("detail")
    @classmethod
    def _require_non_blank_detail(cls, value: str) -> str:
        # A blank detail is not evidence — it names no observation, so it could
        # let an unsupported claim smuggle past the "cite evidence" rule.
        if not value.strip():
            raise ValueError("evidence detail must be non-blank")
        return value


class GateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: str = Field(
        description="The gate being claimed about — e.g. 'tests', 'safe_to_merge', 'risk_covered'."
    )
    status: GateStatus
    statement: str = Field(description="The claim in plain English, as surfaced to the user.")
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @field_validator("gate", "statement")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("gate and statement must be non-blank")
        return value

    @model_validator(mode="after")
    def _evidence_matches_status(self) -> GateClaim:
        # The whole point of the schema: an execution-outcome claim without
        # cited evidence is exactly the "unsupported pass claim" this issue
        # exists to reject.
        if status_requires_evidence(self.status) and not self.evidence:
            raise ValueError(
                f"a {self.status!r} gate claim must cite at least one evidence item "
                "(or use status 'unverified')"
            )
        # 'unverified' is the honest no-evidence state; attaching evidence to it
        # is a contradiction — the claim should then be passed/failed/blocked.
        if self.status == "unverified" and self.evidence:
            raise ValueError(
                "an 'unverified' gate claim must not cite evidence; "
                "use 'passed'/'failed'/'blocked' instead"
            )
        return self


class GateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required, not defaulted: a versioned artifact must carry its version stamp
    # explicitly so a producer that forgot to stamp it can't sneak past
    # validation (the same contract the ledger schema uses).
    schema_version: Literal["1.0"]
    claims: list[GateClaim] = Field(default_factory=list)

    def unresolved_gates(self) -> list[GateClaim]:
        """Claims that are neither ``passed`` nor deliberately ``skipped``.

        Deterministic: returns every ``failed`` / ``blocked`` / ``unverified``
        claim — the gates that prevent an honest "everything passed" report and
        that a workflow must surface rather than overstate.
        """
        return [c for c in self.claims if c.status not in ("passed", "skipped")]

    def is_clean(self) -> bool:
        """True when no gate is unresolved — a clean report with no overstatement."""
        return not self.unresolved_gates()
