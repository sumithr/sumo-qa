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

The judge (`claude-opus-5`, `providers/claude-judge.yaml`) applies a decision-table: only `SHAPE PASS + GROUNDING
PASS + all anti-patterns ABSENT` → PASS. Verdict is JSON, reason quotes
the candidate span the judge graded against.

## NOT in CI

**These evals do not run on the CI pipeline.** Every run makes model calls for
both candidate and judge through the Claude Code CLI (`claude -p`), which needs
a signed-in Claude account that a CI runner does not have, and model output
varies run to run, so a per-push verdict would be noise. Run manually at the
cadences below.

There is no GitHub Actions workflow that invokes `promptfoo` and we should
not add one. If a future automation is wanted (nightly drift check, etc.),
it belongs on a separate scheduled runner with its own explicit approval.

These provider-backed evals are the *quality* layer. The deterministic
routing + tool-call + output-marker contract runs with no model in the
ordinary pytest suite (issue #214); see
[`../../scenarios/CONFORMANCE.md`](../../scenarios/CONFORMANCE.md). Keep the two
split: promptfoo judges behaviour and model variance (manual, cost/cadence
above), the conformance validator pins what does not need an LLM. The
per-scenario variance report for this manual layer is
[`aggregate.py`](aggregate.py).

## When to run

| Trigger | What to run | Why |
|---|---|---|
| You edited a SKILL.md | The single `skill-<name>.yaml` for that skill | Catch shape regressions immediately |
| Pre-release | All `skill-*.yaml` | Catch drift across the estate |
| Quarterly | Full sweep + `aggregate.py` variance report | Drift baseline |
| You're iterating on a rubric | Single skill with `--no-cache` | Tight feedback loop |

### Baseline wrapper vs raw `promptfoo eval -c`

For a **repeatable before/after snapshot** (the `baseline` → `postcut` capture around a SKILL.md edit), drive the config through the `regen-eval-baseline` wrapper — `.claude/skills/regen-eval-baseline/scripts/run_baseline.py`. It writes a dated JSON to `docs/qa/runs/eval-baselines/`, prints pass/fail, and diffs against the prior snapshot. It drives **all three committed config shapes**: the base config via `--skill <name>`, a suffixed scenario config via `--config skill-<name>-<suffix>`, and an `.ab.yaml` control via `--config skill-<name>-<suffix>.ab.yaml`. Selection is exact — a base skill never cross-matches a longer suffixed sibling.

Use **raw `./node_modules/.bin/promptfoo eval -c <path>`** (the commands shown below) for one-off runs and for flags the wrapper doesn't expose — `--repeat N` variance, `-j 1` legible logs, `generate dataset`. The raw form does not snapshot; reach for it when you don't need the persisted baseline/postcut delta. See [`regen-eval-baseline/SKILL.md`](../../../.claude/skills/regen-eval-baseline/SKILL.md).

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

**History: the corpus was built on a reasoning candidate.** On the retired OpenAI
pair, a discovery eval needed a candidate that could reason over a raw diff: the
estate's `gpt-4o-mini` proved too noisy to measure it (its full-corpus
baseline-vs-postcut *inverted* between runs), so the two YAMLs pinned `gpt-5-mini`
with the `gpt-5.5` judge. Today both YAMLs run on the Claude pair like every config,
and carry the `# local-tier: reasoning` marker that selects them for the local
reasoning tier.

```bash
# discovery corpus (B = full skill)
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-adversarial.yaml --no-cache
# discovery LIFT: A0 (no skill) vs A1 (catalogues only) vs B (full skill)
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-adversarial.ab.yaml --no-cache
```

This is a **high-bar stress test, not a 100%-green gate.** Historical numbers,
measured on the retired OpenAI pair (`gpt-5-mini` candidate, `gpt-5.5` judge): adding the skill's
adversarial discovery pass lifted the full corpus from baseline 7/11 → postcut
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
context), runs on the Claude pair (originally measured on the retired OpenAI pair as
estate candidate `gpt-4o-mini`, judge `gpt-5.5`). Picked up by
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
runs on the Claude pair (originally measured on the retired OpenAI pair, candidate
`gpt-5-mini`, judge `gpt-5.5`). This is the catch that scales when
the adversarial codex pass isn't available (CI-only runs, limited codex tokens).

```bash
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
SAFE. Runs on the Claude pair; the probe is reasoning-heavy (detect a
self-referential assertion, derive a date), so on the retired OpenAI pair it was
measured with the `gpt-5-mini` candidate and `gpt-5.5` judge. No `.ab.yaml`
ships for this seed; to isolate the #255 probe behaviour by hand, run the eval
once on this branch (tautology seed PASS), then check the SKILL.md back to its
pre-probe state — `git checkout origin/main -- skills/sumo-qa-reviewing-before-merge/SKILL.md`
— and re-run; the tautology seed flips to FAIL, confirming the verdict comes
from the added probe rather than the corpus. Restore with
`git checkout HEAD -- skills/sumo-qa-reviewing-before-merge/SKILL.md`.

```bash
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-vacuous-test.yaml --no-cache
```

## Discriminating-input fence probe (issue #296)

`skill-reviewing-before-merge-fence-parser.yaml` grades the specialisation of
the 2b discipline to a **stateful character-scanning parser** (the #287 dogfood
miss: a review asserted "fence-aware parse verified correct" for a markdown
heading indexer whose fence tracker stored only the fence CHARACTER, not its
LENGTH — so a 4-tick outer fence wrapping a 3-tick block closes early and
`## heading`-looking lines inside the code block get indexed as real entries).
The seed hands the candidate a diff that delegates fence-skip to a pre-existing
helper whose close-test compares only the marker char, plus a green suite
described as the "comprehensive fenced-code-block test set" using only
well-formed fences. The skill must NOT pronounce the parser "verified correct"
from the code read; it must recognise the structural tell (char-only tracking is
the defect, not proof), map the parser UNPROVEN, and **prescribe the concrete
discriminating input** with broken-vs-correct rationale. The single input that
discriminates a length-not-tracked bug is the **variable-length nested fence —
a 4-tick fence wrapping a 3-tick block** (char-only closes the outer fence
early; length-aware keeps it open) — required in the test gate before SAFE. The
other fence cases (a ≥4-space-indented close-looking line, which per CommonMark
ex.137 stays as block CONTENT and must still be skipped — NOT reparsed as
indented code; `~~~` vs backtick; an unclosed fence at EOF; a trailing-content
close) are general fence edge cases, not the discriminating input for this
seed's char-stored/length-not-tracked bug. Then deliver NOT SAFE TO MERGE.
Runs on the Claude pair (originally measured on the retired OpenAI pair, candidate
`gpt-5-mini`, judge `gpt-5.5`). Picked up by `npm run eval:all` automatically.

