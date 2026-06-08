#!/usr/bin/env python3
"""Validate a LOCAL promptfoo judge against the STORED cloud verdicts.

Why this exists: the local cheap-tier judge is only trustworthy as a RELATIVE
signal if it (a) tracks the cloud judge's direction, (b) discriminates a skill
lift, and (c) is repeatable. Those properties are per (model, num_ctx, GPU,
build) — so re-run this whenever the local judge model or hardware changes.

Three checks (default: all), all read-only on the promptfoo DB and re-graded via
the OpenWebUI proxy with a faithful prompt reconstruction (render.js):

  agreement      Re-grade a balanced sample of cheap-tier rows (cloud-graded by
                 --cloud-judge) and report verdict-for-verdict agreement +
                 confusion matrix. NOTE: absolute agreement is expected to be
                 modest — the local judge is a RELATIVE signal, not a cloud clone.
  discrimination On gpt-5.5-SEPARATED A0/A1 control pairs, does the local judge
                 keep the pass/fail split and rank A1 (skill-on) above A0? This
                 is the fitness metric that actually matters for relative lift.
  determinism    Re-grade identical inputs K times; verdict + score stability.
                 (Relative lift only cancels judge error if the judge is stable.)

Reports (JSON) -> tests/evals/results/judge-validation/ (gitignored).

Usage (via run.sh, which sources the OWUI key):
  bash run.sh                              # all checks, default judge
  bash run.sh --judge sumo-cheap-judge-9b --mode determinism --reps 5
  bash run.sh --mode discrimination --pairs 12
Env: OPENWEBUI_API_KEY (required), SUMO_OWUI_BASE (default below).
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent  # repo/tests/evals/promptfoo/validate-local-judge
REPO = HERE.parents[3]  # parents: promptfoo, evals, tests, repo
RENDER_JS = HERE / "render.js"


def parse_args():
    p = argparse.ArgumentParser(
        description="Validate a local promptfoo judge vs stored cloud verdicts."
    )
    p.add_argument(
        "--judge", default="sumo-cheap-judge-9b", help="local OWUI judge model id to validate"
    )
    p.add_argument(
        "--cloud-judge", default="openai:chat:gpt-5.5", help="stored cloud judge id (ground truth)"
    )
    p.add_argument(
        "--candidate",
        default="openai:chat:gpt-4o-mini",
        help="cheap-tier candidate id for agreement baselines",
    )
    p.add_argument(
        "--owui-base", default=os.environ.get("SUMO_OWUI_BASE", "http://192.168.50.3:3535/api")
    )
    p.add_argument("--db", default=os.path.expanduser("~/.promptfoo/promptfoo.db"))
    p.add_argument(
        "--mode", choices=["all", "agreement", "discrimination", "determinism"], default="all"
    )
    p.add_argument(
        "--sample-per", type=int, default=5, help="agreement: rows per skill per class (PASS/FAIL)"
    )
    p.add_argument(
        "--skills",
        nargs="*",
        default=[
            "implementing-with-tdd",
            "reviewing-before-merge",
            "answering-testing-question",
            "preparing-for-work",
        ],
        help="agreement: skills to sample",
    )
    p.add_argument("--pairs", type=int, default=12, help="discrimination: number of A0/A1 pairs")
    p.add_argument("--reps", type=int, default=5, help="determinism: re-grades per row")
    p.add_argument("--det-rows", type=int, default=12, help="determinism: number of varied rows")
    p.add_argument("--out", default=str(REPO / "tests/evals/results/judge-validation"))
    p.add_argument("--timeout", type=int, default=180, help="per-call OWUI timeout (s)")
    return p.parse_args()


# ---------- OWUI ----------
def make_owui(base, key, timeout):
    def owui(prompt, model):
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 8000,
            }
        ).encode()
        last = None
        # backoff tolerant of a big-model COLD LOAD on the 4090 (a 20b can take
        # >60s to load; OWUI 400s while it loads). 10/20/30/40/50s ≈ 150s total.
        for attempt in range(6):
            try:
                req = urllib.request.Request(
                    f"{base}/chat/completions",
                    data=body,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except Exception as ex:
                last = ex
                time.sleep(10 * (attempt + 1))
                sys.stderr.write(f"[retry {attempt + 1}] {ex}\n")
        raise last

    return owui


def extract_verdict(text):
    cands = re.findall(r"\{.*?\}", text, re.DOTALL)
    if "{" in text and "}" in text:
        cands.append(text[text.find("{") : text.rfind("}") + 1])
    for m in cands:
        try:
            o = json.loads(m)
            if "pass" in o:
                return bool(o.get("pass")), o.get("score")
        except Exception:
            pass
    return None, None


# ---------- DB ----------
def connect(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def llm_rubric_component(gr):
    for c in gr.get("componentResults", []):
        if (c.get("assertion") or {}).get("type") == "llm-rubric":
            return c
    return None


SKILL_NAMES = [
    "implementing-with-tdd",
    "reviewing-before-merge",
    "preparing-for-work",
    "creating-test-plan",
    "answering-testing-question",
    "strategising",
    "planning-qa-rollout",
    "finding-test-data",
]


def skill_of(desc):
    for s in SKILL_NAMES:
        if s in (desc or ""):
            return s
    return "?"


def iter_graded_rows(con, cloud_judge, *, candidate=None, like_any=None, limit=None):
    """Yield re-gradable rows from cloud-graded evals as
    {id, idx, desc, plabel, tmpl, output, rubric, vars, g55} — the SINGLE source of the
    row shape, shared by all three checks. `plabel` is the prompt's LABEL (e.g.
    'A0 — no skill...'), so the discrimination check can pair by prompt IDENTITY rather
    than inferring A0/A1 from the verdict. `candidate` filters to one cheap-tier candidate;
    `like_any` ORs a set of description LIKE patterns; `limit` caps the evals scanned."""
    where = ["json_extract(config,'$.defaultTest.options.provider.id')=?"]
    params = [cloud_judge]
    if candidate:
        where.append("json_extract(config,'$.providers[0].id')=?")
        params.append(candidate)
    if like_any:
        where.append("(" + " OR ".join("description LIKE ?" for _ in like_any) + ")")
        params += list(like_any)
    sql = (
        f"SELECT id, description, config FROM evals WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC" + (f" LIMIT {int(limit)}" if limit else "")
    )
    for e in con.execute(sql, params).fetchall():
        tmpl = json.loads(e["config"])["defaultTest"]["options"].get("rubricPrompt")
        if not tmpl:
            continue
        for r in con.execute(
            "SELECT test_idx,prompt,test_case,response,grading_result "
            "FROM eval_results WHERE eval_id=?",
            (e["id"],),
        ):
            if not r["grading_result"] or not r["response"]:
                continue
            c = llm_rubric_component(json.loads(r["grading_result"]))
            if not c:
                continue
            try:
                plabel = json.loads(r["prompt"]).get("label") if r["prompt"] else None
            except Exception:
                plabel = None
            yield {
                "id": e["id"],
                "idx": r["test_idx"],
                "desc": e["description"] or "",
                "plabel": plabel,
                "tmpl": tmpl,
                "output": json.loads(r["response"]).get("output", ""),
                "rubric": (c.get("assertion") or {}).get("value", ""),
                "vars": json.loads(r["test_case"]).get("vars", {}),
                "g55": bool(c.get("pass")),
            }


# ---------- faithful render ----------
def reconstruct_prompt(workdir, tag, template, raw_rubric, vars_, output):
    raw_path = workdir / f"raw_{tag}.json"
    out_path = workdir / f"prompt_{tag}.txt"
    raw_path.write_text(
        json.dumps(
            {"template": template, "raw_rubric": raw_rubric, "vars": vars_, "output": output}
        )
    )
    res = subprocess.run(
        ["node", str(RENDER_JS), str(raw_path), str(out_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    residual = "residual: 0" not in res.stdout
    return out_path.read_text(), residual


def _tag(prefix, row, *extra):
    code = row["id"].split("-")[1] if "-" in row["id"] else row["id"]
    return "_".join([prefix, code, str(row["idx"]), *map(str, extra)])


def grade_prompt(owui, judge, prompt):
    """One graded call: returns (pass, score) from the judge's verdict."""
    resp = owui(prompt, judge)
    return extract_verdict(resp["choices"][0]["message"].get("content") or "")


