# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Schema models for the host-neutral issue/PR context bundle (issue #149).

The context bundle is an *input contract* for QA review/planning workflows — a
compact, host-neutral way to hand the host LLM the issue, PR, diff, test, and CI
facts it would otherwise have to gather by inspecting the repo. It is NOT a
network requirement and NOT a GitHub dependency: every field can be filled from
manually supplied text, local git state, or an optional host integration. A
missing or partial bundle is first-class — the consuming skill falls back to
direct repo inspection (see ``skills/sumo-qa-reviewing-before-merge`` and
``skills/sumo-qa-preparing-for-work``).

No inference lives here. This module only locks the SHAPE of a bundle so a
deterministic helper can validate it, flag stale evidence, and report conflicts
against newer local repo state. Every field is supplied by the host; nothing is
derived from repo context by this code.

## Freshness is load-bearing

Facts that can go stale — CI status and test evidence — carry their own
``source`` and ``freshness`` metadata. ``freshness`` is one of four DISTINCT
states:

* ``fresh``   — captured against the bundle's current commit; trustworthy now.
* ``stale``   — captured against an OLDER commit than the bundle's
                ``head_sha`` (or otherwise known to predate the current state);
                a consumer must treat it as stale and MUST NOT claim safety from
                it (the acceptance criterion this module exists to enforce).
* ``unknown`` — no freshness signal supplied; the consumer cannot assume fresh,
                so it is treated as not-trustworthy-for-a-safety-claim, like
                ``stale``.
* ``absent``  — the evidence itself was not collected (no CI run, no test run);
                distinct from "ran but stale".

## Conflict with local state

A bundle is point-in-time. When the host can inspect a newer local commit, the
bundle's ``head_sha`` may not match the live ``local_head_sha`` the host reads.
``detect_local_conflict`` reports that mismatch so the consuming skill calls out
the conflict explicitly instead of silently trusting either side (the issue's
"do not let a context bundle override direct repo evidence" guard).
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTEXT_BUNDLE_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

#: Where a fact came from. Host-neutral: NOT a GitHub-only enum. ``manual`` is a
#: hand-supplied fact, ``local_git`` a fact read from local git state, ``github``
#: an optional GitHub-derived fact, ``ci_provider`` any CI system, ``other`` an
#: escape hatch. The vocabulary names capabilities, not one host's API.
FactSource = Literal[
    "manual",
    "local_git",
    "github",
    "ci_provider",
    "other",
]

#: Freshness of a go-stale fact (CI/test). See module docstring for the four
#: distinct states and why ``unknown`` is treated like ``stale`` for safety.
EvidenceFreshness = Literal[
    "fresh",
    "stale",
    "unknown",
    "absent",
]

#: Pass/fail roll-up for CI or a test run. ``not_run`` pairs with
#: ``freshness="absent"`` (nothing was executed); the other three are outcomes of
#: a run that DID happen (whose trustworthiness is then gated by ``freshness``).
EvidenceResult = Literal[
    "passing",
    "failing",
    "mixed",
    "not_run",
]

#: Freshness states a consumer may NOT treat as a basis for a safety claim. Both
#: ``stale`` (known older) and ``unknown`` (no signal) fail the safety gate; only
#: ``fresh`` evidence backs "safe". ``absent`` means nothing ran, which is also
#: not safe-supporting. So the ONLY safety-supporting state is ``fresh``.
NON_TRUSTWORTHY_FRESHNESS: Final[frozenset[str]] = frozenset({"stale", "unknown", "absent"})

#: Minimum length for a sha (or sha prefix) to be treated as a meaningful commit
#: identifier when comparing prefix-wise. Below this, a short string could
#: spuriously prefix-match an unrelated full sha (e.g. a 1-char "a"), so we fall
#: back to exact equality. Seven is git's conventional abbreviated-sha floor.
MIN_SHA_PREFIX_LEN: Final[int] = 7


