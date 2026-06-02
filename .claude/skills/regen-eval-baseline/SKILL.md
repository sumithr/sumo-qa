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

Pass **exactly one** config selector — either `--skill` (the base config) or `--config` (a suffixed scenario / `.ab.yaml` control / explicit path) — plus an optional `--label`.

1. **`--skill <name>`** — the base config `tests/evals/promptfoo/skill-<name>.yaml`. Resolves that file **exactly**; it never cross-matches a longer suffixed sibling (e.g. `--skill reviewing-before-merge` drives `skill-reviewing-before-merge.yaml`, NOT `skill-reviewing-before-merge-adversarial.yaml`). If the named config is absent the script lists the available configs.
2. **`--config <selector>`** — for a suffixed scenario config or an `.ab.yaml` A/B control. Accepts a bare stem (`skill-reviewing-before-merge-adversarial`), a filename including the double suffix (`skill-reviewing-before-merge-adversarial.ab.yaml`), or a full/relative path. Resolved **exactly** — a stem composes one filename and that file must exist; the resolver never falls back to a near-named neighbour, so a base name can't accidentally snapshot a suffixed sibling and vice-versa.
3. **`--label`** — short kebab-case tag for the snapshot, defaults to `baseline`. Past conventions in the dir: `baseline`, `postcut`, `greenfix`, or describe-the-change like `removability-gate`. The label is what makes two snapshots taken on the same day distinguishable.

The snapshot filename derives from the resolved config, not just `--skill`: a `.ab` infix becomes a hyphen in the slug (`skill-x-adversarial.ab.yaml` → `…-skill-x-adversarial-ab-<label>.json`), so the base config, its suffixed scenario, and its `.ab` control each snapshot to a distinct, non-colliding path and diff only against their own prior snapshots.

### Wrapper vs raw `promptfoo eval -c`

Use this wrapper (`--skill` / `--config`) whenever you want the **repeatable before/after snapshot** it exists to provide: it writes the dated JSON to `docs/qa/runs/eval-baselines/`, prints pass/fail, and diffs against the prior snapshot for the same config. That covers base configs, suffixed scenario configs, and `.ab.yaml` controls — drive all three through the wrapper so the baseline/postcut delta is preserved (don't hand-roll `npx promptfoo eval -c …` and lose the snapshot). Reach for **raw `promptfoo eval -c <path>`** only for flags the wrapper does not expose (e.g. `--repeat N` variance runs, `-j 1` legible logs, `generate dataset`) — see `tests/evals/promptfoo/README.md`. For a normal baseline/postcut capture, the wrapper is the supported path.

## Prerequisites the script will check

- `OPENAI_API_KEY` must be set in the environment. The harness reads it from `~/.config/promptfoo-keys.env` per `tests/evals/promptfoo/README.md`; tell the user to `source` that file if the script reports it missing. Never accept the key pasted in chat — both repo policy and the `feedback_never_handle_pasted_secrets` memory rule say so.
- The selected config must exist: `tests/evals/promptfoo/skill-<name>.yaml` for `--skill`, or the exact suffixed / `.ab.yaml` config for `--config`. If it doesn't, the script lists every available config so the user can pick again — it does not guess a near-named sibling.
- A snapshot at the target path already existing will block the run unless `--force` is passed. Don't pass `--force` reflexively — snapshots are evidence of past runs and silently clobbering them loses history.

## Run the script

```bash
# Base config:
python3 .claude/skills/regen-eval-baseline/scripts/run_baseline.py \
  --skill <skill-name> \
  --label <label>

# Suffixed scenario config (no rename to the base skill needed):
python3 .claude/skills/regen-eval-baseline/scripts/run_baseline.py \
  --config skill-reviewing-before-merge-adversarial \
  --label baseline

# .ab.yaml A/B control:
python3 .claude/skills/regen-eval-baseline/scripts/run_baseline.py \
  --config skill-reviewing-before-merge-adversarial.ab.yaml \
  --label postcut
```

The script:

1. Computes the snapshot path: `docs/qa/runs/eval-baselines/<today>-skill-<slug>-<label>.json` (the slug comes from the resolved config — see Inputs).
2. Runs `npx promptfoo eval` with `--no-cache` (so the snapshot reflects fresh judge calls, not stale cache hits) and writes the JSON output to that path.
3. Prints pass/fail counts.
4. If a prior snapshot for the same config exists, prints a delta — passed and failed counts vs the previous run.

## Reading the output

The pass/fail summary tells you the state of the snapshot. The delta tells you whether the most recent SKILL.md edit moved the needle. Three patterns to watch for:

- **Passes increased, failures decreased** — the edit helped. Keep it.
- **Passes decreased, failures increased** — the edit hurt. Investigate before reverting; the failure may be informative.
- **No change** — either the edit was outside the assertions' coverage, or the judge gave the same verdict on different reasoning. Read the JSON's per-test reasons before drawing conclusions.

## When FAILs appear

Don't propose loosening the rubric. The standing repo policy (`feedback_eval_fixes_target_skill_not_rubric`) is to strengthen the SKILL.md so the candidate naturally satisfies the existing rubric. Hand the failing snapshot to the `eval-failure-diagnoser` subagent — it reads the JSON, locates the failing assertion, and recommends a concrete SKILL.md edit. Re-run this skill after the edit to confirm the failure flipped.

## Why the snapshots are gitignored

`docs/qa/` is excluded from the repo (`.gitignore` line 48). Eval snapshots are local evidence — useful for the contributor doing the optimisation work, but not artefact that ships with the package. Per `feedback_no_process_artifacts_in_public_repo`, results live alongside the QA work, not in the public source tree. Don't propose committing snapshots or removing the gitignore entry.
