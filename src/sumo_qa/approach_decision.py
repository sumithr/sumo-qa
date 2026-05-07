"""Decide which QA approach to take for a given change.

The PRIMARY decider is the AI-sampling path inside `aqa_decide_approach`.
The host LLM is grounded as a senior QA engineer (ISTQB Foundation +
Advanced + specialty principles via SENIOR_QA_SYSTEM_PROMPT) and reasons
over the change shape, the loaded team rules, and the team standards to
pick an approach.

This module is the deterministic FALLBACK used only when the host doesn't
support MCP sampling or the user has set `QA_DISABLE_HOST_SAMPLING=1`. By
design it is the thinnest skeleton possible. It does NOT pattern-match —
not file extensions, not path substrings, not phrases. The AI is the
brain; pattern matching in the harness is exactly the failure mode the
user has been pushing back on (the harness can't guess intent or domain
better than the AI can read the change directly).

All the deterministic fallback does:

  - Honour caller-supplied signals (`is_bug`, `is_refactor`,
    `is_test_only`, `is_spike`, `is_strategic_planning`,
    `has_acceptance_criteria`) — the caller already classified the ask
    and is telling us how to route. This is not pattern matching; it's
    an explicit override.
  - Default to tdd-scaffold with a `reasoning_note` telling the caller
    that AI sampling is the right path for accurate routing.

If you want richer reasoning, approve MCP sampling for sumo-qa in your
host — the AI path is what makes this tool actually senior-QA shaped.

Approaches (canonical names; the AI path may invent variants):

  tdd-scaffold                     greenfield-ish change adding behaviour
  regression-first                 bug fix on existing code
  coverage-first-then-refactor     behaviour-preserving refactor
  strengthen-test-coverage         strengthen tests on UNCHANGED prod code
  verify-existing                  trivial / config / version-bump tweak
  no-tests-recommended             pure docs / comments / typos
  spike-first-then-tests           exploratory prototype
  strategy-orchestration           REPO-WIDE / POLICY ask, not a single change
"""
from __future__ import annotations

from typing import Any


_NEXT_TOOL: dict[str, dict[str, Any] | None] = {
    "tdd-scaffold": {
        "tool": "sumo_qa_scaffold_tests",
        "args_hint": {
            "work_item": "<the work item / change summary>",
            "test_conditions": ["<each acceptance criterion as a test condition>"],
            "target_paths": ["<the file(s) being changed>"],
        },
    },
    "regression-first": {
        "tool": "sumo_qa_scaffold_tests",
        "args_hint": {
            "work_item": "<a 1-line description of the bug>",
            "test_conditions": ["Reproduce the failing case exactly as the bug presents."],
            "target_paths": ["<file containing the bug>"],
        },
    },
    "coverage-first-then-refactor": {
        "tool": "sumo_qa_review_local_change",
        "args_hint": {
            "change_summary": "<refactor description>",
            "touched_files": ["<files being refactored>"],
        },
    },
    "strengthen-test-coverage": {
        "tool": "sumo_qa_scaffold_tests",
        "args_hint": {
            "work_item": "Strengthen tests against unchanged production code (e.g. kill surviving mutants / raise coverage)",
            "test_conditions": [
                "<one condition per weak assertion or surviving mutant: name what would break if the test were correct>"
            ],
            "target_paths": ["<the existing test file(s) you're strengthening>"],
        },
    },
    "verify-existing": None,
    "no-tests-recommended": None,
    "spike-first-then-tests": None,
    "strategy-orchestration": None,
}