def grade_row(owui, judge, workdir, tag, row):
    """Reconstruct the faithful prompt for a row and grade it once -> (pass, score, residual)."""
    prompt, residual = reconstruct_prompt(
        workdir, tag, row["tmpl"], row["rubric"], row["vars"], row["output"]
    )
    cp, sc = grade_prompt(owui, judge, prompt)
    return cp, sc, residual


# ---------- checks ----------
def run_agreement(con, owui, args, workdir):
    pool = [
        dict(r, skill=skill_of(r["desc"]))
        for r in iter_graded_rows(con, args.cloud_judge, candidate=args.candidate)
    ]
    # balanced sample: N PASS + N FAIL per requested skill
    sample = []
    for sk in args.skills:
        ps = [x for x in pool if x["skill"] == sk and x["g55"]][: args.sample_per]
        fs = [x for x in pool if x["skill"] == sk and not x["g55"]][: args.sample_per]
        sample += ps + fs
    print(
        f"[agreement] pool={len(pool)} rows; sample={len(sample)} "
        f"({sum(x['g55'] for x in sample)}P/{sum(not x['g55'] for x in sample)}F)",
        flush=True,
    )
    rows = []
    for i, x in enumerate(sample):
        cp, sc, residual = grade_row(owui, args.judge, workdir, _tag("agr", x, i), x)
        rows.append(
            {"skill": x["skill"], "g55": x["g55"], "local": cp, "score": sc, "residual": residual}
        )
        mark = "OK " if cp == x["g55"] else "FLIP"
        print(
            f"  [{i + 1:2}/{len(sample)}] {x['skill'][:22]:22} g55={'P' if x['g55'] else 'F'} "
            f"local={'P' if cp else ('F' if cp is not None else '?')} {mark}",
            flush=True,
        )
    ok = [r for r in rows if r["local"] is not None]
    agree = sum(1 for r in ok if r["local"] == r["g55"])
    pf = sum(1 for r in ok if r["g55"] and not r["local"])
    fp = sum(1 for r in ok if not r["g55"] and r["local"])
    summary = {
        "n": len(rows),
        "parsed": len(ok),
        "agreement": agree,
        "agreement_pct": round(100 * agree / len(ok)) if ok else None,
        "pass_to_fail_flips": pf,
        "fail_to_pass_flips": fp,
        "residual_renders": sum(1 for r in rows if r["residual"]),
    }
    print(
        f"[agreement] {agree}/{len(ok)} = {summary['agreement_pct']}%  "
        f"(PASS->FAIL {pf}, FAIL->PASS {fp})\n",
        flush=True,
    )
    return {"summary": summary, "rows": rows}


