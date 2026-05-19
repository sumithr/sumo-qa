---
name: regen-eval-baseline
description: Captures a promptfoo skill-eval baseline JSON for one sumo-qa skill and snapshots it to docs/qa/runs/eval-baselines/, with an automatic delta against the prior snapshot. Use this whenever the user mentions baselining a skill, capturing a before/after eval, running a single-skill eval, or measuring the effect of a SKILL.md edit — common during token-optimisation rounds. The actual work runs through a bundled script that handles path conventions, API-key checks, and diffing in one go.
disable-model-invocation: true
---

# regen-eval-baseline

Captures a promptfoo run for one sumo-qa skill and stores its JSON output in `docs/qa/runs/eval-baselines/` (gitignored). The deterministic work lives in `scripts/run_baseline.py`; this document is the guide for picking inputs and reading the output.

## When to use

Trigger this skill when the user wants a per-skill eval snapshot. Common phrasings: "baseline this skill", "snapshot the eval", "run the eval for skill X", "capture before/after for the rewrite I just made". The user invokes it explicitly with `/regen-eval-baseline`; it doesn't auto-trigger.

This is single-skill on purpose. Full-sweep regeneration belongs on `npm run eval:all`, which also reads the same `tests/evals/promptfoo/skill-*.yaml` files but runs them sequentially without snapshotting.

## Inputs

1. **Skill name** — matches `tests/evals/promptfoo/skill-<name>.yaml`. If the user is unsure which skills are available, the script will list them when given a bad name.
2. **Label** — short kebab-case tag for the snapshot, defaults to `baseline`. Past conventions in the dir: `baseline`, `postcut`, `greenfix`, or describe-the-change like `removability-gate`. The label is what makes two snapshots taken on the same day distinguishable.

## Prerequisites the script will check

- `OPENAI_API_KEY` must be set in the environment. The harness reads it from `~/.config/promptfoo-keys.env` per `tests/evals/promptfoo/README.md`; tell the user to `source` that file if the script reports it missing. Never accept the key pasted in chat — both repo policy and the `feedback_never_handle_pasted_secrets` memory rule say so.
- `tests/evals/promptfoo/skill-<name>.yaml` must exist. If it doesn't, the script lists every skill that does have a YAML so the user can pick again.
- A snapshot at the target path already existing will block the run unless `--force` is passed. Don't pass `--force` reflexively — snapshots are evidence of past runs and silently clobbering them loses history.

## Run the script

```bash
python3 .claude/skills/regen-eval-baseline/scripts/run_baseline.py \
  --skill <skill-name> \
  --label <label>
```

The script:

1. Computes the snapshot path: `docs/qa/runs/eval-baselines/<today>-skill-<skill>-<label>.json`.
2. Runs `npx promptfoo eval` with `--no-cache` (so the snapshot reflects fresh judge calls, not stale cache hits) and writes the JSON output to that path.
3. Prints pass/fail counts.
4. If a prior snapshot for the same skill exists, prints a delta — passed and failed counts vs the previous run.

## Reading the output

The pass/fail summary tells you the state of the snapshot. The delta tells you whether the most recent SKILL.md edit moved the needle. Three patterns to watch for:

- **Passes increased, failures decreased** — the edit helped. Keep it.
- **Passes decreased, failures increased** — the edit hurt. Investigate before reverting; the failure may be informative.
- **No change** — either the edit was outside the assertions' coverage, or the judge gave the same verdict on different reasoning. Read the JSON's per-test reasons before drawing conclusions.

## When FAILs appear

Don't propose loosening the rubric. The standing repo policy (`feedback_eval_fixes_target_skill_not_rubric`) is to strengthen the SKILL.md so the candidate naturally satisfies the existing rubric. Hand the failing snapshot to the `eval-failure-diagnoser` subagent — it reads the JSON, locates the failing assertion, and recommends a concrete SKILL.md edit. Re-run this skill after the edit to confirm the failure flipped.

## Why the snapshots are gitignored

`docs/qa/` is excluded from the repo (`.gitignore` line 48). Eval snapshots are local evidence — useful for the contributor doing the optimisation work, but not artefact that ships with the package. Per `feedback_no_process_artifacts_in_public_repo`, results live alongside the QA work, not in the public source tree. Don't propose committing snapshots or removing the gitignore entry.
