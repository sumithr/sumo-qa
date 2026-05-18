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
- Full sweep of 14 skills: ~$0.10 per run with `seed: 42` determinism

Running a single skill: pennies. Running all 14 skills with `--repeat 5`:
~$0.30 — still negligible, but worth tracking if you iterate frequently.

If cost becomes a concern, swap the judge to `gpt-4o-mini` in
`defaultTest.options.provider.id` (~5x cheaper, marginally less
adversarial).

## Architecture

All 14 skill YAMLs use `seed: 42` + `temperature: 0.0` for both candidate and judge providers, so runs are reproducible across machines. `disableVarExpansion: true` is set in defaultTest.options to prevent array vars (anti_patterns) from being expanded into per-element tests.

Two patterns are used depending on the skill's shape:

### Pattern A — inline-context skills (e.g. `sumo-qa-implementing-with-tdd`)

For skills where each scenario has a per-scenario ground-truth context
(synthetic code / diff / sibling test), a single YAML file holds everything:

1. `skill_content: file://...` in `defaultTest.vars`
2. ONE seed test inline (with `vars.ground_truth_context`)
3. Skill-level rubric in `defaultTest.vars` (`expected_shape`, `anti_patterns`, `technique_tag`)
4. Decision-table rubric prompt in `defaultTest.options.rubricPrompt`
5. Candidate wrapper prompt in `prompts:`

`promptfoo generate dataset --write` against this YAML synthesises additional
`(user_prompt, ground_truth_context)` pairs on demand.

See [`skill-implementing-with-tdd.yaml`](skill-implementing-with-tdd.yaml).

### Pattern B — catalogue-grounded skills (e.g. `sumo-qa-answering-testing-question`)

For skills where the "context" is the loaded catalogue (universal across
scenarios, not per-scenario synthetic), three files plus a post-processor:

1. **`skill-<name>.yaml`** — main eval config. Loads full catalogues via
   `file://../../../knowledge/principles.md` + `techniques.md` in
   `defaultTest.vars`. References generated tests via `tests: file://...generated-tests.yaml`.
2. **`skill-<name>.gen.yaml`** — generator-only seed. Exposes ONLY
   `user_prompt` to the generator (no `skill_content`, no catalogues, no
   rubric authority). Prevents the generator from fabricating non-catalogue
   content. Updated by `promptfoo generate dataset --write`.
3. **`extract_tests.py`** — post-processor that reads `gen.yaml`'s tests,
   strips all vars except `user_prompt`, and writes a bare TestCase array
   to `skill-<name>.generated-tests.yaml`. Hard-enforces the no-override
   invariant (the soft prompt instruction isn't enough — the LLM may ignore it).
4. **`skill-<name>.generated-tests.yaml`** — bare TestCase array consumed
   by the main eval config via `file://`. Regenerated by `extract_tests.py`.

See [`skill-answering-testing-question.yaml`](skill-answering-testing-question.yaml)
+ `.gen.yaml` + `.generated-tests.yaml` as the worked example.

### Pattern B workflow

```bash
source ~/.config/promptfoo-keys.env

# 1. Generate user_prompt variations into gen.yaml
./node_modules/.bin/promptfoo generate dataset \
    -c tests/evals/promptfoo/skill-<name>.gen.yaml \
    --provider openai:chat:gpt-4o-mini \
    --instructions "<see the v8-codex-approved instruction block in the .gen.yaml file's header comment>" \
    --numPersonas 2 --numTestCasesPerPersona 2 \
    --write

# 2. Extract clean user_prompt-only tests
python3 tests/evals/promptfoo/extract_tests.py \
    tests/evals/promptfoo/skill-<name>.gen.yaml \
    tests/evals/promptfoo/skill-<name>.generated-tests.yaml

# 3. Run the eval
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-<name>.yaml --no-cache
```

The generator instruction is the most-fiddly piece — it determines whether
the synthesised tests stay in-scope or drift into out-of-scope topics that
route to other skills. The per-skill `.gen.yaml` header comment carries the
codex-reviewed instruction text for that skill.

You maintain ~13 files (one per skill, pattern A) OR ~3 files per skill
(pattern B), not hundreds of hand-authored test cases.

## What's in this directory

| File | Purpose |
|---|---|
| `skill-<name>.yaml` (×14) | One config per skill, all covered |
| `skill-answering-testing-question.gen.yaml` | Pattern B generator-only seed |
| `skill-answering-testing-question.generated-tests.yaml` | Pattern B bare-list tests (regenerated) |
| `extract_tests.py` | Pattern B post-processor |
| `aggregate.py` | Variance aggregator for multi-sample runs |
| `README.md` | This file |

## What's intentionally NOT here

- **A CI workflow** — see "NOT in CI" above. Manual cadence only.
- **Stored candidate/judge outputs** — promptfoo writes to a local
  `.promptfoo/` cache and `runs/*` artifacts that are all gitignored.
  Promote interesting failure cases to `docs/qa/runs/` (also gitignored)
  if you want them as point-in-time references.
- **Per-skill hand-authored second/third scenarios** — the architecture
  is generative-from-a-seed deliberately, to avoid maintaining hundreds
  of inputs/outputs.

## A/B value-measurement (experimental)

This measures skill value as `pass_rate(B) - pass_rate(A1)`. A0 is the raw Claude baseline with no catalogues and no skill. A1 adds catalogues only. B adds the full SKILL.md. The gap between B and A1 shows what the skill's decision logic contributes beyond raw knowledge. Run it with `./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-deciding-approach.ab.yaml --no-cache`. Scope is prototype on deciding-approach only, not rolled across the estate.
