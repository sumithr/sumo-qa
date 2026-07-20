# Issue #557 result: PROVEN

A compact judgment prompt plus deterministic workflow/evidence validation used
fewer tokens and preserved or improved quality on the pinned merge-review set.

| Measure | Full review skill | Code-enforced candidate | Result |
|---|---:|---:|---:|
| Unchanged-rubric passes | 5/7 | 7/7 | +2 passes |
| Model input tokens | 131,941 | 28,478 | 78.42% lower |
| Candidate-generation input + completion | 158,321 | 50,591 | 68.05% lower |

The candidate exceeds the required 30% input-token reduction. Its fixed prompt
hash was `9474b648209700b68c97665a95a3d23af731a2c673a51d0016cc91496481387a`.
Candidate usage includes all nine provider attempts across seven scenarios,
including two deterministic repairs. Token totals exclude the rubric-judge calls
on both sides because those are eval-only and are not part of the deployed review
path.

The final comparator revalidates every stored raw response, requires positive and
internally consistent usage for every attempt, binds each graded output to the
validated review, and checks models, scenarios, variables, rubrics, judges, and
loaded context directly against the current pinned configs.

## What was compared

The baseline and candidate used the same scenario text, candidate models, seed,
and `gpt-5.5` rubric judges from the existing eval configs. The candidate
replaced only `skill_content`; loaded classifications/rules/techniques remained
unchanged. Candidate review prose was validated, stripped from its hidden gate
report, then graded with each original assertion, rubric prompt, judge and test
variables through Promptfoo's `echo` provider.

| Pinned group | Scenarios | Baseline input | Candidate input | Reduction | Baseline | Candidate |
|---|---:|---:|---:|---:|---:|---:|
| Core verdict | 1 | 17,877 | 1,696 | 90.51% | 0/1 | 1/1 |
| Adversarial discovery | 3 | 60,263 | 17,662 | 70.69% | 3/3 | 3/3 |
| Verifier evidence | 2 | 35,111 | 2,749 | 92.17% | 2/2 | 2/2 |
| Unproven escalation | 1 | 18,690 | 6,371 | 65.91% | 0/1 | 1/1 |

Every baseline pass remained a pass. Both baseline failures became passes:
core verdict `0.78 -> 1.00`, and unproven substring `0.82 -> 1.00`.

## Deterministic boundary

Code enforces only mechanics:

- typed `scope`, `risks`, and `verification` claims;
- evidence required for observed outcomes;
- no SAFE verdict while any gate is unresolved;
- exactly one supported verdict and no unsupported favourable claim.

The model still identifies risks, chooses techniques and discriminating inputs,
sets review depth, interprets evidence, and authors the verdict. Tests assert
that this model-owned prose is returned byte-for-byte.

The POC is isolated: it is not registered as an MCP tool and does not change the
default server or existing skill-loading behavior.

## Reproduce

Prerequisites are the project dev environment, Node 24, the repo-pinned
Promptfoo binary, and the same OpenAI key used by the existing cloud evals.

Generate the unchanged full-skill baselines:

```bash
./node_modules/.bin/promptfoo eval \
  -c tests/evals/promptfoo/skill-reviewing-before-merge.yaml \
  --filter-pattern '^SEED - auth helper fix with fresh passing tests$' \
  --no-cache --no-progress-bar --no-table -j 1 \
  --output /private/tmp/issue557-baseline-core.json
./node_modules/.bin/promptfoo eval \
  -c tests/evals/promptfoo/skill-reviewing-before-merge-adversarial.yaml \
  --filter-pattern 'weak-assertion|rollback-data-loss|NEGATIVE CONTROL docs-only typo' \
  --no-cache --no-progress-bar --no-table -j 1 \
  --output /private/tmp/issue557-baseline-adversarial.json
./node_modules/.bin/promptfoo eval \
  -c tests/evals/promptfoo/skill-reviewing-before-merge-verifier-evidence.yaml \
  --filter-pattern 'missing-verifier|discharged' \
  --no-cache --no-progress-bar --no-table -j 1 \
  --output /private/tmp/issue557-baseline-verifier.json
./node_modules/.bin/promptfoo eval \
  -c tests/evals/promptfoo/skill-reviewing-before-merge-unproven-escalation.yaml \
  --filter-pattern 'unproven-substring' \
  --no-cache --no-progress-bar --no-table -j 1 \
  --output /private/tmp/issue557-baseline-unproven.json
```

Generate and validate compact outputs:

```bash
for group in core adversarial verifier unproven; do
  uv run python experiments/issue_557/run_candidate.py "$group" \
    --output-dir /private/tmp/issue557
done
```

Grade each generated output with its unchanged rubric:

```bash
for group in core adversarial verifier unproven; do
  ./node_modules/.bin/promptfoo eval \
    -c "/private/tmp/issue557/candidate-$group-grade-config.yaml" \
    --no-cache --no-progress-bar --no-table -j 1 \
    --output "/private/tmp/issue557/candidate-$group-grade.json"
done
```

Calculate the verdict:

```bash
uv run python -m experiments.issue_557.compare_results \
  --baseline-dir /private/tmp \
  --candidate-dir /private/tmp/issue557
```

## Limits

This proves the approach on seven load-bearing review scenarios, not every
sumo-qa behavior or host. The gate report validates structure and cited evidence;
it cannot independently prove that a model-authored observation is truthful.
Production adoption would need a host integration that supplies observed tool
evidence rather than trusting the model to describe it.
