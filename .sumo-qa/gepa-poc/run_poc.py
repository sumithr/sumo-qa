"""GEPA POC entrypoint.
Usage: venv/bin/python run_poc.py --metric-calls 20 [--run-dir runs/...]
Resume: pass the SAME --run-dir; gepa reloads its checkpoint state.
"""

import argparse
import json
import time
from pathlib import Path

import adapter
import gepa
import reflect
import scoring
import scratch

POC = Path(__file__).resolve().parent

# Trainset = the regular reviewing-before-merge files; core + verifier-evidence + core .ab
# are reserved for the validation set (Pareto selection / promotion checks).
REGULAR = [
    "skill-reviewing-before-merge-ac-coverage.yaml",
    # adversarial.yaml EXCLUDED from trainset: 13 tests/instance = ~18 min per minibatch
    # (measured 1083s) vs 1-3 tests for every other file — it dominates rollout cost.
    # Still covered at final validation (full-suite + cloud gate).
    "skill-reviewing-before-merge-doc-drift.yaml",
    "skill-reviewing-before-merge-eval-validity.yaml",
    "skill-reviewing-before-merge-external-contract.yaml",
    "skill-reviewing-before-merge-feature-flow.yaml",
    "skill-reviewing-before-merge-feedback-memory.yaml",
    "skill-reviewing-before-merge-fence-parser.yaml",
    "skill-reviewing-before-merge-guard-coverage.yaml",
    "skill-reviewing-before-merge-ledger.yaml",
    "skill-reviewing-before-merge-mapping-gap.yaml",
    "skill-reviewing-before-merge-repo-map.yaml",
    "skill-reviewing-before-merge-unproven-escalation.yaml",
    "skill-reviewing-before-merge-vacuous-test.yaml",
]
VALSET = [
    {"yaml": "skill-reviewing-before-merge.yaml", "kind": "regular"},
    {"yaml": "skill-reviewing-before-merge-verifier-evidence.yaml", "kind": "regular"},
    {"yaml": "skill-reviewing-before-merge.ab.yaml", "kind": "ab"},
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric-calls", type=int, required=True)
    ap.add_argument("--run-dir", default=None)
    ap.add_argument(
        "--seed-file",
        default=None,
        help="start from this candidate (e.g. a prior run's best_skill.md); "
        "token denominator stays the ORIGINAL skill per protocol",
    )
    args = ap.parse_args()

    sha_before = scratch.primary_sha()
    scratch.build_scratch()
    seed = scratch.seed_text()
    seed_tokens = scoring.token_count(seed)  # ALWAYS the original denominator
    if args.seed_file:
        seed = Path(args.seed_file).read_text(encoding="utf-8")
        print(f"seeding from {args.seed_file}: {scoring.token_count(seed)} tokens")
    run_dir = args.run_dir or str(POC / "runs" / time.strftime("%Y%m%d-%H%M%S"))
    print(f"seed tokens={seed_tokens}  target<={seed_tokens // 2}  run_dir={run_dir}")

    result = gepa.optimize(
        seed_candidate={"skill_md": seed},
        trainset=[{"yaml": y, "kind": "regular"} for y in REGULAR],
        valset=VALSET,
        adapter=adapter.PromptfooAdapter(seed_tokens),
        reflection_lm=reflect.reflection_lm,
        max_metric_calls=args.metric_calls,
        reflection_minibatch_size=1,
        run_dir=run_dir,
        display_progress_bar=True,
    )

    best = result.best_candidate["skill_md"]
    best_tokens = scoring.token_count(best)
    Path(run_dir, "best_skill.md").write_text(best, encoding="utf-8")
    summary = {
        "seed_tokens": seed_tokens,
        "best_tokens": best_tokens,
        "reduction_pct": round(100 * (1 - best_tokens / seed_tokens), 1),
        "total_metric_calls": result.total_metric_calls,
        "num_candidates": result.num_candidates,
    }
    Path(run_dir, "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    assert scratch.primary_sha() == sha_before, (
        "PRIMARY REPO SKILL.md CHANGED — investigate before doing ANYTHING else"
    )
    print("primary repo untouched OK")


if __name__ == "__main__":
    main()
