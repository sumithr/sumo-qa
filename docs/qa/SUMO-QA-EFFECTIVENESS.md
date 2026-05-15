# Sumo-qa Effectiveness on this Repo

A measurable record of what the sumo-qa MCP server + skills library actually delivered when pointed at its own codebase across four phases of QA work over a single sustained session.

The repo dog-fooded sumo-qa: every phase invoked the canonical chain (`using-sumo-qa` → `sumo-qa-deciding-approach` → `sumo-qa-strategising` → `sumo-qa-planning-qa-rollout` → `sumo-qa-executing-qa-rollout` → `sumo-qa-finishing-qa-work`), with knowledge catalogues loaded via the MCP server's `sumo_qa_load_*` tools and per-task work dispatched to fresh subagents through the executing skill's two-stage review pattern.

This document is honest. It measures what improved, what sumo-qa got wrong mid-flight, and what's deliberately not addressed.

## What sumo-qa is

Senior-QA MCP server + skills library that delivers ISTQB-grade testing discipline to AI coding agents. 14 skill files (1 entry router + 13 sub-skills) the host LLM follows literally; 25 MCP tool entry points (14 skill tools + 7 knowledge loaders + 4 test-data tools) for catalogue access and test-data management. The discipline is the product; tools are thin file IO.

## What sumo-qa actually did, phase by phase

### Phase 1 — Quality baseline ([commit `e5567bb`](../../commit/e5567bb), [PR #21](../../pull/21))

**Workflow:** strategising → planning → executing → finishing. 12 dispatchable tasks executed by parallel subagents.

**Substance:**
- Deleted ~1,100 LOC of stale qaskills + node_install middleware that an earlier pivot had abandoned.
- Lifted `installer.py` from 14% to 100% statement coverage (5 new test files, ~1,000 LOC of tests).
- Added `windows-latest` to the CI matrix (was Ubuntu + macOS only).
- Enforced `--cov-fail-under=100` in both `pyproject.toml` `addopts` and `.github/workflows/test.yml`.
- Wrote `docs/COVERAGE.md` policy doc defining the three allowed `# pragma: no cover` cases.
- Standardised the strategy-walk inventory in `knowledge/repo_walk.md` + structural test.
- Added a permanent end-to-end MCP `initialize` test (`tests/test_e2e_mcp_initialize.py`).

**Surfaced mid-flow:**
- The Claude Code MCP-registry install gap — `sumo-qa-install --claude-code` was symlinking skills but not running `claude mcp add`. Fixed inline; otherwise the user couldn't have used sumo-qa to do Phase 1's work.
- **Three Windows-only portability bugs** the new `windows-latest` matrix exposed: missing `encoding="utf-8"` on `read_text` (cp1252 mangles UTF-8 silently), CRLF line endings on shell scripts (bash on Windows chokes), and `bash` on Windows runners resolving to the WSL stub. Fixed before merge in commits `d8c1522`, `eb54d3d`, `d2fb7a8`.

### Phase 2 — Drift guards + parser robustness ([commit `f9f6acc`](../../commit/f9f6acc), [PR #25](../../pull/25))

