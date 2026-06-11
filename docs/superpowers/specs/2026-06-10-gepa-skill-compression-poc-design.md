# GEPA Skill-Compression POC — Design

**Date:** 2026-06-10
**Status:** Draft — awaiting user review
**Scope:** Single-skill proof of concept. Local-only spike; nothing in this POC ships in the public repo.

## Goal

Show whether GEPA (reflective prompt evolution, `pip install gepa`) can compress
`skills/sumo-qa-reviewing-before-merge/SKILL.md` — currently **67,050 bytes (~17k tokens)**,
4–7× every other skill — by **≥50%** with **no eval regression**, before deciding whether to
roll the technique out to the rest of the skill library.

## Decisions already made (brainstorm 2026-06-10)

| Question | Decision |
|---|---|
| Optimizer | GEPA over the real promptfoo harness (Approach 1). No native re-implementation of grading. |
| Control arm | None — GEPA only. |
| Success bar | ≥50% token reduction, local cheap-tier parity (incl. `.ab` lift preserved), ONE cloud gpt-5.5 gate (`--repeat 3`) green on the winner. |
| Rubric policy | **Strictify-only, manual gate.** Rubrics are frozen inside the optimisation loop. Rubric-tightening ideas surfacing in reflection traces are logged to `proposals.md` for manual review; never applied automatically. |
| Inner-loop tier | **Reasoning pairing, user-authorised:** gemma4-12b-bounded candidate on the 5070 laptop + sumo-rjudge-20b (gpt-oss:20b) judge on the 4090. Gen/grade **pipelined** across the two hosts (user's pi experiment proved candidate-host and judge-host run concurrently; the run-eval.sh `-j1` rule only forbids stacking two generations on one GPU). |
| Reflection LM | `claude -p` (existing subscription; no API spend). |
| Cloud spend | Zero until the single final gate run on the winner. |

## Runtime projection (smoke run re-measures before anything long runs)

One GEPA rollout = one mutation attempt: reflection (`claude -p` rewrites the ~17k-token
candidate, ~3–5 min — the per-rollout floor on any hardware) + a 3–4-test minibatch eval.
With gen on the laptop and grading pipelined onto the 4090, judge time hides behind
generation, so a rollout projects to **~10–15 min**.

**Staged budget (agreed):**
1. **Smoke** — 2 rollouts (~25–35 min): proves plumbing, validates cross-host pipelining,
   measures REAL per-test latency and re-projects stage 1 before it starts.
2. **Stage 1** — 10 rollouts (**~2 h projected**): enough to read the trajectory (token count
   falling while minibatch scores hold?).
3. **Trajectory report to the user** → extension toward the 50% bar happens only on their
   explicit say-so, resuming from checkpoints (no redone work).

All projections are estimates calibrated ±2×; the smoke run's measured numbers are the ones
that count. This is a one-off cost for this skill to answer "does GEPA help", not a
recurring cycle.

## Architecture

Spike directory: `.sumo-qa/gepa-poc/`. Note `.sumo-qa/` is currently untracked but NOT
gitignored (only `repo-map.json` under it is), so POC setup adds a `.sumo-qa/gepa-poc/` line
to `.gitignore` — the spike must be impossible to commit by accident. Python venv local to the spike. Spike rigor: build-first, validated by
a real run — no TDD, no mocks, no daemons.

### Components

1. **Scratch repo copy** (`.sumo-qa/gepa-poc/scratch/`)
   Temp mirror of `skills/sumo-qa-reviewing-before-merge/` + `tests/evals/promptfoo/`
   (+ anything the YAMLs reference relatively, e.g. `fixtures/`, `providers/`), preserving
   relative layout so `skill_content: file://../../../skills/.../SKILL.md` resolves. Each
   evaluation writes the candidate text over the scratch SKILL.md. The primary checkout is
   never touched.

2. **`PromptfooAdapter(GEPAAdapter)`** (`adapter.py`)
   - `evaluate(candidates, batch)`: write candidate → invoke the real harness on the
     minibatch's YAML files — local cheap tier, `SUMO_EVAL_REPEAT=1` inside the loop,
     `--output json` — → parse per-test pass/fail + the judge's textual critique.
   - `make_reflective_dataset()`: returns the judge critiques + failing assertion text as
     GEPA's Actionable Side Information.
   - Reuses `run-eval.sh` env conventions (`SUMO_EVAL_BACKEND=local TIER=cheap`); does not
     fork its routing logic.

3. **Score function** (`scoring.py`)
   `score = pass_rate − λ · max(0, tokens/seed_tokens − 0.5)` with λ = 0.5 initially
   (quality dominant; explicit pressure toward the 50% target; no reward for shrinking
   below 50%).
   **Hard floor (score = 0):** any `.ab` control losing its A1-PASS, or output losing the
   required verdict shape. `.ab` controls are constraints + validation only — never training
   examples.

4. **Trainset** — individual test cases extracted from the ~13 non-`.ab`
   `skill-reviewing-before-merge*.yaml` files. Minibatch 3–4 per rollout; GEPA's native
   Pareto validation over the fuller set at its own cadence.

5. **Reflection LM** — `claude -p`, wrapped as a callable. The rewrite prompt is NOT
   hand-rolled: it embeds the `superpowers:writing-skills` authoring guidance
   (`~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/writing-skills/SKILL.md`,
   655 lines, plus its `anthropic-best-practices.md`) as the authoring standard every mutation
   must conform to — per the standing rule that SKILL.md is never hand-authored. On top of
   that standard, the compression bias: *preserve every behavioural rule, trigger, and named
   check; cut redundancy, merged dogfooding patches, and prose.* Judge critiques from the
   minibatch are appended as the failure evidence to react to.

6. **Rubric proposals log** (`proposals.md`) — appended whenever reflection output suggests a
   rubric tightening. Manual strictify-only review by the user after the run.

7. **Checkpointing** — GEPA's run dir under `.sumo-qa/gepa-poc/runs/<timestamp>/`; resumable
   after interruption. Budget via `max_metric_calls` (default ≈ 40 rollouts).

### Error handling

- promptfoo/OWUI infrastructure failure ≠ bad candidate: retry once, then **checkpoint and
  halt**. Never zero-score a candidate on infra noise.
- Malformed candidate (e.g. reflection emitted non-markdown garbage): hard floor applies —
  that IS signal, not noise.
- `claude -p` failure: retry once, then halt (reflection is load-bearing).

### Data flow per rollout

```
GEPA proposes candidate SKILL.md (reflection over prior critiques, via claude -p)
  → adapter writes candidate into scratch checkout
  → promptfoo eval (local cheap tier, minibatch YAMLs, -j1, repeat 1, --output json)
  → parse: per-test pass/fail + judge critique
  → score (pass_rate − token penalty; .ab/shape hard floor)
  → score + critiques back to GEPA → Pareto selection → next rollout
```

## Verification plan (the POC verdict)

1. **Plumbing smoke**: budget=2 run end-to-end; confirm scores parse, checkpoints write,
   scratch isolation holds (primary checkout untouched — `git status` clean).
2. **Baseline capture**: full local cheap-tier reviewing-before-merge suite on the CURRENT
   SKILL.md → recorded pass rates (this is the comparison anchor; `--repeat 3`).
3. **POC run**: ~40 rollouts, unattended.
4. **Winner validation**: full local cheap-tier suite on the best candidate (`--repeat 3`) —
   must be ≥ baseline, `.ab` lift preserved.
5. **Cloud gate, once**: `bash run-eval.sh` cloud on the reviewing-before-merge files with the
   winner in place (`--repeat 3`, gpt-5.5 judge) — the merge-authoritative check.
6. **Report**: before/after token counts, pass-rate table, rubric proposals, verdict
   (win / partial / no-help) → `.sumo-qa/gepa-poc/report.md` (local-only).

**Success:** ≥50% smaller AND step 4 parity AND step 5 green.
**Partial (still useful):** 33–50% smaller with parity — documented; fallback lever below.
**Failure:** <33% or any regression — POC says GEPA doesn't earn rollout; report says why.

## Risks & fallbacks

- **GEPA plateaus below 50%** (papers report ~33% average shortening): documented fallback is
  the structural split (move accumulated dogfooding rule-lists into the existing
  `sumo_qa_load_*` load-on-demand catalogue pattern), as a separate follow-up — explicitly out
  of POC scope.
- **Cheap-judge noise misleads evolution**: mitigated by `.ab` hard floors (binary on stark
  controls is trustworthy), Pareto validation over a larger set, and the final cloud gate.
  Known: a green local run is a *relative* signal, not the merge gate.
- **Winner overfits the eval suite**: the cloud gate plus a manual read-through of the winner
  before any adoption; adoption itself (replacing the shipped SKILL.md) is a normal PR with
  the standard review flow, outside this POC.

## Non-goals

- No rollout to other skills (that's the decision this POC informs).
- No changes to rubrics, eval YAMLs, run-eval.sh, or skill architecture.
- No committed artifacts: everything lives under `.sumo-qa/gepa-poc/` and gitignored docs.
