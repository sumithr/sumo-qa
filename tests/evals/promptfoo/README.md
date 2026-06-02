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

## Adversarial discovery corpus (review-recall, issue #236)

Most skill evals (including `skill-reviewing-before-merge.yaml`) hand the
candidate the named risks in prior-turn context and grade the final **verdict
shape**. `skill-reviewing-before-merge-adversarial.yaml` measures something
different: **independent discovery from a raw diff**. Each scenario supplies
only a raw diff plus a green-but-non-covering test run — no pre-named risks —
seeded from real resolved Codex Review findings on closed PRs (generated-artifact
drift, stale/deleted-file handling, weak assertions, rollback data-loss, partial
CI gates, cwd/path-root bypass, schema-contract weakening, protocol/timeout
cleanup, platform-install mismatch). The candidate must name the concrete defect
class, anchor it to the changed file:line, and reach the correct unsafe/needs-work
verdict. Two docs-only / config-only **negative controls** verify the workflow
does not invent runtime risk on trivial diffs.

**Candidate is `gpt-5-mini`, not the estate's `gpt-4o-mini`.** A discovery eval
needs a candidate that can reason over a raw diff; `gpt-4o-mini` proved too noisy
to measure it (its full-corpus baseline-vs-postcut *inverted* between runs).
`gpt-5-mini` is a cheap reasoning model that gives a stable signal. The two YAMLs
pin `gpt-5-mini` for the candidate (the judge stays `gpt-5.5`).

```bash
source ~/.config/promptfoo-keys.env
# discovery corpus (B = full skill)
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-adversarial.yaml --no-cache
# discovery LIFT: A0 (no skill) vs A1 (catalogues only) vs B (full skill)
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-adversarial.ab.yaml --no-cache
```

This is a **high-bar stress test, not a 100%-green gate.** Adding the skill's
adversarial discovery pass lifts the full corpus from baseline 7/11 → postcut
10/11 (occasionally 11/11), and the `.ab` to **B 6/6** vs A0/A1 (no-skill /
catalogues-only) only ~1-4/6 (the discovery pass perfect-scores the hard
families A0/A1 miss). Both negative controls pass. One *hard* seed flickers
run-to-run on reasoning-model variance — the niche `git ls-files`
deleted-entry-semantics case the candidate doesn't always surface. (A separate
flicker — the candidate echoing a loaded change-rule key into its verdict — was
a real output-discipline leak and is fixed by tightening the SKILL.md
output-discipline, not by loosening the rubric.) Read the **delta** (baseline →
postcut, B over A0) and the negative-control passes as the signal — never chase
a fixed number by loosening the rubric or trivialising seeds.

## Repo-pinned tool-setup corpus (issue #216)

`skill-using-sumo-qa-tool-setup.yaml` measures a different `using-sumo-qa`
behaviour from the router-handoff eval (`skill-using-sumo-qa.yaml`): once a
test tool is chosen, does the agent set it up **repo-pinned** (manifest /
lockfile / pinned-`rev` pre-commit hook) **and CI-reproducible** (a CI step
runs that same pinned tool), and does it **refuse machine-level / global
installs** (`brew`, `npm -g`, system `pip`)? The seed hands the candidate a
chosen tool plus an external handoff whose only install commands are global
(`brew install bats-core` / `npm install --global bats`); a passing response
translates that to the repo-pinned equivalent and wires the CI mirror rather
than running the global form. Standard Pattern A (inline per-scenario
context), estate candidate `gpt-4o-mini`, judge `gpt-5.5`. Picked up by
`npm run eval:all` automatically.

## UNPROVEN-escalation corpus (issue #187)

`skill-reviewing-before-merge-unproven-escalation.yaml` grades a different
move: when a named risk is **UNPROVEN** (the changed path is exercised by a
green test, but no assertion hits the failure mode), the skill must NOT demote
it to a "residual precision trade-off" and ship SAFE. It must (1) name the
technique's catalogued failure mode (`techniques.md` now carries a
`failure_modes` note per black-box technique — equivalence-partitioning
substring/token confusion, both-sides boundary, missing rule row), (2)
**prescribe a concrete discriminating input** — one value that PASSES the
broken impl AND FAILS a correct impl (e.g. `unlocked` against a `locked`
substring matcher; exactly `1000` rows against a `< 1000` limit) required in
the test gate before SAFE — and (3) deliver NOT SAFE TO MERGE. Two seeds cover
the equivalence-partitioning substring case and the boundary-value case;
candidate is `gpt-5-mini`, judge `gpt-5.5`. This is the catch that scales when
the adversarial codex pass isn't available (CI-only runs, limited codex tokens).

