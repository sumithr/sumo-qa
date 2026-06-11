# GEPA Skill-Compression POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a GEPA harness that evolves `skills/sumo-qa-reviewing-before-merge/SKILL.md` (~17k tokens) toward ≥50% fewer tokens with no eval regression, scored through the repo's real promptfoo harness.

**Architecture:** A gitignored spike under `.sumo-qa/gepa-poc/`. A `GEPAAdapter` writes each candidate into a scratch mirror of the repo and shells out to the existing `tests/evals/promptfoo/run-eval.sh` (local backend, reasoning pairing: gemma4-12b-bounded candidate on the laptop + sumo-rjudge-20b judge on the 4090) per minibatch YAML, parsing the JSON report it already emits. Reflection runs via `claude -p` with the superpowers:writing-skills authoring standard prepended. Contract-verification tasks run BEFORE any adapter code; nothing long runs on an unverified assumption.

**Tech Stack:** Python 3 venv (`gepa`, `tiktoken`), bash, existing promptfoo harness (Node 24), Open WebUI proxy, `claude` CLI.

**Spike rigor (per project memory):** build-first, validated by REAL runs — no TDD, no mocks, no daemons. Nothing here is committed to git; "commit" steps are replaced by verification gates. The plan deviates from default TDD task structure for exactly this reason.

**Non-negotiable safety invariants (checked repeatedly):**
1. The primary checkout is NEVER modified — candidates only ever touch the scratch mirror (sha256 of the real SKILL.md asserted before/after every phase).
2. Rubrics/eval YAMLs are never edited — reflection may only emit `RUBRIC-PROPOSAL:` lines into `proposals.md`.
3. Infra failure ≠ bad candidate: retry once, then halt on checkpoint. Never zero-score on infra noise.
4. Long phases only start after the smoke phase re-projects their duration from measured latency.

---

## File Structure

```
.sumo-qa/gepa-poc/
├── venv/               # python venv: gepa + tiktoken
├── CONTRACTS.md        # captured real API/JSON shapes (Task 2 output)
├── scratch.py          # scratch checkout builder + candidate writer
├── harness.py          # run-eval.sh subprocess wrapper + JSON report parser
├── scoring.py          # token count, score fn, .ab floor, shape guard
├── reflect.py          # claude -p reflection callable (+ proposals.md extraction)
├── adapter.py          # PromptfooAdapter(GEPAAdapter)
├── run_poc.py          # entrypoint: seed → gepa.optimize → summary
├── baseline.py         # valset baseline on current SKILL.md
├── proposals.md        # rubric-tightening proposals (manual review only)
├── scratch/            # disposable mirror (skills/<target>/ + tests/evals/promptfoo/)
└── runs/<stamp>/       # gepa run dir: checkpoints, best_skill.md, summary.json, trajectory
```

`git ls-files` must never show any of these. Ignore via `.git/info/exclude` (local-only; avoids a public .gitignore PR for a private spike).

---

### Task 0: Pre-flight gates (hosts, models, CLIs)

**Files:** none (checks only)

- [ ] **Step 0.1: Verify OWUI + the three models route**

```bash
source tests/evals/promptfoo/_owui-env.sh
for m in gemma4-12b-bounded sumo-rjudge-20b:latest gemma4-e4b-bounded; do
  code=$(curl -s --max-time 240 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $OPENWEBUI_API_KEY" -H 'Content-Type: application/json' \
    "$OWUI_BASE/chat/completions" \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"warmup\"}],\"max_tokens\":1}")
  echo "$m -> HTTP $code"
done
```

Expected: three lines ending `HTTP 200`. Any non-200 → STOP, report which box is down.

- [ ] **Step 0.2: Verify Node 24 + promptfoo + claude CLI**

```bash
node --version            # expect v24.x
./node_modules/.bin/promptfoo --version   # expect a version, no error
claude --version          # expect a version
echo "reply with exactly: OK" | claude -p --output-format text   # expect: OK
```