_FOLLOW_UP: dict[str, str] = {
    "tdd-scaffold": (
        "After scaffolding: run each verify_command, see all assertions fail, "
        "implement production code, re-run, see green."
    ),
    "regression-first": (
        "After the reproducer is in place: run the verify_command - test fails. "
        "Implement the fix. Re-run - test passes. Then run a targeted regression "
        "around the impacted area, not the whole suite."
    ),
    "coverage-first-then-refactor": (
        "Use the review verdict + missing_test_levels to find gaps. Add "
        "characterization tests for the current behaviour BEFORE the refactor. "
        "Refactor. Re-run the same tests; they must still pass unchanged."
    ),
    "verify-existing": (
        "Run the existing test suite (`pytest`, `npm test`, etc.) and a smoke "
        "of the touched path. No new tests required for a config-only / "
        "trivial-tweak change."
    ),
    "no-tests-recommended": (
        "Run the build / lint and any documentation linters. No QA test work."
    ),
    "spike-first-then-tests": (
        "Spike freely without tests. When the design settles, capture the "
        "discovered test conditions and call sumo_qa_create_test_plan + "
        "sumo_qa_scaffold_tests on the productionised pass."
    ),
    "strengthen-test-coverage": (
        "For each surviving mutant or weak assertion, scaffold ONE targeted "
        "strengthening test. Re-run the coverage / mutation tool. Iterate "
        "until the threshold is met. For equivalent mutants (e.g. early-return "
        "on already-empty branches, generated lambda noise, logger removals, "
        "synthetic-line Pair.equals), suppress in tool config rather than "
        "chasing them - the tool literature calls these 'equivalent mutants' "
        "and they are not real coverage gaps."
    ),
    "strategy-orchestration": (
        "STOP - this is a strategy ask, not a single change. Load the "
        "sumo-qa-strategising skill. That skill walks the repo with your "
        "host file tools (Glob / Read / Grep / git log) FIRST to map "
        "languages, frameworks, untested domains, gates, hotspots; THEN "
        "chains sumo_qa_decide_approach per priority area. Do not call "
        "sumo_qa_scaffold_tests, sumo_qa_create_test_plan, or "
        "sumo_qa_review_local_change yet - they're per-change tools, "
        "wrong-shaped for a strategy ask."
    ),
}


_ALTERNATIVES_BY_APPROACH: dict[str, list[dict[str, str]]] = {
    "tdd-scaffold": [
        {"approach": "regression-first", "when": "if this is actually fixing an existing-code defect, not adding new behaviour"},
        {"approach": "coverage-first-then-refactor", "when": "if the change is intended to be behaviour-preserving"},
        {"approach": "strengthen-test-coverage", "when": "if production code stays unchanged and only the tests need to get stronger"},
    ],
    "regression-first": [
        {"approach": "tdd-scaffold", "when": "if you also need to add new behaviour as part of the fix"},
        {"approach": "verify-existing", "when": "if the bug is actually in config / data, not code"},
    ],
    "coverage-first-then-refactor": [
        {"approach": "tdd-scaffold", "when": "if the refactor is changing behaviour after all"},
        {"approach": "verify-existing", "when": "if existing test coverage is already known to be strong"},
    ],
    "verify-existing": [
        {"approach": "tdd-scaffold", "when": "if the config change crosses an integration boundary or an SLA"},
        {"approach": "regression-first", "when": "if the config change is reverting a known prior incident"},
    ],
    "no-tests-recommended": [
        {"approach": "verify-existing", "when": "if the doc change references behaviour you should re-confirm with a smoke"},
    ],
    "spike-first-then-tests": [
        {"approach": "tdd-scaffold", "when": "once the spike's design is locked in"},
    ],
    "strengthen-test-coverage": [
        {"approach": "coverage-first-then-refactor", "when": "if you also plan to refactor the production code as part of this work"},
        {"approach": "regression-first", "when": "if the weak tests are masking an actual production bug, not just thin coverage"},
    ],
    "strategy-orchestration": [
        {"approach": "strengthen-test-coverage", "when": "if the user actually wants to fix one specific gate / one weak test, not a repo-wide strategy"},
        {"approach": "tdd-scaffold", "when": "if the user actually wants to add new behaviour to one specific area, not a strategy"},
    ],
}


_FALLBACK_NOTE = (
    "Deterministic fallback - the AI-sampling path inside sumo_qa_decide_approach "
    "is where senior-QA reasoning happens. Approve MCP sampling for sumo-qa in your "
    "host, or set the env var QA_DISABLE_HOST_SAMPLING=1 to silence this. The "
    "fallback never phrase-matches intent text, so novel asks will land here as "
    "a low-confidence default - that's deliberate."
)


