# Phase 2 — Structural Drift Guards + Parser Robustness QA Run Summary

**Date:** 2026-05-14
**Plan:** [`docs/qa/plans/2026-05-14-phase2-drift-guards-parser-robustness.md`](../plans/2026-05-14-phase2-drift-guards-parser-robustness.md)
**Strategy:** [`docs/qa-strategy.md`](../../qa-strategy.md)
**Branch:** `feat/phase2-drift-guards-parser-robustness` → main (PR pending)
**Approach mix:** infrastructure-change (T1) + strengthen-test-coverage (T2, T4, T5) + tdd-scaffold (T6) + regression-first (T3 + T3a defect-fix pair)

## Evidence

**Suite run** *(fresh, this turn):*
- Total: **350 collected**
- Passed: **349**
- xfailed: **1** *(expected — pre-existing)*
- Failed: **0**
- Duration: **8.97s** *(well under the 30s Phase 2 closure-gate budget)*
- Command: `uv run pytest`

**Coverage** *(fresh, this turn — gate `--cov-fail-under=100` still active in CI and pyproject.toml addopts):*

| File | Stmts | Miss | Cover | Δ vs Phase 1 |
|---|---|---|---|---|
| `src/sumo_qa/__init__.py` | 1 | 0 | **100%** | — |
| `src/sumo_qa/__main__.py` | 1 | 0 | **100%** | — |
| `src/sumo_qa/debug_capture.py` | 28 | 0 | **100%** | — |
| `src/sumo_qa/installer.py` | 268 | 0 | **100%** | — |
| `src/sumo_qa/knowledge_loaders.py` | 77 | 0 | **100%** | — |
| `src/sumo_qa/rules.py` | **65** | 0 | **100%** | +1 stmt (T3a fix) |
| `src/sumo_qa/server.py` | 93 | 0 | **100%** | — |
| `src/sumo_qa/skill_prompts.py` | 46 | 0 | **100%** | — |
| `src/sumo_qa/standards.py` | 74 | 0 | **100%** | — |
| `src/sumo_qa/tdm_catalogue.py` | 121 | 0 | **100%** | — |
| `src/sumo_qa/tdm_models.py` | 89 | 0 | **100%** | — |
| `src/sumo_qa/tdm_service.py` | 147 | 0 | **100%** | — |
| `src/sumo_qa/tdm_validation.py` | 85 | 0 | **100%** | — |
| `src/sumo_qa/tools.py` | 52 | 0 | **100%** | — |
| **TOTAL** | **1147** | **0** | **100.00%** | +1 stmt |

**Lint:** `uv run ruff check . && uv run ruff format --check .` — All checks passed; 41 files formatted.

**Tests added: +33** (Phase 1 closed at 316 passed; Phase 2 ends at 349 passed).

## Risk-to-test coverage map

| Risk | Covering test(s) | Status |
|---|---|---|
| **R-SKILLDRIFT** — skill body refs nonexistent tools, OR registered tools with no SKILL ref | `tests/test_skill_tool_crossref.py::test_no_dead_skill_to_tool_refs`, `::test_no_orphan_registered_tools`, `::test_helpers_catch_synthetic_drift` | ✅ green; helpers self-tested against synthetic drift inputs |
| **R-LOADER-INVARIANTS** — `knowledge_loaders.py` parsers under adversarial input | `tests/test_hypothesis_knowledge_loaders.py` — 10 tests (parametrised no-arg loader returns markdown + Hypothesis totality on `load_standards`/`load_rules` over arbitrary classification strings + `None`/no-arg equivalence + filtered-≤-unfiltered length invariant) | ✅ green; no production bugs surfaced |
| **R-RULES-INVARIANTS** — `StandardsRulesEngine.evaluate(classifications)` order/duplicate sensitivity | `tests/test_hypothesis_rules.py` — 5 tests (empty input + idempotence on duplicates + order independence + graceful unknown classification + canonical-keys invariant) | ✅ green **after T3a fix** *(T3 surfaced 2 real defects; T3a fixed both)* |
| **R-STANDARDS-INVARIANTS** — `StandardsEngine.evaluate(workflow)` over arbitrary workflow strings | `tests/test_hypothesis_standards.py` — 6 tests (parametrised over the 3 known workflows in shipped packs + Hypothesis totality + determinism + workflow-echo invariant) | ✅ green; no production bugs surfaced |
| **R-TDM-INVARIANTS** — `assess_freshness`, `_heuristic_issues`, `_lowest_confidence`, `_confidence_from_freshness`, `_ensure_aware` | `tests/test_hypothesis_tdm_validation.py` — 9 tests (assess_freshness monotonicity over time + `_heuristic_issues` totality + `_lowest_confidence` commutative + associative + `_confidence_from_freshness` totality over the 4 known statuses + `_ensure_aware` always-aware invariant) | ✅ green; no production bugs surfaced |

