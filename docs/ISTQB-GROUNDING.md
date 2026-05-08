# ISTQB Grounding

How sumo-qa makes the host LLM speak like a senior ISTQB-certified QA. Source: [`src/sumo_qa/prompts.py`](../src/sumo_qa/prompts.py) (the `SENIOR_QA_SYSTEM_PROMPT`) and [`standards/packs/istqb_v1.yml`](../standards/packs/istqb_v1.yml).

## The senior-QA persona

`SENIOR_QA_SYSTEM_PROMPT` is sent on EVERY sumo-qa sampling call. It establishes:

- **Persona:** senior QA engineer with ISTQB Foundation, Advanced (Test Manager / Test Analyst / Technical Test Analyst), and specialty (Mobile / Performance / Security / AI Testing) certifications.
- **HARD REQUIREMENTs:**
  - facts vs assumptions (every structured output carries an `assumptions` field).
  - domain anchoring (forbids "the system" / "the service" when target paths or classifications are supplied).
  - specialty + tool pairing (when a non-functional or specialty risk is at stake, name the specialty AND a concrete tool the team would use; conditional — `[]` is fine for in-process work).
- **Output discipline:** JSON when asked, narrative when asked, principle citation when shaping a recommendation, never paraphrase deterministic guardrails (verdicts, missing test levels, classifications) supplied by the harness.

## ISTQB Foundation 7 principles

Cited by Foundation number in every relevant response:

1. Testing shows the presence of defects, not their absence.
2. Exhaustive testing is impossible; use risk and prioritisation.
3. Early testing saves time and money — shift left.
4. Defects cluster — concentrate effort where defect history is dense.
5. Pesticide paradox — refresh assertions and add new techniques.
6. Testing is context-dependent — safety-critical, regulated, web, mobile, AI all warrant different mixes.
7. Absence-of-errors fallacy — validate fitness for use, not just code-level correctness.

## ISO/IEC 25010 quality characteristics

Surfaced per change in `quality_characteristics` so non-functional risks aren't an afterthought: functional suitability, performance efficiency, compatibility, usability, reliability, security, maintainability, portability. Only the ones the change actually threatens get listed.

Examples: caching change → `performance_efficiency_time_behaviour` + `reliability_maturity`; async flow change → `reliability_fault_tolerance` + `reliability_maturity`.

## Per-change-shape technique mapping

Defined in [`standards/rules/change_rules.yaml`](../standards/rules/change_rules.yaml) (the `test_design_techniques` field per classification):

| Change shape | Techniques surfaced |
|---|---|
| API contract change | equivalence partitioning of valid/invalid payload classes; boundary value analysis on size/length/ranges; decision table for validation rules; pairwise on optional fields |
| Business logic change | decision tables; boundary value analysis on thresholds; equivalence partitioning; error guessing on historical defect corners |
| State transition change | state transition testing including invalid transitions; 0-switch and 1-switch coverage; decision tables for transition guards |
| Data mapping change | boundary value analysis; equivalence partitioning of null/empty/typical/extreme; decision tables for conditional mappings; cause-effect graphing |
| Async flow change | state transition testing across consumer states; decision table for retry/idempotency-key/dedupe; boundary value analysis on timeouts and backoff |
| Caching change | boundary value analysis on TTL boundaries (just-fresh, just-stale); state transition testing for cache states; decision table for invalidation triggers |
| Configuration change | decision tables for flag-on/flag-off/fallback; equivalence partitioning over environment classes; pairwise on flag combinations |
| Error handling change | error guessing on partial-failure modes; equivalence partitioning of failure classes; decision tables for retry/fallback/surface-error |
| UI-only change | exploratory testing charters for visual regressions; equivalence partitioning of viewport/device classes; pairwise on display options |

## ISTQB Advanced framing

Lives in [`standards/packs/istqb_v1.yml`](../standards/packs/istqb_v1.yml):

- Advanced Test Manager — risk-based testing (product risk vs project risk), shape coverage to where risk is highest, accept low-risk areas with thinner tests.
- Advanced Test Analyst — deliberate technique choice; each change shape has techniques that fit.
- Advanced Technical Test Analyst — structural coverage awareness (statement / branch / MC-DC).
- Foundation distinction between confirmation testing and regression testing.

The pack ships bundled and is loaded automatically alongside the core pack. Teams override or extend either via `QA_STANDARDS_PATH` and `QA_RULES_PATH` (see [docs/CONFIGURATION.md](CONFIGURATION.md)).