```bash
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-fence-parser.yaml --no-cache
```

**Load-bearing control (`.ab.yaml`).** `skill-reviewing-before-merge-fence-parser.ab.yaml`
runs the SAME seed against the PRE-EDIT (origin/main) SKILL.md body (A0) and the
post-#296 body (A1). The pre-edit body names the char-not-length tell and reaches
NOT SAFE, but — lacking the step-4 stateful-parser fence probe — it does NOT
prescribe a concrete discriminating fence input with broken-vs-correct rationale
before SAFE, a SHAPE FAIL under the rubric. A0 (old body) FAILs, A1 (new body)
PASSes; that lift isolates the #296 behaviour. The A0 body is snapshotted at
`fixtures/reviewing-before-merge-PRE-296.SKILL.md` — refresh it if the baseline
moves.

```bash
# A0 (pre-296 body) FAIL vs A1 (post-296 body) PASS
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-fence-parser.ab.yaml --no-cache
```

## Runtime-scope corpus (issue #300)

Issue #300 broadens what `reviewing-before-merge` counts as a **runtime
change**: the trigger now keys on **executable behaviour, not path prefix**. An
executable hook/script/automation under `.claude/hooks/`, `scripts/`, or any
non-`src/` location gets the same mandatory discovery sweep + coverage ledger as
a library module — and the trivial-change exemption is scoped to *genuinely
non-executable* diffs (docs / static config), not "anything outside
`app`/`src`/`lib`". The `executable-hook-out-of-source` FAMILY case in
`skill-reviewing-before-merge-adversarial.yaml` exercises this from a raw diff.

**Load-bearing control (`.ab.yaml`).**
`skill-reviewing-before-merge-runtime-scope.ab.yaml` runs the SAME
executable-hook seed (a command-parsing PreToolUse hook under `.claude/hooks/`,
outside the source dirs) against the PRE-EDIT (origin/main) SKILL.md body (A0)
and the post-#300 body (A1). Both prompts instruct the candidate to classify
runtime-vs-trivial **strictly by the loaded body's stated trigger**, not by its
own intuition about hooks. The pre-#300 body keys the verdict-format runtime gate
on an `app`/`src`/`lib` path prefix and scopes the trivial exemption to a diff
with "no `app`/`src`/`lib` file present", so A0 classifies the hook as
non-runtime/tooling, uses `N/A` or `COVERED BY VERIFICATION` instead of a
mirrored `tests/hooks/` ledger row, and does not reject the "outside src =
trivial" framing — a SHAPE FAIL. A1 (the new body) keys the trigger on executable
behaviour, runs the full sweep, emits a `tests/hooks/`-style coverage-ledger row
marked UNCOVERED/UNPROVEN, flags the command-parsing mis-parse, and reaches NOT
SAFE — a PASS. A0(FAIL) → A1(PASS) is deterministic over 3 runs; that lift
isolates the #300 behaviour. The A0 body is snapshotted at
`fixtures/reviewing-before-merge-PRE-300.SKILL.md` — refresh it if the baseline
moves.

```bash
# A0 (pre-300 body) FAIL vs A1 (post-300 body) PASS
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-runtime-scope.ab.yaml --no-cache
```

## Verification-evidence corpus (issue #332, consolidating #316/#321/#331)

Four configs grade ONE consolidated discipline added to
`sumo-qa-reviewing-before-merge`: a green per-file/codex review + green CI is NOT
evidence that the *changed behaviour* was exercised — the relevant
surface-specific verifier (and the right one, run correctly) must have run. All
four route through the same step-9 "Verification-evidence discipline" block, its
Verdict-format item 8 lines, and the step-10(e) SAFE-blocker. Each carries a
must-flag (NOT SAFE) seed AND a true-negative (SAFE-eligible) seed; the
`.ab.yaml` controls prove the new text is load-bearing (A0 = pre-edit body FAILs,
A1 = post-edit body PASSes). Runs on the Claude pair (originally measured on the retired OpenAI pair,
candidate `gpt-5-mini`, judge `gpt-5.5`).

```bash
for c in verifier-evidence guard-coverage eval-validity feature-flow; do
  ./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-$c.yaml --no-cache
done
# load-bearing controls (.ab.yaml for the checks that carry one)
for c in verifier-evidence eval-validity feature-flow; do
  ./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-$c.ab.yaml --no-cache
done
```

