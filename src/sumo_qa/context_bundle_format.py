# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic markdown projection of a context bundle (issue #149).

Pure formatting — NO inference. Given an already-validated
:class:`ContextBundle`, ``format_context_bundle_markdown`` renders a compact,
host-neutral brief the review/planning skills can read at the top of a turn, and
``compact_summary`` renders a one-line roll-up.

The projection is *honest about freshness*: every go-stale fact (CI, tests) is
rendered with its freshness, and an explicit **Stale-evidence warning** block is
emitted when any present fact is stale or otherwise not trustworthy for a safety
claim. A consumer reading the markdown cannot miss that a stale pass is not
current — that is the acceptance criterion this projection enforces.

When a ``local_head_sha`` is supplied and conflicts with the bundle's
``head_sha``, a **Conflict** block is emitted (via ``detect_local_conflict``) so
the skill calls out the divergence rather than silently trusting the bundle.

Output is bounded: the changed-file list truncates past ``max_files`` so a large
diff can't blow the host/MCP token budget (the #89/#137 token-budget guard).
"""

from __future__ import annotations

import re

from sumo_qa.context_bundle_models import (
    ContextBundle,
    EvidenceFact,
    detect_local_conflict,
)

#: Default cap on rendered changed-file rows. A larger diff is truncated with an
#: explicit "+N more" notice rather than silently dropping files.
DEFAULT_MAX_FILES = 40


def _flatten(value: str) -> str:
    # Collapse any line/paragraph/vertical separator to a single space so a
    # multi-line free-text field (issue/PR summary, constraint) can't break the
    # markdown structure or inject markdown on a fresh line. Mirrors the ledger
    # formatter's separator handling.
    return re.sub(r"[\r\n\x0b\x0c\x1c\x1d\x1e\x85  ]+", " ", value).strip()


def _evidence_line(label: str, fact: EvidenceFact | None) -> str:
    if fact is None:
        return f"- **{label}:** not supplied."
    parts = [f"result={fact.result}", f"freshness={fact.freshness}", f"source={fact.source}"]
    if fact.captured_at:
        parts.append(f"captured_at={_flatten(fact.captured_at)}")
    if fact.detail:
        parts.append(_flatten(fact.detail))
    trust = "" if fact.is_trustworthy_for_safety() else "  ⚠ not safety-supporting"
    return f"- **{label}:** {', '.join(parts)}.{trust}"


def format_context_bundle_markdown(
    bundle: ContextBundle,
    *,
    local_head_sha: str | None = None,
    max_files: int = DEFAULT_MAX_FILES,
) -> str:
    """Render the bundle as a compact, host-neutral markdown brief.

    ``local_head_sha`` (optional) is the host's live local head; when it differs
    from the bundle's ``head_sha`` a conflict block is emitted. ``max_files``
    caps the rendered changed-file list.
    """
    lines: list[str] = ["**Context bundle**"]

    if bundle.head_sha:
        lines.append(f"- **Head:** {_flatten(bundle.head_sha)}")
    if bundle.issue_summary:
        lines.append(f"- **Issue:** {_flatten(bundle.issue_summary)}")
    if bundle.pr_summary:
        lines.append(f"- **PR:** {_flatten(bundle.pr_summary)}")

    lines.append(_evidence_line("Tests", bundle.test_evidence))
    lines.append(_evidence_line("CI", bundle.ci_status))

    if bundle.changed_files:
        cap = max(max_files, 0)
        shown = bundle.changed_files[:cap]
        hidden = len(bundle.changed_files) - len(shown)
        rendered = ", ".join(f"{_flatten(f.path)} ({f.change_kind})" for f in shown)
        lines.append(f"- **Changed files ({len(bundle.changed_files)}):** {rendered}")
        if hidden:
            lines.append(f"  … +{hidden} more file(s) truncated.")
    else:
        lines.append("- **Changed files:** none supplied.")

    if bundle.user_constraints:
        lines.append("- **Constraints:**")
        for constraint in bundle.user_constraints:
            lines.append(f"  - {_flatten(constraint)}")

    # Stale / untrustworthy evidence callout — the safety-honesty block. Listed
    # whenever a present go-stale fact is not a fresh pass, so a stale/unknown
    # pass can never be silently read as current.
    untrusted = bundle.untrustworthy_evidence_fields()
    if untrusted:
        stale = set(bundle.stale_evidence_fields())
        lines.append("")
        lines.append("**Stale-evidence warning:**")
        for field in untrusted:
            fact = bundle.test_evidence if field == "test_evidence" else bundle.ci_status
            assert fact is not None  # untrustworthy fields are always present
            reason = "stale" if field in stale else f"{fact.freshness}/{fact.result}"
            lines.append(
                f"- `{field}` is NOT safety-supporting ({reason}); treat it as "
                "stale and re-verify against fresh evidence — do not claim safety from it."
            )

    conflict = detect_local_conflict(bundle, local_head_sha)
    if conflict is not None:
        lines.append("")
        lines.append("**Conflict — bundle vs. local state:**")
        lines.append(f"- {conflict}")

    return "\n".join(lines)


def compact_summary(bundle: ContextBundle, *, local_head_sha: str | None = None) -> str:
    """Render a single-line roll-up of the bundle's trust state.

    Example: ``Context bundle: 3 changed file(s); tests passing/fresh, CI
    passing/stale; 1 stale-evidence field; bundle-vs-local conflict.`` Clauses
    are omitted when they don't apply.
    """
    parts = [f"{len(bundle.changed_files)} changed file(s)"]

    ev_parts = []
    if bundle.test_evidence is not None:
        ev_parts.append(f"tests {bundle.test_evidence.result}/{bundle.test_evidence.freshness}")
    if bundle.ci_status is not None:
        ev_parts.append(f"CI {bundle.ci_status.result}/{bundle.ci_status.freshness}")
    if ev_parts:
        parts.append(", ".join(ev_parts))

    untrusted = bundle.untrustworthy_evidence_fields()
    if untrusted:
        parts.append(f"{len(untrusted)} non-fresh evidence field(s)")

    if detect_local_conflict(bundle, local_head_sha) is not None:
        parts.append("bundle-vs-local conflict")

    return "Context bundle: " + "; ".join(parts) + "."