def _sha_equivalent(a: str | None, b: str | None) -> bool:
    """True when two shas name the same commit, prefix-aware.

    Compares case-insensitively. An abbreviated sha that is a non-empty prefix
    of the fuller sha (in either direction) is the SAME commit. To avoid a short
    string spuriously matching an unrelated sha, prefix-matching only applies
    when the shorter side is at least :data:`MIN_SHA_PREFIX_LEN` chars; below
    that, equality is required. When the two are equal length, exact match.

    Absent or whitespace-only on either side ⇒ not equivalent (callers decide
    what an absent sha means; this helper only answers "do these two present
    shas match?").
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < MIN_SHA_PREFIX_LEN:
        return False
    return longer.startswith(shorter)


class EvidenceFact(BaseModel):
    """A go-stale fact (CI status or test evidence) with source + freshness.

    The result (passing/failing/…) is ONLY safety-supporting when ``freshness``
    is ``fresh``. ``is_trustworthy_for_safety`` encodes that: a stale pass, an
    unknown-freshness pass, or an absent run never backs a safe-to-merge claim.
    """

    model_config = ConfigDict(extra="forbid")

    result: EvidenceResult
    freshness: EvidenceFreshness
    source: FactSource
    captured_at: str | None = Field(
        default=None,
        description=(
            "Optional ISO-8601 timestamp (or any freshness marker) of when the "
            "evidence was captured. Absence does not imply fresh — freshness is "
            "carried by the `freshness` field, never inferred from a missing time."
        ),
    )
    captured_against_sha: str | None = Field(
        default=None,
        description=(
            "Optional commit the evidence was captured against. When it differs "
            "from the bundle head_sha the evidence is older than the current "
            "state — the producer should mark freshness='stale'."
        ),
    )
    detail: str | None = Field(
        default=None,
        description="Optional free-text detail (e.g. '3 failed, 211 passed').",
    )

    def is_trustworthy_for_safety(self) -> bool:
        """True only when this evidence may back a safe-to-merge claim.

        Deterministic: a fact is trustworthy for a safety claim iff it is a
        ``passing`` result captured ``fresh``. Any non-fresh freshness (stale,
        unknown, absent) or any non-passing result (failing, mixed, not_run)
        means the consumer MUST NOT claim safety from it.
        """
        if self.freshness in NON_TRUSTWORTHY_FRESHNESS:
            return False
        return self.result == "passing"

    def is_stale(self) -> bool:
        """True when the evidence ran but no longer reflects the current state.

        ``unknown`` is treated as stale-for-safety (see module docstring) but is
        NOT reported as stale here — only an explicitly ``stale`` freshness is a
        stale-evidence finding. ``absent`` means nothing ran, which is not
        "stale evidence".
        """
        return self.freshness == "stale"


class ChangedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Repo-relative path of the changed file.")
    change_kind: Literal["added", "modified", "removed", "renamed"] = Field(
        default="modified",
        description="How the file changed in this diff.",
    )

    @field_validator("path")
    @classmethod
    def _require_non_blank_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("changed file path must be non-blank")
        return value


class ContextBundle(BaseModel):
    """A host-neutral issue/PR context bundle for QA review/planning.

    Every field is optional — an empty bundle is a valid (if minimally useful)
    bundle, so an absent or partial bundle never fails to load. ``schema_version``
    defaults to :data:`CONTEXT_BUNDLE_SCHEMA_VERSION`, so an unstamped empty/partial
    bundle loads cleanly stamped ``"1.0"``; a PRESENT but mismatched version is
    still rejected by ``load_context_bundle`` (schema_version_mismatch). The
    consuming skill decides how much to trust based on what is present and on each
    go-stale fact's freshness.
    """

    model_config = ConfigDict(extra="forbid")

    # Defaulted (not required) so an unstamped empty/partial bundle still loads —
    # the first-class-partial contract. A present-but-mismatched version is still
    # rejected explicitly in context_bundle_validation.load_context_bundle.
    schema_version: Literal["1.0"] = CONTEXT_BUNDLE_SCHEMA_VERSION

    issue_summary: str | None = Field(
        default=None, description="Plain-text summary of the issue/ticket under review."
    )
    pr_summary: str | None = Field(
        default=None, description="Plain-text summary of the PR/change under review."
    )
    head_sha: str | None = Field(
        default=None,
        description=(
            "The commit the bundle describes. Compared against the host's live "
            "local head to detect a stale-bundle conflict (detect_local_conflict)."
        ),
    )
    changed_files: list[ChangedFile] = Field(default_factory=list)
    test_evidence: EvidenceFact | None = Field(
        default=None,
        description="Go-stale test-run evidence. None ⇒ no test evidence supplied.",
    )
    ci_status: EvidenceFact | None = Field(
        default=None,
        description="Go-stale CI evidence. None ⇒ no CI evidence supplied.",
    )
    user_constraints: list[str] = Field(
        default_factory=list,
        description="Host/user-supplied constraints the review must honour (e.g. 'no schema changes').",
    )
    # Optional links to local .sumo-qa artifacts (#154 scope update). Gated on
    # #155/#156: absence is fine — these are weaker, optional context, never a
    # blocker or a GitHub dependency.
    repo_map_ref: str | None = Field(
        default=None,
        description="Optional path/hash of a .sumo-qa/repo-map.json artifact (#155).",
    )
    diff_impact_ref: str | None = Field(
        default=None,
        description="Optional path/hash of a .sumo-qa/diff-impact.json artifact (#156).",
    )

    def _fact_sha_mismatched(self, fact: EvidenceFact | None) -> bool:
        """True when a fact was captured against a DIFFERENT commit than head.

        A fact may be labelled ``fresh``/``passing`` yet carry a
        ``captured_against_sha`` that does not match the bundle's ``head_sha`` —
        it was captured against another commit and is effectively stale, so it
        must not back safety. Compared PREFIX-AWARE (an abbreviated capture sha
        that prefixes the full head, or vice-versa, is the SAME commit and is NOT
        a mismatch). Only a mismatch when BOTH shas are present and they are not
        prefix-equivalent.
        """
        if fact is None or not fact.captured_against_sha or not self.head_sha:
            return False
        return not _sha_equivalent(fact.captured_against_sha, self.head_sha)

    def stale_evidence_fields(self) -> list[str]:
        """Names of the go-stale fields whose evidence is effectively stale.

        Returns ``["test_evidence"]``, ``["ci_status"]``, both, or none. A field
        is listed when its freshness is explicitly ``stale`` OR when it was
        captured against a commit other than ``head_sha`` (a sha mismatch — a
        fresh-labelled pass against another commit is still stale relative to the
        current state). Used by the formatter to emit an explicit stale-evidence
        callout so a consumer cannot silently treat a stale pass as current.
        """
        stale: list[str] = []
        for name, fact in (("test_evidence", self.test_evidence), ("ci_status", self.ci_status)):
            if fact is not None and (fact.is_stale() or self._fact_sha_mismatched(fact)):
                stale.append(name)
        return stale

    def untrustworthy_evidence_fields(self) -> list[str]:
        """Go-stale fields present but NOT trustworthy for a safety claim.

        Wider than ``stale_evidence_fields``: includes unknown-freshness and
        absent/failing/mixed evidence. A field is listed when it exists and
        either ``is_trustworthy_for_safety()`` is False OR it was captured
        against a commit other than ``head_sha`` (a sha mismatch — even a
        fresh+passing fact is untrustworthy when it was captured against a
        different commit). Empty ⇒ every present go-stale fact is a fresh pass
        captured against the current head.
        """
        untrusted: list[str] = []
        for name, fact in (("test_evidence", self.test_evidence), ("ci_status", self.ci_status)):
            if fact is not None and (
                not fact.is_trustworthy_for_safety() or self._fact_sha_mismatched(fact)
            ):
                untrusted.append(name)
        return untrusted


def detect_local_conflict(bundle: ContextBundle, local_head_sha: str | None) -> str | None:
    """Report a bundle-vs-local-state conflict, or None when consistent.

    A conflict exists when the bundle names a ``head_sha`` AND the host supplies
    a ``local_head_sha`` AND the two differ — the host can see a newer (or
    simply different) local commit than the bundle describes, so the bundle's
    facts may be out of date relative to the live tree.

    Deterministic and conservative: when either sha is absent there is no signal
    to compare, so no conflict is reported (the consumer falls back to direct
    inspection). The comparison is PREFIX-AWARE — an abbreviated sha on one side
    that prefixes the fuller sha on the other names the SAME commit and is NOT a
    conflict (only a mismatch when neither is a prefix of the other). The
    returned message is the actionable signal the skill surfaces verbatim; it
    never resolves the conflict by trusting one side.
    """
    if not bundle.head_sha or not local_head_sha:
        return None
    if _sha_equivalent(bundle.head_sha, local_head_sha):
        return None
    return (
        f"Context bundle describes commit {bundle.head_sha!r} but the local head is "
        f"{local_head_sha!r}. The bundle may be stale relative to the working tree — "
        "verify against the live diff before trusting the bundle's facts."
    )