def ab_arm(label):
    """Map a prompt LABEL to its control arm by reading prompt IDENTITY, never the verdict.
    'A0 — no skill, no catalogues' -> 'A0'; 'A1 - post-296 body (new)' -> 'A1'. Returns None
    for the 'B — full skill' arm and for single-prompt probe configs (whose 'label' is the raw
    prompt text), so only genuine A0/A1 arms can be paired. The arm digit must be followed by a
    non-alphanumeric boundary (space/dash/em-dash) or end-of-label, so 'A10' or 'A0probe' do
    NOT match the 'A1'/'A0' arms."""
    head = (label or "").strip().upper()
    arm = head[:2]
    if arm in ("A0", "A1") and (len(head) == 2 or not head[2].isalnum()):
        return arm
    return None


def discrimination_pairs(con, args):
    # A gpt-5.5-SEPARATED pair = the SAME test where the cloud judge PASSED the A1 (skill-on)
    # prompt and FAILED the A0 (skill-off) prompt. Pair by PROMPT IDENTITY (label), not by
    # verdict: the old %probe%/%control% filters also matched single-prompt probe configs, and
    # labelling one-PASS/one-FAIL outputs A1/A0 from their verdicts could pair arbitrary prompt
    # variants — or two reps of the SAME prompt that the cloud judge graded differently —
    # corrupting the lift signal. We restrict to the genuine A0/A1 control families and read
    # the A0/A1 arm from each row's prompt label.
    arms = {}  # (eval_id, test_idx) -> {"A0": row|None, "A1": row|None}
    for r in iter_graded_rows(
        con,
        args.cloud_judge,
        like_any=["%A/B/C value-measurement%", "%A0/A1 control%", "%discovery-lift measurement%"],
    ):
        arm = ab_arm(r["plabel"])
        if arm is None:
            continue
        slots = arms.setdefault((r["id"], r["idx"]), {})
        if arm not in slots:
            slots[arm] = r
        elif slots[arm] is not None and slots[arm]["g55"] != r["g55"]:
            slots[arm] = None  # cloud disagreed with itself across reps -> not a clean arm
    pairs = []
    for (eid, idx), slots in arms.items():
        a0, a1 = slots.get("A0"), slots.get("A1")
        if a0 and a1 and a1["g55"] and not a0["g55"]:
            pairs.append({"eid": eid[:7], "idx": idx, "A1": a1, "A0": a0})
    return pairs


