# Phase 3 Mutation Baseline — 2026-05-14

**Branch:** `feat/phase3-mutation-baseline-tdm-freshness`
**Date:** 2026-05-14
**Tool:** mutmut 3.5.0 | Python 3.14.4 | pytest 9.0.3
**Risk covered:** R-MUT-DRIFT — without a baseline, assertion-strength regressions go unnoticed.

Related:
- Strategy: [docs/qa-strategy.md](../../qa-strategy.md)
- Plan: [docs/qa/plans/2026-05-14-phase3-mutation-baseline-tdm-freshness.md](../plans/2026-05-14-phase3-mutation-baseline-tdm-freshness.md)
- Machine-readable snapshot: [mutmut-baseline.json](../../../mutmut-baseline.json)

---

## Per-Module Mutation Scores

| Module | Total mutants | Killed | Survived | Score % | Above 75% threshold? |
|---|---|---|---|---|---|
| `knowledge_loaders.py` | 153 | 110 | 43 | 71.9% | No |
| `rules.py` | 41 | 40 | 1 | 97.6% | Yes |
| `standards.py` | 25 | 15 | 10 | 60.0% | No |
| `tdm_validation.py` | 219 | 162 | 57 | 74.0% | No |
| **TOTAL** | **438** | **327** | **111** | **74.7%** | No (combined) |

---

## Run Summary

- **Total mutants:** 438
- **Killed:** 327
- **Survived:** 111
- **Skipped:** 0
- **Combined score:** 74.7%
- **Runtime note:** Stats-phase fork+hypothesis thread interaction on macOS arm64 (Python 3.14.4) causes all mutants to show "segfault" when the stats cache is cold. Running with a warm cache resolves this; the workaround is to run `mutmut run` twice (first run builds the stats cache, second run executes mutations cleanly).

---

## All Surviving Mutants by Location

### knowledge_loaders.py — 43 survivors

**`_read()` — encoding= arg stripped (2 survivors)**
- `x__read__mutmut_3` — `encoding="utf-8"` → `encoding=None` (no assertion on encoding in the returned text)
- `x__read__mutmut_5` — similar encoding mutation

**Per-catalogue loader filename case (5 survivors)**
- `x_sumo_qa_load_classifications__mutmut_3` — `"classifications.md"` → `"CLASSIFICATIONS.MD"`
- `x_sumo_qa_load_approaches__mutmut_3` — same pattern on approaches filename
- `x_sumo_qa_load_principles__mutmut_3` — same pattern on principles filename
- `x_sumo_qa_load_techniques__mutmut_3` — same pattern on techniques filename
- `x_sumo_qa_load_specialty_tools__mutmut_3` — same pattern on specialty_tools filename

**`_standards_dir()` path resolution (3 survivors)**
- `x__standards_dir__mutmut_12` — `"packs"` → `"PACKS"` in conditional subdirectory check
- `x__standards_dir__mutmut_29` — path string mutation in subdirectory fallback
- `x__standards_dir__mutmut_31` — path string mutation in subdirectory fallback

**`sumo_qa_load_standards()` — 15 survivors**
- `mutmut_8`, `_9`, `_15`, `_17`, `_20`, `_22`, `_25`, `_26`, `_27`, `_28`, `_29`, `_30`, `_31`, `_33`, `_36` — mutations on YAML parsing logic, key-name mutations (`"packs"`, `"id"`, `"description"` etc.) and conditional-return paths within `sumo_qa_load_standards()`

**`_rules_path()` — 6 survivors**
- `x__rules_path__mutmut_26` — `"standards"` → `"STANDARDS"` in first candidate path
- `x__rules_path__mutmut_28`, `_34`, `_36`, `_37`, `_38` — candidate path string mutations and fallback-order mutations

**`sumo_qa_load_rules()` — 12 survivors**
- `x_sumo_qa_load_rules__mutmut_3` — `encoding="utf-8"` → `encoding=None`
- `x_sumo_qa_load_rules__mutmut_5`, `_8`, `_11`, `_12`, `_15`, `_17`, `_18`, `_19`, `_20`, `_22`, `_23` — YAML key mutations, classification-filter path mutations, and error-handling mutations in the `try/except` block

---

### rules.py — 1 survivor

- `x__dedupe__mutmut_4` — `seen.add(item)` → `seen.add(None)` in `_dedupe()`. The set still grows (though all slots become `None`), so the deduplication still prevents duplicates from `item not in seen` check by accident on the first occurrence. No test asserts on the content of `seen` directly.

---

### standards.py — 10 survivors

All 10 survivors are in `StandardsEngine.evaluate()`, mutants 7–16 and 20:

- `mutmut_7` — `"title"` key → `"XXtitleXX"` in the result dict; no test checks the exact key name `"title"` in the evaluate output
- `mutmut_8` through `mutmut_16` — similar dict-key mutations (`"severity"`, `"qa_focus"`, `"pass_criteria"`, `"applies_to"`, etc.) in the matched-check dict construction
- `mutmut_20` — mutation on `matched.append(...)` or `return` structure

The evaluate method builds and returns a list of matched check dicts; assertions check presence of results but don't assert on all dict keys.

---

### tdm_validation.py — 57 survivors

**`MockValidator.validate()` — 9 survivors**
- `mutmut_24` — `_lowest_confidence(entry.confidence, freshness_level, ...)` → drops `entry.confidence` from the call; no test asserts the entry's own confidence level contributes to the result
- `mutmut_25`, `_26`, `_34`, `_35`, `_36`, `_37`, `_38`, `_42` — mutations on confidence-level argument ordering, `valid` bool computation, and `reason` construction

