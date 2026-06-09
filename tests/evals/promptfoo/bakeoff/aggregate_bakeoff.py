#!/usr/bin/env python3
"""Score the bake-off JSONs: per (candidate, judge) combo, how close to the gpt-defined
A0-FAIL / A1-PASS split on the binary-lift controls. Reads tests/evals/results/bakeoff/*.json
(promptfoo --output), pairs arms by prompt label, reports separation / score-rank / determinism.

A combo's verdicts are "close to gpt" when, per control, it FAILS the A0 (pre-fix) arm and
PASSES the A1 (post-fix) arm — the lift the cloud judge produces by construction. We score that
over --repeat reps (majority vote) and flag any arm whose verdict flips across reps."""

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "results/bakeoff"


def arm(label):
    h = (label or "").strip().upper()[:2]
    return h if h in ("A0", "A1") else None


def rows(j):
    r = j.get("results", j)
    return r.get("results", []) if isinstance(r, dict) else (r if isinstance(r, list) else [])


def grade(row):
    gr = row.get("gradingResult") or {}
    return gr.get("pass"), gr.get("score")


def maj(xs, val):
    """Majority vote: more than half of xs equal val (by identity)."""
    return sum(1 for x in xs if x is val) > len(xs) / 2


def main():
    files = sorted(OUT.glob("*__*__*.json"))
    if not files:
        sys.exit(f"no bake-off JSON in {OUT} — run run-bakeoff.sh first")
    combos = defaultdict(
        lambda: {"sep_ok": 0, "pairs": 0, "rank_ok": 0, "flips": 0, "unparsable": 0}
    )
    for f in files:
        try:
            ctrl, cand, judge = f.stem.split("__")
        except ValueError:
            continue
        j = json.loads(f.read_text())
        # group reps by (control, test identity, arm) -> list of (pass, score)
        arms = defaultdict(lambda: {"A0": [], "A1": []})
        for row in rows(j):
            lbl = (row.get("prompt") or {}).get("label") or row.get("promptLabel")
            a = arm(lbl)
            if not a:
                continue
            # Seed identity = the resolved VARS, hashed. A seed's A0/A1 arms share identical vars
            # (the arm differs only in the PROMPT) but distinct seeds differ in vars — so this
            # groups A0/A1 of one seed AND keeps separate seeds apart. Do NOT key on testCase:
            # its `description` encodes the arm ("A0 ..."/"A1 ...") for fence-parser-style controls,
            # which would split A0/A1 into separate groups; and the earlier testCase[:160] key
            # collided the two unproven-escalation seeds via their shared assertion prefix.
            desc = row.get("vars") or {}
            tid = hashlib.sha1(json.dumps(desc, sort_keys=True).encode()).hexdigest()
            arms[(ctrl, tid)][a].append(grade(row))
        c = combos[(cand, judge)]
        for _, v in arms.items():
            if not v["A0"] or not v["A1"]:
                continue
            c["pairs"] += 1
            a0p = [p for p, _ in v["A0"]]
            a1p = [p for p, _ in v["A1"]]
            a0s = [s for _, s in v["A0"] if isinstance(s, (int, float))]
            a1s = [s for _, s in v["A1"] if isinstance(s, (int, float))]
            if None in a0p or None in a1p:
                c["unparsable"] += 1
            if maj(a1p, True) and maj(a0p, False):
                c["sep_ok"] += 1
            if a1s and a0s and (sum(a1s) / len(a1s)) > (sum(a0s) / len(a0s)):
                c["rank_ok"] += 1
            if len(set(a0p)) > 1 or len(set(a1p)) > 1:
                c["flips"] += 1
    table = []
    for (cand, judge), c in combos.items():
        n = max(c["pairs"], 1)
        table.append(
            {
                "candidate": cand,
                "judge": judge,
                "pairs": c["pairs"],
                "separation": f"{c['sep_ok']}/{c['pairs']}",
                "sep_pct": round(100 * c["sep_ok"] / n),
                "score_rank": f"{c['rank_ok']}/{c['pairs']}",
                "unstable_pairs": c["flips"],
                "unparsable_pairs": c["unparsable"],
            }
        )
    table.sort(
        key=lambda r: (r["sep_pct"], -r["unstable_pairs"], -r["unparsable_pairs"]), reverse=True
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(table, indent=2))
    print(
        f"{'candidate':14} {'judge':18} {'sep':>7} {'sep%':>5} {'rank':>6} {'unstbl':>7} {'unparse':>8}"
    )
    print("-" * 70)
    for r in table:
        print(
            f"{r['candidate']:14} {r['judge']:18} {r['separation']:>7} {r['sep_pct']:>5} "
            f"{r['score_rank']:>6} {r['unstable_pairs']:>7} {r['unparsable_pairs']:>8}"
        )
    print(f"\nsummary -> {OUT / 'summary.json'}")


if __name__ == "__main__":
    main()
