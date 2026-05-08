# Design: AI-Driven Iteration Loop for sumo-qa

Date: 2026-05-07
Status: Draft for user review

## Goal

Make sumo-qa output indistinguishable from a senior ISTQB-certified QA
engineer working at the level of Tesla / SpaceX engineering quality.
Drive every QA decision via AI prompts grounded in ISTQB principles —
no hardcoded keyword tables. Validate that the output is genuinely
senior-grade by running the MCP against a real production repo
(by-variant-data-feeder) and iterating prompts/standards/grounding
until every scenario passes a strict ISTQB rubric.

## Non-Goals

- No external API calls outside the host LLM the MCP already samples.
- No hardcoded keywords / phrase tables added back. The AI is the brain.
- No automatic source modifications outside `qa-shift-left-mcp/`. The
  by-variant-data-feeder repo is read-only context.

## Success Criteria

1. Every scripted scenario in the suite scores `senior-istqb-grade`
   from BOTH the AI self-eval AND the human reviewer (you) on a final
   read-through.
2. The scenarios span the full specificity spectrum — from
   very-specific ("review this exact diff line 42-67") to very-generic
   ("design a test strategy for this service") — and the rubric is
   met at BOTH ends.
3. Iteration runs at least one full round with **no new scenarios
   added**. Without this, we haven't reached steady state.
4. The output cites ISTQB principles by name/number when they shape
   the recommendation, names specific test design techniques,
   identifies the smallest useful test set, separates facts from
   assumptions, never waives evidence, and never resorts to generic
   advice.
5. No regressions: 175+ unit tests pass, eval suite stays 28/28.
6. The debug mode is reusable — future iterations against any repo
   work the same way.

## Current State (background for the reviewer)

- All phrase tables already removed (Iter 70-71). The AI is grounded by
  `SENIOR_QA_SYSTEM_PROMPT` (ISTQB Foundation 7 principles, ISO/IEC
  25010, test design techniques, senior-QA disciplines) plus per-tool
  prompt builders (`_build_decide_approach_sampling_prompt`, etc.).
- The deterministic harness honours caller-supplied signals
  (`is_bug`, `is_test_only`, `is_strategic_planning`,
  `explicit_classifications`, …) but does NOT pattern-match intent text,
  paths, or extensions.
- 175 tests pass; eval suite 28/28. `sumo-qa-mcp` installed via uv.
- Target test repo:
  `/Users/SumithRamsookbhai/Desktop/repos/apo/apo-configurator/by-variant-data-feeder`
  (Kotlin/Gradle service).

## Architecture

```
Main thread (Claude Code, this conversation)
  │
  ├── plans the initial scenario suite (~10 scenarios spanning
  │   very-specific → very-generic across canonical approaches)
  ├── dispatches scenarios to subagents in parallel (3-5 at a time)
  │
  └── per iteration round:
       │
       ├── reads each subagent's brief verdict
       ├── aggregates named gaps + suggested prompt fixes
       ├── edits sumo-qa source (prompts.py / per-tool builders /
       │   standards packs / SKILL.md as needed)
       ├── adds NEW scenarios when a recurring gap isn't currently
       │   stressed by any scenario (suite grows until steady state)
       ├── reinstalls sumo-qa via `uv tool install --reinstall`
       ├── triggers MCP reload (option C below)
       └── re-dispatches failing + new scenarios

Iteration terminates only when:
  (a) every scenario scores senior-istqb-grade, AND
  (b) the user (human review) confirms the output is Tesla/SpaceX-grade, AND
  (c) at least one full round adds no new scenarios (steady state).

Subagent (one per scenario, runs in parallel)
  │
  ├── reads the latest sumo-qa source files (prompts.py, per-tool
  │   prompt builders, standards packs) — NOT through the MCP server,
  │   so edits take effect immediately, no reload needed
  ├── reads the relevant by-variant-data-feeder files for repo context
  ├── reasons through the prompts AS the host LLM would (subagent IS
  │   an LLM grounded by SENIOR_QA_SYSTEM_PROMPT)
  ├── grades the resulting output against the ISTQB rubric (self-eval)
  └── returns a tight verdict: {scenario_id, verdict, named_gaps[],
       suggested_prompt_fixes[]}

Final verification round (real MCP server)
  │
  ├── user (or main thread) restarts the MCP from Claude Code
  ├── main thread invokes the live MCP tools against a few scenarios
  └── confirms wire-protocol behaviour matches the in-process results
```

## Components

### 1. Scenario suite (`evaluation/repo_scenarios/`)

A python module per scenario family. Each scenario is a dataclass:

```python
@dataclass(frozen=True)
class RepoScenario:
    id: str                    # e.g. "review.bundle_validator_change"
    description: str           # human-readable framing
    tool: str                  # "qa_review_local_change" / "qa_decide_approach" / ...
    args: dict                 # what to pass the tool
    specificity: str           # "very-specific" | "specific" | "moderate" | "generic" | "very-generic"
    rubric_focus: list[str]    # rubric items this scenario stress-tests
    repo_files_to_load: list[str]  # files the subagent should read for context
```

