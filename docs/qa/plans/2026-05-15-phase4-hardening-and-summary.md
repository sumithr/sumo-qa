# Phase 4 — Hardening + Effectiveness Summary QA Plan

> **For agentic execution:** Use `sumo-qa-executing-qa-rollout` to dispatch this plan task-by-task with two-stage review.

**Strategy reference:** [`docs/qa-strategy.md`](../../qa-strategy.md). Phase 4 is a hardening + closure pass that wasn't in the original strategy; it's added here because Phases 1–3 surfaced infrastructure gaps and the user explicitly requested an effectiveness summary.

**Goal:** Close the loose threads from Phases 1–3 (mutation gate parser bug, missing `tdm-freshness` label, gate ratchet), fold the "smoother confirmation discipline" feedback INTO the sumo-qa skill files themselves (not just per-user memory) so every future user benefits, and produce a single document measuring what sumo-qa actually delivered across all four phases. Smaller scope; ships fast; closes the rollout cleanly.

**Branch:** `feat/phase4-hardening-and-summary` off `main`.

**Approach mix:** infrastructure-change (T1, T2, T3) + docs-change (T4)

**Files touched:**

Edited:
- `.github/workflows/mutation.yml` (T1: fix JSON parser to match actual `mutmut export-cicd-stats` schema; T3: ratchet gate to strict 100% kill rate)

New:
- `docs/qa/SUMO-QA-EFFECTIVENESS.md` (T4: cross-phase effectiveness summary + measurable quality improvement)
- `docs/qa/runs/2026-05-15-phase4-hardening-and-summary.md` (run summary, written by sumo-qa-finishing-qa-work)

External actions (no file changes):
- T2: `gh label create tdm-freshness ...` against the GitHub repo

**Risks covered:**
- **R-MUT-GATE-RED** — last 2 scheduled mutation runs failed at the parser step; nightly mutation gate has zero signal until fixed. T1 fixes the parser; T3 then ratchets to strict 100%.
- **R-FRESHNESS-LABEL** — `tdm-freshness.yml` workflow opens an issue with `--label tdm-freshness` on non-2xx; if the label doesn't exist on the repo, the issue creation step fails. T2 creates the label.
- **R-NO-CLOSURE-DOC** — four phases of QA work but no single document the user can show as "this is what sumo-qa delivered". T4 produces it with measurable metrics.

---

### Task 1 — Fix mutation.yml JSON parser `[parallel]`

**Approach:** infrastructure-change
**Risk covered:** R-MUT-GATE-RED
**Files:** `.github/workflows/mutation.yml`

**The problem:** PR #27's parser fix replaced `mutmut results` text parsing with `mutmut export-cicd-stats` JSON parsing, but the JSON walk is too speculative — it guessed at the schema without reading mutmut's source. Result: parser produces `current killed = 0` for every module, gate fails with false "DROPPED".