- **`skill-reviewing-before-merge-verifier-evidence.yaml` + `.ab.yaml` (#332).**
  When the changed surface has a relevant repo-specific verifier (promptfoo eval,
  fixture/parser corpus, contract test, smoke probe, generated-artifact
  verification), SAFE requires that verifier to have RUN with the right
  runtime/env/key/scope/tree. Eval-surface skill changes KEEP promptfoo as the
  REQUIRED verifier (Node 24 + the configured key). When sibling PRs co-edit ONE
  surface, per-branch-green is NOT combined-green — combined-tree verification is
  required (the #332 dogfood: external-contract 3/3 per-branch → 1/3 combined).
  Three seeds: an unrun-eval skill change with a CLOSED risk gate and no pre-named
  unrun eval — IDENTIFYING the required-but-unrun verifier is the discriminating
  behaviour (→ UNVERIFIED (surface verifier), NOT SAFE), sibling PRs with no
  combined-tree run (→ NOT SAFE pending combined-tree), and a discharged
  combined-tree run (→ SAFE-eligible, over-trigger guard). The `.ab.yaml` runs the
  unrun-eval seed against `fixtures/reviewing-before-merge-PRE-332.SKILL.md` (A0,
  no verification-evidence block, no generic uncovered-risk hook → SAFE on green
  CI = FAIL) vs the post-#332 body (A1 → NOT SAFE = PASS).
- **`skill-reviewing-before-merge-guard-coverage.yaml` (#316).** When a change
  ADDS a regression guard / bidirectional "do X but NOT Y" rule, "the guard is
  described" is NOT "the guard is tested": its eval must carry a discriminating
  true-negative / over-trigger seed a guard-violating reviewer would FAIL. A
  one-sided (positive-only) eval leaves the guard UNCOVERED, a SAFE-blocker,
  mirroring uncovered-risk → NOT SAFE and the #255 vacuous-test probe. Two seeds:
  a one-sided over-trigger guard (only external-output seeds, no internal-value
  true-negative → guard UNCOVERED, NOT SAFE) and the same guard with a
  discriminating internal/self-produced true-negative seed (→ COVERED,
  SAFE-eligible).
- **`skill-reviewing-before-merge-eval-validity.yaml` + `.ab.yaml` (#321).** When
  a SKILL.md edit ships a new/changed A/B "load-bearing" eval, probe the eval's
  OWN validity: A0 must be structurally INCAPABLE of passing via pre-existing
  rules (a single A0-FAIL is variance, not isolation; a lift explainable by a
  pre-existing rule is UNPROVEN), AND apply the 2b rule to the RUBRIC — a credited
  "discriminating" input must actually discriminate the seed defect. Two seeds: a
  non-load-bearing A/B (A0 passes via the pre-existing generic 2b rule + rubric
  credits `~~~`/unclosed-at-EOF, non-discriminating for the char-stored bug → NOT
  SAFE) and a genuinely load-bearing A/B (A0 cannot reach PASS, 3/3 deterministic;
  rubric credits only the variable-length nested fence → SAFE-eligible). The
  `.ab.yaml` runs the non-load-bearing seed against
  `fixtures/reviewing-before-merge-PRE-321.SKILL.md` (A0, no eval-validity probe →
  accepts the lift at face value = FAIL) vs the post-#321 body (A1 = PASS).
- **`skill-reviewing-before-merge-feature-flow.yaml` + `.ab.yaml` (#331).** Even
  with NO supplied AC, a change whose primary FEATURE FLOW (the closest realistic
  UI/API/CLI/worker/artifact path) was never driven end-to-end this turn — only a
  lower-level unit ran — is UNVERIFIED (feature flow), a SAFE-blocker DISTINCT
  from an UNMET AC (#314). Reuse the MET/UNVERIFIED boundary: no over-fire when a
  fresh path-matching test genuinely drives the flow. The feature flow is a CLI
  export-artifact path (`qa export --format csv` writing a report file),
  deliberately DIFFERENT from the retry-on-5xx / backoff-delay flow the pre-edit
  body already exemplifies in its AC worked contrast. Two seeds: the CSV-export
  feature whose only fresh test is a `_row_to_csv` formatter unit (the CLI command
  + written artifact never driven → UNVERIFIED (feature flow), NOT SAFE) and the
  same feature with a fresh end-to-end test invoking the CLI command and asserting
  the written CSV file (→ VERIFIED, SAFE-eligible). The `.ab.yaml` runs the
  unexercised seed against `fixtures/reviewing-before-merge-PRE-332.SKILL.md` (A0,
  no feature-flow check, no AC supplied → SAFE on the green formatter unit = FAIL)
  vs the post-#332 body (A1 → NOT SAFE = PASS).
## Review-feedback-memory corpus (issue #145)

`skill-preparing-for-work-feedback-memory.yaml` and
`skill-reviewing-before-merge-feedback-memory.yaml` grade the #145
advisory-hints behaviour: when the team has saved a recurring review lesson
(`sumo_qa_capture_review_feedback`) whose `trigger_signal` matches the in-flight
change, the skill consults it as a SEPARATE ADVISORY hint that sharpens a named
risk — never an override of a canonical classification/change-rule, never an
auto-capture, and (memory-absent) never an invented hint. The
reviewing-before-merge seed makes the hint-derived rollover/DST risk UNCOVERED
by the fresh test, so it is a SAFE-blocker and the verdict is NOT SAFE TO MERGE.
The candidate prompts are NEUTRAL — they carry only the output-format scaffold
plus a generic "consult any supplied team context; the loaded skill governs how"
— so the behaviour comes ONLY from the injected `skill_content`, not the prompt.
Runs on the Claude pair (originally measured on the retired OpenAI pair, candidate
`gpt-5-mini`, judge `gpt-5.5`). Picked up by `npm run eval:all` automatically.

```bash
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-preparing-for-work-feedback-memory.yaml --no-cache
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-feedback-memory.yaml --no-cache
```

**Load-bearing controls (`.ab.yaml`).**
`skill-preparing-for-work-feedback-memory.ab.yaml` and
`skill-reviewing-before-merge-feedback-memory.ab.yaml` run the SAME
memory-PRESENT seed against the PRE-EDIT (origin/main) SKILL.md body (A0) and the
post-#145 body (A1), under the neutral prompt. The pre-#145 body has no
review-feedback-memory note, so A0 has nothing instructing it to consult the
saved lesson: it grades the change on the diff risks + green-but-non-covering
test alone, does not surface the lesson as a separate advisory hint or map the
rollover/DST probe into the coverage ledger, and can wave the change through — a
SHAPE FAIL. A1 (the new body) consults the matched lesson as a separate advisory
hint and reaches the correct shape/verdict — a PASS. A0(FAIL) → A1(PASS) isolates
the #145 behaviour. The A0 bodies are snapshotted at
`fixtures/preparing-for-work-PRE-145.SKILL.md` and
`fixtures/reviewing-before-merge-PRE-145.SKILL.md` — refresh them if the baseline
moves.

```bash
# A0 (pre-145 body) FAIL vs A1 (post-145 body) PASS
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-preparing-for-work-feedback-memory.ab.yaml --no-cache --repeat 3
./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-feedback-memory.ab.yaml --no-cache --repeat 3
```

## How to run

### One-time setup

**Node 20.20+ or 22.22+** is required (`promptfoo` ships ESM). If you use nvm:
`nvm use 24` (or any supported version).

Install promptfoo as a local dev dependency (pinned in `package.json`):

```bash
npm install
```

The eval gate runs on the Claude pair through the Claude Code CLI, so `claude`
must be on `PATH` and signed in. There is no API key to set up.

### Common commands (via npm scripts)

```bash
npm run eval              # the TDD skill eval on the Claude pair (the merge gate)
npm run eval:all          # every skill-*.yaml on the Claude pair, sequentially
npm run eval:generate     # synthesise more tests from the seed (--write merges into the YAML)
npm run eval:view         # open the local results UI
```

### The Claude pair (the default backend and merge gate)

`run-eval.sh` defaults to `SUMO_EVAL_BACKEND=claude`: every config runs on your Claude
subscription through the local Claude Code CLI. The candidate is
`providers/claude-candidate.yaml` (`claude-haiku-4-5`, the weakest current model) and
the judge is `providers/claude-judge.yaml` (`claude-opus-5`). Every `skill-*.yaml` pins
those two provider files, and `run-eval.sh` also passes them as `--providers` /
`--grader`, so a bare `promptfoo eval -c <config>` runs on the same pair and never on an
OpenAI model. The OpenAI cloud backend was removed in #682; `SUMO_EVAL_BACKEND=cloud`
fails and names the valid backends (`claude|local`).

```bash
npm run eval                                          # skill-implementing-with-tdd.yaml, one pass
npm run eval -- tests/evals/promptfoo/skill-using-sumo-qa.yaml   # one config
npm run eval:all                                      # every skill-*.yaml, one pass
SUMO_EVAL_REPEAT=3 npm run eval:all                   # variance run
SUMO_EVAL_DRY_RUN=1 npm run eval:all                  # print the promptfoo commands, call no model
```

Reports land in `tests/evals/results/claude-reports/<config>.json` (gitignored).

- `providers/claude_cli.py` calls `claude -p --output-format json` with tools, MCP
  servers, user settings and slash commands switched off, and a fixed system prompt.
  Without the system prompt Claude Code's agent prompt applies and the candidate
  narrates tool use it cannot perform, so rubrics fail it.
- Any call that is not a successful answer (usage limit, quota, non-zero exit, empty
  answer) is a promptfoo **error**, never graded output. A judge call that fails, or
  returns no parseable verdict, is recorded by promptfoo as a failed assertion tagged
  `graderError`; `run-eval.sh` counts both, stops at the first config that has either,
  and exits 3: neither is a skill verdict (#651).
- Usage is subscription usage. The `cost` in reports is the CLI's list-price figure,
  notional, not an invoice. A full single pass over all 61 configs (2026-09-14,
  `claude-haiku-4-5` candidate, `claude-opus-5` judge) used ~3.6M tokens, $12.30 at
  list price, with 0 provider errors; the slowest configs take 10 to 20 minutes each.

### Local tiers (OpenWebUI proxy): unmetered iteration, not a merge gate

`run-eval.sh` adds a `SUMO_EVAL_BACKEND=local` toggle so you can iterate on a SKILL.md
against models on your own hardware, with no subscription involved. Promptfoo talks to
ONE endpoint, the OpenWebUI proxy (`$SUMO_OWUI_BASE`, OpenAI-compatible API, key from
`~/.config/owui.env` as `OPENWEBUI_API_KEY`), which routes each model id to the box that
holds it (single-host tags) and applies model-level params. Only the candidate
(`--providers`) and judge (`--grader`) are overridden; the configs' Claude pins are
untouched.

Split into two tiers so the 4090 (a personal machine) is only touched on demand:

```bash
npm run eval:local:cheap      # 4060 candidate + laptop judge — NEVER the 4090
npm run eval:local:reasoning  # laptop candidate + 4090 judge: `# local-tier: reasoning` configs, uses the 4090
npm run eval:local:quality    # laptop candidate + 4090 judge — ALL skills, uses the 4090
```

> **NOT a merge gate.** Local runs measure *relative* movement: did a SKILL.md edit
> raise or lower the pass-rate with a **fixed** local candidate+judge. They do not
> reproduce the Claude pair. The merge decision always re-runs the Claude pair
> (`npm run eval` / `eval:all`); a local lift is iteration signal only.

**Multiple runs & readable reports.** Each test runs `--repeat 3` by default
(`SUMO_EVAL_REPEAT=N npm run eval:local:cheap` to change). Every run writes an HTML + JSON
report to `tests/evals/results/local-reports/<skill>.<tier>.html` (gitignored) — open the
HTML for the full grid: every candidate output + judge verdict, reason and score. The CLI
table is unreadable; use the HTML. For an interactive UI across **all** past runs (filter,
compare two runs, diff cells) run `npm run eval:view` (= `promptfoo view`). Note: promptfoo
exits non-zero whenever any assertion fails — that's "not 100 % green", not a harness error;
read the pass-rate, not the exit code.

We grade `message.content` only (`showThinking: false`), so a candidate can REASON
(body-faithful discrimination) while the judge sees a clean verdict. The **cheap-tier
models are the 2026-06 judge/candidate bake-off winners** (tooling in `bakeoff/` +
`validate-local-judge/`): candidate `gemma4-e4b-bounded` on the 4060, judge
`gemma4-12b-bounded` on the laptop. Headline vs stored verdicts from `gpt-5.5`, the judge of the
retired OpenAI gate at the time: the judge agrees
**92 %** (vs ~56 % for the old reasoning-off qwen3.5:9b) and is **binary-deterministic**
on fixed input; the `gemma4-e4b` candidate is the only 4060 model that lifts all three
`.ab` control types. The rep-to-rep wobble is **candidate-side** (the e4b regenerates near
the pass threshold at temp 0), so pair with `--repeat 3`. Still a *relative* signal; the
Claude pair is the merge gate. The 4090 `gpt-oss:20b` judge was tested and **rejected for
now** (too strict — 0/3 separation, beaten by the laptop judge); revisit with a tuned 20B.
The old instant `sumo-cheap-judge-9b` remains available via `SUMO_CHEAP_JUDGE`.

| Tier | Scope | Candidate (host) | Judge (host) | 4090? |
|---|---|---|---|---|
| cheap | configs without the reasoning marker | `gemma4-e4b-bounded`: bounded Gemma 4 e4b (4060) | `gemma4-12b-bounded`: bounded Gemma 4 12B (laptop), 92% agreement with the former gpt-5.5 gate | no |
| reasoning | configs marked `# local-tier: reasoning` | `gemma4-12b-bounded`: OWUI alias for bounded Gemma 4 12B on the laptop | `sumo-rjudge-20b`: gpt-oss:20b (4090) | yes |
| quality | **all** skills | `gemma4-12b-bounded` (laptop) — or another model via `SUMO_QUALITY_CANDIDATE` | `sumo-rjudge-20b` — gpt-oss:20b (4090) | yes |

The **quality** tier is the highest-fidelity local option — the laptop reasoning candidate +
the bigger, different-family 4090 judge across *every* skill, for when the 4090 is free. It's
slow (both sides reason) and uses the 4090, so it's opt-in; it's still a relative signal, not
the merge gate. Validate its judge before relying on it: `npm run eval:validate-judge -- --judge sumo-rjudge-20b`.

`gemma4-12b-bounded` is an OpenWebUI workspace alias, so it appears in the chat model
picker rather than as a separately managed Ollama model. Promptfoo addresses it directly
by that stable model ID through `$SUMO_OWUI_BASE/chat/completions`. The alias persists
`think=medium`; its underlying `gemma4-12b-bounded:latest` laptop tag persists the 128K
context, Gemma sampling parameters, anti-loop system prompt, and 4096-token hard cap.

Override any default via the `SUMO_CHEAP_*` / `SUMO_REASON_*` env vars in `run-eval.sh`.
Each model needs a **16k+-num_ctx variant** (`ollama create <m> --from <base>` with
`num_ctx 16384`) — the ~14k-token skill prompts 400-error at Ollama's 4096 default.
Tags pinned 2026-06; revisit when the hardware or Ollama version changes.

The reasoning marker is a comment line directly above `providers:` in the configs the
removed OpenAI tier ran on its `gpt-5-mini` reasoning candidate; `run-eval.sh` greps for
it to split the cheap and reasoning tiers.

`SUMO_EVAL_CONCURRENCY` sets promptfoo's `-j` (number of test cases in flight; defaults
**1** on both backends). Raising local `-j` looks tempting (overlap candidate-gen on one
host with judge-grading on the other), but on the single-GPU local tiers it **backfires**:
`-j>1` stacks several concurrent *reasoning* generations onto the one candidate GPU (and
grades onto the one judge GPU), which thrashes them. Verified 2026-06-08: at `-j 3` the
laptop reasoning candidate pegged and never finished a generation while the 4090 judge sat
idle. The gen/grade host-overlap can't be isolated from same-GPU stacking via `-j`, and the
reasoning models can't share a GPU, so **local stays `-j 1`**.

### Reusable provider configs (`providers/`)

Candidate and judge providers are factored out of the test YAMLs into reusable
`providers/*.yaml` files and referenced through `file://`. Every config pins the Claude
pair; the `.ab` controls add an env-var override on top of that default:

```yaml
# a plain config
providers:
  - file://providers/claude-candidate.yaml
defaultTest:
  options:
    provider: file://providers/claude-judge.yaml

# an .ab control
providers:
  - file://{{ env.SUMO_EVAL_CANDIDATES_FILE | default('providers/claude-candidate.yaml') }}
defaultTest:
  options:
    provider: file://{{ env.SUMO_EVAL_JUDGE_FILE | default('providers/claude-judge.yaml') }}
```

With **no env vars set**, both shapes resolve to the Claude pair, the merge gate. On an
`.ab` control, setting `SUMO_EVAL_CANDIDATES_FILE` and/or `SUMO_EVAL_JUDGE_FILE` swaps in a
local pairing for the relative tiers — one switch per side, no per-file `--providers`/`--grader`
flags, and the judge provider is shared across every test so grading runs **concurrently** with
candidate generation across the two boxes.

| Provider file | Role | Model (host) |
|---|---|---|
| `local-laptop-qwen-judge.yaml` | judge | `sumo-cheap-judge-9b` — qwen3.5:9b reasoning-off (laptop) |
| `local-4090-judge.yaml` | judge | `sumo-rjudge-20b` — gpt-oss:20b (4090) |
| `local-4060-gemma-candidate.yaml` | candidate | `gemma4-e4b-bounded` (4060) |
| `local-laptop-gemma-candidate.yaml` | candidate | `gemma4-12b-bounded` (laptop) |
| `local-gemma-candidates.yaml` | candidate list | both bounded Gemma 4 tags (laptop + 4060) |
| `claude-candidate.yaml` | candidate (default, the merge gate) | `claude-haiku-4-5` via `claude -p` (subscription) |
| `claude-judge.yaml` | judge (default, the merge gate) | `claude-opus-5` via `claude -p` (subscription) |

`SUMO_OWUI_BASE` is interpolated into the local provider files' `apiBaseUrl`, and
`showThinking: false` keeps the judge grading clean `content` (no `<think>` channel). To run a
`.ab` control on a local pairing instead of the Claude pair:

```bash
# from the repo root (env-var paths resolve relative to the config file's dir, the -c path to cwd)
SUMO_EVAL_CANDIDATES_FILE=providers/local-4060-gemma-candidate.yaml \
SUMO_EVAL_JUDGE_FILE=providers/local-laptop-qwen-judge.yaml \
  ./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-fence-parser.ab.yaml --repeat 3
```

### Validating the local judge (`validate-local-judge/`)

A local judge is only safe to trust as a *relative* signal if it tracks the stored
cloud judge's direction, discriminates a skill lift, and is repeatable; and those are per
`(model, num_ctx, GPU, build)`. **Re-run this whenever the local judge model or
hardware changes** (it's the executable form of "re-baseline on change"):

```bash
npm run eval:validate-judge                       # all checks, default sumo-cheap-judge-9b
npm run eval:validate-judge -- --mode determinism --reps 5
npm run eval:validate-judge -- --judge <model> --mode discrimination --pairs 12
```

It reads the local `~/.promptfoo/promptfoo.db` read-only, faithfully reconstructs the
exact `llm-rubric` prompt each stored cloud row was graded with (by default the
`openai:chat:gpt-5.5` rows the retired OpenAI gate recorded, `--cloud-judge`; promptfoo's own
nunjucks, via `render.js` — apples-to-apples), re-grades through OpenWebUI, and reports:

- **agreement** — verdict-for-verdict vs the stored cloud verdicts + confusion matrix.
  Expect this to be *modest* (~56 % for the 9B) — the local judge is a relative signal,
  not a cloud clone; this number is diagnostic, not a gate.
- **discrimination** — on gpt-5.5-**separated** A0/A1 control pairs, does it keep the
  pass/fail split and rank A1 (skill-on) > A0? This is the fitness metric that matters.
  Pairs are drawn only from the genuine A0/A1 control families (the A/B/C value-measurement
  and A0/A1 control configs) and matched by each prompt's **A0/A1 label**, never inferred
  from the verdict — so single-prompt probe configs can't be mistaken for a control pair.
- **determinism** — re-grade identical inputs N times; verdict/score stability (at
  temp 0 the 9B is fully deterministic, score range 0.0, which is what makes the
  before/after delta meaningful). An **unparsable** verdict counts as a failure, not a
  stable result — a judge that never emits valid verdict JSON can't score as deterministic.

Reports land in `tests/evals/results/judge-validation/` (gitignored — process artifact,
not tool output). Needs `~/.config/owui.env` (`OPENWEBUI_API_KEY`); Node for `render.js`.
Reference numbers captured 2026-06 (`sumo-cheap-judge-9b`): agreement ~56 %, discrimination
~9/12 split + ~10/12 score-rank, determinism 12/12 stable.

### Direct binary invocation (for flags not in the scripts)

The local binary is at `./node_modules/.bin/promptfoo` after `npm install`.

```bash
# Multi-sample variance check (each test runs 5 times):
./node_modules/.bin/promptfoo eval \
    -c tests/evals/promptfoo/skill-implementing-with-tdd.yaml \
    --no-cache \
    --repeat 5 \
    --output /tmp/result.json

# Sequential / legible logs:
./node_modules/.bin/promptfoo eval -c <config> -j 1

# Generate dataset with custom instructions (synthesised by the Claude candidate; the
# provider path resolves against the config's directory):
./node_modules/.bin/promptfoo generate dataset \
    -c tests/evals/promptfoo/skill-implementing-with-tdd.yaml \
    --provider file://providers/claude-candidate.yaml \
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

## Usage

Every run goes through `claude -p` on the signed-in Claude account, so it spends
subscription usage; see "The Claude pair" above for a measured full pass.

### Historical: the retired OpenAI pair

OpenAI pricing as of 2026-05, measured on the retired OpenAI pair:

- Candidate (`gpt-4o-mini`): ~$0.001 per scenario
- Judge (`gpt-5.5`): ~$0.005 per scenario
- Full sweep of 18 skills: ~$0.11 per run with `seed: 42` determinism
- The `reviewing-before-merge-adversarial` corpus pinned a `gpt-5-mini` candidate
  (reasoning tokens, a few cents per full run); see "Adversarial discovery corpus"
  above for why.

Running a single skill: pennies. Running all 18 skills with `--repeat 5`: ~$0.30.

## Architecture

Every skill YAML pins the Claude candidate and judge provider files (see "The Claude pair" above). The Claude provider sets no temperature or seed, so run-to-run variance is measured with `--repeat` and `aggregate.py` rather than assumed away. `disableVarExpansion: true` is set in defaultTest.options to prevent array vars (anti_patterns) from being expanded into per-element tests.

Two patterns are used depending on the skill's shape:

### Pattern A — inline-context skills (e.g. `sumo-qa-implementing-with-tdd`)

For skills where each scenario has a per-scenario ground-truth context
(synthetic code / diff / sibling test), a single YAML file holds everything:

1. `skill_content: file://...` in `defaultTest.vars`
2. ONE seed test inline (with `vars.ground_truth_context`)
3. Skill-level rubric in `defaultTest.vars` (`expected_shape`, `anti_patterns`, `technique_tag`)
4. Decision-table rubric prompt in `defaultTest.options.rubricPrompt`. It passes `{{ground_truth_context}}` to the judge in a `SUPPLIED CONTEXT` block, because the GROUNDING axis grades against that evidence and the judge cannot check it otherwise. For the same reason it renders every catalogue the candidate prompt renders (`{{loaded_techniques}}`, `{{loaded_classifications}}`, `{{loaded_rules}}`, `{{principles}}`, ...) in a labelled `--- LOADED <NAME> (catalogue the candidate was given) ---` block, or a leg-scoped `--- REFERENCE <NAME> (...) ---` block in an A/B config where some prompt leg does not render that catalogue (see [Judge catalogue context](#judge-catalogue-context))
5. Candidate wrapper prompt in `prompts:`
6. A shared `javascript` grounding assertion (`value: file://asserts/cites-catalogue-technique.js`) that passes when the candidate cites a technique name drawn from `knowledge/techniques.md`'s `###` headings; the accepted set is derived from the catalogue, never a hardcoded allowlist (issue #350)

`promptfoo generate dataset --provider file://providers/claude-candidate.yaml --write`
against this YAML (what `npm run eval:generate` runs) synthesises additional
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
# 1. Generate user_prompt variations into gen.yaml
./node_modules/.bin/promptfoo generate dataset \
    -c tests/evals/promptfoo/skill-<name>.gen.yaml \
    --provider file://providers/claude-candidate.yaml \
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

### Judge catalogue context

A `rubricPrompt` only receives the vars it renders. When a config gives the
candidate a catalogue (a `file://` var under `knowledge/` or `standards/` that
a `prompts:` template renders), its `rubricPrompt` renders that same var too,
after the supplied/repo context block (`SUPPLIED CONTEXT`, or `REPO CONTEXT`
in `skill-strengthening-tests-artifact.yaml`):

```yaml
      --- LOADED TECHNIQUES (catalogue the candidate was given) ---

      {{loaded_techniques}}

      --- END LOADED TECHNIQUES ---
```

Without it the judge grades a catalogue citation from memory. Measured in
#683 with a fixed candidate answer (judge only, `claude-opus-5`): an answer
citing `metamorphic testing`, a real technique that `techniques.md` does not
carry, passed at 0.85 when the catalogues were left out of the rubric (the
judge noted it could only check the citation was "plausibly present"), and
failed at 0.25 as training-data drift with them in. The same answer citing
`property-based testing` passed both ways. Re-grading saved candidate answers
for `skill-reviewing-before-merge-unproven-escalation.yaml` and
`skill-preparing-for-work-feedback-memory.yaml` with the block added changed
no verdict.

The block adds the rendered catalogue to every judge call: about 1.8k tokens
for `techniques.md` and 4.4k for `classifications.md` plus `change_rules.yaml`.
#### A/B configs: leg-scoped label

An `.ab.yaml` config shares one `rubricPrompt` across every prompt leg, and the
judge is not told which leg wrote the answer. When every leg renders the
catalogue (the PRE/post body comparisons such as
`skill-reviewing-before-merge-runtime-scope.ab.yaml`), the `LOADED` label above
is true for every answer and stays. When some leg never renders it (the A0
"no skill, no catalogues" leg), "the candidate was given" is false for that
leg: the judge could hold A0 to a catalogue it never saw, grade it down harder
than A1 and B, and inflate the measured lift. Those blocks name the legs that
load the catalogue instead:

```yaml
      --- REFERENCE CLASSIFICATIONS (the catalogue the A1 and B legs load; the A0 no-skill leg was not given it, so do not penalise a response for not quoting it) ---

      {{classifications}}

      --- END REFERENCE CLASSIFICATIONS ---
```

The wording follows what each leg's prompt actually renders. In
`skill-implementing-with-tdd.ab.yaml` the B full-skill leg renders
`{{loaded_techniques}}` but not `{{principles}}`, so its `principles` block
reads `(the catalogue only the A1 catalogues-only leg loads; the A0 no-skill and
B full-skill legs were not given it, so do not penalise a response for not
quoting it)`. The block only changes what the judge is told about the
catalogue; the axes, pass criteria and verdict format are unchanged.

`tests/test_eval_judge_catalogue_context.py` fails any config whose
`rubricPrompt` leaves out a catalogue its candidate prompt renders (a catalogue
var in `defaultTest.vars`, in an inline `tests[].vars`, or in a `file://` tests
include), and any `LOADED ... (catalogue the candidate was given)` block whose
var some prompt leg does not render, or `REFERENCE` block whose var every leg
renders.

## What's in this directory

| File | Purpose |
|---|---|
| `skill-<name>.yaml` (×16) | One config per skill, all covered |
| `skill-reviewing-before-merge-adversarial.yaml` + `.ab.yaml` | Issue #236 discovery corpus + A0/A1/B lift (see "Adversarial discovery corpus" above) |
| `skill-reviewing-before-merge-unproven-escalation.yaml` + `.ab.yaml` | Issue #187 UNPROVEN-escalation corpus + A0(pre-edit)/A1(post-edit) load-bearing control (see "UNPROVEN-escalation corpus" above) |
| `skill-reviewing-before-merge-external-contract.yaml` | Issue #263 external-contract corpus, three seeds: (1) a matcher/parser over external CLI/API/tool output validated only by a hand-authored fixture → external-contract risk UNPROVEN, withhold SAFE; (2) a fixture traceable to a real run → external-contract risk discharged, SAFE-eligible (over-trigger guard); (3) a matcher over an INTERNAL/self-produced value the same module emits → external-contract axis must NOT fire at all (true-negative over-trigger guard) |
| `skill-reviewing-before-merge-ac-coverage.yaml` | Issue #264 acceptance-criteria coverage: three seeds — UNMET AC → NOT SAFE, all-MET → SAFE-eligible, and plausibly-implemented-but-no-end-to-end-evidence → UNVERIFIED (not UNMET) → NOT SAFE — exercising the three-state MET/UNMET/UNVERIFIED discriminator |
| `fixtures/reviewing-before-merge-PRE-187.SKILL.md` | Snapshot of the pre-#187 SKILL.md body, the A0 control leg for the unproven-escalation `.ab.yaml` |
| `skill-reviewing-before-merge-fence-parser.yaml` + `.ab.yaml` | Issue #296 discriminating-input fence probe + A0(pre-edit)/A1(post-edit) load-bearing control (see "Discriminating-input fence probe" above) |
| `fixtures/reviewing-before-merge-PRE-296.SKILL.md` | Snapshot of the pre-#296 SKILL.md body, the A0 control leg for the fence-parser `.ab.yaml` |
| `skill-reviewing-before-merge-runtime-scope.ab.yaml` | Issue #300 A0(pre-edit)/A1(post-edit) load-bearing control for the behaviour-not-path runtime-scope rule (see "Runtime-scope corpus" above) |
| `fixtures/reviewing-before-merge-PRE-300.SKILL.md` | Snapshot of the pre-#300 SKILL.md body, the A0 control leg for the runtime-scope `.ab.yaml` |
| `skill-reviewing-before-merge-verifier-evidence.yaml` + `.ab.yaml` | Issue #332 surface-specific verifier-evidence corpus (3 seeds: unrun eval with a CLOSED risk gate, the unrun eval NOT pre-named → NOT SAFE, no combined-tree run → NOT SAFE, discharged combined-tree run → SAFE-eligible) + A0(pre-edit)/A1(post-edit) load-bearing control (see "Verification-evidence corpus" above) |
| `fixtures/reviewing-before-merge-PRE-332.SKILL.md` | Snapshot of the pre-#332 SKILL.md body, the shared A0 control leg for the verifier-evidence and feature-flow `.ab.yaml` controls |
| `skill-reviewing-before-merge-guard-coverage.yaml` | Issue #316 regression-guard coverage corpus (2 seeds: one-sided over-trigger guard → UNCOVERED, NOT SAFE; two-sided guard with a discriminating internal-value true-negative → COVERED, SAFE-eligible) |
| `skill-reviewing-before-merge-eval-validity.yaml` + `.ab.yaml` | Issue #321 eval-validity probe (2 seeds: non-load-bearing A/B + non-discriminating credited input → NOT SAFE; structurally-isolating A/B with only discriminating inputs → SAFE-eligible) + A0(pre-edit)/A1(post-edit) load-bearing control |
| `fixtures/reviewing-before-merge-PRE-321.SKILL.md` | Snapshot of the pre-#321 SKILL.md body, the A0 control leg for the eval-validity `.ab.yaml` |
| `skill-reviewing-before-merge-feature-flow.yaml` + `.ab.yaml` | Issue #331 primary feature-flow evidence corpus (2 seeds: CSV-export CLI feature with only a `_row_to_csv` formatter unit → UNVERIFIED (feature flow), NOT SAFE; fresh end-to-end test invoking the CLI command + asserting the written CSV → VERIFIED, SAFE-eligible) + A0(pre-#332)/A1(post-#332) load-bearing control on the unexercised seed |
| `skill-preparing-for-work-feedback-memory.yaml` + `.ab.yaml` | Issue #145 review-feedback-memory advisory-hints corpus (prep side) + A0(pre-edit)/A1(post-edit) load-bearing control (see "Review-feedback-memory corpus" above) |
| `skill-reviewing-before-merge-feedback-memory.yaml` + `.ab.yaml` | Issue #145 review-feedback-memory advisory-hints corpus (review side, uncovered-rollover NOT-SAFE driver) + A0/A1 load-bearing control |
| `skill-reviewing-before-merge-coverage-artifact.yaml` | Issue #147 coverage/mutation-artifact corpus (review side, 2 seeds): a local coverage/mutation artifact (any format — Cobertura/lcov/coverage.json/Stryker/PIT/mutmut) is folded in as ASYMMETRIC supporting evidence — an uncovered changed line RAISES a NAMED, UNCOVERED risk (seed 1, high % + green suite must NOT read as SAFE), but a line the artifact marks "covered/executed" never discharges a risk without a fresh path-matching assertion (seed 2) → NOT SAFE while a changed-code risk is uncovered |
| `skill-strengthening-tests-artifact.yaml` | Issue #147 mutation-artifact corpus (strengthening side, 2 seeds): with no pasted report, DISCOVER + read the repo's own mutation artifact (Stryker schema) and present the artifact-named survivors scoped to the target at the first confirmation gate (seed 1); with no artifact anywhere, a concise "not available" that asks for a report or specific targets without fabricating survivors (seed 2) |
| `fixtures/preparing-for-work-PRE-145.SKILL.md` | Snapshot of the pre-#145 prep SKILL.md body, the A0 control leg for the prep feedback-memory `.ab.yaml` |
| `fixtures/reviewing-before-merge-PRE-145.SKILL.md` | Snapshot of the pre-#145 review SKILL.md body, the A0 control leg for the review feedback-memory `.ab.yaml` |
| `skill-answering-testing-question.gen.yaml` | Pattern B generator-only seed |
| `skill-answering-testing-question.generated-tests.yaml` | Pattern B bare-list tests (regenerated) |
| `extract_tests.py` | Pattern B post-processor |
| `aggregate.py` | Variance aggregator for multi-sample runs |
| `asserts/cites-catalogue-technique.js` | Shared `javascript` grounding assertion for the three `skill-implementing-with-tdd*` configs; passes when the candidate cites a technique whose name is a `###` heading in `knowledge/techniques.md`, derived from the catalogue (single source of truth) instead of a hardcoded six-technique allowlist (issue #350) |
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

This measures skill value as `pass_rate(B) - pass_rate(A1)`. A0 is the raw Claude baseline with no catalogues and no skill. A1 adds catalogues only. B adds the full SKILL.md. The gap between B and A1 shows what the skill's decision logic contributes beyond raw knowledge. Run it with `./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-deciding-approach.ab.yaml --no-cache`. `.ab.yaml` controls exist for a subset of skills and corpora (`ls tests/evals/promptfoo/*.ab.yaml`); the pattern is not rolled across the whole estate.

A control only measures lift if A0 cannot pass on material the prompt already hands it. When the shared prompt or a seed's recap spells out the decisions the skill teaches, A0 passes by construction and the control does not discriminate. Document that in the config header, or add a seed that targets a taught behaviour A0 is not given.

### `skill-strengthening-tests.ab.yaml` on the Claude pair (issue #688)

The three original seeds (VIP promo boundary, youth discount boundary, identity multiplication equivalent) do **not** discriminate on the Claude pair: the #679 run scored A0 3/3, A1 3/3, B 3/3. The shared prompt already states config-side suppression, no tautological test, production unchanged and no confirmation question. Each seed's context also pre-decides the rest. The two boundary seeds' "Prior turns recap" hands over the real verdict and the technique name, and their report excerpt names the missing boundary input. The identity-multiplication seed hands over the equivalence verdict and the config-side suppression surface (`mutation-testing.yml`, `ignoredMutants`). A0 is left with only the mechanics, which `claude-haiku-4-5` does unaided. Those seeds stay as regression guards for B, not as lift evidence.

The **production-defect seed** (`SEED - boundary survivor exposing a production defect`) is the discriminating case. It targets the skill's HARD-GATE: the test file quotes an acceptance criterion ("free when the basket total is £50.00 or more") that matches the mutant `>= 5000`, not the original `> 5000`. The right move is no strengthening test and a hand-off to a separate regression-first fix. Pinning the current behaviour would lock in the bug. The recap does not pre-decide the verdict. Measured 2026-09-14, this seed only, one pass per leg. The first two columns used the old binary prompt ("real assertion gap or an equivalent mutant", two formats only); they are kept as history. The last two used the neutral prompt described below:

| Leg | Binary prompt, before the SKILL.md fix | Binary prompt, after | Neutral prompt, first review fix | Neutral prompt, final |
|---|---|---|---|---|
| A0 (no skill) | FAIL: test expects `false` at 5000, pinning the bug | FAIL: same | FAIL (0.15): flags the spec mismatch but delivers a `true`-at-5000 test and recommends fixing production in this flow | FAIL (0.00): test expects `false` at 5000, never cites SHIP-218 |
| A1 (catalogues) | FAIL: delivers a red `true`-at-5000 test as the strengthening test | FAIL: same | FAIL (0.10): delivers a `true`-at-5000 test, never states the code/spec disagreement | FAIL (0.05): test expects `false` at 5000, never cites SHIP-218 |
| B (full skill) | FAIL: test expects `false` at 5000 | PASS (0.88): stops, cites the criterion, routes to regression-first | FAIL (0.55): right diagnosis, no test, but names only a skill (no failing-test-then-fix steps) and omits "production stays unchanged" | PASS (0.80): writes no test, cites SHIP-218 and 5000, hands off a failing test at 5000 then the production fix, production unchanged |

The before-fix B failure was a skill gap, not a rubric problem. The HARD-GATE existed, but triage only sorted survivors into equivalent or real, so nothing prompted a check against a stated spec. The fix adds a third triage outcome to the SKILL.md (a current, authoritative spec that matches the mutant means a production defect: write no test, stop and hand off to a separate regression-first fix, a failing test at the disagreeing input first and then the production fix, with production unchanged in this flow). No rubric clause was loosened.

The shared prompt's answer space is neutral and identical across A0, A1 and B. It used to say "decide whether the survivor is a real assertion gap or an equivalent mutant", offer only those two formats and forbid additional sections. A0 and A1 could not stop on a production defect without disobeying the prompt, while B's skill overrode it, so the lift was confounded. The prompt now says "decide what the survivor needs" and lets a survivor that fits neither format be answered in one short section saying why, closing with the same `Production code stays unchanged.` last line as the two formats. It does not name the spec check, and every other constraint is unchanged. The production-defect seed also fails a response that surfaces an internal control label such as HARD-GATE. The first neutral-prompt run showed two gaps, both fixed before the final run: the neither-format line lacked the shared `Production code stays unchanged.` last line, and step 3(c) did not say what the regression-first hand-off is. It now spells it out: a failing test at the input where spec and code disagree first, then the production fix, with production unchanged in this flow. No output in either neutral-prompt run surfaced HARD-GATE. Rerun just this seed with the filtered command:

```bash
cd tests/evals/promptfoo
SUMO_EVAL_DRY_RUN=1 bash run-eval.sh skill-strengthening-tests.ab.yaml   # prints the resolved command
# append --filter-pattern 'production defect' to that command and run it from this directory
```
