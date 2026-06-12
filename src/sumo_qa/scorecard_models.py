# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Schema + evidence semantics for the QA readiness scorecard (issue #151).

The scorecard is an *evidence summary*, NOT a predictive quality score. It does
no risk inference of its own: it COMPOSES the artifacts the host already
produces — the #144 risk-to-test ledger and the #149 issue/PR context bundle,
plus optional coverage / mutation signals — and DERIVES a readiness
recommendation from them deterministically. The host never asserts "ready"; the
recommendation is computed from the supplied evidence, which is what makes the
"refuse ready when risks are uncovered or evidence is stale" guarantee
structural rather than advisory.

## Why there is no numeric score

Acceptance criterion: the scorecard "avoids unsupported numeric quality scores
unless every component is transparent and evidence-backed". A composite 0–100
"quality score" is fake precision — it blends incommensurable signals behind one
number. So this module emits only *counts of real evidence* (N risks, M passing,
K uncovered blockers) and *categorical states*, every one of which is traceable
to a supplied row or fact. No percentage is invented.

## The four recommendation states (derived, first-match-wins)

* ``blocked``                        — a hard stop exists: an uncovered
                                       high-impact risk (a ledger
                                       ``is_uncovered_blocker`` row) or a present
                                       failing/mixed test or CI result. You may
                                       not ship.
* ``insufficient_evidence``          — no blocker, but readiness cannot be
                                       *asserted*: required test evidence is
                                       absent, stale, or unknown-freshness; a
                                       ledger risk is only ``planned`` (not run)
                                       or ``stale``; or no evidence was supplied
                                       at all. "Tests are stale" lands here, not
                                       in ``ready`` — the acceptance criterion
                                       this state exists to enforce.
* ``ready_with_accepted_residuals``  — evidence is sufficient and nothing blocks,
                                       but at least one risk is a consciously
                                       accepted residual (covered by an explicit
                                       accept decision, not a passing test).
* ``ready``                          — evidence is sufficient, fresh, and
                                       passing; no blockers and no accepted
                                       residuals.

## Per-dimension status

