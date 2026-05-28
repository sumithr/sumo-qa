# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
import re
from pathlib import Path

import pytest
import yaml

from sumo_qa.rules import StandardsRulesEngine

ROOT = Path(__file__).resolve().parents[1]


def test_rules_map_classification_to_qa_expectations() -> None:
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    evaluation = engine.evaluate(["async_flow_change"])

    assert "async_flow_change" in evaluation["matched_rules"]
    assert "idempotency" in evaluation["must_consider"]
    assert "nonfunctional" in evaluation["suggested_test_types"]


def test_missing_rules_file_returns_empty_engine(tmp_path: Path) -> None:
    engine = StandardsRulesEngine.from_file(tmp_path / "does_not_exist.yaml")

    evaluation = engine.evaluate([])

    assert evaluation == {
        "matched_rules": [],
        "must_consider": [],
        "suggested_test_types": [],
        "avoid_testing": [],
        "risk_templates": [],
        "test_design_techniques": [],
        "quality_characteristics": [],
        "templates_by_classification": {},
    }


def test_evaluate_surfaces_istqb_test_design_techniques() -> None:
    """ISTQB Foundation/Advanced test design techniques (boundary value analysis,
    decision tables, state transition testing, pairwise, equivalence partitioning)
    must be available per classification, so the QA brain reasons in named
    techniques rather than generic bullets.
    """
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    api = engine.evaluate(["api_contract_change"])
    assert api["test_design_techniques"], "api_contract_change should have ISTQB techniques"
    techniques_text = " ".join(api["test_design_techniques"]).lower()
    assert "boundary value" in techniques_text or "equivalence" in techniques_text
    assert "decision table" in techniques_text or "pairwise" in techniques_text

    state = engine.evaluate(["state_transition_change"])
    state_text = " ".join(state["test_design_techniques"]).lower()
    assert "state transition" in state_text


def test_evaluate_surfaces_iso25010_quality_characteristics() -> None:
    """ISO/IEC 25010 quality characteristics (functional suitability, performance
    efficiency, reliability, security, etc.) per classification."""
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    caching = engine.evaluate(["caching_change"])
    chars = [item.lower() for item in caching["quality_characteristics"]]
    # caching directly affects performance efficiency and reliability
    assert any("performance" in c for c in chars)
    assert any("reliability" in c for c in chars)

    api = engine.evaluate(["api_contract_change"])
    api_chars = [item.lower() for item in api["quality_characteristics"]]
    assert any("compatibility" in c or "functional" in c for c in api_chars)


def test_evaluate_returns_per_classification_template_map() -> None:
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    evaluation = engine.evaluate(["api_contract_change", "data_mapping_change"])

    by_classification = evaluation["templates_by_classification"]
    assert "api_contract_change" in by_classification
    assert "data_mapping_change" in by_classification
    # api template should be under api, not data_mapping
    api_marker = "payload shape or validation changes silently"
    assert any(api_marker in template for template in by_classification["api_contract_change"])
    assert all(api_marker not in template for template in by_classification["data_mapping_change"])