**`assess_freshness()` — 15 survivors**
- `mutmut_3` — `datetime.now(timezone.utc)` → `datetime.now(None)` (naive datetime fallback); tests don't explicitly assert timezone-awareness of the reference timestamp
- `mutmut_8`, `_9`, `_13`, `_14`, `_15` — boundary mutations on the `<= 30 days` / `<= 60 days` / `<= 90 days` freshness thresholds (e.g., `<` vs `<=`)
- `mutmut_24`, `_25`, `_26` — string mutations on `status` values (`"fresh"`, `"aging"`, `"stale"`)
- `mutmut_31`, `_32` — mutations on `days_since` calculation or comparison direction
- `mutmut_42`, `_43`, `_46`, `_47` — mutations on `FreshnessMetadata` field values

**`_heuristic_issues()` — 5 survivors**
- `mutmut_4`, `_8`, `_12`, `_16`, `_20` — the issue-message string mutations (e.g., `"environment is required"` → `"XXenvironment is requiredXX"`). Tests assert on the existence of issues but not on the exact issue message text.

**`_plausibility_issues()` — 12 survivors**
- `mutmut_5` — `validated_at > now` → `validated_at >= now` (boundary condition)
- `mutmut_7`, `_8`, `_9` — string content mutations in issue messages
- `mutmut_17`, `_18`, `_19`, `_20` — mutations on `confidence` checks or the confidence-comparison threshold
- `mutmut_29`, `_30`, `_31`, `_32` — mutations in the high-confidence + stale freshness path

**`_confidence_from_freshness()` — 3 survivors**
- `mutmut_1` — `if status == "fresh"` → `if status != "fresh"` (inverted conditional; returns `"high"` for all non-fresh statuses)
- `mutmut_2`, `_3` — mutations on `"aging"` → `"medium"` mapping and the final `return "low"` fallback

**`_lowest_confidence()` — 1 survivor**
- `mutmut_10` — `rank = {"low": 0, "medium": 1, "high": 2}` → `{"high": 3}` (changes ranking but preserves relative order, so `min()` still picks the same winner in most tested scenarios)

**`_validation_reason()` — 12 survivors**
- `mutmut_2`, `_4`, `_5`, `_6`, `_7`, `_8`, `_10`, `_11`, `_12`, `_14`, `_15`, `_16` — mutations on the string format templates for the reason message (e.g., separator `', '` → `'XX, XX'`, status string mutations). Tests assert on the presence of a reason but not on the exact reason text content.

---

## Commentary: Modules Needing Strengthening to Reach 100%

### Priority order (worst score first):

1. **`standards.py` — 60.0% (10 survivors)** — All survivors are in `StandardsEngine.evaluate()`. The result dict keys (`"title"`, `"severity"`, `"qa_focus"`, `"pass_criteria"`) are never asserted on directly; tests check count of results or top-level shape. Add assertions that verify specific keys exist in each returned dict entry.

2. **`knowledge_loaders.py` — 71.9% (43 survivors)** — Two clusters:
   - **Encoding survivors (7):** Tests never assert the returned text is correctly decoded (valid UTF-8 vs garbage). Adding a test with a non-ASCII character would kill these.
   - **Filename/path string mutations (20):** `sumo_qa_load_standards()` and `_rules_path()` survivors indicate tests pass even when the wrong path variant is chosen. This is because both paths resolve to the same bundled data in the test environment. Tests need to exercise the `QA_STANDARDS_PATH` / `QA_RULES_PATH` env-var override path explicitly with a distinct fixture.
   - **YAML parsing key mutations (12 in `sumo_qa_load_rules`):** Tests assert on content but not on key presence in the returned YAML structure.

3. **`tdm_validation.py` — 74.0% (57 survivors)** — Three main clusters:
   - **Issue-message string content (17 survivors across `_heuristic_issues`, `_plausibility_issues`, `_validation_reason`):** Tests assert issues are non-empty but don't check exact message content. Adding `assertIn("environment is required", issues)` etc. would kill these.
   - **Boundary conditions (8 survivors in `assess_freshness` + `_plausibility_issues`):** `>` vs `>=` and threshold-day boundary tests are missing.
   - **Confidence logic (13 survivors across `_confidence_from_freshness`, `_lowest_confidence`, `MockValidator.validate`):** The confidence assembly chain isn't fully exercised — particularly the `entry.confidence` contribution to `_lowest_confidence`.

4. **`rules.py` — 97.6% (1 survivor)** — Essentially at parity. The single survivor in `_dedupe()` can be killed by asserting on the _content_ of the returned deduplicated list, not just its length.

### Total survivors to kill for 100%: **111**

All four modules are below 100%. `rules.py` is nearest (1 survivor); `standards.py` needs the most proportional strengthening relative to its size (40% survivors).

---

## Infrastructure Note: Fork+Hypothesis Crash on macOS arm64

During this baseline run, a reproducible issue was found with mutmut 3.5.0 on Python 3.14.4/macOS arm64: when the mutmut stats cache (`mutants/mutmut-stats.json`) is absent, mutmut runs the full test suite (including hypothesis-based tests) to build timing stats, then immediately `os.fork()`s 438 child processes. The hypothesis library creates background threads during stats collection; `os.fork()` after threading on macOS arm64 reliably causes SIGSEGV in child processes (all 438 report "segfault", score = 0%).

**Workaround:** Run `uv run mutmut run` with the stats cache warm (i.e., after a prior run or with `mutants/mutmut-stats.json` present). The CI workflow (P3-T3) must preserve this file between runs, or seed it before the mutation run.

This issue was diagnosed and resolved during this task; the second full run with a warm cache produced clean results (0 segfaults, 327 killed, 111 survived).
