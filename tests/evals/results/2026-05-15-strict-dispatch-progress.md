# Strict-dispatch + rubric calibration progress — 2026-05-15

Follow-up to the [baseline run](2026-05-15-baseline-run.md) (6/25 PASS = 24%). Two improvements: (1) tightened the candidate-dispatch prompt to demand strict skill discipline rather than permissive *"adapt as you see fit"*, (2) extended the tool-selection rubric to recognise the confirm-before-call discipline for write-side mutating tools.

## Headline

**12/25 PASS = 48%.** Doubled the pass rate from the 24% baseline. **All 10 tool-selection scenarios now PASS (10/10).** Skill-behaviour scenarios at 2/15 (up from 0/15).

## Per-scenario delta from baseline

| Scenario | Baseline | After strict | Delta | Reason |
|---|---|---|---|---|
| **Tool-selection** | 6/10 | 10/10 | +4 | TS-03/07/08 fixed by strict-dispatch (full args, exact catalogue wording); TS-10 fixed by rubric calibration (write-side confirm-before-call recognised as valid SELECTION) |
| **Skill-behaviour — env-independent** | 0/7 | 2/7 | +2 | SCN-10 (deciding-approach + mkdocs render check), SCN-15 (suggesting-external-skill with skills.sh URL) |
| Skill-behaviour — env-mismatch | 0/8 | 0/8 | 0 | Sandbox pilot for SCN-01 in flight |
| Skill-behaviour — multi-turn / overconstrained | 0/2 | 0/2 | 0 | Architectural fix (multi-turn eval) needed |

## What changed

### Strict candidate-dispatch prompt template

Original dispatch said *"adapt — files don't exist; respond honestly"*, which gave agents permission to skip discipline beats. The strict template demands:

- Load the matched skill body in full (not summary)
- Load the catalogues the skill's checklist names (classifications, approaches, principles, techniques, standards, rules)
- Iron Laws / HARD-GATEs are non-negotiable — actually `Bash(uv run pytest)` when the skill says "run tests in this turn"
- Never surface internal taxonomy labels (no *"Routing to..."* announcements)
- Use file tools (`Bash(ls)`, `Bash(find)`) to confirm absence when scenarios reference non-existent files; don't just narrate

### Tool-selection rubric — write-side confirm-before-call

Added a clause to `rubrics/tool-selection.md`: write-side tools that mutate the local catalogue (`sumo_qa_register_known_good_test_data`) follow a confirm-before-call discipline. SELECTION = PASS when the agent **constructs the full args dict and explicitly stages the call pending user confirmation**, even if no actual tool invocation is in the trajectory. The actual invocation happens in turn 2 after user yes; turn 1 = construct + stage = correct senior-QA behaviour.

This unblocked TS-10 (was FAIL on SELECTION because the agent correctly asked confirmation before calling register; now PASS).

## Remaining failures (13)

### Environment mismatch (7) — sandbox approach validated for SCN-01 only

SCN-01, SCN-03, SCN-04, SCN-05, SCN-08, SCN-13, SCN-14. Scenarios reference files (billing service, pricing, Pitest report, customer-platform monorepo, plan markdown, etc.) that don't exist in sumo-qa's tree.

**Sandbox approach:** built stub sandboxes under `/tmp/eval-sandboxes/SCN-XX/` with the named files. Subagents dispatched with sandbox cwd; can `Read` and `Write` the named files.

**Result: SCN-01 PASS. SCN-03/04/05/08/13/14 still FAIL** — sandboxes resolved the file-existence problem, but the rubric beats expose multi-turn discipline:
- SCN-03/04: skill says "ask ONE focused clarification before writing the test" (multi-turn beat — turn 1 ask, turn 2 write). Agents in sandbox went straight to writing.
- SCN-05: skill expects "rerun Pitest against the mutated production code to verify the mutant is killed" — sandbox doesn't have Pitest installed (would need full mutmut + JVM toolchain).
- SCN-08: skill expects "walk subsequent sections one at a time with confirmation gates" — turn 1 was the inventory; turn 2-4 are the per-area walks. Single-turn eval can't capture this.
- SCN-13: skill expects "actually dispatch fresh subagents for each plan task" — single-turn eval truncates this; agent described the dispatch shape instead of doing it.
- SCN-14: skill's Iron Law expects "fresh suite evidence with counts, duration, AND coverage %" — sandbox has 1 trivial test and no coverage config; can't produce the full surface.

Sandboxes solve the *file-existence* problem but not the *multi-turn-design* problem.

### Spec overconstraint / multi-turn (2)

SCN-09 (creating-test-plan) and SCN-12 (planning-qa-rollout). These skills have HARD-GATEs that say *"walk section-by-section, NEVER single-shot dump"* — but the rubric expects the final deliverable in turn 1. The eval shape doesn't match the skill shape. Architectural fix: multi-turn eval support (substantial harness change), or scenario rewrite.

### Real discipline gaps (4)

SCN-02, SCN-06, SCN-07, SCN-11. With strict dispatch, these went from missing 5–8 beats to missing 1–3 beats — but still FAIL because PASS requires ALL beats. Examples:
- SCN-02: agent ran `git diff --stat` (statistics) instead of `git diff` (hunks). Borderline.
- SCN-06: agent answered well but didn't surface "performance under load" as a shape.
- SCN-11: agent loaded skills + did the work but routing felt non-transparent.

These could be closed with even more prescriptive dispatch, OR by tightening the SKILL.md text itself to forbid the specific anti-patterns.

## Final tally (this session)

**13/25 = 52% PASS.** Up from 24% baseline.

| Bucket | Count | PASS rate |
|---|---|---|
| Tool-selection (TS-01..10) | 10 | 10/10 = 100% |
| Skill-behaviour env-independent (SCN-06, 10, 11, 15, 02, 07) | 6 | 2/6 = 33% (SCN-10, 15) |
| Skill-behaviour env-mismatch with sandboxes (SCN-01, 03, 04, 05, 08, 13, 14) | 7 | 1/7 = 14% (SCN-01 only) |
| Skill-behaviour multi-turn / overconstrained (SCN-09, 12) | 2 | 0/2 |

## Path forward

To reach 95% (24/25) from 52% (13/25):

1. ~~**Sandbox 7 env-mismatch scenarios**~~ — done. Only SCN-01 passed. The other 6 expose multi-turn beats that no amount of sandboxing fixes.
2. **Multi-turn eval support** — substantial harness change. Each scenario becomes a 2-4 turn role-play (turn 1 ask, turn 2 user-says-yes, turn 3 deliverable). Judge against full transcript. This unblocks SCN-03/04/08/09/12/13/14 = +7 → 20/25 = 80%.
3. **Tighten SKILL.md text** for the 4 remaining real-discipline misses (SCN-02 git diff vs git diff --stat; SCN-06 surface performance shape; SCN-07 full args; SCN-11 transparent handoff). Could push another +3 → 23/25 = 92%.
4. **Spec calibration on SCN-09/12** (Iron Law contradicts shape beat) — split each into a per-turn rubric. → +2 → 25/25 = 100%.

**Realistic single-session ceiling without multi-turn:** ~16/25 = 64%.
**To hit 95% requires multi-turn eval support + skill tightening, not just more dispatch attempts.**

## Key insight

The eval harness itself is working — verdicts are real, judge is adversarial, false positives are rare. The 95% bar isn't reachable on the current scenario set with single-turn capture because **half the skills are designed for multi-turn confirmation gates** and the rubric correctly demands what those skills demand. The next move is architectural (multi-turn harness), not iterative (more dispatch attempts).