```bash
source ~/.config/promptfoo-keys.env
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-unproven-escalation.yaml --no-cache
```

**Load-bearing control (`.ab.yaml`).** `skill-reviewing-before-merge-unproven-escalation.ab.yaml`
runs the SAME two seeds against the PRE-EDIT (origin/main) SKILL.md body (A0)
and the post-#187 body (A1). The pre-edit body already marks the risk UNPROVEN
and reaches NOT SAFE, but it lacks the step-6 technique-keyed failure-mode hints
and the 2b prescribed-input requirement, so it does NOT prescribe a concrete
discriminating input — a SHAPE FAIL under the rubric. A0 (old body) FAILs, A1
(new body) PASSes; that lift isolates the #187 behaviour. The A0 body is
snapshotted at `fixtures/reviewing-before-merge-PRE-187.SKILL.md` — refresh it
if the baseline moves.

```bash
source ~/.config/promptfoo-keys.env
# A0 (pre-187 body) FAIL vs A1 (post-187 body) PASS
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-unproven-escalation.ab.yaml --no-cache
```

## Vacuous-test corpus (issue #255)

`skill-reviewing-before-merge-vacuous-test.yaml` grades the **test_change**
move: when the diff is test files only (no runtime file), there is no runtime
anchor for the coverage-ledger, so the central risk is whether each new/changed
test can actually FAIL. The skill must run a test-quality probe — reusing the
tautology / setup-discriminator / expected-value-derivation framing from
`sumo-qa-implementing-with-tdd` step 3 by cross-reference — and NOT rubber-stamp
a green suite. Two seeds: a tautological diff (a `expected` value read from the
same call under test, plus a type-only check) that must yield NEEDS WORK / NOT
SAFE naming the vacuous assertion; and a genuine-discriminator diff (a derived
leap-year expected value with captured RED-on-pre-fix evidence) that must yield
SAFE. Candidate is `gpt-5-mini` (the probe is reasoning-heavy — detect a
self-referential assertion, derive a date), judge `gpt-5.5`. No `.ab.yaml`
ships for this seed; to isolate the #255 probe behaviour by hand, run the eval
once on this branch (tautology seed PASS), then check the SKILL.md back to its
pre-probe state — `git checkout origin/main -- skills/sumo-qa-reviewing-before-merge/SKILL.md`
— and re-run; the tautology seed flips to FAIL, confirming the verdict comes
from the added probe rather than the corpus. Restore with
`git checkout HEAD -- skills/sumo-qa-reviewing-before-merge/SKILL.md`.

```bash
source ~/.config/promptfoo-keys.env
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-vacuous-test.yaml --no-cache
```

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
- The `reviewing-before-merge-adversarial` corpus pins a `gpt-5-mini` candidate
  (reasoning tokens → a few cents per full run, still negligible) — see
  "Adversarial discovery corpus" above for why.

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
| `skill-reviewing-before-merge-adversarial.yaml` + `.ab.yaml` | Issue #236 discovery corpus + A0/A1/B lift (see "Adversarial discovery corpus" above) |
| `skill-reviewing-before-merge-unproven-escalation.yaml` + `.ab.yaml` | Issue #187 UNPROVEN-escalation corpus + A0(pre-edit)/A1(post-edit) load-bearing control (see "UNPROVEN-escalation corpus" above) |
| `fixtures/reviewing-before-merge-PRE-187.SKILL.md` | Snapshot of the pre-#187 SKILL.md body, the A0 control leg for the unproven-escalation `.ab.yaml` |
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

This measures skill value as `pass_rate(B) - pass_rate(A1)`. A0 is the raw Claude baseline with no catalogues and no skill. A1 adds catalogues only. B adds the full SKILL.md. The gap between B and A1 shows what the skill's decision logic contributes beyond raw knowledge. Run it with `./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-deciding-approach.ab.yaml --no-cache`. `.ab.yaml` files exist for `deciding-approach`, `reviewing-before-merge`, and the `reviewing-before-merge-adversarial` discovery corpus (issue #236, see above); it is not rolled across the whole estate.
