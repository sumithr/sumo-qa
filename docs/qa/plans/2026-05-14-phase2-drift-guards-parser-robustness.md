# Phase 2 — Structural Drift Guards + Parser Robustness QA Plan

> **For agentic execution:** Use `sumo-qa-executing-qa-rollout` to dispatch this plan task-by-task with two-stage review. Tasks use checkbox (`- [ ]`) syntax for tracking. Tasks marked `[parallel]` can be dispatched concurrently after their `blocks` dependency completes; `[sequential]` tasks must run alone.

**Strategy reference:** [`docs/qa-strategy.md`](../../qa-strategy.md). This plan implements Phase 2 (items 5–6) of that strategy.

**Goal:** Add a structural cross-reference test that catches skill ↔ MCP-tool drift (renamed / deleted / never-referenced tools), and Hypothesis property-based tests on the four parser / decision modules — `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py` — to surface adversarial-input edge cases that happy-path unit tests miss.

**Branch:** `feat/phase2-drift-guards-parser-robustness` off `main`. One PR into main.

**Approach mix:**
- T1 — infrastructure-change (dev dependency + hook config)
- T2–T5 — strengthen-test-coverage (Hypothesis property tests on existing production code; production stays unchanged)
- T6 — tdd-scaffold (new structural test for an existing behavioural contract that wasn't previously asserted)

**Files touched:**

New tests:
- `tests/test_hypothesis_knowledge_loaders.py` (T2)
- `tests/test_hypothesis_rules.py` (T3)
- `tests/test_hypothesis_standards.py` (T4)
- `tests/test_hypothesis_tdm_validation.py` (T5)
- `tests/test_skill_tool_crossref.py` (T6)

Edited config:
- `pyproject.toml` (T1: add `hypothesis>=6,<7` to `[project.optional-dependencies].dev`)
- `.pre-commit-config.yaml` (T1: add `hypothesis>=6,<7` to pytest hook's `additional_dependencies`)

Production code: **untouched** — strengthen-test-coverage and tdd-scaffold (against existing behaviour) don't change production.

**Risks covered (anchored):**
- **R-SKILLDRIFT** — skill body refs `sumo_qa_load_X` but no such tool exists (deletion / rename drift); OR a tool is registered with no SKILL.md referencing it (dead tool). Currently checked only by humans during review. The cross-ref test in T6 catches both directions in CI.
- **R-LOADER-INVARIANTS** — `knowledge_loaders.py` parsers may behave unexpectedly on adversarial inputs: missing files, empty catalogues, classification strings that don't match any frontmatter, oversized inputs. Happy-path unit tests cover the canonical case only. T2 covers invariants like "every loader returns non-empty markdown starting with `#`" and "filter loaders return the catalogue without crashing for arbitrary classification strings".
- **R-RULES-INVARIANTS** — `StandardsRulesEngine.evaluate(classifications)` may produce non-deterministic results under classification list shuffles or duplicates. T3 covers idempotence on duplicate classifications + order independence + graceful handling of unknown classifications.
- **R-STANDARDS-INVARIANTS** — `StandardsEngine.evaluate(workflow)` against arbitrary workflow strings. T4 covers: known workflows produce non-empty output; unknown workflows produce graceful empty/default output without crashing.
- **R-TDM-INVARIANTS** — `assess_freshness`, `_heuristic_issues`, `_confidence_from_freshness`, `_lowest_confidence` may misbehave on edge-case freshness inputs (future dates, very old dates, missing fields). T5 covers: freshness is monotonic with age; `_heuristic_issues` returns a list (never None); `_confidence_from_freshness` maps every known status; `_lowest_confidence` is associative and commutative.

**Hypothesis configuration:** default `max_examples=100` per test (Phase 2 closure gate is ≤ 30s suite duration; current 316-test suite runs ~2s, so we have budget). No custom profile.

---

### Task 1 — Add Hypothesis to dev deps + pre-commit hook deps `[sequential]`

**Approach:** infrastructure-change
**Risk covered:** prerequisite for T2–T5 (those tests `import hypothesis`)
**Blocks:** T2, T3, T4, T5 (T6 doesn't need Hypothesis)

**Files:**
- Edit: `pyproject.toml` — add `"hypothesis>=6,<7"` to `[project.optional-dependencies].dev` (likely listed near `pytest`, `pytest-cov`, `ruff`).
- Edit: `.pre-commit-config.yaml` — add `- "hypothesis>=6,<7"` line to the pytest hook's `additional_dependencies` (alongside the existing `pytest-cov`, `pytest`, `mcp`, `pydantic`, `PyYAML`).

- [ ] Step 1: Read both files first; locate the exact insertion points.
- [ ] Step 2: Add `hypothesis>=6,<7` to both. Match the pin format already used (`>=X,<Y`).
- [ ] Step 3: Run `uv sync --all-extras` to install Hypothesis into the active venv.
- [ ] Step 4: Verify with `uv run python -c "import hypothesis; print(hypothesis.__version__)"`.
- [ ] Step 5: Re-run `uv run pytest -q` to confirm the existing suite still passes after the sync.

**Done when:** `import hypothesis` succeeds; existing suite still green (316 passed + 1 xfailed at 100% coverage); ruff still clean.

---

### Task 2 — Hypothesis tests for `knowledge_loaders.py` `[parallel]`

**Approach:** strengthen-test-coverage (production code MUST stay unchanged)
**Risk covered:** R-LOADER-INVARIANTS
**Blocked by:** T1

**Files:**
- Create: `tests/test_hypothesis_knowledge_loaders.py`
- Touch: none (production stays unchanged)

The 7 loader entry points to cover (from `src/sumo_qa/knowledge_loaders.py`):
- `sumo_qa_load_classifications()`
- `sumo_qa_load_approaches()`
- `sumo_qa_load_principles()`
- `sumo_qa_load_techniques()`
- `sumo_qa_load_specialty_tools()`
- `sumo_qa_load_standards(classification: str | None = None)`
- `sumo_qa_load_rules(classification: str | None = None)`

Properties to test:

1. **Every no-arg loader returns non-empty markdown** — for each of the 5 no-arg loaders, the returned string is non-empty AND starts with a `#` (markdown heading). No `@given` needed — this is a single assertion per loader; combine into a parametrised test.
2. **Filter loaders are total over arbitrary strings** — `@given(classification=st.text())` against `load_standards` and `load_rules`: the call always returns a string (no exception, no None). Use `st.text()` with reasonable max_size to avoid pathological inputs.
3. **None classification == no filter** — `load_standards(None)` and `load_standards()` return the same content (same for `load_rules`).

- [ ] Step 1: Read `src/sumo_qa/knowledge_loaders.py` end-to-end. Read the existing `tests/test_knowledge_loaders.py` for fixture conventions.
- [ ] Step 2: Write `tests/test_hypothesis_knowledge_loaders.py` with the 3 property groups above (≥ 3 test functions; parametrised tests count as one for purposes of `≥ X tests`).
- [ ] Step 3: Run `uv run pytest tests/test_hypothesis_knowledge_loaders.py -v`. Confirm all pass.
- [ ] Step 4: Run the full suite to confirm no regressions and the 100% coverage gate still passes.
- [ ] Step 5: Confirm `git diff src/sumo_qa/knowledge_loaders.py` is empty.

**Done when:** ≥ 3 property tests pass; production diff empty; full suite still green at 100% coverage.

---

### Task 3 — Hypothesis tests for `rules.py` `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-RULES-INVARIANTS
**Blocked by:** T1

**Files:**
- Create: `tests/test_hypothesis_rules.py`
- Touch: none

The target: `StandardsRulesEngine.evaluate(classifications: list[str]) -> dict[str, Any]` in `src/sumo_qa/rules.py:94`.

Properties to test:

1. **`evaluate([])` returns a valid dict** — empty input doesn't crash; result is a dict.
2. **Idempotence on duplicates** — `evaluate(["api_contract_change", "api_contract_change"]) == evaluate(["api_contract_change"])`. Use `@given(st.lists(st.sampled_from(known_classifications), min_size=1))` and assert duplicates collapse.
3. **Order independence** — `evaluate(list)` == `evaluate(reversed(list))` for non-empty classification lists. Property over `@given(st.lists(st.sampled_from(known_classifications)))`.
4. **Graceful unknown** — `@given(classification=st.text(min_size=1, max_size=50))` calling `evaluate([classification])` always returns a dict (no exception).

Known classifications come from `knowledge/classifications.md` — there are 10. Use the list directly.

- [ ] Step 1: Read `src/sumo_qa/rules.py:94` (`evaluate`) + the existing `tests/test_rules.py` for fixture style.
- [ ] Step 2: Write the 4 property tests. Use `StandardsRulesEngine.from_file(DEFAULT_RULES_PATH)` to construct the engine (or whatever path the existing tests use).
- [ ] Step 3: Run; full suite; production-diff-empty check; coverage gate.

**Done when:** ≥ 4 property tests pass; production diff empty; suite green.

---

### Task 4 — Hypothesis tests for `standards.py` `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-STANDARDS-INVARIANTS
**Blocked by:** T1

**Files:**
- Create: `tests/test_hypothesis_standards.py`
- Touch: none

The target: `StandardsEngine.evaluate(workflow: str) -> StandardsEvaluation` in `src/sumo_qa/standards.py:105`.

Properties to test:

1. **Known workflows produce non-empty results** — for each workflow string present in the loaded packs, `evaluate(workflow)` returns a `StandardsEvaluation` with at least one applicable pack. Combine as a parametrised test over the known workflows extracted from the packs.
2. **Unknown workflows return graceful empty result** — `@given(workflow=st.text(min_size=1, max_size=50))`, calling `evaluate(workflow)` always returns a `StandardsEvaluation` (no exception, no None). Whitelist or filter to exclude workflow strings that match real workflows in test input.
3. **`evaluate` is deterministic** — calling `evaluate(w)` twice in a row yields equal-valued results (same applicable packs, same checks).

- [ ] Step 1: Read `src/sumo_qa/standards.py:105` + `tests/test_standards.py`.
- [ ] Step 2: Write the 3 property tests. Use `StandardsEngine.from_directory(DEFAULT_STANDARDS_PATH)` or equivalent.
- [ ] Step 3: Run; full suite; production-diff-empty; coverage gate.

**Done when:** ≥ 3 property tests pass; production diff empty; suite green.

---

### Task 5 — Hypothesis tests for `tdm_validation.py` `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-TDM-INVARIANTS
**Blocked by:** T1

**Files:**
- Create: `tests/test_hypothesis_tdm_validation.py`
- Touch: none

Targets in `src/sumo_qa/tdm_validation.py`:
- `assess_freshness(created_at, expires_at, now)` — line 50
- `not_applicable_freshness(reason)` — line 77
- `_heuristic_issues(entry)` — line 81
- `_plausibility_issues(...)` — line 96
- `_confidence_from_freshness(status)` — line 122
- `_lowest_confidence(*levels)` — line 130
- `_validation_reason(...)` — line 135
- `_ensure_aware(value)` — line 149

Properties to test:

1. **`assess_freshness` is monotonic with age** — given two `created_at` times where one is older, the older one's freshness status is "worse-or-equal" (stale → not stale order). `@given(st.datetimes(...), st.datetimes(...))`.
2. **`_heuristic_issues` always returns a list (never None)** — `@given(...)` against arbitrary TestDataEntry objects. Use `from_regex` or `composite` to build plausible entries.
3. **`_lowest_confidence` is associative and commutative** — `_lowest_confidence(a, b) == _lowest_confidence(b, a)` and `_lowest_confidence(a, _lowest_confidence(b, c)) == _lowest_confidence(_lowest_confidence(a, b), c)`. Sample over the known `TDMConfidenceLevel` values.
4. **`_confidence_from_freshness` is total over the known status strings** — `@pytest.mark.parametrize` over every status string present in the production code's `FreshnessMetadata` definitions; assert each maps to a valid `TDMConfidenceLevel`. (This is parametrised, not strictly Hypothesis — include in the same file since it's the same theme.)
5. **`_ensure_aware`** — `@given(st.datetimes(timezones=st.none()))` returns a tz-aware datetime; `@given(st.datetimes(timezones=st.timezones()))` returns the same value.

- [ ] Step 1: Read `src/sumo_qa/tdm_validation.py` + `tdm_models.py` for the dataclass shapes + `tests/test_tdm.py` for existing patterns.
- [ ] Step 2: Write the 5 property tests above.
- [ ] Step 3: Run; full suite; production-diff-empty; coverage gate.

**Done when:** ≥ 5 property tests pass; production diff empty; suite green.

---

### Task 6 — Skill ↔ MCP tool cross-reference test `[parallel]`

**Approach:** tdd-scaffold (new structural test pinning an existing contract)
**Risk covered:** R-SKILLDRIFT
**Blocked by:** none (independent of Hypothesis; can run before/alongside T1)

**Files:**
- Create: `tests/test_skill_tool_crossref.py`
- Touch: none (production stays unchanged)

Two structural assertions:

1. **Forward direction — every `sumo_qa_*` referenced in a SKILL is a registered tool** — scan every `skills/*/SKILL.md` file body for occurrences matching the regex `\bsumo_qa_[a-z_]+\b`. For each unique match, assert the name is in the live MCP server's registered tool list (use `build_mcp_server()._tool_manager._tools.keys()` introspection as in the existing `test_server.py`). Failure message must list the dead refs with file path.
2. **Reverse direction — every registered tool is referenced by at least one SKILL** — for each registered tool name, assert at least one `skills/*/SKILL.md` references it via regex. Exception list: the skill-content tools (one per skill, named after the skill itself — e.g. `using_sumo_qa`, `sumo_qa_deciding_approach`) are referenced by NAME of the skill file rather than as a `sumo_qa_*` call. Build the exception list from `{p.name.replace("-", "_") for p in skills_dir.iterdir() if p.is_dir()}`.

To prove the test actually catches drift, include a unit-test-of-the-test:

3. **Self-test — known-bad inputs trigger the assertion** — write a small helper function that the two main tests delegate to, and unit-test the helper against synthetic inputs (e.g. one SKILL body referencing a fake `sumo_qa_nonexistent_thing`; one registered tool not in any SKILL). Confirm the helper flags exactly those drifts.

- [ ] Step 1: Read `tests/test_server.py` for the tool-registry introspection pattern (`_tool_manager._tools.keys()`).
- [ ] Step 2: Read 2-3 `skills/*/SKILL.md` files to confirm the `sumo_qa_*` reference style (backticks, inline code).
- [ ] Step 3: Write `tests/test_skill_tool_crossref.py` with the three tests above.
- [ ] Step 4: Run `uv run pytest tests/test_skill_tool_crossref.py -v` — confirm all pass on current main.
- [ ] Step 5: Verify the regression-catching power: temporarily add a fake `sumo_qa_fake_tool` reference to one SKILL, re-run, confirm the forward-direction test fails; remove the fake before final commit.

**Done when:** 3 tests pass; the self-test test (#3) demonstrates the helper flags both drift directions; production diff empty; full suite green.

---

## Phase 2 closure gate

All 6 tasks complete + branch in this state:

- `uv run pytest -q` exits 0, suite count goes up by ~18 tests (Hypothesis tests + cross-ref tests).
- `uv run pytest --cov=src/sumo_qa --cov-fail-under=100` exits 0 (no new coverage gaps).
- Full suite duration ≤ 30s (Phase 2 budget) — Hypothesis default 100 examples per test should fit comfortably.
- `uv run ruff check . && uv run ruff format --check .` clean.
- `import hypothesis` works in the pre-commit hook's pytest venv.
- Cross-ref test catches a deliberate "rename a tool, don't update SKILL" injection — verified at task T6 step 5.
- One previously-uncaught edge case found via Hypothesis *or* documented as "parsers are robust to the shrunk inputs we tried" in the run summary.

When all of the above hold, the PR is ready for review. After merge, route to `sumo-qa-finishing-qa-work` to capture evidence + draft the PR description + write `docs/qa/runs/<date>-phase2-drift-guards-parser-robustness.md`.
