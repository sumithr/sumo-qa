# Post-Cleanup Verification — 2026-05-08 01:42

## What was verified

After the 5-round prompt iteration converged at 11/11 senior-istqb-grade
(commit `997c80f`), two further commits applied MCP-builder retrospective
cleanups:

- `62a6a01` — Agent A: tool annotations (readOnlyHint / destructiveHint /
  idempotentHint / openWorldHint), pagination metadata on
  `qa_find_test_data`, server name fix (`qa-shift-left-mcp` → `sumo-qa`),
  `isError` envelope wrapping, Pydantic `Field` examples
- `7c87506` — Agent B: `outputSchema` declarations via Pydantic models,
  tool prefix rename `qa_*` → `sumo_qa_*` (breaking change), and a
  `response_format=json|markdown` parameter on every tool

The risk: the rename + outputSchema changes touched the AI prompt
schemas (`next_action.tool` in `_build_decide_approach_sampling_prompt`,
plus the JSON schema lines in every per-tool builder). Could regress
the rubric verdicts.

## Verdict matrix

All 11 scenarios re-dispatched with regenerated briefs (the briefs read
the live source so they reflect the renamed tool names automatically).

| scenario_id | round 5 | post-cleanup |
|---|---|---|
| very-specific.bundle-validator-line-diff | senior-grade | **senior-grade** |
| very-specific.regression-stale-stock | senior-grade | **senior-grade** |
| specific.scaffold-bundle-validator | senior-grade | **senior-grade** |
| specific.security-token-refresh | senior-grade | **senior-grade** |
| moderate.refactor-pricing-pipeline | senior-grade | **senior-grade** |
| moderate.mutation-testing-followup | senior-grade | **senior-grade** |
| moderate.config-ttl-bump | senior-grade | **senior-grade** |
| generic.how-to-test-this-service | senior-grade | **senior-grade** |
| generic.docs-only-update | senior-grade | **senior-grade** |
| very-generic.test-strategy-from-scratch | senior-grade | **senior-grade** |
| very-generic.spike-throwaway-prototype | senior-grade | **senior-grade** |

**11/11 senior-istqb-grade preserved.** No regressions.

## Observations from the post-cleanup run

The graders flagged a handful of *additional* improvements that didn't
exist as gaps before but became visible once the schemas were tightened.
None block senior-grade; recording them as backlog notes:

1. **Review schema is less strict than the question schema** (flagged
   on #1 bundle-validator-line-diff). The question tool now requires
   `principle_cited`, `named_techniques`, `recommended_approach`,
   `smallest_useful_tests` (capped 3-5) — but `_build_review_sampling_prompt`
   still has the older `narrative` / `checks` shape. A junior model run
   could pass review-tool schema validation without citing principles
   or naming techniques. Worth harmonising.

2. **Strategy-orchestration has no dedicated structured schema** (flagged
   on #10 test-strategy-from-scratch). The AI invented `pyramid_shape`,
   `gate_calibration`, `ci_feedback_time`, `rollout_plan` fields — they're
   exactly what a strategy ask needs, but the schema doesn't formally
   require them. Another run could omit them.

3. **`next_action` ambiguity at the strategy boundary** (flagged on #10).
   For `strategy-orchestration`, `next_action.tool` is `"sumo-qa-strategising"`
   — but that's a SKILL name, not an MCP tool name. Schema says
   "MCP tool to call next"; a strict parser could mis-route. Options:
   add `{"skill": "<name>"}` as a distinct shape, or document that
   `next_action.tool` accepts skill names too.

4. **Specialty-tool fit doesn't have positive examples per risk shape**
   (flagged on #7 config-ttl-bump in earlier round, partly addressed in
   round 4). For JWT-TTL changes the right tool is JJWT integration
   testing, not OWASP ZAP. The system prompt now says "tool must FIT THE
   RISK" but doesn't enumerate examples per risk shape.

These are quality-of-life polish items for a hypothetical Round 6 — none
are blocking. The current state is the strongest the prompts have been.

## Regression gates held

- `uv run pytest` → 236 passed (after both cleanup commits)
- `uv run sumo-qa-eval` → 28/28
- `sumo-qa-mcp` reinstalled successfully
- All 10 MCP tools advertise: `sumo_qa_*` prefix, annotations, outputSchema,
  Pydantic Field examples, `response_format` param, `isError` envelope
- `qa_find_test_data` → `sumo_qa_find_test_data` advertises pagination
  metadata (`total_count`, `has_more`, `next_offset`)

## Branch state

Branch: `feat/ai-driven-iteration-loop` (17 commits, not pushed)

```
post-cleanup verification (this file, will commit next)
7c87506 refactor(server): MCP best practices part 2 — outputSchema, tool prefix rename, response_format
62a6a01 refactor(server): MCP best practices — tool annotations, pagination metadata, isError, Field examples, server name fix
997c80f docs(iteration): steady state — 11/11 scenarios senior-istqb-grade across 5 rounds
6bb9ef6 feat(prompts): round 5 — scaffold schema gets top_risks + uncovered_branches + cross_cutting_assertions
6a98756 feat(prompts): round 4 — soften specialty rule (allow []), add boundary_scaffolds, security scenario uses target_paths
40dc7b5 feat(prompts): round 3 — scaffold/question schema HARD REQUIREMENTs, specialty+tool pairing, security_change classification, target_paths on prepare
9b92ea2 feat(prompts): round 2 — add assumptions/top_risks/suggested_tests, force domain anchoring, drop generic-risk hardcoding
69186ca feat(server): add SUMO_QA_DEBUG_DIR capture for manual review during final verification
... (Phase 1 harness commits)
```

## Next steps for the user

The MCP is converged AND post-cleanup-verified. Two ways to proceed:

1. **Live MCP verification (optional, more confident):** restart the
   sumo-qa MCP from Claude Code's MCP panel so the latest reinstalled
   binary is loaded, set `SUMO_QA_DEBUG_DIR=/tmp/sumo-qa-final-verification`,
   then invoke 3-5 scenarios via the live MCP. Read the captured
   `trace.md` files to confirm wire-protocol output matches the
   in-process verdicts. Catches any wire-level surprise the inner loop
   couldn't.

2. **Read the trace summaries directly and call it done.** Steady-state
   is `docs/superpowers/iteration-runs/steady-state-2026-05-07-1927.md`;
   this file is the post-cleanup verification. If both look right to
   you, the iteration is complete.

If anything still looks weak to your eye, name the scenario and the
dimension. I'll add a sharper scenario that stresses it and re-run.
