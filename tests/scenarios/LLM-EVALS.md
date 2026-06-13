# LLM-as-judge evals — design

How sumo-qa's scenario specs ([`SCENARIOS.md`](SCENARIOS.md) + [`TOOL-SELECTION.md`](TOOL-SELECTION.md)) become automatable LLM-as-judge evals.

This is a **design doc**, not a runnable harness. It specifies the rubric, the scoring, and the cadence so any of the established LLM-eval frameworks (promptfoo, Inspect, Anthropic Workbench, etc.) can be wired up by a future PR without re-litigating the contract. The framework choice is deliberately deferred — it's exactly the kind of "specialty tooling" that the discovery discipline in `using-sumo-qa` covers (observe the surface, web-search current options for the user's stack, recommend with citation).

> **Runnable implementation:** these evals now live in `tests/evals/promptfoo/` (added 2026-05-17). See `tests/evals/promptfoo/README.md` for run instructions; this doc remains as framework-agnostic design.

## Scope

| Scenario class | Source | Count |
|---|---|---|
| Skill behaviour | [`SCENARIOS.md`](SCENARIOS.md) §1–18 | 18 (covers all 16 skills; sub-skills #3 + #4 share `sumo-qa-implementing-with-tdd` with two approaches, and #16 + #17 share `sumo-qa-closing-qa-gaps` with two entry kinds) |
| Tool selection — atomic tools | [`TOOL-SELECTION.md`](TOOL-SELECTION.md) §TS-1 to TS-15 | 15 (6 knowledge loaders + 4 test-data tools + 4 external-skill lifecycle tools + 1 capabilities-discovery tool) |
| Tool selection — skill tools | [`TOOL-SELECTION.md`](TOOL-SELECTION.md) §"Skill tools (16)" | 16 (transitive — same scenarios as the skill behaviour evals; the *selection* assertion is independent of the *behaviour* assertion) |
| **Total** | | **49 distinct evals** (31 tool-selection evals + 18 skill-behaviour scenarios; 16 skill scenarios double as their own tool-selection evals; `sumo_qa_ingest_knowledge_pack` has no selection scenario) |

## Why LLM-as-judge, not pattern matching

The user-facing output of a sumo-qa-driven host LLM is conversational prose with multiple acceptable shapes. Pattern-matching assertions (`assert "risk" in response`) are too noisy: the agent might phrase the named risk as *"if the rate limiter under-counts at the 100→101 boundary"* instead of literal *"R1: rate limit boundary"*. A judge LLM, given the rubric, can grade *meaning* without prescribing wording.

The flip side: judge LLMs hallucinate. The rubric must be tight enough that the judge's call is mechanical, not editorial. Each assertion below is a *yes/no* check with a *concrete-evidence* requirement — the judge cites a quoted span from the candidate response, not a vibe.

## Rubric template — skill behaviour eval

```
You are reviewing whether a host LLM correctly executed the sumo-qa skill named in the scenario.
You are NOT reviewing the *quality* of the QA work; you are reviewing whether the skill's
discipline beats fired.

SCENARIO:
  Skill expected: {skill_id}
  User prompt:    {user_prompt}
  Expected interaction shape (from SCENARIOS.md):
    {numbered_expected_shape}
  Anti-patterns (from SCENARIOS.md):
    {bulleted_anti_patterns}

CANDIDATE RESPONSE:
  {candidate_first_turn}

For EACH item in "Expected interaction shape":
  - PASS / FAIL
  - Quote the exact span from the candidate that satisfies (or fails) the item.
  - Two-sentence explanation.

For EACH item in "Anti-patterns":
  - PRESENT / ABSENT
  - Quote the exact span if PRESENT; "not observed" if ABSENT.

Final verdict:
  - PASS if all expected items PASS and all anti-patterns ABSENT.
  - FAIL otherwise.
  - Surface the worst-failing item first.
```

## Rubric template — tool selection eval

```
You are reviewing whether a host LLM picked the correct sumo-qa MCP tool given the user's intent.

SCENARIO:
  User prompt:           {user_prompt}
  Expected tool:         {tool_name}({arg_shape})
  Anti-pick (one of):    {anti_pick_list}
  Expected use of result: {usage_assertion}

CANDIDATE TRAJECTORY:
  Tool calls made (in order): {tool_calls_with_args}
  First user-facing response: {candidate_response}

Checks:
  1. SELECTION: Did the LLM invoke `{tool_name}` (or its slash equivalent) on the first turn?
     PASS / FAIL — quote the tool call.
  2. ARG SHAPE: Did the call use the right argument shape?
     PASS / FAIL — quote the args; explain any deviation.
  3. ANTI-PICK: Did the LLM call any of the anti-picks first?
     ABSENT / PRESENT — quote the anti-pick call if PRESENT.
  4. RESULT USE: Did the response use the tool's output (per "Expected use of result")?
     PASS / FAIL — quote the relevant span.

Final verdict:
  - PASS if SELECTION + ARG SHAPE + RESULT USE all PASS and ANTI-PICK absent.
  - FAIL otherwise.
```

## Cadence

**Not on every commit.** Per the existing discipline in `SCENARIOS.md`:

> They're not re-run on every commit (would cost API credits each time); they're a point-in-time validation that the skill works on a real scenario.

Recommended cadence:

| Trigger | What runs | Why |
|---|---|---|
| **Pre-release manual** | Full 47 evals against the candidate sumo-qa version + a pinned host LLM (e.g. Claude Sonnet 4.6) | Catch a regression in skill or tool descriptions before users do. |
| **Touched skill / tool description** | Just the affected scenarios (subset by skill name or tool name) | Cheap incremental signal on a PR that edits SKILL.md or `server.py` tool descriptions. |
| **Quarterly drift-check** | Full 47 evals against the *latest* host LLM version, even if sumo-qa hasn't changed | Catch host-LLM-side drift (a model upgrade that changes how tools get picked). |
| **On scenario-spec change** | Just the changed scenario | Sanity-check the new spec is judge-able before adding it to the suite. |

`pytest` is **not** the right runner. Pytest is for code-level correctness (what the 431 unit tests in `tests/` already cover); these evals are for skill-level discipline and are deliberately decoupled — they don't gate merges, they audit drift.

## Costs (rough order of magnitude)

Per eval: one host-LLM run (~5k–20k input tokens for the SKILL.md context + scenario prompt + a few tool calls, ~2k–5k output tokens) + one judge-LLM run (~3k–8k input tokens for the rubric + candidate response, ~500 output tokens). At ~2 turns per scenario on average and Claude Sonnet 4.6 pricing (~$3 / 1M input, ~$15 / 1M output as of the cutoff of this design doc — verify current pricing at run time), one full pass is in the **single-digit dollars** range. Manageable for pre-release + quarterly cadence; not justifiable on every commit.

## Adding a scenario

1. Decide which file the scenario belongs in:
   - Skill behaviour → append to `SCENARIOS.md` under a new numbered heading, matching the existing structure (User prompt → Skill activated → Expected interaction shape → Anti-patterns).
   - Tool selection (atomic tool, novel intent) → append to `TOOL-SELECTION.md` under a new `TS-N` heading.
2. **Behaviour scenarios** must include all of: User prompt, Skill activated, Expected interaction shape (numbered list of disciplines that should fire), Anti-patterns (bullet list of failure modes).
3. **Tool-selection scenarios** must include all of: User prompt, Expected tool (with arg shape), Expected use of result (one sentence on what the LLM should do with the output), Anti-pick (which tool a less-disciplined LLM might wrongly pick).
4. Optional but encouraged: a worked example under `worked-examples/` showing what a "good" first-turn response looks like, so the rubric has a concrete reference.

## Open design questions

| Question | Current default | Reason it matters |
|---|---|---|
| Which judge LLM? | Same family as the candidate, but pinned to a specific version (e.g. judge = Claude Opus 4.7, candidate = Claude Sonnet 4.6) | Mixing families introduces cross-family-bias; pinning prevents judge drift between runs. |
| How many trials per scenario? | 3 (median verdict wins) | Single-trial verdicts are noisy on borderline cases; 3 is the cheapest stable median. |
| What counts as a "regression"? | A scenario that PASSED last release and now FAILS — pinned by SHA + judge + candidate version | Drift happens both in sumo-qa and in the host LLM; the pinned 3-tuple makes the cause attributable. |
| How do we treat partial failures? | Block release if any HARD-GATE-class scenario fails; non-blocking warning otherwise | HARD-GATE scenarios (e.g. `sumo-qa-reviewing-before-merge` declaring SAFE without fresh evidence) are higher-stakes than discipline-style failures; the rubric should mark which is which. |

## Out of scope (for this design doc)

- The runnable harness — picking promptfoo vs Inspect vs Workbench vs custom script. Defer to the `using-sumo-qa` discovery discipline at implementation time.
- LLM-as-judge prompt fine-tuning. The rubric templates above are the v1; tighten on observed disagreement between judge and human review.
- Scoring numerics (e.g. "85% pass rate"). All-or-nothing per scenario is the v1; weighted scoring is a v2 if it ever matters.
- Continuous LLM-eval CI integration. The cadence section explicitly says these don't gate merges; that's the v1 stance and worth preserving until there's evidence it should change.