**Workflow:** planning → executing → finishing (strategy already covered Phase 2 from Phase 1's strategy walk). 6 tasks.

**Substance:**
- New `tests/test_skill_tool_crossref.py` — asserts every `sumo_qa_*` reference in any `skills/*/SKILL.md` resolves to a registered MCP tool, AND every registered tool is referenced by some SKILL (drift in either direction now fails CI).
- 30 new Hypothesis property-based tests across `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py`.

**The marquee win:** Hypothesis tests on `rules.py` **surfaced two real production defects** in `StandardsRulesEngine.evaluate` that happy-path unit tests had missed for months:
- `evaluate(['X', 'X'])` returned `matched_rules=['X', 'X']` (duplicated input not deduped).
- `evaluate([A, B])` and `evaluate([B, A])` returned different orderings — meaning callers passing the same classification set in different orders got different recommendations from the same QA decision.

Fixed in the same PR as the discovery (`src/sumo_qa/rules.py`: `+3 lines`, `classifications = sorted(set(classifications))` at the top of `evaluate`). All existing tests in `tests/test_rules.py` still passed — the normalisation was a pure refinement.

### Phase 3 — Mutation baseline → 100% killed ([commit `ae8e458`](../../commit/ae8e458), [PR #26](../../pull/26))

**Workflow:** planning → executing → strengthening-tests interactive walk → finishing. Started at 4 tasks; expanded mid-flow when the user raised the closure gate from "baseline floor" to **"100% killed"**.

**Substance:**
- Configured `mutmut>=3,<4` against the 4 parser/decision modules with custom `[tool.mutmut]` (paths_to_mutate, pytest_add_cli_args bypassing the coverage gate, also_copy mirroring the full src/ tree).
- Diagnosed and worked around 3 distinct root causes for mutmut + pytest config interaction (missing package modules in `mutants/src/`, missing data dirs, subprocess-spawning E2E test conflict with mutmut's CWD manipulation).
- Captured baseline: 438 mutants total, 327 killed (74.7%), 111 survivors.
- Per-class triage of 111 survivors → **68 strengthening tests** across 13 mutation classes via spy/monkeypatch patterns + parametrised boundary tests + exact-text assertions on observable output. Result: **405 killed, 0 survived, 33 mutmut-skipped on Linux CI = 100% kill rate on testable mutants**.
- Added `.github/workflows/mutation.yml` (nightly + workflow_dispatch) with score-floor gate.
- Added `.github/workflows/tdm-freshness.yml` + `scripts/check_tdm_freshness.py` for weekly TDM URL freshness checks.

**Local verification limitation:** macOS arm64 + Python 3.14 + mutmut hits a known `os.fork()`-after-Hypothesis-thread crash that segfaults every mutant on cold cache. Linux CI is unaffected. Documented honestly in the run summary.

### Phase 4 — Hardening + this summary ([commit pending], [PR pending])

**Workflow:** strategising (light) → planning → executing → finishing. 6 tasks.

**Substance:**
- T1: Fixed `mutation.yml`'s parser — discovered PR #27's earlier fix had two real bugs (`mutmut export-cicd-stats` writes to a FILE not stdout; emits only aggregate totals with no per-module breakdown). New parser reads `mutants/src/sumo_qa/<module>.py.meta` files directly, exactly as mutmut's own `browse`/`results` commands do internally.
- T2: Created the `tdm-freshness` GitHub label + re-added `--label tdm-freshness` to the workflow's `gh issue create` call.
- T3: Ratcheted the mutation gate from "≥ baseline" to **strict 100% kill rate** (any survivor on any module fails the workflow).
- T5: **Baked the "drive don't quiz" confirmation discipline INTO the sumo-qa skill files themselves** (rather than leaving as per-user memory). Added a `### Confirmation discipline` section to `using-sumo-qa`'s Global discipline; updated `sumo-qa-strategising`, `sumo-qa-planning-qa-rollout`, `sumo-qa-strengthening-tests` Checklist notes to permit batched confirmation when the user has already endorsed the trajectory. **Product improvement, not preference rule.** Every future user benefits without future Claude having to relearn it.
- **T6: Added Claude Desktop host support** to `sumo-qa-install` after the user found Claude Cowork (the desktop app) couldn't detect the MCP server. New `_setup_claude_desktop` function writes to the OS-correct path (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%/Claude/` on Windows, `~/.config/Claude/` on Linux) AND merges with existing MCP entries (doesn't clobber other servers). 8 new tests; 100% coverage maintained.

## Measurable quality improvement

| Metric | Pre-Phase 1 | Post-Phase 4 | Delta |
|---|---|---|---|
| Test count | ~219 | **425** | **+206 tests (+94%)** |
| Statement coverage | ~75% | **100.00%** *(1147/1147)* | +25 percentage points |
| Coverage gate enforced in CI | No | Yes (`--cov-fail-under=100`) | new |
| Coverage gate enforced pre-push | No | Yes (pre-commit hook) | new |
| Mutation testing infrastructure | None | mutmut nightly + strict 100% gate | new |
| Mutation kill rate (4 parser modules, Linux CI) | n/a (no mutation testing) | **100% (405/405 testable, 33 mutmut-skipped)** | new |
| Property-based tests | 0 | 30 Hypothesis tests across 4 modules | new |
| CI matrix (OS × Python) | 2×5 = 10 jobs | **3×5 = 15 jobs** | +50% |
| CI workflows | 2 (lint, test) | **5** (lint, test, release, mutation, tdm-freshness) | +3 |
| SAST (CodeQL) | None | Default-setup CodeQL active | new |
| Open Dependabot alerts | 1 moderate (pytest CVE-2025-71176) | **0** | resolved |
| Production defects found by tests added during this exercise | 0 | **2** (StandardsRulesEngine.evaluate idempotence + order) | +2 |
| Source-code dead code | ~1,100 LOC qaskills+node_install | 0 | removed |
| Production LOC | 3,081 | 2,573 | −508 (cleanup) |
| Test LOC | ~2,000 *(estimated pre-baseline)* | **6,064** | +200% |
| Documented QA policy | None | `COVERAGE.md`, `qa-strategy.md`, `repo_walk.md`, 4 plans, 4 run summaries, this doc | new |
| Skill ↔ MCP-tool drift guard in CI | None | `tests/test_skill_tool_crossref.py` | new |
| Repo-walk inventory recipe | Per-session judgment | `knowledge/repo_walk.md` + structural test | new |
| Hosts the installer can configure | 3 (Claude Code, VS Code, JetBrains) | **4** (+ Claude Desktop / Cowork) | +1 |

**Suite duration:** ~2s (pre-Phase 1) → ~10s (post-Phase 4). Cost of the +206 tests is well within the 30s budget the strategy set.

## What sumo-qa got wrong (honest)

These are real failure modes the dog-fooding exercise surfaced. Each one led to a concrete improvement (memory rule, skill update, or process change).

1. **Phase 1's planning step skipped the test-design sub-skills.** Approach tags on the plan tasks (`strengthen-test-coverage`, `tdd-scaffold`, etc.) were treated as scaffolding labels, not invocations. Test design happened from training-data judgment instead of the catalogued discipline. Surfaced + fixed mid-Phase 2 (memory rule `feedback_route_test_design_through_subskill.md`).
2. **Phase 1 wrote a strict policy doc (`COVERAGE.md`) but shipped with policy violations as "non-blocking follow-ups".** User pushed back: *"Why aren't we fixing the known gaps?"* Three pragmas in production code didn't match the policy's allowed cases. Fixed before merge by deleting dead code + refactoring `_detect_install_mode()` into a testable function. Memory rule `feedback_fix_violations_not_ship_with_gaps.md`.
3. **Local mutmut on macOS arm64 + Python 3.14 segfaults on cold cache** due to `os.fork()` after Hypothesis thread initialisation. Three workaround paths attempted; ultimately documented as a known platform limitation. Linux CI saved the verification.
4. **Phase 3's CI mutation gate parser shipped broken** (PR #27 guessed at the `mutmut export-cicd-stats` JSON schema without reading mutmut source). Phase 4 T1 fixed it; the workflow was red for ~12 hours between Phase 3 merge and the parser fix.
5. **Phase 4 strategising over-questioned with structured `AskUserQuestion` blocks** for granular calls the user lacked context for. User feedback: *"i normally just being agreeing yes to most things it asks"*. Fixed by baking the **Confirmation discipline** into `using-sumo-qa`'s Global discipline (T5) — a sumo-qa product improvement, not a per-user preference rule.
6. **Sumo-qa-install didn't support Claude Desktop / Cowork at all.** User discovered when trying to use sumo-qa from Claude Cowork. The installer was writing `claude_desktop_config.json` to the wrong path (`~/.config/claude/` instead of `~/Library/Application Support/Claude/` on macOS), so the file existed but Claude Desktop never read it. Fixed in Phase 4 T6 by adding a real `_setup_claude_desktop` host with OS-correct paths + merge-not-clobber logic.

## What's NOT addressed (residual risks accepted)

- **Mutation coverage gap on remaining modules** — `installer.py` (268 LOC), `tdm_service.py` (147), `tdm_catalogue.py` (121), `server.py` (93), `tools.py` (52), `skill_prompts.py` (46), `debug_capture.py` (28) — ~755 LOC of production code currently has 0 mutation coverage. Phase 4 deliberately limited scope to closure + hardening; expanding mutation surface is a hypothetical Phase 5.
- **macOS arm64 mutmut segfault unresolved upstream** — local-dev mutation runs on macOS arm64 will continue to crash. Linux CI works fine; the strategic answer is "trust CI" rather than fight the upstream tool.
- **Skill-content quality eval** (LLM-as-judge eval of skill prompt outputs — Promptfoo / DeepEval / Ragas) remains out of scope. Worked-example markdowns in `tests/scenarios/worked-examples/` are the human-eval proxy. Worth lifting only if user-reported skill drift becomes recurring.
- **Real-host integration tests** — the installer is tested with mocked subprocess + `tmp_path`. We do NOT actually install into a real Claude Code / VS Code / JetBrains / Claude Desktop and observe MCP tools surface end-to-end. Mitigated by: T6's manual verification on the real machine, the Phase 1 e2e MCP `initialize` smoke test, the install-fix's manual gate (`pip install + sumo-qa-install + claude mcp get sumo-qa` post-merge). **Residual:** silent host-API drift (e.g. Claude Desktop changing its config schema) won't be caught until a user report.
- **Performance / load testing** of the MCP server under high tool-call rates — no SLO articulated; deselected per ISO/IEC 25010 prioritisation.

## For other repos pointing sumo-qa at their codebase

Based on this real run (not theoretical claims), here's what to expect:

1. **The strategising walk works against any codebase Sumo-qa can read.** It uses `find` / `wc -l` / `pytest --co` / `pytest --cov` / `cat .github/workflows/*.yml` / `cat .pre-commit-config.yaml` per the recipe in `knowledge/repo_walk.md`. Inventory takes ~30 seconds; per-area risk analysis another minute or two.
2. **Hypothesis property tests will surface real defects.** Phase 2 found 2 in a codebase that already had 75% coverage and looked clean. The technique is most productive on parser / decision / pure-function modules.
3. **Mutation testing will reveal weak assertions.** Phase 3's baseline was 74.7% killed despite 100% statement coverage — line coverage is not assertion strength. Plan ~10 minutes per 100 mutants for the strengthening pass.
4. **The "interactive walks" in `sumo-qa-strengthening-tests` work in batches.** Strict per-mutant flow is hours of work for hundreds of survivors; per-class batching (presented in this doc + now baked into the skill) is the practical path.
5. **Be prepared for sumo-qa to find gaps in itself.** This run surfaced 6 distinct defects in sumo-qa during the dog-fooding (5 process / product issues + the Claude Desktop install gap). Expect the same on any codebase being audited rigorously.

## Closing

This is one repo's experience with sumo-qa. The repo whose product is "helping other repos achieve quality" now meets the bar it asks of others — 100% statement coverage, 100% mutation kill rate on parser modules, drift guards in CI, structured QA strategy/plan/run docs, mutation + freshness CI workflows on schedules. The honest answer to "did sumo-qa work?" is yes, with the caveats above; the honest answer to "did dog-fooding it improve sumo-qa?" is also yes — six real product/process improvements landed because the user pushed back when sumo-qa was sloppy.

**Linked artefacts:**
- Strategy: [`docs/qa-strategy.md`](../qa-strategy.md)
- Phase 1 plan + run: [`docs/qa/plans/2026-05-14-phase1-quality-baseline.md`](plans/2026-05-14-phase1-quality-baseline.md), [`docs/qa/runs/2026-05-14-phase1-quality-baseline.md`](runs/2026-05-14-phase1-quality-baseline.md)
- Phase 2 plan + run: [`docs/qa/plans/2026-05-14-phase2-drift-guards-parser-robustness.md`](plans/2026-05-14-phase2-drift-guards-parser-robustness.md), [`docs/qa/runs/2026-05-14-phase2-drift-guards-parser-robustness.md`](runs/2026-05-14-phase2-drift-guards-parser-robustness.md)
- Phase 3 plan + run: [`docs/qa/plans/2026-05-14-phase3-mutation-baseline-tdm-freshness.md`](plans/2026-05-14-phase3-mutation-baseline-tdm-freshness.md), [`docs/qa/runs/2026-05-15-phase3-mutation-100pct-tdm-freshness.md`](runs/2026-05-15-phase3-mutation-100pct-tdm-freshness.md)
- Phase 4 plan + run: [`docs/qa/plans/2026-05-15-phase4-hardening-and-summary.md`](plans/2026-05-15-phase4-hardening-and-summary.md), [`docs/qa/runs/2026-05-15-phase4-hardening-and-summary.md`](runs/2026-05-15-phase4-hardening-and-summary.md)
- Coverage policy: [`docs/COVERAGE.md`](../COVERAGE.md)