def test_unknown_suggested_test_type_raises_value_error(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.safe_dump(
            {
                "made_up_change": {
                    "suggested_test_types": ["chaos"],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        StandardsRulesEngine.from_file(rules_path)

    message = str(excinfo.value)
    assert "made_up_change" in message
    assert str(rules_path) in message
    assert "chaos" in message


def test_unknown_field_under_classification_raises_value_error(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.safe_dump(
            {
                "made_up_change": {
                    "must_consider": ["something"],
                    "unexpected_key": ["nope"],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        StandardsRulesEngine.from_file(rules_path)

    assert "made_up_change" in str(excinfo.value)
    assert str(rules_path) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Mutation-strengthening tests (Phase 3) — see docs/qa/runs/2026-05-14-phase3-*
# ---------------------------------------------------------------------------


def test_dedupe_removes_duplicates_preserving_first_seen_order() -> None:
    """Direct unit test of `_dedupe()` to kill mutmut survivor
    `sumo_qa.rules.x__dedupe__mutmut_4` (`seen.add(item)` → `seen.add(None)`).

    With the mutation, `seen` only ever contains None, so every input item passes
    the `item not in seen` check and `_dedupe` returns the input unchanged. This
    test asserts a concrete deduped output that the broken mutation would not
    produce.
    """
    from sumo_qa.rules import _dedupe

    assert _dedupe(["a", "a", "b", "a", "c"]) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Issue #98 — tech-agnostic surface probes
#
# Three implementation-surface patterns must carry concrete QA probes that go
# *beyond* the generic classification text, while staying host-neutral (no
# library / protocol / framework names). `security_change` is the concreteness
# template; these guards bring the schema/protocol, async/idempotency, and
# CI/config/deploy surfaces up to the same bar without overfitting to a vendor.
# ---------------------------------------------------------------------------

# surface rule -> concrete probe markers that MUST appear in the rule's
# ENRICHED fields (must_consider + risk_templates only — NOT test_design_techniques,
# so a marker can't be satisfied by pre-existing technique text). Each marker is a
# tech-agnostic phrase absent from the pre-#98 generic entries, so the guard fails
# (red) until the rule carries the concrete probe itself.
SURFACE_PROBE_MARKERS = {
    # schema/model validation + request/response/IPC protocol surface
    "api_contract_change": ("removed", "omits", "old-shaped"),
    # CI / config / deployment surface
    "configuration_change": ("missing or empty", "precedence", "in flight"),
    # async / retry / idempotency surface
    "async_flow_change": ("double-apply", "poison", "out-of-order"),
    # docs surface (#99): broken links / stale commands plus the #176 fold-in
    # inventory-drift probe — a documented count, list, public-surface name,
    # or schema field that changed in one place but lingers stale elsewhere.
    "docs_change": ("broken links", "stale occurrences", "documented count"),
    # test surface (#99): tautological assertions, prod-change hidden in a
    # test-only diff, and the no-real-red-phase failure mode.
    "test_change": ("tautological", "fails on the intended", "hidden inside"),
}

# Host-neutrality BACKSTOP — a deliberately small, NON-EXHAUSTIVE tripwire, not a
# proof of neutrality. Host-neutrality is a semantic property (does a probe reason
# in a specific technology?), so its real owner is the eval's semantic anti-pattern
# ("broker/library-specific advice standing in for the risk pattern") plus
# adversarial review — NOT a maintained list of names, which is the very static
# catalogue #98 argues against. This set only trips an obvious fat-finger (a vendor
# name pasted into a probe); deliberately one or two iconic names per surface
# category. Do NOT grow it chasing completeness — strengthen the eval instead.
# Matched as whole word-tokens, so "restore" never trips "rest".
_BANNED_TECH_TOKENS = frozenset(
    {
        "kafka",  # async/broker
        "sqs",
        "grpc",  # request/response/IPC protocol
        "graphql",
        "rest",
        "fastapi",  # web framework
        "react",
        "kubernetes",  # CI/config/deploy
        "terraform",
        "redis",  # datastore
        "postgres",
        "jwt",  # auth/token
        "oauth",
    }
)


def _surface_text(
    engine: StandardsRulesEngine, classification: str, *, include_techniques: bool
) -> str:
    ev = engine.evaluate([classification])
    fields = ev["must_consider"] + ev["risk_templates"]
    if include_techniques:
        fields = fields + ev["test_design_techniques"]
    return " ".join(fields).lower()


@pytest.mark.parametrize(("classification", "markers"), SURFACE_PROBE_MARKERS.items())
def test_surface_exposes_concrete_probes_beyond_classification_text(
    classification: str, markers: tuple[str, ...]
) -> None:
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")
    # Markers must come from the enriched probe fields, not pre-existing techniques.
    text = _surface_text(engine, classification, include_techniques=False)
    missing = [marker for marker in markers if marker not in text]
    assert not missing, (
        f"{classification} is missing concrete probe markers {missing}; its "
        f"guidance is still generic classification text, not a concrete probe"
    )


@pytest.mark.parametrize("classification", sorted(SURFACE_PROBE_MARKERS))
def test_surface_probes_stay_host_neutral(classification: str) -> None:
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")
    # Backstop tripwire (see _BANNED_TECH_TOKENS): scan every surfaced field,
    # techniques included, so the widest text is checked against the small set.
    tokens = set(
        re.findall(r"[a-z0-9]+", _surface_text(engine, classification, include_techniques=True))
    )
    leaked = sorted(_BANNED_TECH_TOKENS & tokens)
    assert not leaked, (
        f"{classification} probes name specific technologies {leaked}; probes "
        f"must describe the risk pattern, not a library/protocol/framework"
    )


# ---------------------------------------------------------------------------
# Issue #99 — engine.evaluate must surface non-empty fields for the new
# docs_change and test_change rule entries (the AC's load-bearing assertion).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("classification", ["docs_change", "test_change"])
def test_evaluate_surfaces_non_empty_fields_for_docs_and_test_change(
    classification: str,
) -> None:
    """`StandardsRulesEngine.evaluate(['docs_change'])` and (['test_change'])
    must surface non-empty rule fields — these classifications previously had
    no rule entry, so evaluate returned the empty-engine shape and the
    reviewer skill had nothing concrete to apply."""
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    ev = engine.evaluate([classification])

    assert classification in ev["matched_rules"], (
        f"{classification} must be in matched_rules; missing means change_rules.yaml "
        f"has no entry for it"
    )
    assert ev["must_consider"], f"{classification}.must_consider must be non-empty"
    assert ev["suggested_test_types"], f"{classification}.suggested_test_types must be non-empty"
    assert ev["test_design_techniques"], (
        f"{classification}.test_design_techniques must be non-empty"
    )
    assert ev["quality_characteristics"], (
        f"{classification}.quality_characteristics must be non-empty"
    )