**Done when:**
- The actual `mutmut export-cicd-stats` JSON schema is read (from mutmut's source OR from the artifact uploaded by the last failing run OR by running mutmut locally with the warm cache).
- The parser correctly extracts per-module killed counts; on the first re-trigger after merge, the gate compares against baseline AND reports correctly (knowledge_loaders: 153 expected, rules: 41 expected, standards: 25 expected, tdm_validation: 219 expected — the `tested` count from Phase 3's strengthened state).
- The workflow run completes successfully (no false-DROPPED).

**Steps:**
1. Download a `mutmut-current.json` artifact from a recent failed mutation run via `gh run download` (or run mutmut locally if the macOS arm64 segfault doesn't fire on cold cache today).
2. Inspect the actual JSON schema: which key holds the per-mutant entries; what field names it uses (`name`/`mutant_name`, `result`/`status`, etc.); what the per-mutant module-name format is.
3. Rewrite the parser block in `.github/workflows/mutation.yml`'s "Compare against baseline" step to match the real schema.
4. Verify locally if possible: feed the downloaded JSON through the new parser and confirm it produces sensible per-module counts. If macOS local mutmut crashes, skip and rely on the next CI run.

---

### Task 2 — Create `tdm-freshness` GitHub label `[parallel]`

**Approach:** infrastructure-change (external state, no file change)
**Risk covered:** R-FRESHNESS-LABEL
**Files:** none in repo

**The problem:** `tdm-freshness.yml` workflow's "Open issue on failure" step uses `gh issue create --label tdm-freshness ...`. If the label doesn't exist, this step fails before any non-2xx scenario can be reported. P3-T4's implementer dropped the `--label` flag from the workflow because of this; we need to either re-add the flag (after creating the label) or document that issues will be created without the label.

**Done when:**
- `gh label create tdm-freshness --description "TDM URL freshness check found non-2xx URLs" --color 0e8a16` succeeds (or returns "already exists").
- `gh label list | grep tdm-freshness` shows the label.
- Optionally: re-add `--label tdm-freshness` to the `gh issue create` command in `tdm-freshness.yml`. (If kept out, that's also fine — the issue can be labelled manually.)

**Steps:**
1. `gh label create tdm-freshness --description "..." --color 0e8a16` (or whatever colour Sumith prefers; green suggests "tracking-only").
2. Verify with `gh label list`.
3. Optional file change: edit `tdm-freshness.yml` to re-include `--label tdm-freshness` in the gh issue create command.

---

### Task 3 — Ratchet mutation gate to strict 100% `[sequential]`

**Approach:** infrastructure-change
**Risk covered:** locks in the user's "100% killed" target
**Blocked by:** T1 (gate must work before tightening it)

**The problem:** Phase 3's plan set the gate to "≥ baseline" with a manual ratchet to 100% after the first Linux CI run confirmed kill rate. We have that confirmation (Phase 3's mutmut.log: 405 killed, 0 survived, 33 mutmut-skipped on Linux); the user's stated gate is 100%. Time to tighten.

**Done when:**
- `.github/workflows/mutation.yml`'s "Compare against baseline" step now fails when ANY surviving (non-skipped) mutant is found, regardless of baseline.
- A successful re-trigger after T1 confirms the workflow still passes (since kill rate is currently 100% on testable mutants).
- Comment in the workflow updated: "100% kill rate on testable mutants" (skipped/excluded mutants don't count against the gate).

**Steps:**
1. Edit the parser block: in addition to the baseline comparison, add a strict check that fails if any module has `survived > 0` in the parsed JSON.
2. Update the workflow's top-of-file comment to document the strict gate.
3. Workflow_dispatch a fresh run after merge; verify pass.

---

### Task 5 — Bake "drive don't quiz" confirmation discipline into sumo-qa skills `[parallel]`

**Approach:** docs-change (skill bodies are markdown)
**Risk covered:** **R-CONFIRMATION-OVERHEAD** — the strategising / planning skills' "section-by-section with confirmation gates" + "ONE focused question per turn" pattern, when followed literally, peppers the user with structured `AskUserQuestion` blocks for granular calls they often lack context to choose between. They end up saying "yes" to most options because the question doesn't actually gate a decision they care about. This is a sumo-qa PRODUCT defect, not a per-user preference — bake the fix into the skill files so every user benefits.

**Files:**
- Edit: `skills/using-sumo-qa/SKILL.md` — add a "Confirmation discipline" section to the **Global discipline** block (inherited by every sub-skill).
- Edit: `skills/sumo-qa-strategising/SKILL.md` — update the Checklist / Process Flow notes so step 4–10 collapse adjacent obvious confirmations into a single update; only walk per-section when there's real per-section judgment to surface.
- Edit: `skills/sumo-qa-planning-qa-rollout/SKILL.md` — same: update step 6 to allow batch-confirming sections that the user has clearly already endorsed via earlier confirmations.
- (Optionally) edit `skills/sumo-qa-strengthening-tests/SKILL.md` — its "one mutant at a time" rule was the same shape; allow per-class batching when same-mechanism mutants permit a class-level decision (which is what we did successfully in Phase 3).

**The discipline to bake in** (paste into `using-sumo-qa` Global discipline):

```markdown
### Confirmation discipline

The skills' confirmation gates exist to prevent driving past wrong assumptions
— but applying them literally to every minor specifics-call wastes the user's
attention. Use this hierarchy:

1. **Surface + proceed** is the default. State what you're doing, briefly cite
   the call, and act. The user will redirect if they disagree.
2. **Inline confirm** for moderate forks. Phrase as one declarative line ending
   in a question: *"Going with X (Y is the alternative); shout if not."* Then
   act unless they object.
3. **Structured `AskUserQuestion` ONLY for genuine 50/50 forks** that
   meaningfully change downstream work. Reserve for: irreversible commits,
   scope changes that double the work, choices the user has explicit context to
   make better than you. NOT for "which of these 4 phrasings sounds right" or
   "should this filename use X or Y convention".

Rule of thumb: if you'd predict the user's answer with >80% confidence, don't
ask. Surface and proceed. The cost of a wrong default is one redirect; the
cost of asking is the user's attention budget across N turns.

Skill checklists that say *"walk section-by-section with confirmation gates"*
should be read as: walk per-section when each section genuinely needs the
user's per-section judgment. Collapse adjacent obvious sections into a single
update. The Iron Law is "don't dump the whole strategy in one turn"; the goal
is structured collaboration, not maximum question count.
```

**Done when:**
- `skills/using-sumo-qa/SKILL.md` has the Confirmation discipline section in Global discipline.
- `skills/sumo-qa-strategising/SKILL.md` step list updated to permit batched confirmation.
- `skills/sumo-qa-planning-qa-rollout/SKILL.md` step list updated similarly.
- `tests/test_skill_conformance.py` (and any related conformance test) still passes — the section additions don't break structural assertions on Iron Law, Red Flags, Checklist headings.
- `tests/test_skill_tool_crossref.py` still passes — no `sumo_qa_*` tool references added/removed.
- `uv run pytest -q` 100% green; ruff clean.

**Steps:**
1. Read `skills/using-sumo-qa/SKILL.md` end-to-end. Find the Global discipline block.
2. Add the Confirmation discipline section as a peer to "Knowledge authority hierarchy" / "Setting up the recommended tool" / "Internal reasoning vs user output".
3. Edit `sumo-qa-strategising/SKILL.md`: in the Checklist commentary, note that adjacent sections may be batched into a single confirmation when the user has already endorsed the trajectory.
4. Edit `sumo-qa-planning-qa-rollout/SKILL.md`: same update to step 6.
5. (Optional) Edit `sumo-qa-strengthening-tests/SKILL.md`: per-class batching documented as acceptable where the mechanism is uniform.
6. Run pytest + ruff. Conformance + cross-ref tests must stay green.

---

### Task 4 — Write `docs/qa/SUMO-QA-EFFECTIVENESS.md` `[sequential]`

**Approach:** docs-change
**Risk covered:** R-NO-CLOSURE-DOC + the user's explicit ask
**Blocked by:** T1, T2, T3 (so the doc reflects the final state)
**Files:** `docs/qa/SUMO-QA-EFFECTIVENESS.md` (new); also extend `docs/qa-strategy.md` with a "## Phase 4" section if the strategy doc is consulted in the doc body.

**Content shape:**

1. **What sumo-qa is** (one paragraph for context: senior-QA MCP server + skills library; this repo dog-fooded it on its own codebase).
2. **What sumo-qa actually did** — narrative of each phase invocation:
   - Phase 1 = strategising → planning → executing → finishing chain on a 12-task quality baseline. Surfaced the Claude Code MCP install gap mid-flow. Caught Windows-specific portability bugs once the matrix expanded.
   - Phase 2 = strategising-skipped (Phase 2 was Phase 1 strategy's item 5–6); planning → executing → finishing on 6 tasks. Hypothesis property tests **surfaced 2 real production defects** in `StandardsRulesEngine.evaluate` (idempotence + order-sensitivity) — the canonical sumo-qa win.
   - Phase 3 = same chain on 4 tasks with mid-flow gate change ("baseline" → "100% killed"), 68 strengthening tests added across 13 mutation classes.
   - Phase 4 = closure (this PR).
3. **Measurable quality improvement** — table comparing pre-Phase-1 vs post-Phase-4:

   | Metric | Pre-Phase 1 | Post-Phase 4 | Δ |
   |---|---|---|---|
   | Test count | 219 (or whatever the actual pre-baseline was) | 417 | + |
   | Statement coverage | 75% | 100% | +25pp |
   | Coverage gate enforced | No | Yes (`--cov-fail-under=100`) | new |
   | Mutation kill rate (4 parser modules) | 74.7% | 100% | +25.3pp |
   | Mutation testing infra | None | mutmut nightly + score-floor gate | new |
   | CI matrix (OS × Python) | 2×5 = 10 | 3×5 = 15 | +50% |
   | CI workflows | 2 (lint, test) | 5 (+ release, mutation, tdm-freshness) | +3 |
   | Open Dependabot alerts | (unknown — was 1 moderate at start of Phase 1) | 0 | resolved |
   | Pre-existing production defects found by tests | 0 | 2 (`evaluate` idempotence + order) | +2 |
   | Documented QA policy | None | COVERAGE.md, qa-strategy.md, repo_walk.md, 4 plans, 4 run summaries | new |
   | Skill ↔ MCP-tool drift guard | None | `tests/test_skill_tool_crossref.py` | new |
   | Repo-walk recipe | Per-session judgment | `knowledge/repo_walk.md` + `tests/test_repo_walk_recipe.py` | new |
4. **What sumo-qa got wrong** (honest):
   - Phase 1 plan skipped invoking the test-design sub-skills during planning (Approach tags weren't enough discipline) — surfaced + memorised mid-Phase 2 (`feedback_route_test_design_through_subskill.md`).
   - Phase 1 strategy wrote a strict policy doc (COVERAGE.md) but shipped with policy violations as "non-blocking follow-ups" — fixed only after Sumith pushed back (`feedback_fix_violations_not_ship_with_gaps.md`).
   - Phase 4 strategising over-questioned the user with structured AskUserQuestion blocks for granular calls he lacked context for — surfaced + memorised mid-Phase 4 (`feedback_drive_dont_quiz.md`).
   - Local mutmut on macOS arm64 segfaults; couldn't verify Phase 3 strengthening locally (Linux CI saved it).
   - Phase 3's mutation gate parser shipped broken (PR #27); needed Phase 4 T1 to fix.
5. **What's NOT covered** (residual risks accepted):
   - Mutation testing on installer / server / tdm_* modules (~700 LOC) — deferred to a hypothetical Phase 5.
   - Skill-content quality eval (LLM-as-judge eval of skill prompt outputs) — out of scope; worked-examples are the proxy.
   - Real-host integration tests (actually install into Claude Code/VS Code/JetBrains and observe MCP tools surface) — mitigated by the install-fix and the e2e MCP smoke test, but full end-to-end host install isn't fixtured.
6. **For other repos using sumo-qa**: a 5-bullet "what to expect when you point sumo-qa at your codebase" — based on this real run, not theoretical claims.

**Done when:** the doc exists; metrics in the table are computed against actual git/CI state (not estimated); honest "what sumo-qa got wrong" section present; linked from README.

---

## Phase 4 closure gate

- T1: mutation.yml gate fires correctly (next workflow_dispatch passes, not falsely-fails).
- T2: `gh label list | grep tdm-freshness` returns the label.
- T3: gate is strict 100% (any survivor fails the workflow).
- T4: `docs/qa/SUMO-QA-EFFECTIVENESS.md` exists with the table populated against real metrics.
- T5: skill files updated; Confirmation discipline visible in `using-sumo-qa/SKILL.md`; relevant sub-skills' Checklist notes permit batched confirmation.
- All existing checks (pytest, ruff, CodeQL, skill conformance, skill ↔ tool cross-ref) still green.

When all of the above hold, route to `sumo-qa-finishing-qa-work` for the run summary + PR description, then commit + push + open PR + merge.