Any failure → STOP (Node 24 via `nvm use 24` per repo convention).

- [ ] **Step 0.3: Record the primary-skill fingerprint**

```bash
shasum -a 256 skills/sumo-qa-reviewing-before-merge/SKILL.md | tee /tmp/poc-skill-sha-before.txt
```

Expected: one sha line. This is the never-modified invariant's anchor.

### Task 1: Spike scaffold + git safety

**Files:**
- Create: `.sumo-qa/gepa-poc/` (dirs), `.git/info/exclude` entry, venv

- [ ] **Step 1.1: Local-only ignore + dirs**

```bash
grep -qx '.sumo-qa/gepa-poc/' .git/info/exclude || echo '.sumo-qa/gepa-poc/' >> .git/info/exclude
mkdir -p .sumo-qa/gepa-poc/runs
git check-ignore -v .sumo-qa/gepa-poc/x; echo "exit=$?"
```

Expected: check-ignore prints the exclude rule, `exit=0`.

- [ ] **Step 1.2: Venv with gepa + tiktoken**

```bash
python3 -m venv .sumo-qa/gepa-poc/venv
.sumo-qa/gepa-poc/venv/bin/pip install --quiet gepa tiktoken
.sumo-qa/gepa-poc/venv/bin/python -c "import gepa, tiktoken; print('gepa', gepa.__version__); print(len(tiktoken.get_encoding('o200k_base').encode('hello world')))"
```

Expected: a gepa version and `2`. (tiktoken downloads its encoding on first use — do it here, not mid-run.)

- [ ] **Step 1.3: Confirm repo cleanliness unchanged**

```bash
git status --porcelain
```

Expected: identical to before Task 1 (only pre-existing untracked entries; nothing new tracked).

### Task 2: Contract capture (GEPA API, promptfoo JSON, judge separation, claude -p)

**Files:**
- Create: `.sumo-qa/gepa-poc/CONTRACTS.md`

- [ ] **Step 2.1: Capture the REAL gepa interface**

```bash
.sumo-qa/gepa-poc/venv/bin/python - <<'PY'
import inspect, gepa
from gepa.core.adapter import GEPAAdapter, EvaluationBatch
print("== optimize ==");  print(inspect.signature(gepa.optimize))
print("== EvaluationBatch =="); print(inspect.getsource(EvaluationBatch))
print("== GEPAAdapter =="); print(inspect.getsource(GEPAAdapter))
PY
```

Expected: signatures print. Record into `CONTRACTS.md`. **Reconcile rule:** the code in Tasks 5–7 below is written against `gepa.optimize(seed_candidate=…, trainset=…, valset=…, adapter=…, reflection_lm=…, max_metric_calls=…, reflection_minibatch_size=…, run_dir=…)` and `EvaluationBatch(outputs=…, scores=…, trajectories=…)`. If the real signature differs (renamed/missing params, import path), adjust the code to the REAL interface and note the delta in CONTRACTS.md. If `reflection_lm` does not accept a plain `str -> str` callable, STOP and surface before writing more code.

- [ ] **Step 2.2: Real promptfoo JSON shape + per-test latency (smallest file, real run)**

```bash
cd tests/evals/promptfoo
time SUMO_EVAL_BACKEND=local TIER=reasoning SUMO_EVAL_REPEAT=1 \
  bash run-eval.sh "$PWD/skill-reviewing-before-merge-ledger.yaml"
python3 - <<'PY'
import json; from pathlib import Path
p = sorted(Path("../results/local-reports").glob("skill-reviewing-before-merge-ledger.reasoning.json"))[-1]
d = json.loads(p.read_text())
rows = d["results"]["results"]
print("tests:", len(rows))
r = rows[0]
print("keys:", sorted(r.keys()))
print("success:", r.get("success"), "score:", r.get("score"))
print("desc:", (r.get("testCase") or {}).get("description"))
print("reason head:", ((r.get("gradingResult") or {}).get("reason") or "")[:300])
PY
```

