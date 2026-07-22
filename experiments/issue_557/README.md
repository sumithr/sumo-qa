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

## Quality-constrained reduction sweep

The follow-up searched for a smaller reduction instead of assuming the 85%
cut was the right target.

| Candidate | Input-token effect | Valid quality evidence | Decision |
|---|---:|---:|---|
| Full skill plus deterministic response gate | 4.25% higher | 39/46 vs 40/46 baseline | Reject |
| Compact prompt | 85.41% lower | 31/46 vs 40/46 baseline; 12 regressions | Reject |
| Full root minus the optional ledger and scorecard appendices, with explicit routes back to the full skill | 6.69% lower | Corrected AC screen: 1/3 vs 2/3 full-skill baseline | Reject |

The routed candidate retained the original red flags, examples, process flow,
and every non-appendix instruction. It still regressed on the AC-UNMET case:
the response correctly blocked merge but classified changelog evidence as
`UNVERIFIED` where the unchanged rubric required `MET`. This is a shape failure,
not a reason to loosen the rubric.

The 6.69% figure is provider-reported generation usage across all 46 scenarios
(908,313 full-skill input tokens versus 847,554 routed input tokens). Those
usage records remain valid because the generation prompts were correct. The
first fallback quality sweep is invalid: the experiment serializer converted
structured anti-pattern lists to JSON strings, so the judge iterated their
characters. Its grades are not used here. The serializer now keeps rubric
lists native and stringifies only structured cold context inserted into the
candidate prompt; a regression test guards both representations.

A corrected exhaustive rerun could not complete: the target OpenAI account
returns `429 insufficient_quota`, and the Gemini fallback stopped returning
even a single judge result within six minutes. The fail-closed conclusion is
therefore: **no non-zero reduction is proven quality-neutral.** Production skill
content remains unchanged.

The balance rule for any next candidate is now explicit: route one
self-contained section at a time, rerun all 46 unchanged rubrics on the target
model, and accept only candidates with zero per-scenario regressions. Token
savings are optimized only inside that quality constraint.

## Regression-guided compact follow-up

A second compact candidate keeps the 4,131-character core and adds a
4,866-character precision-contract layer covering only the failure classes seen
in the 12 regressions: AC state/row discipline, executable-versus-inert scope,
A/B isolation, producer provenance, feature-flow evidence, absent memory,
fence-length discrimination, and readiness evidence.

The targeted independent screen is positive but is not yet the final proof:

| Measure | Full skill | Regression-guided compact | Result |
|---|---:|---:|---:|
| Candidate text | 72,563 characters | 8,997 characters | 87.60% lower |
| Provider input, same 12 scenarios | 232,038 tokens | 41,550 tokens | 82.09% lower |
| Provider input + completion | 237,837 tokens | 48,953 tokens | 79.42% lower |
| Unchanged-rubric targeted screen | N/A | 12/12 passed | all original regressions repaired |
| First-attempt deterministic validation | N/A | 11/12 | one repairable envelope-status mismatch |

The provider-token comparison uses the same 12 scenario prompts and
`google:gemini-3.1-pro-preview` for full-skill and repaired-candidate generation.
The earlier full-skill generation usage remains valid: the prior Gemini defect
was confined to rubric-list serialization during grading, not candidate prompt
generation. The repaired responses were graded with the corrected native-list
serialization and the original rubrics unchanged.

This result does not supersede `NOT PROVEN`. The target OpenAI account still
returns `429 insufficient_quota`, and Gemini reached the project's monthly
spending cap before the remaining 34 scenarios could complete. The acceptance
bar remains all 46 scenarios with zero per-scenario regressions on the target
model. Production skill content remains unchanged until that run succeeds.

## ChatGPT subscription rerun

`run_subscription_eval.py` reruns the same 46 scenarios through isolated
`codex exec` sessions authenticated by the existing ChatGPT subscription. It
removes `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `CODEX_API_KEY` from every child
process, requires `codex login status` to report ChatGPT authentication, runs
ephemerally in a read-only sandbox, rejects tool-use events, and writes resumable
JSON evidence after every scenario.

The judge now receives the scenario ground truth as well as the unchanged rubric.
This prevents memory-present and memory-absent cases from being graded without
the context needed to distinguish them. Reused baseline outputs are regraded with
the same grounded judge as candidates.

The latest complete subscription run preceded the final four contract repairs:

| Measure | Full skill | Regression-guided compact | Result |
|---|---:|---:|---:|
| Static candidate text | 72,563 characters | 14,834 characters | 79.56% lower |
| Generation input | 1,483,174 tokens | 1,070,031 tokens | 27.86% lower |
| First-attempt generation input | 1,483,174 tokens | 824,631 tokens | 44.40% lower |
| Deterministic-envelope repair input | N/A | 245,400 tokens across 13 repairs | reduces net saving |
| Unchanged-rubric passes | 37/46 | 39/46 | candidate has four regressions |

Those four failures were repaired and rerun alone through the subscription
harness. All four preserved or improved their baseline grade, with 44.92% lower
generation input on that subset. This targeted pass is not a replacement for a
new 46-scenario run, so the overall result remains `NOT PROVEN`.

Run the complete subscription comparison without provider API credentials:

```zsh
env -u OPENAI_API_KEY -u GEMINI_API_KEY -u CODEX_API_KEY \
  .venv/bin/python -m experiments.issue_557.run_subscription_eval \
  --output /private/tmp/issue557-subscription/evidence.json \
  --workers 3 --fresh
```

The default subscription model is `gpt-5.6-luna` with low reasoning effort.
Judge usage is excluded from the reported generation-token comparison but remains
present in the raw evidence.

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