Each dimension (risk coverage, test evidence, CI, coverage, mutation, residual
risks) carries its own status so the markdown table and the serialized snapshot
(#157's ``.sumo-qa/qa-report.html``) can show *where* the evidence is thin:

* ``ok``            — the dimension is satisfied by fresh, passing evidence.
* ``gap``           — a non-blocking shortfall (e.g. a planned-not-run risk).
* ``blocker``       — a shortfall that blocks readiness (uncovered blocker,
                      failing result).
* ``stale``         — evidence exists but is not trustworthy now (stale / unknown
                      freshness).
* ``not_measured``  — the optional signal was not supplied. Distinct from a
                      *passing* signal: an absent coverage/mutation artifact is
                      reported as ``not_measured`` and never assumed green, so it
                      can never outweigh an uncovered high-impact risk.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sumo_qa.context_bundle_models import (
    ContextBundle,
    EvidenceFreshness,
    detect_local_conflict,
)
from sumo_qa.ledger_models import RiskLedger, RiskLedgerRow

SCORECARD_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

#: Plain-language labels + freshness words for the human-facing recommendation
#: reasons. The reasons surface verbatim in the scorecard output AND in the
#: #157 QA report's verdict block, so a raw field name (``test_evidence``) or a
#: ``key=value`` debug fragment must never reach them.
_EVIDENCE_LABELS: Final[dict[str, str]] = {
    "test_evidence": "test evidence",
    "ci_status": "CI",
}
_FRESHNESS_WORDS: Final[dict[str, str]] = {
    "stale": "stale",
    "unknown": "of unknown freshness",
    "absent": "not yet captured",
}

#: The final readiness verdict. Four DISTINCT states (issue #151 AC + the #154
#: scope comment) — see the module docstring for the derivation order.
ScorecardRecommendation = Literal[
    "ready",
    "ready_with_accepted_residuals",
    "blocked",
    "insufficient_evidence",
]

#: Per-dimension status. ``not_measured`` (absent optional signal) is held
#: distinct from ``ok`` so an unsupplied coverage/mutation artifact is never read
#: as passing.
DimensionStatus = Literal[
    "ok",
    "gap",
    "blocker",
    "stale",
    "not_measured",
]


class _MeasurementSignal(BaseModel):
    """Shared base for the optional coverage/mutation signals.

    A signal is only *evidence* when it carries an actual measurement; the
    ``freshness`` and ``detail`` fields are metadata about a measurement, not a
    measurement themselves. ``has_measurement`` lets the load envelope collapse a
    payload that carries no measurement (an empty ``{}`` or freshness/detail
    only) to ``None`` so the dimension reports ``not_measured`` rather than
    claiming an unmeasured dimension was measured.
    """

    #: Subclass-declared names of the fields that carry an actual measurement.
    MEASUREMENT_FIELDS: ClassVar[tuple[str, ...]] = ()

    def has_measurement(self) -> bool:
        """True when at least one measurement field is populated (a zero counts)."""
        return any(getattr(self, name) is not None for name in self.MEASUREMENT_FIELDS)


class CoverageSignal(_MeasurementSignal):
    """An OPTIONAL line/branch-coverage signal (issue #147 artifacts).

    Reported, never gated on a threshold: the scorecard names the number and its
    freshness, but invents no "80% = ready" rule (that would be the fake
    precision the scorecard exists to avoid). Absence ⇒ the dimension is
    ``not_measured``, never assumed passing.
    """

    model_config = ConfigDict(extra="forbid")

    MEASUREMENT_FIELDS: ClassVar[tuple[str, ...]] = ("line_percent",)

    line_percent: float | None = Field(
        default=None, description="Optional line-coverage percentage in [0, 100]."
    )
    freshness: EvidenceFreshness = Field(
        default="unknown",
        description="Freshness of the coverage signal; non-fresh is reported, not trusted.",
    )
    detail: str | None = Field(default=None, description="Optional free-text detail.")

    @field_validator("line_percent")
    @classmethod
    def _percent_in_range(cls, value: float | None) -> float | None:
        if value is not None and not (0.0 <= value <= 100.0):
            raise ValueError("line_percent must be between 0 and 100")
        return value


class MutationSignal(_MeasurementSignal):
    """An OPTIONAL mutation-testing signal (surviving / killed mutants).

    Like coverage: reported with its freshness, never turned into a gate or a
    score. Absence ⇒ ``not_measured``.
    """

    model_config = ConfigDict(extra="forbid")

    MEASUREMENT_FIELDS: ClassVar[tuple[str, ...]] = ("survivors", "killed")

    survivors: int | None = Field(
        default=None, description="Optional count of surviving mutants (>= 0)."
    )
    killed: int | None = Field(default=None, description="Optional count of killed mutants (>= 0).")
    freshness: EvidenceFreshness = Field(
        default="unknown",
        description="Freshness of the mutation signal; non-fresh is reported, not trusted.",
    )
    detail: str | None = Field(default=None, description="Optional free-text detail.")

    @field_validator("survivors", "killed")
    @classmethod
    def _non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("mutant counts must be non-negative")
        return value


class ScorecardDimension(BaseModel):
    """One row of the scorecard table: a named evidence dimension + its status."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: DimensionStatus
    detail: str


class QaScorecard(BaseModel):
    """A readiness scorecard composed from already-produced QA evidence.

    Every field is optional — a scorecard built from nothing is valid and simply
    derives ``insufficient_evidence``. The model holds the *inputs*; the
    derivation methods compute the dimensions and the final recommendation. No
    field on this model lets a caller assert "ready" directly: readiness is only
    ever a computed conclusion from the evidence.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCORECARD_SCHEMA_VERSION
    scope: str | None = Field(
        default=None,
        description="Optional short label for what is being assessed (a PR title, a release name).",
    )
    ledger: RiskLedger | None = Field(
        default=None, description="The #144 risk-to-test ledger, when supplied."
    )
    context_bundle: ContextBundle | None = Field(
        default=None, description="The #149 issue/PR context bundle, when supplied."
    )
    coverage: CoverageSignal | None = Field(
        default=None, description="Optional coverage signal; absence ⇒ not_measured."
    )
    mutation: MutationSignal | None = Field(
        default=None, description="Optional mutation signal; absence ⇒ not_measured."
    )

    # ---- evidence helpers (deterministic, no inference) -------------------

    def _ledger_rows(self) -> list[RiskLedgerRow]:
        return list(self.ledger.rows) if self.ledger is not None else []

    def accepted_residual_rows(self) -> list[RiskLedgerRow]:
        """Rows representing a consciously accepted residual risk.

        Keyed on the dedicated ``accepted_residual`` evidence state — a deliberate
        decision not to fully cover, distinct from an un-run check. The ``residual``
        decision is a SEPARATE axis: the canonical ledger convention marks a fully
        covered risk ``passing`` / ``residual=accepted`` (accepted = the residual
        question is closed), so keying on ``residual == "accepted"`` would wrongly
        treat every covered risk as a residual and flip ``ready`` to
        ``ready_with_accepted_residuals``.
        """
        return [row for row in self._ledger_rows() if row.evidence_status == "accepted_residual"]

    def uncovered_blocker_rows(self) -> list[RiskLedgerRow]:
        """Ledger rows that are uncovered high-impact blockers (reuses #144)."""
        return [row for row in self._ledger_rows() if row.is_uncovered_blocker()]

    def open_residual_rows(self) -> list[RiskLedgerRow]:
        """Rows whose residual decision is still ``open`` (undecided)."""
        return [row for row in self._ledger_rows() if row.residual == "open"]

    def _has_fresh_pass(self) -> bool:
        """True when SOME supplied signal is a fresh, passing positive.

        A ``ready`` verdict needs a positive — not merely the absence of
        blockers. A fresh-passing CI/test fact qualifies; so does a ledger row
        whose evidence is ``passing`` ("executed and currently passing" — the
        ledger holds ``stale`` as a separate state, so ``passing`` is current).
        """
        bundle = self.context_bundle
        if bundle is not None:
            for fact in (bundle.test_evidence, bundle.ci_status):
                if fact is not None and fact.is_trustworthy_for_safety():
                    return True
        return any(row.evidence_status == "passing" for row in self._ledger_rows())

    # ---- derivation (the heart — see module docstring) --------------------

    def blocking_reasons(self, *, local_head_sha: str | None = None) -> list[str]:
        """Hard stops that force ``blocked``. Empty ⇒ nothing blocks.

        A blocker is an uncovered high-impact risk (reusing #144's
        ``is_uncovered_blocker``), a ledger row whose covering test is
        ``failing``, or a present test/CI fact whose result is ``failing`` /
        ``mixed``. Optional coverage/mutation signals are deliberately NOT
        consulted here — they can never outweigh an uncovered high-impact risk.
        """
        reasons: list[str] = []
        for row in self.uncovered_blocker_rows():
            reasons.append(f"{row.risk_id}: {row.risk} (uncovered high-impact risk)")
        for row in self._ledger_rows():
            # A failing covering test blocks even when residual != blocker; skip
            # rows already reported as uncovered blockers to avoid double-listing.
            if row.evidence_status == "failing" and not row.is_uncovered_blocker():
                reasons.append(f"{row.risk_id}: {row.risk} (covering test is failing)")
        bundle = self.context_bundle
        if bundle is not None:
            for label, fact in (
                ("test evidence", bundle.test_evidence),
                ("CI", bundle.ci_status),
            ):
                if fact is not None and fact.result in ("failing", "mixed"):
                    outcome = "failing" if fact.result == "failing" else "mixed (some failures)"
                    reasons.append(f"{label} is {outcome}")
        return reasons

    def insufficiency_reasons(self, *, local_head_sha: str | None = None) -> list[str]:
        """Reasons readiness cannot be asserted (absent/stale/unknown evidence).

        Only meaningful once ``blocking_reasons`` is empty; an empty list here
        (with no blockers) means the evidence is sufficient to claim readiness.
        Stale/unknown evidence and planned-not-run risks land here — this is the
        state that enforces "do not claim ready when tests are stale".
        """
        rows = self._ledger_rows()
        bundle = self.context_bundle

        has_ledger = bool(rows)
        has_bundle_signal = bundle is not None and (
            bundle.test_evidence is not None
            or bundle.ci_status is not None
            or bool(bundle.changed_files)
        )
        if not has_ledger and not has_bundle_signal:
            return ["no QA evidence supplied, so readiness cannot be assessed"]

        reasons: list[str] = []
        accepted_ids = {row.risk_id for row in self.accepted_residual_rows()}
        for row in rows:
            if row.risk_id in accepted_ids:
                continue
            if row.evidence_status == "stale":
                reasons.append(f"{row.risk_id}: {row.risk} (covering evidence is stale)")
            elif row.evidence_status == "planned":
                reasons.append(
                    f"{row.risk_id}: {row.risk} (covering test only planned, not executed)"
                )

        if bundle is not None:
            for name in bundle.untrustworthy_evidence_fields():
                fact = bundle.test_evidence if name == "test_evidence" else bundle.ci_status
                # failing/mixed is a blocker, reported there — not an insufficiency.
                if fact is not None and fact.result in ("failing", "mixed"):
                    continue
                assert fact is not None  # untrustworthy fields are always present
                label = _EVIDENCE_LABELS.get(name, name.replace("_", " "))
                # A fact is untrustworthy either because its freshness is not
                # trustworthy (stale/unknown/absent) OR because it is fresh+passing
                # but was captured against a different commit (sha mismatch). The
                # `_FRESHNESS_WORDS` keys ARE the non-trustworthy freshness values,
                # so a freshness outside them can only be the sha-mismatch case —
                # never describe a fresh fact as "but fresh".
                if fact.freshness in _FRESHNESS_WORDS:
                    why = _FRESHNESS_WORDS[fact.freshness]
                else:
                    why = "was captured against a different commit"
                reasons.append(
                    f"{label} is {fact.result} but {why}, so it cannot support a ready verdict"
                )
            if detect_local_conflict(bundle, local_head_sha) is not None:
                reasons.append("context bundle is stale relative to the local tree")

        if not self._has_fresh_pass():
            reasons.append("no fresh, passing test evidence to support a ready verdict")

        # De-dup, preserving first-seen order.
        seen: set[str] = set()
        deduped: list[str] = []
        for reason in reasons:
            if reason not in seen:
                seen.add(reason)
                deduped.append(reason)
        return deduped

    def recommendation(self, *, local_head_sha: str | None = None) -> ScorecardRecommendation:
        """Derive the final readiness verdict from the supplied evidence.

        First-match-wins over the four states: a hard stop ⇒ ``blocked``;
        otherwise insufficient/stale/unknown evidence ⇒ ``insufficient_evidence``;
        otherwise an accepted residual ⇒ ``ready_with_accepted_residuals``;
        otherwise ``ready``. The caller cannot short-circuit to ready: it is only
        reached when nothing blocks AND the evidence is sufficient.
        """
        if self.blocking_reasons(local_head_sha=local_head_sha):
            return "blocked"
        if self.insufficiency_reasons(local_head_sha=local_head_sha):
            return "insufficient_evidence"
        if self.accepted_residual_rows():
            return "ready_with_accepted_residuals"
        return "ready"

    def is_ready(self, *, local_head_sha: str | None = None) -> bool:
        """True when the verdict permits shipping (ready or ready-with-residuals)."""
        return self.recommendation(local_head_sha=local_head_sha) in (
            "ready",
            "ready_with_accepted_residuals",
        )

    def dimensions(self, *, local_head_sha: str | None = None) -> list[ScorecardDimension]:
        """Per-dimension status rows for the scorecard table + serialized snapshot.

        The test/CI dimensions consult the SAME trust signals the recommendation
        uses — ``untrustworthy_evidence_fields`` (which folds in a stale freshness
        AND a capture-sha mismatch) plus a bundle-vs-local-head conflict — so the
        table never reads ``ok`` for a fact the verdict treats as stale.
        """
        bundle = self.context_bundle
        untrustworthy: set[str] = set()
        bundle_conflicted = False
        if bundle is not None:
            untrustworthy = set(bundle.untrustworthy_evidence_fields())
            bundle_conflicted = detect_local_conflict(bundle, local_head_sha) is not None
        return [
            self._risk_coverage_dimension(),
            self._evidence_dimension(
                "Test evidence",
                "test_evidence",
                bundle.test_evidence if bundle is not None else None,
                untrustworthy=untrustworthy,
                bundle_conflicted=bundle_conflicted,
            ),
            self._evidence_dimension(
                "CI status",
                "ci_status",
                bundle.ci_status if bundle is not None else None,
                untrustworthy=untrustworthy,
                bundle_conflicted=bundle_conflicted,
            ),
            self._coverage_dimension(),
            self._mutation_dimension(),
            self._residual_dimension(),
        ]

    def _risk_coverage_dimension(self) -> ScorecardDimension:
        rows = self._ledger_rows()
        if not rows:
            return ScorecardDimension(
                name="Risk coverage", status="not_measured", detail="no risk ledger supplied"
            )
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.evidence_status] = counts.get(row.evidence_status, 0) + 1
        order = ["passing", "planned", "failing", "stale", "accepted_residual"]
        parts = [f"{counts[s]} {s.replace('_', ' ')}" for s in order if counts.get(s)]
        detail = f"{len(rows)} risk(s) — " + ", ".join(parts)
        blockers = self.uncovered_blocker_rows()
        if blockers:
            detail += f"; {len(blockers)} uncovered blocker(s)"

        if blockers or any(row.evidence_status == "failing" for row in rows):
            status: DimensionStatus = "blocker"
        elif any(row.evidence_status == "stale" for row in rows):
            status = "stale"
        elif any(row.evidence_status == "planned" for row in rows):
            status = "gap"
        else:
            status = "ok"
        return ScorecardDimension(name="Risk coverage", status=status, detail=detail)

    @staticmethod
    def _evidence_dimension(
        name: str,
        field: str,
        fact: object,
        *,
        untrustworthy: set[str],
        bundle_conflicted: bool,
    ) -> ScorecardDimension:
        from sumo_qa.context_bundle_models import EvidenceFact

        if fact is None:
            return ScorecardDimension(name=name, status="not_measured", detail="not supplied")
        assert isinstance(fact, EvidenceFact)
        detail = f"{fact.result}/{fact.freshness} ({fact.source})"
        if fact.result in ("failing", "mixed"):
            status: DimensionStatus = "blocker"
        elif field in untrustworthy or bundle_conflicted:
            # Not fresh-passing OR captured against a different sha OR the bundle
            # is stale relative to the live tree — the same signal that drives the
            # recommendation to insufficient_evidence.
            status = "stale"
        else:
            status = "ok"
        return ScorecardDimension(name=name, status=status, detail=detail)

    def _coverage_dimension(self) -> ScorecardDimension:
        cov = self.coverage
        if cov is None:
            return ScorecardDimension(name="Coverage", status="not_measured", detail="not measured")
        bits: list[str] = []
        if cov.line_percent is not None:
            bits.append(f"{cov.line_percent:g}% lines")
        bits.append(f"freshness={cov.freshness}")
        if cov.detail:
            bits.append(cov.detail)
        # Reported, never gated: coverage status does NOT feed the recommendation.
        status: DimensionStatus = "ok" if cov.freshness == "fresh" else "stale"
        return ScorecardDimension(name="Coverage", status=status, detail=", ".join(bits))

    def _mutation_dimension(self) -> ScorecardDimension:
        mut = self.mutation
        if mut is None:
            return ScorecardDimension(name="Mutation", status="not_measured", detail="not measured")
        bits: list[str] = []
        if mut.survivors is not None:
            bits.append(f"{mut.survivors} survivor(s)")
        if mut.killed is not None:
            bits.append(f"{mut.killed} killed")
        bits.append(f"freshness={mut.freshness}")
        if mut.detail:
            bits.append(mut.detail)
        status: DimensionStatus = "ok" if mut.freshness == "fresh" else "stale"
        return ScorecardDimension(name="Mutation", status=status, detail=", ".join(bits))

    def _residual_dimension(self) -> ScorecardDimension:
        accepted = len(self.accepted_residual_rows())
        open_count = len(self.open_residual_rows())
        # Residuals are informational: an accepted residual is a decision, not a
        # gap, so this dimension never blocks — it just records the counts.
        return ScorecardDimension(
            name="Residual risks",
            status="ok",
            detail=f"{accepted} accepted, {open_count} open",
        )