**Specificity range — every iteration round must span this spectrum**:

- **very-specific** — points at one method / one diff / one file with full context.
  Example: "review this exact diff in `BundleVariantValidator.kt` line 42-67".
- **specific** — names a class / module / one user story.
  Example: "scaffold tests for the `BundleVariantValidator` class".
- **moderate** — names a feature area with some constraints.
  Example: "what should I test before changing the variant filtering logic".
- **generic** — broad QA question about a service or domain.
  Example: "how do I test this service" / "where are the gaps in our test coverage".
- **very-generic** — open-ended strategy / pyramid / rollout.
  Example: "design a test strategy for by-variant-data-feeder" /
  "audit our QA across the test pyramid".

The scenarios at the generic end are where keyword tables historically
broke the hardest, and where Tesla/SpaceX-grade output requires real
senior-QA reasoning rather than pattern guessing. Both ends must pass
the rubric for the iteration to terminate.

**Starting size:** ~10 scenarios spread across the specificity spectrum and
across the canonical approaches (tdd-scaffold, regression-first,
coverage-first-then-refactor, strengthen-test-coverage, verify-existing,
no-tests-recommended, spike-first-then-tests, strategy-orchestration).

**Open-ended growth:** the suite is not capped at 10. Whenever a round
exposes a recurring weakness that none of the existing scenarios
specifically stress, I add a new scenario that targets that weakness
and re-run. Iteration terminates only when:

  (a) every scenario in the current suite scores `senior-istqb-grade`
      from the AI self-eval, AND
  (b) the user reads a sample of trace summaries and confirms it is
      genuinely Tesla/SpaceX-grade, AND
  (c) at least one full round passes with NO new scenarios added
      (otherwise we haven't reached steady state — adding another
      stress test would still surface gaps).

**Stretch scenarios** the initial 10 must cover:

- Security-critical change (auth / token / encryption / access boundary).
- Mutation-testing prompt (production code unchanged; kill surviving mutants).
- Test-strategy ask (whole-repo / pyramid / rollout).
- Refactor with hidden behaviour change (behaviour drift the AI must catch).
- Ambiguous "fix the thing" prompt (forces the AI to ask clarifying questions
  rather than guess).
- Pure config tweak that crosses an SLA (verify-existing should NOT apply).
- Pure docs change (no-tests-recommended).
- API contract change with backward-compatibility implications.
- Ambiguous prompt that conflates strategy with single change.
- by-variant-data-feeder-specific change (real domain context).

### 2. Debug-mode capture (in subagent context)

No disk writes during the inner loop. The subagent reads the live
sumo-qa source files, reasons through the prompts as the host LLM
would, and produces the QA output entirely in its own conversation
context. The bulky exchanges (system prompt, per-tool prompt, host
reasoning, tool output, self-eval reasoning) all live in the
subagent's context — only a tight verdict comes back to the main
thread. Token usage in the main thread stays small even across 15+
scenarios.

For the final verification round, the live MCP can additionally write
to `SUMO_QA_DEBUG_DIR` if set — a small, optional addition to
`server.py` that intercepts each tool call and writes input / sampling
exchanges / output to disk. This is for the user's manual review only.

### 3. ISTQB rubric (the grading prompt)

A single rubric used by both the subagent's self-eval and (later) the
human review. Lives at `src/sumo_qa/rubric.py`. Key dimensions:

- **Principle citation:** does the output cite at least one ISTQB
  Foundation principle by name/number when the principle shapes the
  recommendation?
- **Smallest useful test set:** does the output identify the minimum
  tests that would give release confidence — not a generic checklist?
- **Named techniques:** does the output name specific test design
  techniques (boundary value analysis, decision tables, state
  transition, MC-DC, exploratory charters, etc.) tied to actual change
  characteristics?
- **Risk-based focus:** are the top risks specific to THIS change, not
  generic ("missing test data")?
- **Facts vs assumptions:** are unknowns called out explicitly?
- **No waived evidence:** the verdict never softens "needs-test-evidence"
  into "looks fine".
- **Decisive routing:** the recommended approach matches the change
  shape (no forcing TDD on a strategy ask, no forcing strengthen-test
  on a greenfield add, etc.).
- **Specialty awareness:** when the change implies a specialty
  (frontend / contract / performance / security / mobile / a11y / AI),
  the right specialty surfaces.
- **Domain specificity:** the output names the actual domain
  (by-variant-data-feeder = product variant filtering / inventory
  feeding) rather than abstract "the system".
- **No generic advice:** every recommendation is tied to a specific
  risk; no boilerplate.

Each dimension scored binary (met / not met) with a short reason.
Final verdict: `senior-istqb-grade` (all met) /
`needs-iteration` (any unmet) / `unfit-for-merge` (multiple unmet).

### 4. MCP reload strategy (option C — confirmed)

**Inner loop (fast, autonomous): subagents test the PROMPTS directly,
not the wire protocol.** The whole iteration is about AI prompt
quality (system prompt, per-tool grounding, standards packs). The
deterministic plumbing in `tools.py` is already covered by 175 unit
tests; we don't need to re-exercise it on every round.

