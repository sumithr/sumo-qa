"""Repo scenarios for the sumo-qa iteration loop.

Each scenario stresses a slice of the rubric. The suite spans the full
specificity spectrum (very-specific -> very-generic) so the iteration
loop catches both the "AI reads exact diff" case and the "AI reasons
about strategy" case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SPECIFICITY_VALUES: tuple[str, ...] = (
    "very-specific",
    "specific",
    "moderate",
    "generic",
    "very-generic",
)


@dataclass(frozen=True)
class RepoScenario:
    """One scenario the iteration loop dispatches to a subagent.

    `rubric_focus` is a list of tags this scenario is meant to stress.
    Tags can be either rubric dimension IDs (e.g. `principle_citation`,
    `decisive_routing`) or canonical approach names (e.g. `tdd-scaffold`,
    `verify-existing`). The mixed vocabulary is intentional — approach
    names double as searchable tags so the canonical-approach coverage
    test can find them.
    """

    id: str
    description: str
    tool: str
    args: dict[str, Any]
    specificity: str
    rubric_focus: list[str] = field(default_factory=list)
    repo_files_to_load: list[str] = field(default_factory=list)


SCENARIOS: list[RepoScenario] = [
    # --------------------- very-specific (one diff / one method) ----------------------
    RepoScenario(
        id="very-specific.bundle-validator-line-diff",
        description=(
            "Review a tdd-scaffold-shaped change: a specific 6-line diff inside "
            "BundleVariantValidator.kt that adds a new branch for empty variants. "
            "The AI must read the diff, name the boundary cases, and produce a "
            "smallest-useful-test-set (not a generic checklist)."
        ),
        tool="qa_review_local_change",
        args={
            "change_summary": "Add empty-variants branch to BundleVariantValidator (lines 42-47).",
            "diff": (
                "+ if (variants.isEmpty()) {\n"
                "+     return ValidationResult.failure(\"NO_VARIANTS\")\n"
                "+ }\n"
            ),
            "touched_files": [
                "src/main/kotlin/.../BundleVariantValidator.kt",
            ],
            "explicit_classifications": ["business_logic_change"],
        },
        specificity="very-specific",
        rubric_focus=[
            "principle_citation",
            "smallest_useful_test_set",
            "named_techniques",
            "no_generic_advice",
            "tdd-scaffold",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "build.gradle.kts",
        ],
    ),
    RepoScenario(
        id="very-specific.regression-stale-stock",
        description=(
            "regression-first scenario: a bug fix on existing code. User reports "
            "that bundles with stale stock get blocked at checkout. The AI must "
            "produce a reproducer-as-failing-test path, not a TDD scaffold."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "fix the bug where bundles with stale stock get blocked at checkout"
            ),
            "target_paths": ["src/main/kotlin/.../StockEligibility.kt"],
            "signals": {"is_bug": True},
        },
        specificity="very-specific",
        rubric_focus=["decisive_routing", "facts_vs_assumptions", "regression-first"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    # --------------------- specific (one class / one user story) ----------------------
    RepoScenario(
        id="specific.scaffold-bundle-validator",
        description=(
            "tdd-scaffold scenario: scaffold tests for the BundleVariantValidator "
            "class given two acceptance criteria. The AI must produce honest red-"
            "phase scaffolds with named ISTQB techniques."
        ),
        tool="qa_scaffold_tests",
        args={
            "work_item": (
                "Scaffold tests for BundleVariantValidator that block invalid "
                "variant payload shapes at write time."
            ),
            "test_conditions": [
                "Invalid bundle variants are blocked at write time.",
                "Each violation surfaces a clear reason and the offending SKU.",
            ],
            "target_paths": [
                "src/main/kotlin/.../BundleVariantValidator.kt",
            ],
            "explicit_classifications": ["business_logic_change", "api_contract_change"],
        },
        specificity="specific",
        rubric_focus=[
            "named_techniques",
            "smallest_useful_test_set",
            "specialty_awareness",
            "tdd-scaffold",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "src/test/kotlin/com/johnlewis/byvariantdatafeeder",
        ],
    ),
    RepoScenario(
        id="specific.security-token-refresh",
        description=(
            "Critical-path tdd-scaffold scenario: add JWT refresh-token validation "
            "in the auth boundary. The AI must surface the security-critical "
            "character (Foundation principle 4: defects cluster on critical paths) "
            "and recommend tighter coverage + at least one boundary test per rule."
        ),
        tool="qa_prepare_for_work",
        args={
            "work_item": "Add JWT refresh token validation in the auth boundary",
            "acceptance_criteria": [
                "Refresh tokens older than 7 days are rejected",
                "Tokens are rotated on use (single-use semantics)",
                "Replay of an old refresh token returns 401, not 500",
            ],
            "risk_notes": ["Critical path — auth boundary. Regression hits all customers."],
            "explicit_classifications": ["business_logic_change"],
        },
        specificity="specific",
        rubric_focus=[
            "principle_citation",
            "decisive_routing",
            "no_waived_evidence",
        ],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    # --------------------- moderate (a feature area) ----------------------
    RepoScenario(
        id="moderate.refactor-pricing-pipeline",
        description=(
            "coverage-first-then-refactor scenario: extract pricing calculation "
            "into its own module. No intended behaviour change. The AI must NOT "
            "scaffold new behaviour tests; it must say 'audit existing coverage "
            "first, add characterization tests for current behaviour, THEN refactor'."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "refactor the pricing pipeline to extract the eligibility step into "
                "its own module — no behaviour change intended"
            ),
            "target_paths": [
                "src/main/kotlin/.../pricing/PricingPipeline.kt",
            ],
            "signals": {"is_refactor": True},
        },
        specificity="moderate",
        rubric_focus=["decisive_routing", "coverage-first-then-refactor"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    RepoScenario(
        id="moderate.mutation-testing-followup",
        description=(
            "strengthen-test-coverage scenario: Pitest at 86% (below 87% gate). "
            "6 surviving mutants on BundleVariantValidator, 5 of which are "
            "equivalent (Kotlin bytecode noise + early-return on already-empty "
            "branches). No production code changes. The AI must NOT scaffold "
            "new behaviour tests; it must (a) propose ONE strengthening test per "
            "real mutant and (b) suppress equivalent mutants in tool config."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "Pitest test strength is 86% (below 87% gate, build failing). "
                "6 surviving mutations on BundleVariantValidator: 5 equivalent "
                "(Kotlin bytecode noise + early-return emptyList replacing "
                "branches that already return emptyList) and 1 from a "
                "deliberately weak BR4 BDD scenario. JaCoCo reports 100% "
                "line and instruction coverage. No production code changes "
                "on this branch."
            ),
            "target_paths": [
                "src/main/kotlin/.../BundleVariantValidator.kt",
                "src/test/kotlin/.../BundleVariantValidatorTest.kt",
            ],
            "signals": {"is_test_only": True},
        },
        specificity="moderate",
        rubric_focus=["decisive_routing", "no_generic_advice", "strengthen-test-coverage"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    RepoScenario(
        id="moderate.config-ttl-bump",
        description=(
            "verify-existing scenario: bump the JWT refresh-token TTL from 7d to 14d "
            "in application.yml — config-only change, no production code touched. "
            "The AI must NOT scaffold new tests; it must say 'run the existing "
            "auth integration suite + a smoke of the refresh path' and explain why "
            "writing new tests would add no release confidence."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "bump JWT refresh-token TTL from 7d to 14d in application.yml — "
                "no code change, just a config tweak"
            ),
            "target_paths": [
                "src/main/resources/application.yml",
            ],
            "signals": {"is_config_only": True},
        },
        specificity="moderate",
        rubric_focus=[
            "decisive_routing",
            "no_generic_advice",
            "verify-existing",
        ],
        repo_files_to_load=[
            "src/main/resources",
        ],
    ),
    # --------------------- generic (broad QA question) ----------------------
    RepoScenario(
        id="generic.how-to-test-this-service",
        description=(
            "Open-ended QA question against the whole service. Forces the AI to "
            "(a) read the repo to understand what the service does, (b) name "
            "concrete things to verify with risk-based prioritisation, and (c) "
            "name the smallest useful test set rather than a checklist."
        ),
        tool="qa_answer_testing_question",
        args={
            "question": "How should I test the by-variant-data-feeder service?",
            "context": "It feeds product variant availability data downstream.",
        },
        specificity="generic",
        rubric_focus=[
            "domain_specificity",
            "smallest_useful_test_set",
            "no_generic_advice",
            "named_techniques",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "README.md",
        ],
    ),
    RepoScenario(
        id="generic.docs-only-update",
        description=(
            "no-tests-recommended scenario: pure docs change. The AI must NOT "
            "recommend tests; it must say 'run the build, run any doc linters, "
            "no QA test work'."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": "update README and add architecture diagram",
            "target_paths": ["README.md", "docs/architecture.md"],
            "signals": {"is_docs_only": True},
        },
        specificity="generic",
        rubric_focus=["decisive_routing", "no-tests-recommended"],
        repo_files_to_load=["README.md"],
    ),
    # --------------------- very-generic (strategy / pyramid / rollout) ----------------------
    RepoScenario(
        id="very-generic.test-strategy-from-scratch",
        description=(
            "strategy-orchestration scenario: design a test strategy across the "
            "test pyramid for this service. The AI must NOT force a per-change "
            "approach. It must redirect to sumo-qa-strategising and reason about "
            "the pyramid (unit / integration / contract / e2e), gate calibration, "
            "CI feedback time, and rollout."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "design and implement a test strategy for the by-variant-data-feeder "
                "service that delivers high quality software in the shortest time "
                "with the lowest bug count. Holistic strategy across the test "
                "pyramid (unit / integration / contract / e2e), gate calibration, "
                "CI feedback time, and rollout plan to other services."
            ),
            "target_paths": [
                "src/main/kotlin/com/johnlewis/byvariantdatafeeder/",
                "src/test/kotlin/com/johnlewis/byvariantdatafeeder/",
                "build.gradle.kts",
                ".gitlab-ci.yml",
            ],
            "signals": {"is_strategic_planning": True},
        },
        specificity="very-generic",
        rubric_focus=[
            "decisive_routing",
            "domain_specificity",
            "no_generic_advice",
            "strategy-orchestration",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "src/test/kotlin/com/johnlewis/byvariantdatafeeder",
            "build.gradle.kts",
        ],
    ),
    RepoScenario(
        id="very-generic.spike-throwaway-prototype",
        description=(
            "spike-first-then-tests scenario: throwaway exploratory code. The AI "
            "must NOT demand TDD discipline on the spike itself; it must say "
            "'spike freely, capture conditions for the productionised pass'."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "spike: prototype a new pricing engine to see if the model fits — "
                "throwaway code, no production wiring yet"
            ),
            "target_paths": ["spikes/pricing.kt"],
            "signals": {"is_spike": True},
        },
        specificity="very-generic",
        rubric_focus=["decisive_routing", "spike-first-then-tests"],
        repo_files_to_load=[],
    ),
]
