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
Candidate `gpt-5-mini`,
judge `gpt-5.5`. Picked up by `npm run eval:all` automatically.

```bash
source ~/.config/promptfoo-keys.env
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
source ~/.config/promptfoo-keys.env
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
source ~/.config/promptfoo-keys.env
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
A1 = post-edit body PASSes). Candidate `gpt-5-mini`, judge `gpt-5.5`.

```bash
source ~/.config/promptfoo-keys.env
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
Candidate `gpt-5-mini`, judge `gpt-5.5`. Picked up by `npm run eval:all`
automatically.

```bash
source ~/.config/promptfoo-keys.env
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
source ~/.config/promptfoo-keys.env
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

### Local fallback (OpenWebUI proxy) — when you're out of OpenAI quota

`run-eval.sh` adds a `SUMO_EVAL_BACKEND=local` toggle so you can keep iterating on
a SKILL.md when the OpenAI quota is exhausted. Promptfoo talks to ONE endpoint — the
OpenWebUI proxy (`$SUMO_OWUI_BASE`, OpenAI-compatible) — which routes each model id to
the box that holds it (single-host tags) and applies model-level params. Only the
candidate (`--providers`) and judge (`--grader`) are overridden; cloud is untouched.

Split into two tiers so the 4090 (a personal machine) is only touched on demand:

```bash
npm run eval:local:cheap      # 4060 candidate + laptop judge — NEVER the 4090
npm run eval:local:reasoning  # laptop candidate + 4090 judge — gpt-5-mini files, uses the 4090
npm run eval:local:quality    # laptop candidate + 4090 judge — ALL skills, uses the 4090
```

> **NOT merge-authoritative.** Local runs measure *relative* movement — did a
> SKILL.md edit raise or lower the pass-rate with a **fixed** local candidate+judge
> — not cloud parity. The merge decision always re-runs the cloud backend
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
`gemma4-12b-bounded` on the laptop. Headline vs stored gpt-5.5 verdicts: the judge agrees
**92 %** (vs ~56 % for the old reasoning-off qwen3.5:9b) and is **binary-deterministic**
on fixed input; the `gemma4-e4b` candidate is the only 4060 model that lifts all three
`.ab` control types. The rep-to-rep wobble is **candidate-side** (the e4b regenerates near
the pass threshold at temp 0), so pair with `--repeat 3`. Still a *relative* signal; cloud
(gpt-5.5) is the merge gate. The 4090 `gpt-oss:20b` judge was tested and **rejected for
now** (too strict — 0/3 separation, beaten by the laptop judge); revisit with a tuned 20B.
The old instant `sumo-cheap-judge-9b` remains available via `SUMO_CHEAP_JUDGE`.

| Tier | Scope | Candidate (host) | Judge (host) | 4090? |
|---|---|---|---|---|
| cheap | gpt-4o-mini files | `gemma4-e4b-bounded` — bounded Gemma 4 e4b (4060) | `gemma4-12b-bounded` — bounded Gemma 4 12B (laptop), 92% gpt-5.5 agreement | no |
| reasoning | gpt-5-mini files | `gemma4-12b-bounded` — OWUI alias for bounded Gemma 4 12B on the laptop | `sumo-rjudge-20b` — gpt-oss:20b (4090) | yes |
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

`SUMO_EVAL_CONCURRENCY` sets promptfoo's `-j` (number of test cases in flight; defaults
**1** local, **4** cloud). Raising local `-j` looks tempting — overlap candidate-gen on one
host with judge-grading on the other — but on the single-GPU local tiers it **backfires**:
`-j>1` stacks several concurrent *reasoning* generations onto the one candidate GPU (and
grades onto the one judge GPU), which thrashes them. Verified 2026-06-08: at `-j 3` the
laptop reasoning candidate pegged and never finished a generation while the 4090 judge sat
idle. The gen/grade host-overlap can't be isolated from same-GPU stacking via `-j`, and the
reasoning models can't share a GPU, so **local stays `-j 1`**. Cloud has no single-GPU limit
(OpenAI's fleet) so its default is promptfoo's `4`, bounded only by the OpenAI rate-limit
(429), not compute.

### Reusable provider configs (`providers/`)

Candidate and judge providers are factored out of the test YAMLs into reusable
`providers/*.yaml` files and referenced through `file://` with an env-var override and a
**cloud default**. A test file pins its providers like this:

```yaml
providers:
  - file://{{ env.SUMO_EVAL_CANDIDATES_FILE | default('providers/cloud-reasoning-candidate.yaml') }}
defaultTest:
  options:
    provider: file://{{ env.SUMO_EVAL_JUDGE_FILE | default('providers/cloud-quality-judge.yaml') }}
```

With **no env vars set**, the file resolves to its cloud default → the same pinned
`gpt-5-mini`/`gpt-4o-mini` candidate + `gpt-5.5` judge as before, so the **cloud merge gate
is unchanged**. Setting `SUMO_EVAL_CANDIDATES_FILE` and/or `SUMO_EVAL_JUDGE_FILE` swaps in a
local pairing for the relative tiers — one switch per side, no per-file `--providers`/`--grader`
flags, and the judge provider is shared across every test so grading runs **concurrently** with
candidate generation across the two boxes.

| Provider file | Role | Model (host) |
|---|---|---|
| `cloud-quality-judge.yaml` | judge (default) | `gpt-5.5`, `response_format: json_object` — the merge gate |
| `cloud-reasoning-candidate.yaml` | candidate (default, reasoning files) | `gpt-5-mini` |
| `local-laptop-qwen-judge.yaml` | judge | `sumo-cheap-judge-9b` — qwen3.5:9b reasoning-off (laptop) |
| `local-4090-judge.yaml` | judge | `sumo-rjudge-20b` — gpt-oss:20b (4090) |
| `local-4060-gemma-candidate.yaml` | candidate | `gemma4-e4b-bounded` (4060) |
| `local-laptop-gemma-candidate.yaml` | candidate | `gemma4-12b-bounded` (laptop) |
| `local-gemma-candidates.yaml` | candidate list | both bounded Gemma 4 tags (laptop + 4060) |

`SUMO_OWUI_BASE` is interpolated into the local provider files' `apiBaseUrl`, and
`showThinking: false` keeps the judge grading clean `content` (no `<think>` channel). To run a
`.ab` control on a local pairing instead of the cloud gate:

```bash
# from the repo root (env-var paths resolve relative to the config file's dir, the -c path to cwd)
SUMO_EVAL_CANDIDATES_FILE=providers/local-4060-gemma-candidate.yaml \
SUMO_EVAL_JUDGE_FILE=providers/local-laptop-qwen-judge.yaml \
  ./node_modules/.bin/promptfoo eval -c tests/evals/promptfoo/skill-reviewing-before-merge-fence-parser.ab.yaml --repeat 3
```

### Validating the local judge (`validate-local-judge/`)

A local judge is only safe to trust as a *relative* signal if it tracks the cloud
judge's direction, discriminates a skill lift, and is repeatable — and those are per
`(model, num_ctx, GPU, build)`. **Re-run this whenever the local judge model or
hardware changes** (it's the executable form of "re-baseline on change"):

```bash
npm run eval:validate-judge                       # all checks, default sumo-cheap-judge-9b
npm run eval:validate-judge -- --mode determinism --reps 5
npm run eval:validate-judge -- --judge <model> --mode discrimination --pairs 12
```

It reads the local `~/.promptfoo/promptfoo.db` read-only, faithfully reconstructs the
exact `llm-rubric` prompt each cloud `gpt-5.5` row was graded with (promptfoo's own
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
- Full sweep of 16 skills: ~$0.10 per run with `seed: 42` determinism
- The `reviewing-before-merge-adversarial` corpus pins a `gpt-5-mini` candidate
  (reasoning tokens → a few cents per full run, still negligible) — see
  "Adversarial discovery corpus" above for why.

Running a single skill: pennies. Running all 16 skills with `--repeat 5`:
~$0.30 — still negligible, but worth tracking if you iterate frequently.

If cost becomes a concern, swap the judge to `gpt-4o-mini` in
`defaultTest.options.provider.id` (~5x cheaper, marginally less
adversarial).

## Architecture

All 16 skill YAMLs use `seed: 42` + `temperature: 0.0` for both candidate and judge providers, so runs are reproducible across machines. `disableVarExpansion: true` is set in defaultTest.options to prevent array vars (anti_patterns) from being expanded into per-element tests.

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
