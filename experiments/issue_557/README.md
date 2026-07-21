# Issue #557 result: NOT PROVEN

The compact review prompt reduces tokens substantially, but it does not preserve
the full review skill's quality across the existing review behavior corpus.

| Measure | Full review skill | Compact code-gated candidate | Result |
|---|---:|---:|---:|
| Unchanged-rubric passes | 40/46 | 31/46 | 9 fewer passes |
| Per-scenario quality regressions | 0 | 12 | quality criterion failed |
| Model input tokens | 865,740 | 126,342 | 85.41% lower |
| Candidate-generation input + completion | 1,079,443 | 291,169 | 73.03% lower |

The token target was met, but the acceptance criterion requires quality to be
preserved on every load-bearing rubric. The final verdict is therefore
`NOT PROVEN`. Do not roll this design into production.

## What was measured

The exhaustive comparison covers every non-control
`skill-reviewing-before-merge*.yaml` behavior config:

- 19 configs and 46 scenarios;
- the same scenario prompts, variables, candidate models, seed, assertions,
  rubric prompts, and `gpt-5.5` judges;
- a fresh no-cache full-skill baseline;
- a candidate prompt that differs from its baseline prompt only by replacing
  `skill_content` with `compact_review_prompt.md`;
- deterministic validation before the candidate review is passed to the
  unchanged Promptfoo rubric;
- provider-reported usage for all candidate attempts, including two repair
  attempts across the 46 scenarios.

All 46 corrected candidate outputs passed deterministic validation. All 13
integrity checks passed, including prompt substitution, config hashes, scenario
variables, models, rubrics, judge bindings, stored-response revalidation, and
token accounting.

The nine `.ab.yaml` configs are intentionally excluded. They are historical
controls whose test rows embed two or three fixed skill bodies. Replacing those
control bodies with one candidate would destroy the A/B question they measure.
Every current-skill behavior config was included.

## Per-config results

| Config | Scenarios | Baseline | Candidate | Regressions |
|---|---:|---:|---:|---:|
| ac-coverage | 3 | 3 | 1 | 2 |
| adversarial | 13 | 12 | 11 | 2 |
| base | 1 | 1 | 1 | 0 |
| coverage-artifact | 2 | 2 | 2 | 0 |
| doc-drift | 1 | 1 | 1 | 0 |
| eval-validity | 2 | 1 | 0 | 2 |
| external-contract | 3 | 2 | 1 | 2 |
| feature-flow | 2 | 2 | 1 | 1 |
| feedback-memory | 2 | 2 | 1 | 1 |
| fence-parser | 1 | 1 | 0 | 1 |
| guard-coverage | 2 | 2 | 2 | 0 |
| ledger | 1 | 0 | 0 | 0 |
| mapping-gap | 1 | 1 | 1 | 0 |
| repo-map | 1 | 1 | 1 | 0 |
| scorecard | 2 | 1 | 0 | 1 |
| security-relevance | 2 | 2 | 2 | 0 |
| unproven-escalation | 2 | 2 | 2 | 0 |
| vacuous-test | 2 | 1 | 1 | 0 |
| verifier-evidence | 3 | 3 | 3 | 0 |

The 12 per-scenario regressions include baseline passes that became failures and
baseline failures whose score decreased. The lost behaviors include acceptance
criteria coverage, executable-hook discovery, benign-config negative control,
eval-validity reasoning, internal-versus-external producer discrimination,
feature-flow evidence, absent-memory handling, fence-parser discrimination, and
stale-evidence scorecard handling.

## Why the original seven-case result was insufficient

The earlier report selected only 7 of the 46 behavior scenarios from four
configs. It showed that a small prompt could perform well on those selected
cases, not that it preserved the review skill. It also left `skill_content`
overrides at the test-row level unguarded when the harness was generalized.

The exhaustive harness now enforces the substitution after all config and test
variables are resolved. A test proves that every candidate prompt equals the
matching full-skill prompt with only the skill body replaced. This prevents an
eval from silently falling back to the original skill.

## Deterministic boundary

Code still enforces mechanics only:

- typed `scope`, `risks`, and `verification` claims;
- evidence for observed outcomes;
- no SAFE verdict while a gate is unresolved;
- exactly one supported verdict and no unsupported favorable claim.

The model still identifies risks, chooses techniques and discriminating inputs,
sets review depth, interprets evidence, and writes the recommendation. The
negative result therefore comes from lost model guidance, not server code
making the QA judgments.

The POC remains isolated. It is not registered as an MCP tool and does not
change the default server, skill, installer, host configuration, or routing.

## Evidence and revisions

- Baseline source revision: `d9aecf6` (`origin/main` when captured).
- Candidate branch parent before the exhaustive harness: `e885797`.
- Compact prompt SHA-256:
  `9474b648209700b68c97665a95a3d23af731a2c673a51d0016cc91496481387a`.
- Promptfoo: repo-pinned `0.121.11`, cache disabled, concurrency 1.
- Candidate and judge seeds: `42` from the existing configs.
- Local evidence directory for this run:
  `/private/tmp/issue557-full-DyskLM`.

## Reproduce

Use Node 24, the project Python environment, the repo-pinned Promptfoo binary,
and the existing Promptfoo key file.

Capture every current-skill behavior baseline:

```zsh
ISSUE557_EVIDENCE=/private/tmp/issue557-full
mkdir -p "$ISSUE557_EVIDENCE/baseline" "$ISSUE557_EVIDENCE/candidate"
source ~/.config/promptfoo-keys.env
for config in tests/evals/promptfoo/skill-reviewing-before-merge*.yaml; do
  [[ "$config" == *.ab.yaml ]] && continue
  name=${config:t}
  suffix=${${name%.yaml}#skill-reviewing-before-merge}
  suffix=${suffix#-}
  [[ -z "$suffix" ]] && suffix=base
  ./node_modules/.bin/promptfoo eval -c "$config" \
    --no-cache --no-progress-bar --no-table -j 1 \
    --output "$ISSUE557_EVIDENCE/baseline/issue557-baseline-full-$suffix.json"
done
```

Generate and validate all compact candidates:

```zsh
.venv/bin/python experiments/issue_557/run_candidate.py \
  --all-review --output-dir "$ISSUE557_EVIDENCE/candidate"
```

Grade every validated review with its unchanged rubric:

```zsh
for config in "$ISSUE557_EVIDENCE"/candidate/candidate-full-*-grade-config.yaml; do
  name=${config:t}
  group=${name%-grade-config.yaml}
  ./node_modules/.bin/promptfoo eval -c "$config" \
    --no-cache --no-progress-bar --no-table -j 1 \
    --output "$ISSUE557_EVIDENCE/candidate/$group-grade.json"
done
```

Calculate the fail-closed result:

```zsh
.venv/bin/python -m experiments.issue_557.compare_results \
  --all-review \
  --baseline-dir "$ISSUE557_EVIDENCE/baseline" \
  --candidate-dir "$ISSUE557_EVIDENCE/candidate"
```
