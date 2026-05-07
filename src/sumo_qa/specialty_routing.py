"""Specialty testing routing.

A senior QA reading a change instinctively spots when extra capability is
needed: 'this needs a Cypress test', 'this needs a load test', 'this needs
OWASP ZAP'. This module exposes a STATIC REGISTRY of specialty approaches
the AI is grounded against; the AI is the one that picks which approaches
the change actually needs.

The deterministic detector matches ONLY on structural signals (file
extensions, path substrings, deterministic-classifier output). It does
NOT phrase-match free text — phrase tables can't keep up with how language
varies and produce silent wrong-shaped output for novel asks. The AI path
reads the work_item / change_summary directly via MCP sampling and is
grounded in the registry exposed below.

Each specialty entry names:
  - the testing approach (so the user can search for any tool that fits),
  - well-known tools (a few canonical names),
  - an mcp_hint (whether an MCP server is known to exist for this approach),
  - when_to_use (so the recommendation is decision-grade, not noise).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class _SpecialtyRule:
    id: str
    approach: str
    well_known_tools: tuple[str, ...]
    mcp_hint: str
    when_to_use: str
    triggers_classifications: tuple[str, ...] = field(default_factory=tuple)
    triggers_extensions: tuple[str, ...] = field(default_factory=tuple)
    triggers_path_substrings: tuple[str, ...] = field(default_factory=tuple)


# The static registry of specialty testing approaches. The AI reasons over
# this list; the deterministic detector below matches structural signals
# only (extensions, paths, classifications) — never free-text phrases.
SPECIALTY_REGISTRY: tuple[_SpecialtyRule, ...] = (
    _SpecialtyRule(
        id="frontend_e2e",
        approach="Browser-driven end-to-end and component testing",
        well_known_tools=("Playwright", "Cypress", "Selenium", "React Testing Library"),
        mcp_hint=(
            "Search your MCP registry for a Playwright or Cypress server "
            "(e.g. mcp-server-playwright). Both have community implementations."
        ),
        when_to_use=(
            "When the change affects user-visible UI behaviour, navigation, "
            "forms, or component rendering."
        ),
        triggers_classifications=("ui_only_change",),
        triggers_extensions=(".tsx", ".jsx", ".vue", ".svelte", ".html"),
    ),
    _SpecialtyRule(
        id="contract_testing",
        approach="Consumer-driven contract testing or schema validation",
        well_known_tools=("Pact", "Schemathesis", "Dredd", "Spectral"),
        mcp_hint=(
            "Search your MCP registry for a Pact or Schemathesis server. "
            "OpenAPI-based contract tooling is sometimes wrapped as MCP."
        ),
        when_to_use=(
            "When the change touches API contracts, payload shapes, schema "
            "definitions, or any cross-service boundary."
        ),
        triggers_classifications=("api_contract_change", "data_mapping_change"),
    ),
    _SpecialtyRule(
        id="performance_testing",
        approach="Load testing, latency profiling, and throughput measurement",
        well_known_tools=("k6", "Locust", "JMeter", "Gatling"),
        mcp_hint=(
            "k6 has emerging MCP support. Otherwise integrate the test as a "
            "CI step and surface the result via a thin MCP wrapper."
        ),
        when_to_use=(
            "When latency, throughput, or concurrency is part of the "
            "acceptance bar - typically caching, async, or hot-path changes."
        ),
        triggers_classifications=("caching_change", "async_flow_change"),
    ),
    _SpecialtyRule(
        id="security_testing",
        approach="Static + dynamic application security testing (SAST + DAST)",
        well_known_tools=("OWASP ZAP", "Burp Suite", "Semgrep", "Snyk", "Bandit"),
        mcp_hint=(
            "Semgrep has an MCP server. Burp / ZAP integrations are usually CLI; "
            "wrap them in a thin MCP if you want the host model to drive scans."
        ),
        when_to_use=(
            "When the change touches authentication, authorization, sensitive "
            "data handling, input parsing, escaping, or anything user-supplied "
            "that crosses a trust boundary."
        ),
        triggers_path_substrings=("auth", "security", "credentials"),
    ),
    _SpecialtyRule(
        id="mobile_testing",
        approach="Mobile UI automation and on-device testing",
        well_known_tools=("Appium", "Maestro", "Detox", "XCUITest", "Espresso"),
        mcp_hint=(
            "Appium has community MCP servers. Maestro is CLI-friendly and "
            "easy to wrap as MCP."
        ),
        when_to_use=(
            "When the change targets iOS, Android, or cross-platform mobile."
        ),
        triggers_extensions=(".swift", ".kt", ".m", ".mm"),
        triggers_path_substrings=("/ios/", "/android/", "/mobile/", "react-native"),
    ),
    _SpecialtyRule(
        id="ai_ml_testing",
        approach="LLM and ML model evaluation, prompt regression, embedding sanity",
        well_known_tools=("Promptfoo", "DeepEval", "Evidently", "Trulens", "Ragas"),
        mcp_hint=(
            "Promptfoo has CLI / library form factors that wrap easily as MCP. "
            "Evidently is Python-friendly. The space is moving fast - check "
            "your registry for the freshest options."
        ),
        when_to_use=(
            "When the change involves LLM calls, prompts, embeddings, RAG "
            "retrieval, or any non-deterministic model behaviour."
        ),
        triggers_path_substrings=("/ml/", "/ai/", "/llm/", "/models/", "/prompts"),
    ),
    _SpecialtyRule(
        id="accessibility_testing",
        approach="Automated and manual accessibility validation against WCAG",
        well_known_tools=("axe-core", "Pa11y", "Lighthouse", "NVDA", "VoiceOver"),
        mcp_hint=(
            "axe-core integrates into Playwright and Cypress, so the same MCP "
            "server can drive both functional and a11y checks. Lighthouse is "
            "CLI-runnable."
        ),
        when_to_use=(
            "When the change affects rendered UI, especially forms, "
            "navigation, modals, or anything keyboard- or screen-reader-driven."
        ),
        triggers_classifications=("ui_only_change",),
    ),
)


# Backwards-compatible alias for code that imports the old name.
_RULES = SPECIALTY_REGISTRY


def detect_specialty_needs(
    classifications: list[str],
    touched_files: list[str],
    free_text: str,  # kept for API stability; no longer pattern-matched.
) -> list[dict[str, Any]]:
    """Return specialty testing approaches the change implies.

    Pattern detection (file extensions, path substrings, free-text phrase
    tables) is gone — the AI is the brain that reads the change and picks
    specialties. The deterministic harness now only fires off the team-
    classification → specialty mapping (since classifications are explicit
    facts about the change, not pattern guesses about it). When MCP
    sampling is unavailable and no classifications are supplied, this
    returns an empty list and the caller should rely on the AI path or
    consult `SPECIALTY_REGISTRY` directly.
    """
    results: list[dict[str, Any]] = []
    for rule in SPECIALTY_REGISTRY:
        if rule.triggers_classifications and any(
            c in classifications for c in rule.triggers_classifications
        ):
            results.append(
                {
                    "id": rule.id,
                    "approach": rule.approach,
                    "well_known_tools": list(rule.well_known_tools),
                    "mcp_hint": rule.mcp_hint,
                    "when_to_use": rule.when_to_use,
                }
            )
    return results
