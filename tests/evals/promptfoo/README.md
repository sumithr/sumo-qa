# Promptfoo skill-eval harness

Declarative eval harness for measuring whether sumo-qa skills, when read by an
LLM, produce the correct shape of senior-QA response. Runs from the CLI; no
LLM-in-the-loop for orchestration.

## What this measures

For each skill (currently: `sumo-qa-implementing-with-tdd`; others land in
follow-up PRs):

- **SHAPE** — does the candidate response produce the concrete artefact the
  skill demands (e.g. a failing test, an assertion, a file path), not hedged
  narration?
- **GROUNDING** — does the response visibly use the supplied ground-truth
  context (synthetic file contents / diff / sibling test) rather than
  hallucinating?
- **ANTI-PATTERNS** — for each named anti-pattern in the rubric, is it
  ABSENT (PASS) or PRESENT (FAIL)?

The judge (`gpt-5.5`) applies a decision-table: only `SHAPE PASS + GROUNDING
PASS + all anti-patterns ABSENT` → PASS. Verdict is JSON, reason quotes
the candidate span the judge graded against.

## NOT in CI

**These evals do not run on the CI pipeline.** Every run hits the OpenAI API
for both candidate and judge calls — running them on every push or PR would
bill the maintainer for noise. Run manually at the cadences below.

There is no GitHub Actions workflow that invokes `promptfoo` and we should
not add one. If a future automation is wanted (nightly drift check, etc.),
it belongs on a separate scheduled runner with explicit billing approval.

## When to run

| Trigger | What to run | Why |
|---|---|---|
| You edited a SKILL.md | The single `skill-<name>.yaml` for that skill | Catch shape regressions immediately |
| Pre-release | All `skill-*.yaml` | Catch drift across the estate |
| Quarterly | Full sweep + `aggregate.py` variance report | Drift baseline |
| You're iterating on a rubric | Single skill with `--no-cache` | Tight feedback loop |

## How to run

### One-time setup

**Node 20.20+ or 22.22+** is required (`promptfoo` ships ESM). If you use nvm:
`nvm use 24` (or any supported version).

Install promptfoo as a local dev dependency (pinned in `package.json`):

```bash
npm install
```

Store your OpenAI API key in a non-tracked file (the harness reads
`OPENAI_API_KEY` from env; do not put the literal key in any repo file):

```bash
mkdir -p ~/.config
cat > ~/.config/promptfoo-keys.env <<'EOF'
export OPENAI_API_KEY='sk-proj-...'
EOF
chmod 600 ~/.config/promptfoo-keys.env
```

### Common commands (via npm scripts)

```bash
source ~/.config/promptfoo-keys.env
npm run eval              # run TDD skill eval (uses --no-cache)
npm run eval:generate     # synthesise more tests from the seed (--write merges into the YAML)
npm run eval:view         # open the local results UI
npm run eval:all          # run all skill-*.yaml configs sequentially
```

### Direct binary invocation (for flags not in the scripts)

The local binary is at `./node_modules/.bin/promptfoo` after `npm install`.

```bash
source ~/.config/promptfoo-keys.env

# Multi-sample variance check (each test runs 5 times):
./node_modules/.bin/promptfoo eval \
    -c tests/evals/promptfoo/skill-implementing-with-tdd.yaml \
    --no-cache \
    --repeat 5 \
    --output /tmp/result.json

# Sequential / legible logs:
./node_modules/.bin/promptfoo eval -c <config> -j 1

# Generate dataset with custom instructions:
./node_modules/.bin/promptfoo generate dataset \
    -c tests/evals/promptfoo/skill-implementing-with-tdd.yaml \
    --instructions "Synthesise realistic developer chat messages that should route to this skill. Vary language, framework, bug shape." \
    --numPersonas 2 \
    --numTestCasesPerPersona 2 \
    --write
```

Useful flags:

- `--repeat 5` — multi-sample variance check
- `--no-cache` — bypass the local SQLite cache (use while iterating)
- `--output /tmp/result.json` — structured output for the variance aggregator
- `-j 1` — sequential, for legible logs

### View the results

```bash
npm run eval:view
```

Spins up a local web UI showing per-test pass/fail, judge reasoning,
token costs, and diff-against-previous-run.

### Aggregate variance across N samples

After running with `--repeat 5`, the JSON outputs can be aggregated:

```bash
python tests/evals/promptfoo/aggregate.py /tmp/promptfoo-variance/
```

Reports verdict-flip rate per scenario. Exits 0 if every scenario's
flip-rate ≤ 20% (the stability bar per the design plan).

## Cost guardrails

OpenAI pricing as of 2026-05:

- Candidate (`gpt-4o-mini`): ~$0.001 per scenario
- Judge (`gpt-5.5`): ~$0.005 per scenario
- Full per-skill eval (1 seed + ~4 generated × 5 samples): ~$0.03 per run

Running a single skill: pennies. Running all 13 skills with `--repeat 5`:
~$0.30 — still negligible, but worth tracking if you iterate frequently.

If cost becomes a concern, swap the judge to `gpt-4o-mini` in
`defaultTest.options.provider.id` (~5x cheaper, marginally less
adversarial).

## Architecture

The maintained artefact per skill is ONE YAML file containing:

1. The skill file path (`skill_content: file://...`)
2. ONE seed test (canonical worked example)
3. The skill-level rubric in `defaultTest.vars` (expected_shape,
   anti_patterns, technique_tag) — inherited by seed AND generated tests
4. The decision-table rubric prompt in `defaultTest.options.rubricPrompt`
5. The candidate wrapper prompt in `prompts:`

Promptfoo's `generate dataset` synthesises additional `(user_prompt,
ground_truth_context)` pairs on demand, so the test set grows without
hand-authoring. You maintain ~13 files (one per skill), not hundreds.

See [`skill-implementing-with-tdd.yaml`](skill-implementing-with-tdd.yaml)
as the worked example.

## What's in this directory

| File | Purpose |
|---|---|
| `skill-implementing-with-tdd.yaml` | Worked-example eval config (TDD skill) |
| `aggregate.py` | Variance aggregator for multi-sample runs |
| `README.md` | This file |

Remaining 12 skills follow the same pattern in subsequent PRs.

## What's intentionally NOT here

- **A CI workflow** — see "NOT in CI" above. Manual cadence only.
- **Stored candidate/judge outputs** — promptfoo writes to a local
  `.promptfoo/` cache and `runs/*` artifacts that are all gitignored.
  Promote interesting failure cases to `docs/qa/runs/` (also gitignored)
  if you want them as point-in-time references.
- **Per-skill hand-authored second/third scenarios** — the architecture
  is generative-from-a-seed deliberately, to avoid maintaining hundreds
  of inputs/outputs.