Each subagent's prompt is structured exactly as the running MCP would
structure things:

1. Read `src/sumo_qa/prompts.py` → use `SENIOR_QA_SYSTEM_PROMPT`
   verbatim as the subagent's standing context.
2. Read the relevant per-tool prompt builder from
   `src/sumo_qa/tools.py` (e.g. `_build_decide_approach_sampling_prompt`)
   and the team's loaded standards from `standards/packs/*.yaml`.
3. Read the scenario inputs (work_item / change_summary / paths /
   classifications) from the scenario spec.
4. Read the relevant by-variant-data-feeder files for context.
5. Produce the output as if responding to the MCP's sampling request.
6. Grade against the ISTQB rubric.
7. Return the structured verdict.

This means edits to `prompts.py` / per-tool builders / standards packs
take effect instantly on the next subagent dispatch — no MCP server
restart needed for the inner loop. The subagents always see the latest
file content because they `Read` the files at the start of each run.

**Final verification (one round, end of iteration):** user restarts
the MCP from Claude Code's MCP panel. Main thread invokes live MCP
tools against a sampled subset of scenarios. Confirms the live-server
results match the in-process results. Catches any wire-protocol or
serialization issues that the inner loop wouldn't surface.

### 5. Iteration orchestration (main thread, no separate module)

I (the main thread) am the orchestrator. No Python module — just:

- The scenario list lives in `evaluation/repo_scenarios.py` (data only).
- Each round I dispatch a batch of scenarios as subagents using the
  `Agent` tool with parallel tool calls (3-5 in flight at a time).
- I aggregate verdicts from the returned messages.
- I write a per-round summary to
  `docs/superpowers/iteration-runs/round-<N>-<timestamp>.md` so you
  can review progress asynchronously without me having to recap.
- I decide next-round actions based on aggregated gaps.

## Data Flow

```
1. Main thread reads scenario list from evaluation/repo_scenarios/
2. Main thread spawns N subagents with the scenario specs and the rubric
3. Each subagent:
   a. Reads the latest `prompts.py`, the relevant per-tool prompt
      builder from `tools.py`, and any relevant standards packs
   b. Reads the relevant by-variant-data-feeder files for repo context
   c. Reasons through the prompts as the host LLM would, producing
      the structured QA output the MCP would return
   d. Grades against the ISTQB rubric (a second inline reasoning pass)
   e. Returns a structured verdict to the main thread
4. Main thread aggregates verdicts:
   - Which dimensions failed across multiple scenarios?
   - Which prompt fixes were suggested most often?
5. Main thread edits sumo-qa source files (prompts.py, per-tool
   builders, standards packs, SKILL.md if needed)
6. Main thread runs `pytest` + `sumo-qa-eval` to confirm no regression
7. Main thread reinstalls sumo-qa via `uv tool install --reinstall`
8. Main thread re-dispatches the failing scenarios
9. Loop until every scenario passes
10. Main thread writes a final iteration summary
11. User restarts the MCP and runs final verification round
```

## Error Handling

- **Subagent fails / timeouts:** main thread treats the scenario as
  `needs-iteration` with a `harness-error` gap; the next round
  re-dispatches.
- **Test regression after a prompt edit:** main thread reverts the
  edit, marks the gap as `requires-different-fix`, picks an alternate
  fix from the agent suggestions.
- **Eval regression (28/28 → less):** treated like a test regression —
  revert and try a different fix.
- **Subagent disagrees with itself across re-runs (flaky verdict):**
  main thread runs the scenario twice; if both rounds agree, accept;
  if they disagree, the scenario stays `needs-iteration` and the
  rubric gets sharpened.
- **Convergence stall** (same gaps surface 3 rounds in a row): main
  thread escalates by reading the failing transcripts in the
  subagent's brief and proposing a structural change (e.g. add a new
  rubric dimension to the system prompt) rather than tweaking
  wording.

## Testing Strategy

- The iteration loop itself is tested by a smoke scenario that uses
  the existing eval YAMLs as a known-good baseline. If the iteration
  loop can grade the existing 28 eval items without regression, the
  loop is wired correctly.
- The `RepoScenario` dataclass and the scenario list have unit tests
  pinning that every canonical approach has at least one scenario.
- The rubric dimensions each have at least one scenario that
  explicitly stresses them (e.g. a strategy ask for the
  decisive-routing dimension; a refactor with hidden behaviour change
  for facts-vs-assumptions; a security-critical change for the
  critical-path-tightening dimension).

## Not Doing

- No persistent state across iteration rounds — each round is
  self-contained from the MCP's perspective.
- No autonomous loop on a timer — the orchestrator runs once per
  invocation; the main thread decides when to re-dispatch.
- No live API calls outside the host LLM the MCP already samples
  (via the subagent's inline reasoning).
- No new MCP tools — the iteration uses the existing tools.

## Open Questions (need user answer before plan)

None — both clarifying questions answered:
- Debug mode lives in subagent context, no disk writes during inner loop.
- Grading uses both AI self-eval AND user judgement (option C).
- MCP reload uses option C: in-process for inner loop, live MCP for
  final verification.
