# sumo-qa LLM eval harness

Runs the 25 scenarios designed in [`tests/scenarios/SCENARIOS.md`](../scenarios/SCENARIOS.md) (15 skill-behaviour) and [`tests/scenarios/TOOL-SELECTION.md`](../scenarios/TOOL-SELECTION.md) (10 atomic-tool selection) through an **adversarial judge** powered by `codex exec` — different model family from the candidate (which runs in Claude Code), so the judge doesn't share Claude's blind spots.

The judge's framing is borrowed from [`/codex:adversarial-review`](https://github.com/openai/codex): *"position it as a challenge review that questions the chosen implementation, design choices, tradeoffs, and assumptions"*. The verdict is constrained to a JSON schema so verdicts are machine-grep-able, not prose.

## What this is, and isn't

- **Is:** a local-only loop that grades sumo-qa-driven Claude Code responses against the discipline beats declared in the scenario specs. Per-scenario invocation. Codex CLI auth (`~/.codex/auth.json`) covers the judge; no third-party API keys.
- **Isn't:** a CI gate. The Codex auth is local; CI would need separate credentials. Not a pytest replacement either — pytest stays for code-level correctness; this is for skill/tool-level discipline.

## Invocation

### From a Claude Code conversation (the normal path)

Ask the orchestrator something like:

> *"Run eval SCN-10."*
> *"Run all skill-behaviour evals and report failures."*

The orchestrator (i.e. Claude Code with sumo-qa loaded) will:

1. Dispatch a **fresh** Claude Code subagent via the `Agent` tool with sumo-qa MCP available. The subagent role-plays the scenario: it sees the user prompt verbatim and produces its first-turn response as if a real user had asked.
2. Capture the subagent's response to `/tmp/<scenario_id>-candidate.md`.
3. Run `python tests/evals/run_eval.py --scenario <id> --candidate /tmp/<id>-candidate.md`.
4. Surface the one-line verdict + a pointer to the artifact dir.

### Manual invocation (if you already have a candidate.md from elsewhere)

```bash
python tests/evals/run_eval.py --scenario SCN-10 --candidate /tmp/scn-10-candidate.md
```

### Candidate file format

The judge needs to see **both** what tools the agent invoked AND the user-facing prose. The candidate.md must have two h2 sections:

```markdown
## Tool calls

- `mcp__sumo-qa__sumo_qa_load_classifications()` → <ok | one-line excerpt>
- `mcp__sumo-qa__using_sumo_qa()` → <ok>

## Response

<the user-facing prose, verbatim — formatted as it would appear in chat>
```

Without the `## Tool calls` section, `SELECTION` and `ARG SHAPE` checks on tool-selection evals will FAIL — the judge has no evidence of trajectory, only narrative. Skill-behaviour evals that name expected tool calls (e.g. *"calls `sumo_qa_load_principles()`"*) will also FAIL the relevant shape check.

Output:

```
SCN-10: FAIL | worst_item='shape_5: offers lightweight render verification follow-up' | artifacts=/Users/.../tests/evals/runs/2026-05-15T17-58-31Z
```

Exit code `0` on PASS, `1` on FAIL.

## Artifact layout

Each run drops two files under `tests/evals/runs/<UTC-timestamp>/`:

```
tests/evals/runs/2026-05-15T17-58-31Z/
├── SCN-10.candidate.md      # The agent's first-turn response (verbatim)
└── SCN-10.verdict.json      # Codex's structured verdict
```

The `runs/` directory is gitignored beyond `.gitkeep` — artifacts stay local. Promote interesting ones to `tests/scenarios/worked-examples/` if you want them as point-in-time references.

The verdict JSON conforms to [`schemas/verdict.schema.json`](schemas/verdict.schema.json):

```json
{
  "verdict": "PASS" | "FAIL",
  "items": [
    {"check": "shape_1: classifies as docs_change", "pass": true, "evidence": "<quoted span>"}
  ],
  "overall_evidence": "<one-paragraph justification>",
  "worst_item": "<check string of the most damning failure>"
}
```

## Costs

Per scenario:

| Phase | Tokens | Notes |
|---|---|---|
| Candidate dispatch | ~15–25K | Claude Code subagent reads the scenario + sumo-qa SKILL.md + produces response. Covered by your Claude Code subscription. |
| Judge | ~15–25K | `codex exec` reads rubric + scenario spec + candidate response + returns JSON verdict. Covered by Codex CLI auth. |

The smoke run for SCN-10 used 17.5K tokens on the judge step (verified). At current Codex pricing, a full 25-scenario sweep is in the **single-digit dollars** range — manageable for ad-hoc invocation. **Not justified on every commit.** Recommended cadence per [`tests/scenarios/LLM-EVALS.md`](../scenarios/LLM-EVALS.md): pre-release manual / on-touched-skill / quarterly drift-check.

## How to add a scenario

1. Drop a new spec into [`tests/scenarios/SCENARIOS.md`](../scenarios/SCENARIOS.md) (for a skill scenario) or [`tests/scenarios/TOOL-SELECTION.md`](../scenarios/TOOL-SELECTION.md) (for an atomic-tool scenario). Spec authority lives there — these are the human-reviewable docs.
2. Add the extraction under [`scenarios/`](scenarios/) with the YAML frontmatter format:

   **Skill scenario (`scenarios/SCN-XX.md`):**
   ```yaml
   ---
   id: SCN-XX
   scenario_type: skill
   expected_skill: sumo-qa-<name>
   anti_patterns:
     - <one-line bullet>
   ---
   ```

   **Tool scenario (`scenarios/TS-XX.md`):**
   ```yaml
   ---
   id: TS-XX
   scenario_type: tool
   expected_tool: sumo_qa_<name>
   expected_arg_shape: <one-line, e.g. "no args" or "classification=str">
   anti_picks:
     - <one-line bullet>
   ---
   ```

3. The body has `## User prompt`, `## Expected interaction shape` (skill) or `## Expected use of result` (tool), and `## Anti-patterns` (skill) or `## Anti-pick` (tool) sections. The runner reads these h2 sections by heading; don't rename them.
4. Run `python tests/evals/run_eval.py --scenario <id> --candidate <path>` to verify the runner picks it up.

## Why Codex as the judge

Same-family judges (Claude grading Claude) share blind spots and bias toward agreement — exactly the sycophancy drift this harness exists to catch. Codex's adversarial-review framing ([`~/.claude/plugins/marketplaces/openai-codex/plugins/codex/commands/adversarial-review.md`](../../README.md)) is *purpose-built* to question assumptions rather than validate output. The rubric templates in [`rubrics/`](rubrics/) borrow that framing and apply it to per-scenario grading.

The judge's `pass=true` decisions are backed by **quoted spans** from the candidate response — not impressions. The schema enforces this; a verdict with empty `evidence` strings would fail to parse.

## Files

| Path | Purpose |
|---|---|
| `rubrics/skill-behaviour.md` | Adversarial judge template for skill scenarios |
| `rubrics/tool-selection.md` | Adversarial judge template for tool-selection scenarios |
| `schemas/verdict.schema.json` | Verdict structure enforced via `codex exec --output-schema` |
| `scenarios/SCN-XX.md`, `TS-XX.md` | Per-scenario specs with YAML frontmatter |
| `run_eval.py` | Glue: parse scenario, render rubric, invoke Codex, write artifacts |
| `runs/<timestamp>/` | Per-run artifacts (candidate + verdict). Gitignored. |