def run_discrimination(con, owui, args, workdir):
    pairs = discrimination_pairs(con, args)[: args.pairs]
    print(f"[discrimination] gpt-5.5-separated pairs tested: {len(pairs)}", flush=True)
    rows = []
    sep = 0
    ranked = 0
    for n, p in enumerate(pairs):
        a1p, a1s, _ = grade_row(owui, args.judge, workdir, _tag("disc", p["A1"], "A1", n), p["A1"])
        a0p, a0s, _ = grade_row(owui, args.judge, workdir, _tag("disc", p["A0"], "A0", n), p["A0"])
        preserved = a1p is True and a0p is False
        rank_ok = isinstance(a1s, (int, float)) and isinstance(a0s, (int, float)) and a1s > a0s
        sep += preserved
        ranked += rank_ok
        rows.append(
            {
                "eid": p["eid"],
                "idx": p["idx"],
                "A1_pass": a1p,
                "A1_score": a1s,
                "A0_pass": a0p,
                "A0_score": a0s,
                "separated": preserved,
            }
        )
        print(
            f"  {p['eid']} idx={p['idx']}: A1->{'P' if a1p else 'F' if a1p is not None else '?'}(s={a1s}) "
            f"A0->{'P' if a0p else 'F' if a0p is not None else '?'}(s={a0s}) "
            f"{'SEPARATED' if preserved else ('rank_ok' if rank_ok else 'COLLAPSED')}",
            flush=True,
        )
    summary = {"pairs": len(pairs), "separation_preserved": sep, "score_ranked": ranked}
    print(
        f"[discrimination] separation {sep}/{len(pairs)}, score-rank {ranked}/{len(pairs)}\n",
        flush=True,
    )
    return {"summary": summary, "rows": rows}