Expected: report exists; keys include `success`, `score`, `gradingResult`, `testCase`. Record the ACTUAL key paths + the measured wall-clock per test into CONTRACTS.md — every later duration projection uses this number. If key paths differ from `parse_report` in Task 4, fix the parser NOW against the real shape.

- [ ] **Step 2.3: Judge-separation gate (the 20b-rejection check) + .ab row labeling**

```bash
cd tests/evals/promptfoo
SUMO_EVAL_BACKEND=local TIER=reasoning SUMO_EVAL_REPEAT=1 \
  bash run-eval.sh "$PWD/skill-reviewing-before-merge.ab.yaml"
python3 - <<'PY'
import json; from pathlib import Path
p = Path("../results/local-reports/skill-reviewing-before-merge.ab.reasoning.json")
d = json.loads(p.read_text())
for r in d["results"]["results"]:
    desc = (r.get("testCase") or {}).get("description") or "?"
    print(f"{'PASS' if r.get('success') else 'FAIL'}  {desc}")
PY
```

Expected: A0-labelled rows FAIL and A1-labelled rows PASS (= the judge separates).
**Decision rule (pre-agreed, executes without asking):**
- Separation OK → keep `sumo-rjudge-20b` (user's pairing) for the run.
- A1 rows FAIL too (the documented "too strict, 0/3 separation" failure) → `export SUMO_REASON_JUDGE=gemma4-12b-bounded` (the 92%-agreement validated judge) for all subsequent runs, and record the swap prominently in CONTRACTS.md and the final report.
Also record the EXACT description strings: the `is_a0()` regex in Task 5 must match the real labels — adjust it to the captured strings.

- [ ] **Step 2.4: claude -p reflection probe (latency + length)**

```bash
time claude -p --output-format text \
  "Rewrite the following in half the words, preserving every rule. Then stop. RULES: always run tests before merge; never claim success without output; cite test names in verdicts; refuse merge without fresh evidence; one confirmation question max."
```

Expected: coherent compressed text; record wall-clock (this scales to ~3–5 min for full-skill rewrites). If `claude -p` errors → STOP (reflection is load-bearing).

### Task 3: `scratch.py` — isolated scratch checkout

**Files:**
- Create: `.sumo-qa/gepa-poc/scratch.py`

- [ ] **Step 3.1: Write scratch.py**

```python
"""Isolated scratch mirror: candidate SKILL.md writes can never touch the real repo."""
import hashlib
import shutil
import subprocess
from pathlib import Path

POC = Path(__file__).resolve().parent
REPO = POC.parents[1]                      # .sumo-qa/gepa-poc -> repo root
SCRATCH = POC / "scratch"
TARGET = "sumo-qa-reviewing-before-merge"
SKILL_REL = Path("skills") / TARGET / "SKILL.md"
EVAL_REL = Path("tests/evals/promptfoo")


def build_scratch() -> Path:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / SKILL_REL).parent.mkdir(parents=True)
    shutil.copy2(REPO / SKILL_REL, SCRATCH / SKILL_REL)
    shutil.copytree(
        REPO / EVAL_REL, SCRATCH / EVAL_REL,
        ignore=shutil.ignore_patterns("bakeoff", "validate-local-judge",
                                      "*.cache.json", "output*.json"),
    )
    (SCRATCH / "node_modules").symlink_to(REPO / "node_modules")
    return SCRATCH


def write_candidate(text: str) -> None:
    (SCRATCH / SKILL_REL).write_text(text, encoding="utf-8")


def seed_text() -> str:
    return (REPO / SKILL_REL).read_text(encoding="utf-8")


def primary_sha() -> str:
    return hashlib.sha256((REPO / SKILL_REL).read_bytes()).hexdigest()


def repo_porcelain() -> str:
    return subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                          capture_output=True, text=True, check=True).stdout
```

- [ ] **Step 3.2: Canary verification — scratch run resolves the SCRATCH skill, not the real one**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python - <<'PY'
import scratch
scratch.build_scratch()
sha0 = scratch.primary_sha()
scratch.write_candidate(scratch.seed_text() + "\nCANARY-DO-NOT-SHIP\n")
assert "CANARY" in (scratch.SCRATCH / scratch.SKILL_REL).read_text()
assert scratch.primary_sha() == sha0, "PRIMARY MODIFIED — BUG"
print("scratch isolated OK; primary sha:", sha0[:12])
PY
shasum -a 256 ../../skills/sumo-qa-reviewing-before-merge/SKILL.md
diff <(cut -d' ' -f1 /tmp/poc-skill-sha-before.txt) <(shasum -a 256 ../../skills/sumo-qa-reviewing-before-merge/SKILL.md | cut -d' ' -f1) && echo PRIMARY-UNCHANGED
```

Expected: `scratch isolated OK` + `PRIMARY-UNCHANGED`.

- [ ] **Step 3.3: Scratch harness run end-to-end (real promptfoo through the scratch mirror)**

```bash
cd .sumo-qa/gepa-poc/scratch/tests/evals/promptfoo
SUMO_EVAL_BACKEND=local TIER=reasoning SUMO_EVAL_REPEAT=1 \
  bash run-eval.sh "$PWD/skill-reviewing-before-merge-ledger.yaml"
ls ../results/local-reports/skill-reviewing-before-merge-ledger.reasoning.json && echo SCRATCH-REPORT-OK
```

Expected: `SCRATCH-REPORT-OK` (report written INSIDE scratch; run-eval.sh's ROOT resolves to the scratch mirror; promptfoo found via the node_modules symlink). Then re-verify `PRIMARY-UNCHANGED` as in 3.2.

### Task 4: `harness.py` — eval runner + parser

**Files:**
- Create: `.sumo-qa/gepa-poc/harness.py`

- [ ] **Step 4.1: Write harness.py** (parser key-paths must match CONTRACTS.md from Step 2.2 — adjust if the real shape differed)

```python
"""Run the real promptfoo harness (run-eval.sh) inside the scratch mirror; parse reports."""
import json
import os
import subprocess
import time
from pathlib import Path

from scratch import EVAL_REL, SCRATCH

TIER = os.environ.get("POC_TIER", "reasoning")
REPORTS = SCRATCH / "tests/evals/results/local-reports"
TIMINGS = Path(__file__).resolve().parent / "timings.jsonl"


class InfraError(RuntimeError):
    pass


def run_yaml(yaml_name: str, repeat: int = 1, timeout_s: int = 5400) -> list[dict]:
    cfg = SCRATCH / EVAL_REL / yaml_name
    env = os.environ.copy()        # passes through SUMO_REASON_JUDGE etc. overrides
    env.update({
        "SUMO_EVAL_BACKEND": "local",
        "TIER": TIER,
        "SUMO_EVAL_REPEAT": str(repeat),
        "SUMO_EVAL_CONCURRENCY": env.get("POC_CONCURRENCY", "2"),
    })
    t0 = time.time()
    proc = subprocess.run(["bash", str(SCRATCH / EVAL_REL / "run-eval.sh"), str(cfg)],
                          env=env, capture_output=True, text=True, timeout=timeout_s)
    out_json = REPORTS / f"{cfg.stem}.{TIER}.json"
    if not out_json.exists():
        raise InfraError(
            f"no JSON report for {yaml_name} rc={proc.returncode}\n"
            f"STDOUT tail: {proc.stdout[-2000:]}\nSTDERR tail: {proc.stderr[-2000:]}")
    rows = parse_report(out_json)
    with TIMINGS.open("a") as fh:
        fh.write(json.dumps({"yaml": yaml_name, "secs": round(time.time() - t0, 1),
                             "tests": len(rows)}) + "\n")
    out_json.unlink()              # stale-report guard: next run must produce a fresh one
    return rows


def run_yaml_with_retry(yaml_name: str, **kw) -> list[dict]:
    try:
        return run_yaml(yaml_name, **kw)
    except (InfraError, subprocess.TimeoutExpired):
        time.sleep(30)
        return run_yaml(yaml_name, **kw)   # second failure propagates -> halt on checkpoint


def parse_report(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    rows = []
    for r in data["results"]["results"]:
        grading = r.get("gradingResult") or {}
        rows.append({
            "desc": (r.get("testCase") or {}).get("description") or "",
            "success": bool(r.get("success")),
            "score": float(r.get("score") or 0.0),
            "reason": (grading.get("reason") or "")[:4000],
        })
    return rows
```

- [ ] **Step 4.2: Verify against the scratch run's real report**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python - <<'PY'
import harness
rows = harness.run_yaml("skill-reviewing-before-merge-ledger.yaml")
assert rows and all(set(r) == {"desc", "success", "score", "reason"} for r in rows)
print(f"parsed {len(rows)} rows; first: success={rows[0]['success']} score={rows[0]['score']}")
print("reason head:", rows[0]["reason"][:120])
PY
cat timings.jsonl
```

Expected: parsed rows with non-empty `reason` (the judge critique — GEPA's feedback signal) and a timing line. If `reason` is empty, STOP and find where the judge text lives in the real JSON before proceeding.

### Task 5: `scoring.py` — score, token count, floors

**Files:**
- Create: `.sumo-qa/gepa-poc/scoring.py`

- [ ] **Step 5.1: Write scoring.py** (the `A0_PAT` regex must match the REAL labels captured in Step 2.3 — adjust there and then here)

```python
"""Candidate scoring: pass-rate minus token penalty; hard floors for .ab and shape."""
import re

import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
LAMBDA = 0.5          # token-pressure weight (spec: no reward below the 50% target)
TARGET_RATIO = 0.5
A0_PAT = re.compile(r"\bA0\b")   # verified against Step 2.3 captured descriptions


def token_count(text: str) -> int:
    return len(ENC.encode(text))


def shape_ok(text: str) -> bool:
    """Cheap malformed-candidate guard: must still look like a SKILL.md."""
    head = text[:2000]
    return text.strip().startswith("---") and "description:" in head and len(text) > 2000


def ab_floor_ok(rows: list[dict]) -> bool:
    a0 = [r for r in rows if A0_PAT.search(r["desc"])]
    a1 = [r for r in rows if not A0_PAT.search(r["desc"])]
    return bool(a1) and all(r["success"] for r in a1) and all(not r["success"] for r in a0)


def candidate_score(rows: list[dict], cand_tokens: int, seed_tokens: int) -> float:
    pass_rate = sum(r["success"] for r in rows) / max(len(rows), 1)
    penalty = LAMBDA * max(0.0, cand_tokens / seed_tokens - TARGET_RATIO)
    return max(0.0, pass_rate - penalty)
```

- [ ] **Step 5.2: Verify with real values**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python - <<'PY'
import scoring, scratch
seed = scratch.seed_text()
n = scoring.token_count(seed)
print("seed tokens:", n)                      # expect ~15000-19000
assert scoring.shape_ok(seed)
assert not scoring.shape_ok("garbage")
full = [{"desc": "x", "success": True, "score": 1, "reason": ""}]
assert scoring.candidate_score(full, n, n) == 0.75          # full size: 1 - 0.5*0.5
assert scoring.candidate_score(full, n // 2, n) == 1.0      # at 50%: no penalty
print("scoring OK")
PY
```

Expected: seed token count printed (record it — this is the baseline number) + `scoring OK`.

### Task 6: `reflect.py` — claude -p reflection callable

**Files:**
- Create: `.sumo-qa/gepa-poc/reflect.py`

- [ ] **Step 6.1: Write reflect.py**

```python
"""claude -p reflection wrapper. Prepends the writing-skills authoring standard to every
prompt GEPA composes. RUBRIC-PROPOSAL lines are logged to proposals.md, never applied."""
import subprocess
import time
from pathlib import Path

_WS = Path.home() / (".claude/plugins/cache/claude-plugins-official/"
                     "superpowers/5.1.0/skills/writing-skills")
STANDARD = ((_WS / "SKILL.md").read_text(encoding="utf-8") + "\n\n"
            + (_WS / "anthropic-best-practices.md").read_text(encoding="utf-8"))
PROPOSALS = Path(__file__).resolve().parent / "proposals.md"

PREAMBLE = f"""You are improving a SKILL.md for an LLM agent. Conform to this authoring \
standard when writing any skill text:
<authoring-standard>
{STANDARD}
</authoring-standard>
Compression objective: preserve EVERY behavioural rule, trigger phrase, named check, gate \
and verdict format; cut redundancy, duplicated dogfooding patches, repetition and filler \
prose. Shorter is better ONLY when no behaviour is lost.
You MUST NOT propose changes to eval rubrics or test YAML. If you believe a rubric should \
be TIGHTENED, emit a single line starting with 'RUBRIC-PROPOSAL:' describing it, outside \
any code fence.
"""


def reflection_lm(prompt: str) -> str:
    full = PREAMBLE + "\n\n" + prompt
    last = None
    for _attempt in (1, 2):
        proc = subprocess.run(["claude", "-p", "--output-format", "text"],
                              input=full, capture_output=True, text=True, timeout=1800)
        text = proc.stdout.strip()
        if proc.returncode == 0 and text:
            for line in text.splitlines():
                if line.startswith("RUBRIC-PROPOSAL:"):
                    with PROPOSALS.open("a") as fh:
                        fh.write(line + "\n")
            return text
        last = f"rc={proc.returncode} stderr={proc.stderr[-500:]}"
        time.sleep(10)
    raise RuntimeError(f"claude -p failed twice: {last}")
```

- [ ] **Step 6.2: Verify with a real (small) reflection-shaped call**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python - <<'PY'
from reflect import reflection_lm
out = reflection_lm(
    "Current instruction text: 'Always run the tests. Always always run all of the tests "
    "before you merge anything at all.' Feedback: verbose. Propose an improved instruction "
    "inside a ```markdown fence.")
print(out[:500])
assert "```" in out
print("reflect OK")
PY
```

Expected: a fenced, shorter instruction; `reflect OK`.

### Task 7: `adapter.py` + `run_poc.py` — wire GEPA

**Files:**
- Create: `.sumo-qa/gepa-poc/adapter.py`
- Create: `.sumo-qa/gepa-poc/run_poc.py`

- [ ] **Step 7.1: Write adapter.py** (against the interface captured in CONTRACTS.md — reconcile if it differed)

```python
"""GEPA adapter scoring candidates through the real promptfoo harness."""
from gepa.core.adapter import EvaluationBatch, GEPAAdapter

import harness
import scoring
import scratch


class PromptfooAdapter(GEPAAdapter):
    def __init__(self, seed_tokens: int):
        self.seed_tokens = seed_tokens

    def evaluate(self, batch, candidate, capture_traces=False):
        text = candidate["skill_md"]
        outputs, scores, trajectories = [], [], []
        if not scoring.shape_ok(text):
            for inst in batch:
                outputs.append({"yaml": inst["yaml"], "rows": []})
                scores.append(0.0)
                trajectories.append({"yaml": inst["yaml"], "rows": [], "note":
                                     "malformed candidate (shape guard)"})
            return EvaluationBatch(outputs=outputs, scores=scores,
                                   trajectories=trajectories if capture_traces else None)
        scratch.write_candidate(text)
        cand_tokens = scoring.token_count(text)
        for inst in batch:
            rows = harness.run_yaml_with_retry(inst["yaml"])
            if inst["kind"] == "ab":
                score = 1.0 if scoring.ab_floor_ok(rows) else 0.0
            else:
                score = scoring.candidate_score(rows, cand_tokens, self.seed_tokens)
            outputs.append({"yaml": inst["yaml"], "rows": rows})
            scores.append(score)
            trajectories.append({"yaml": inst["yaml"], "rows": rows})
        return EvaluationBatch(outputs=outputs, scores=scores,
                               trajectories=trajectories if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        items = []
        for out in eval_batch.outputs:
            for r in out["rows"]:
                if not r["success"]:
                    items.append({
                        "Inputs": f"{out['yaml']} :: {r['desc']}",
                        "Generated Outputs": f"(judge score {r['score']:.2f})",
                        "Feedback": r["reason"],
                    })
        if not items:
            cand_tokens = scoring.token_count(candidate["skill_md"])
            items.append({
                "Inputs": "all minibatch tests passing",
                "Generated Outputs": f"candidate is {cand_tokens} tokens",
                "Feedback": (f"All tests passed. Candidate is {cand_tokens} tokens vs seed "
                             f"{self.seed_tokens}; target is <= {self.seed_tokens // 2}. "
                             "Compress further WITHOUT losing any behavioural rule, trigger, "
                             "named check, gate or verdict format."),
            })
        return {"skill_md": items}
```

- [ ] **Step 7.2: Write run_poc.py**

```python
"""GEPA POC entrypoint.
Usage: venv/bin/python run_poc.py --metric-calls 20 [--run-dir runs/...]
Resume: pass the SAME --run-dir; gepa reloads its checkpoint state.
"""
import argparse
import json
import time
from pathlib import Path

import gepa

import adapter
import reflect
import scoring
import scratch

POC = Path(__file__).resolve().parent

# Trainset = the regular reviewing-before-merge files; core + verifier-evidence + core .ab
# are reserved for the validation set (Pareto selection / promotion checks).
REGULAR = [
    "skill-reviewing-before-merge-ac-coverage.yaml",
    "skill-reviewing-before-merge-adversarial.yaml",
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
    args = ap.parse_args()

    sha_before = scratch.primary_sha()
    scratch.build_scratch()
    seed = scratch.seed_text()
    seed_tokens = scoring.token_count(seed)
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
    }
    Path(run_dir, "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    assert scratch.primary_sha() == sha_before, \
        "PRIMARY REPO SKILL.md CHANGED — investigate before doing ANYTHING else"
    print("primary repo untouched OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.3: Import-and-dry-check (no rollouts yet)**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python -c "import adapter, run_poc; print('imports OK')"
venv/bin/python - <<'PY'
import adapter, scoring, scratch
scratch.build_scratch()
a = adapter.PromptfooAdapter(seed_tokens=17000)
eb = a.evaluate([{"yaml": "x.yaml", "kind": "regular"}], {"skill_md": "garbage"})
assert eb.scores == [0.0]
print("malformed-candidate floor OK (no eval was run)")
PY
```

Expected: `imports OK` + floor check passes WITHOUT invoking promptfoo.

### Task 8: Baseline capture (current SKILL.md, valset, repeat 3)

**Files:**
- Create: `.sumo-qa/gepa-poc/baseline.py`

- [ ] **Step 8.1: Write baseline.py**

```python
"""Valset baseline on the CURRENT SKILL.md — the comparison anchor for the POC verdict."""
import json
from pathlib import Path

import harness
import scoring
import scratch
from run_poc import VALSET

scratch.build_scratch()                  # scratch == current skill (the seed)
out = {}
for inst in VALSET:
    rows = harness.run_yaml_with_retry(inst["yaml"], repeat=3)
    out[inst["yaml"]] = {
        "tests": len(rows),
        "pass": sum(r["success"] for r in rows),
        "ab_floor_ok": scoring.ab_floor_ok(rows) if inst["kind"] == "ab" else None,
    }
print(json.dumps(out, indent=2))
Path(__file__).with_name("baseline.json").write_text(json.dumps(out, indent=2))
```

- [ ] **Step 8.2: Run it (longest pre-run step; ~45–60 min projected — re-project from timings.jsonl first)**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python baseline.py
cat baseline.json
```

Expected: per-file pass counts; `ab_floor_ok: true` for the `.ab` entry. **If the baseline itself fails its own `.ab` floor or the core file scores 0, STOP — the environment, not GEPA, is broken, and running stage 1 would waste hours.**

### Task 9: Smoke run (2 rollouts) — go/no-go gates

- [ ] **Step 9.1: Run with a tiny budget**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python run_poc.py --metric-calls 6 2>&1 | tee runs/smoke.log
```

Expected: completes; prints summary + `primary repo untouched OK`.

- [ ] **Step 9.2: Check the gates**

```bash
cd .sumo-qa/gepa-poc
tail -5 timings.jsonl          # measured per-yaml durations
ls runs/*/                     # gepa checkpoint/state files exist
git -C ../.. status --porcelain | head   # nothing new tracked
cat proposals.md 2>/dev/null   # rubric proposals (may be empty)
```

Gates (ALL must hold before stage 1):
1. Smoke completed without InfraError halts.
2. `timings.jsonl` per-yaml duration is sane → project stage 1: `20 metric-calls × measured-avg + ~10 × reflection-time`. Report the projection.
3. Pipelining check: compare per-test latency at `POC_CONCURRENCY=2` (default) vs the Step 2.2 `-j1` measurement. If `-j2` inflated per-test latency >1.5× (gen-gen stacking), set `POC_CONCURRENCY=1` for stage 1 and note it.
4. Primary repo untouched (sha + porcelain).
5. Candidate tokens moved (reflection actually rewrites — if both rollouts returned the seed unchanged, inspect `runs/<stamp>/` reflection outputs before burning stage 1).

### Task 10: Stage 1 (≈10 rollouts) + trajectory report — then STOP for user

- [ ] **Step 10.1: Launch stage 1 (unattended; run in background)**

```bash
cd .sumo-qa/gepa-poc
venv/bin/python run_poc.py --metric-calls 20 2>&1 | tee runs/stage1.log
```

(If the judge swap triggered in Step 2.3, ensure `SUMO_REASON_JUDGE=gemma4-12b-bounded` is exported in this shell.)

- [ ] **Step 10.2: Produce the trajectory report for the user**

Report (to chat + `runs/<stamp>/report.md`, local-only):
- token curve per accepted candidate (seed → best), reduction %
- minibatch/val scores vs baseline.json
- `.ab` floor events (how many candidates were floored)
- judge used (20b kept vs 12b fallback) + any judge anomalies
- `proposals.md` contents
- projected additional rollouts/hours to reach the 50% bar at the observed slope

**STOP. Extension beyond stage 1, winner validation (valset repeat-3 on best candidate), and the one-shot CLOUD gate (`bash run-eval.sh` cloud over the reviewing files with the winner in place, `--repeat 3`) all happen ONLY on the user's explicit go — that gate was agreed in brainstorming.**

---

## Self-review checklist (run after writing, before execution)

1. Spec coverage: scratch isolation ✓ (T3), real-harness scoring ✓ (T4), token-pressured score + .ab floor ✓ (T5), writing-skills standard in reflection ✓ (T6), strictify-only proposals ✓ (T6), staged budget ✓ (T9/T10), baseline anchor ✓ (T8), judge-separation pre-flight ✓ (T2.3), infra-vs-candidate distinction ✓ (T4), primary-repo invariant ✓ (T0.3/T3.2/T7.2).
2. No placeholders: every step has runnable code/commands + expected output.
3. Contract reconciliation points are explicit: Steps 2.1 (gepa API), 2.2 (JSON shape), 2.3 (A0 labels), with downstream code marked to adjust.