def choose_approach(
    intent_text: str,
    classifications: list[str],
    target_paths: list[str],
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic-fallback decider.

    The AI-sampling path is the senior-QA brain. This function exists only
    for the case where MCP sampling isn't available. It does NOT pattern-
    match — not on intent text, not on file extensions, not on path
    substrings. It honours explicit caller-supplied signals (an override,
    not pattern matching), and otherwise returns a generic tdd-scaffold
    skeleton with a `reasoning_note` telling the caller that AI sampling
    is the right path for accurate routing.

    `intent_text`, `classifications`, and `target_paths` are accepted for
    API stability but the deterministic path no longer reads them — the
    AI is the only thing that should be reasoning about a change.
    """
    signals = signals or {}

    # Caller-supplied override signals — the caller has already classified
    # the ask and is telling us how to route. Not pattern matching.
    if signals.get("is_strategic_planning"):
        return _build_decision(
            "strategy-orchestration",
            (
                "Caller flagged this as a repo-wide strategy ask. Per-change MCP "
                "tools are the wrong shape - load the sumo-qa-strategising skill "
                "and walk the repo with your file tools first, then chain "
                "sumo_qa_decide_approach per priority area."
            ),
            confidence="high",
        )
    if signals.get("is_test_only"):
        return _build_decision(
            "strengthen-test-coverage",
            (
                "Caller flagged this as a tests-only change against unchanged "
                "production code. For each surviving mutant / weak assertion, "
                "scaffold one targeted strengthening test. Suppress equivalent "
                "mutants in tool config rather than chasing them."
            ),
            confidence="high",
        )
    if signals.get("is_bug"):
        return _build_decision(
            "regression-first",
            (
                "Caller flagged this as a bug fix on existing code. Reproduce "
                "the failure as one failing test, fix production code, confirm "
                "green; then run targeted regression on the impacted area."
            ),
            confidence="high",
        )
    if signals.get("is_refactor"):
        return _build_decision(
            "coverage-first-then-refactor",
            (
                "Caller flagged this as a behaviour-preserving refactor. Audit "
                "existing coverage of the touched code first; add characterization "
                "tests if there are gaps; refactor; rerun the same tests to "
                "confirm behaviour preserved."
            ),
            confidence="high",
        )
    if signals.get("is_spike"):
        return _build_decision(
            "spike-first-then-tests",
            (
                "Caller flagged this as exploratory / throwaway code. Apply test "
                "discipline to the productionised pass, not the spike itself."
            ),
            confidence="high",
        )
    if signals.get("is_docs_only"):
        return _build_decision(
            "no-tests-recommended",
            (
                "Caller flagged this as a docs / comment / typo change. No "
                "behaviour to test - run the build and any doc linters."
            ),
            confidence="high",
        )
    if signals.get("is_config_only"):
        return _build_decision(
            "verify-existing",
            (
                "Caller flagged this as a config-only change. Run the existing "
                "suite + a smoke of the touched code path; do not scaffold new tests."
            ),
            confidence="high",
        )

    # No signals + no AI = generic tdd-scaffold skeleton with an honest
    # reasoning_note. The deterministic harness deliberately does not try
    # to be cleverer than this — the AI is what reads the change.
    confidence = "low"
    if signals.get("has_acceptance_criteria"):
        confidence = "medium"
    return _build_decision(
        "tdd-scaffold",
        (
            "Generic fallback. Without AI sampling the deterministic harness "
            "does not pattern-match the intent or paths to pick a specific "
            "approach. Defaulting to tdd-scaffold (plan -> red -> implement -> "
            "green) because that's the safest discipline when in doubt. Pass an "
            "explicit signal (is_bug / is_refactor / is_test_only / is_spike / "
            "is_docs_only / is_config_only / is_strategic_planning) or enable "
            "MCP sampling so the AI can read the change directly."
        ),
        confidence=confidence,
        reasoning_note=_FALLBACK_NOTE,
    )


def _build_decision(
    approach: str,
    rationale: str,
    confidence: str = "medium",
    reasoning_note: str | None = None,
) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "approach": approach,
        "rationale": rationale,
        "next_action": _NEXT_TOOL.get(approach),
        "follow_up": _FOLLOW_UP.get(approach, ""),
        "confidence": confidence,
        "alternatives": _ALTERNATIVES_BY_APPROACH.get(approach, []),
    }
    if reasoning_note:
        decision["reasoning_note"] = reasoning_note
    return decision