def run_determinism(con, owui, args, workdir):
    # varied spread of cheap-tier rows (mix of PASS/FAIL by gpt-5.5); limit scan — we only need a few
    pool = list(iter_graded_rows(con, args.cloud_judge, candidate=args.candidate, limit=60))
    half = args.det_rows // 2
    spread = [x for x in pool if x["g55"]][:half] + [x for x in pool if not x["g55"]][
        : args.det_rows - half
    ]
    print(f"[determinism] {len(spread)} rows x {args.reps} reps", flush=True)
    rows = []
    stable = 0
    for i, x in enumerate(spread):
        # render ONCE, re-grade K times — the judge is the only nondeterminism we're measuring
        prompt, _ = reconstruct_prompt(
            workdir, _tag("det", x, i), x["tmpl"], x["rubric"], x["vars"], x["output"]
        )
        reps = [grade_prompt(owui, args.judge, prompt) for _ in range(args.reps)]
        passes = [r[0] for r in reps]
        scores = [r[1] for r in reps]
        sc = [s for s in scores if isinstance(s, (int, float))]
        unparsable = sum(1 for p in passes if p is None)
        # An unparsable verdict is a FAILURE, not a stable result. Without this guard a judge
        # that never emits valid verdict JSON gives passes=[None,...] -> one unique value
        # (counted "stable") with an empty score list (zero range) -> a false clean signal.
        st = unparsable == 0 and len(set(passes)) == 1
        sd = (max(sc) - min(sc)) if len(sc) > 1 else 0.0
        stable += st
        rows.append(
            {
                "passes": passes,
                "scores": scores,
                "stable": st,
                "score_range": sd,
                "unparsable": unparsable,
            }
        )
        print(
            f"  [{i + 1:2}/{len(spread)}] {''.join('P' if p else ('F' if p is not None else '?') for p in passes)} "
            f"scores={scores} {'STABLE' if st else 'FLIPS'}",
            flush=True,
        )
    summary = {
        "rows": len(spread),
        "reps": args.reps,
        "binary_stable_rows": stable,
        "rows_with_unparsable": sum(1 for r in rows if r["unparsable"]),
        "max_score_range": max((r["score_range"] for r in rows), default=0.0),
    }
    print(
        f"[determinism] binary-stable {stable}/{len(spread)}, "
        f"rows-with-unparsable {summary['rows_with_unparsable']}, "
        f"max score range {summary['max_score_range']}\n",
        flush=True,
    )
    return {"summary": summary, "rows": rows}


def main():
    args = parse_args()
    key = os.environ.get("OPENWEBUI_API_KEY")
    if not key:
        sys.exit(
            "ERROR: OPENWEBUI_API_KEY not set (run via run.sh, which sources ~/.config/owui.env)."
        )
    if not os.path.exists(args.db):
        sys.exit(f"ERROR: promptfoo DB not found: {args.db}")
    out = Path(args.out)
    (out / ".work").mkdir(parents=True, exist_ok=True)
    workdir = out / ".work"
    con = connect(args.db)
    owui = make_owui(args.owui_base, key, args.timeout)

    print(
        f"validate-local-judge: judge={args.judge} vs cloud={args.cloud_judge} via {args.owui_base}"
    )
    print(f"  warming {args.judge} ...", flush=True)
    owui("ok", args.judge)
    print("  ready\n", flush=True)

    report = {
        "judge": args.judge,
        "cloud_judge": args.cloud_judge,
        "candidate": args.candidate,
        "owui_base": args.owui_base,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    modes = ["agreement", "discrimination", "determinism"] if args.mode == "all" else [args.mode]
    if "agreement" in modes:
        report["agreement"] = run_agreement(con, owui, args, workdir)
    if "discrimination" in modes:
        report["discrimination"] = run_discrimination(con, owui, args, workdir)
    if "determinism" in modes:
        report["determinism"] = run_determinism(con, owui, args, workdir)

    report_path = out / f"report-{args.judge.replace(':', '_').replace('/', '_')}.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"report -> {report_path}")
    # headline verdict
    print("\n==== HEADLINE ====")
    if "agreement" in report:
        s = report["agreement"]["summary"]
        print(
            f"  absolute agreement vs cloud:  {s['agreement_pct']}% (relative signal — modest is expected)"
        )
    if "discrimination" in report:
        s = report["discrimination"]["summary"]
        print(
            f"  discrimination (lift signal): separation {s['separation_preserved']}/{s['pairs']}, "
            f"score-rank {s['score_ranked']}/{s['pairs']}"
        )
    if "determinism" in report:
        s = report["determinism"]["summary"]
        print(
            f"  determinism (repeatability):  {s['binary_stable_rows']}/{s['rows']} stable, "
            f"{s['rows_with_unparsable']} unparsable, max score range {s['max_score_range']}"
        )


if __name__ == "__main__":
    main()