**Risks covered: 5 / 5.**

## Notable finding — Hypothesis surfaced 2 real production defects

T3 (Hypothesis property tests for `rules.py`) initially had 2 failing tests:

1. **`test_evaluate_idempotent_on_duplicates`** — `evaluate(['X', 'X'])` returned `matched_rules=['X', 'X']` (duplicated), while `evaluate(['X'])` returned `['X']`. Production code's `_dedupe()` helper was applied to per-field content lists but not to the input classifications.
2. **`test_evaluate_order_independent`** — `evaluate([A, B])` and `evaluate([B, A])` returned lists in different orders; all list fields (`matched_rules`, `must_consider`, `risk_templates`, …) reflected input iteration order. Different callers passing the same set of classifications in different orders would get different recommendations from the same QA decision.

**T3a fix** *(`src/sumo_qa/rules.py:94` `evaluate` body, +3 lines):*

```python
def evaluate(self, classifications: list[str]) -> dict[str, Any]:
    # Normalise so callers passing the same set in different orders or with
    # duplicates always get identical output (set-equivalent semantics).
    classifications = sorted(set(classifications))
    matched = [self._rules[name] for name in classifications if name in self._rules]
    # ...rest unchanged
```

This is exactly the kind of bug Phase 2 was designed to catch — invariant violations that happy-path unit tests miss but property-based fuzzing surfaces. Both T3 tests now pass; existing 7 tests in `tests/test_rules.py` still pass (no test relied on input-order preservation in the output, so the normalisation is a refinement, not a breaking change).

## Known gaps + open follow-ups

**This rollout closed all 5 named risks. No KNOWN GAPs.**

**Process feedback captured during this run:**
- Sumith's correction: Approach tags on plan tasks are scaffolding, not discipline. Test-design steps in `sumo-qa-planning-qa-rollout` should invoke `sumo-qa-implementing-with-tdd` (for `tdd-scaffold` / `regression-first` / `coverage-first-then-refactor` tasks) or `sumo-qa-strengthening-tests` (for `strengthen-test-coverage` tasks) to design the property/test idea properly, not just from training-data judgment. Captured to memory as `feedback_route_test_design_through_subskill.md`. **Apply for Phase 3 planning.**

**Phase 3 deliverables ready to plan** *(per `docs/qa-strategy.md`):*
- Mutation testing via `mutmut` on `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py` — assertion-strength check after coverage floor is in. Adds CI time — earn it.
- TDM known-good URL freshness as scheduled GHA — fetches each known-good test-data entry's URL with `requests.head` weekly, opens an issue if non-2xx. Lowest risk × lowest gap; scheduled, not per-push.

## Files touched

**New (5 test files + 1 plan + 1 run summary):**
- `tests/test_hypothesis_knowledge_loaders.py` (T2) — 10 tests
- `tests/test_hypothesis_rules.py` (T3) — 5 tests
- `tests/test_hypothesis_standards.py` (T4) — 6 tests
- `tests/test_hypothesis_tdm_validation.py` (T5) — 9 tests
- `tests/test_skill_tool_crossref.py` (T6) — 3 tests
- `docs/qa/plans/2026-05-14-phase2-drift-guards-parser-robustness.md` — the plan
- `docs/qa/runs/2026-05-14-phase2-drift-guards-parser-robustness.md` — this document

**Modified (3 files — minimal):**
- `src/sumo_qa/rules.py` (T3a) — `+3 lines` (1 statement + 2 comment) at top of `evaluate()` to normalise input as `sorted(set(classifications))`
- `pyproject.toml` (T1) — added `"hypothesis>=6,<7"` to `[project.optional-dependencies].dev`
- `.pre-commit-config.yaml` (T1) — added `- "hypothesis>=6,<7"` to the pytest pre-push hook's `additional_dependencies`
- `uv.lock` — auto-regenerated by `uv sync` after the pyproject change

**Diff magnitude:** 33 net new tests, 3 production lines, 2 dependency additions.
