"""Run the real promptfoo harness (run-eval.sh) inside the scratch mirror; parse reports."""

import json
import os
import subprocess
import time
from pathlib import Path

from scratch import EVAL_REL, SCRATCH

TIER = os.environ.get("POC_TIER", "reasoning")
# Judge pinned by Task 2 empirical disqualification of sumo-rjudge-20b (bare "FAIL",
# no critique, false-fails). pi-gpt-oss-20b-16k = same family, non-clipping config.
DEFAULT_JUDGE = "pi-gpt-oss-20b-16k:latest"
REPORTS = SCRATCH / "tests/evals/results/local-reports"
TIMINGS = Path(__file__).resolve().parent / "timings.jsonl"


class InfraError(RuntimeError):
    pass


def run_yaml(yaml_name: str, repeat: int = 1, timeout_s: int = 5400) -> list[dict]:
    cfg = SCRATCH / EVAL_REL / yaml_name
    env = os.environ.copy()  # passes through SUMO_* overrides
    env.setdefault("SUMO_REASON_JUDGE", DEFAULT_JUDGE)
    env.update(
        {
            "SUMO_EVAL_BACKEND": "local",
            "TIER": TIER,
            "SUMO_EVAL_REPEAT": str(repeat),
            "SUMO_EVAL_CONCURRENCY": env.get("POC_CONCURRENCY", "2"),
        }
    )
    t0 = time.time()
    proc = subprocess.run(
        ["bash", str(SCRATCH / EVAL_REL / "run-eval.sh"), str(cfg)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    (Path(__file__).resolve().parent / "last-run.log").write_text(
        proc.stdout[:3000]
        + "\n…\n"
        + proc.stdout[-5000:]
        + "\n--- STDERR ---\n"
        + proc.stderr[-2000:]
    )
    out_json = REPORTS / f"{cfg.stem}.{TIER}.json"
    if not out_json.exists():
        raise InfraError(
            f"no JSON report for {yaml_name} rc={proc.returncode}\n"
            f"STDOUT tail: {proc.stdout[-2000:]}\nSTDERR tail: {proc.stderr[-2000:]}"
        )
    rows = parse_report(out_json)
    with TIMINGS.open("a") as fh:
        fh.write(
            json.dumps({"yaml": yaml_name, "secs": round(time.time() - t0, 1), "tests": len(rows)})
            + "\n"
        )
    out_json.unlink()  # stale-report guard: next run must produce a fresh one
    return rows


def run_yaml_with_retry(yaml_name: str, **kw) -> list[dict]:
    try:
        return run_yaml(yaml_name, **kw)
    except (InfraError, subprocess.TimeoutExpired):
        time.sleep(30)
        return run_yaml(yaml_name, **kw)  # second failure propagates -> halt on checkpoint


def parse_report(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    # .ab configs encode arms on the prompts axis: labels "A0 - …", "A1 - …", "B - …";
    # rows carry promptIdx into that list. Regular configs have a single unlabelled prompt.
    labels = [(p.get("label") or "") for p in (data["results"].get("prompts") or [])]
    # Host-died-mid-file guard (2026-06-11 12:46, laptop reboot during promotion valset):
    # provider-error rows are INFRA, not candidate failures — scoring them as FAILs would
    # deny promotions on noise. Raise so the retry/watchdog path owns it.
    errored = [r for r in data["results"]["results"] if r.get("error")]
    if errored:
        raise InfraError(
            f"{len(errored)} provider-error rows in {path.name} — "
            f"first: {str(errored[0].get('error'))[:300]}"
        )
    rows = []
    for r in data["results"]["results"]:
        grading = r.get("gradingResult") or {}
        # Judge text lives in componentResults (top-level reason can be bare "FAIL").
        reasons = [c.get("reason") or "" for c in (grading.get("componentResults") or [])]
        reason = "\n".join(x for x in reasons if x) or (grading.get("reason") or "")
        idx = r.get("promptIdx")
        arm = labels[idx] if isinstance(idx, int) and 0 <= idx < len(labels) else ""
        rows.append(
            {
                "desc": (r.get("testCase") or {}).get("description") or "",
                "arm": arm,
                "success": bool(r.get("success")),
                "score": float(r.get("score") or 0.0),
                "reason": reason[:4000],
            }
        )
    return rows
