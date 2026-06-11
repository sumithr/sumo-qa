# Captured contracts (real, not assumed) — 2026-06-10

## Compression failure mode identified (2026-06-11 stage 1, doc-drift)
- The smoke winner KEPT every doc-drift rule but DELETED the worked contrast example
  (original SKILL.md ~147–150: BAD crammed-row vs GOOD per-stale-path rows with value
  pairs) → doc-drift went 0.898 (original) → 0.0 (compressed). Worked examples pin the
  output shape the judge grades — they are load-bearing, not padding.
- BOUNDARY ACTION: add to the reflection PREAMBLE: "worked examples that pin output
  format are load-bearing — compress their prose, never delete the example." (Skill-side
  guidance, not a rubric change. Applies from the extension run; do not hot-edit mid-run.)

## Agreed extension protocol (user, 2026-06-11 ~01:30)
1. Stage 1 completes → trajectory report → user go.
2. Extension to the 50% bar (TARGET_RATIO 0.5, original seed_tokens=15664 denominator).
3. Cloud gpt-5.5 gate on the 50% winner = the POC verdict.
4. Frontier phase: re-seed from the winner, ratchet TARGET_RATIO down (0.4 → 0.3 → …).
   GUARDRAILS — anchors NEVER move: degradation = confirmed (repeat-3) drop below the
   ORIGINAL seed bars (valset 0.389 / .ab B-arm 0.22). Each stage winner needs the
   repeat-3 confirm before becoming the next seed. Deliverable: the measured safe
   compression frontier. Topology changes (4090 split-host / phase-batch) only at stage
   boundaries with a bridge re-anchor.

## gepa 0.1.1 (pip)
- `gepa.optimize(seed_candidate, trainset, valset=None, adapter=None, …, reflection_lm=None,
  reflection_minibatch_size=None, max_metric_calls=None, run_dir=None,
  display_progress_bar=False, raise_on_exception=True, seed=0, …)` — all plan kwargs exist.
- `EvaluationBatch(outputs: list, scores: list[float], trajectories: list|None = None,
  objective_scores=None)`; scores SUMMED for minibatch acceptance, AVERAGED over valset.
- `GEPAAdapter.evaluate(self, batch, candidate, capture_traces)` /
  `make_reflective_dataset(self, candidate, eval_batch, components_to_update)` — match plan.
- `reflection_lm: LanguageModel | str | None` where
  `LanguageModel = Callable[[str | list[dict]], str]` → **wrapper must accept list-of-messages
  too** (flatten content). ADJUSTMENT applied to reflect.py.
- `GEPAResult.best_candidate` ✓; also `total_metric_calls`, `num_candidates`,
  `val_aggregate_subscores` (wait: attr list shows `val_aggregate_subscores`) — use for report.
- `raise_on_exception=True` default → InfraError propagates = halt-on-checkpoint behaviour. ✓
- gepa has no `__version__` attr; version via `pip show gepa` → 0.1.1.

## Environment
- Node v24.16.0; promptfoo 0.121.11 (repo-pinned); claude CLI 2.1.170 (`claude -p` OK).
- OWUI routes gemma4-12b-bounded, sumo-rjudge-20b:latest, gemma4-e4b-bounded (HTTP 200 warm).
- Primary SKILL.md sha256: 33c0643badd40faaed6a761a125b707ffe188b2acedeb119d6ad338fdc70cd9a

## promptfoo report JSON shape (real, from ledger run)
- Rows at `data["results"]["results"]`; per row: `success` (bool), `score` (float),
  `testCase.description`, `gradingResult.componentResults[].reason` (the judge text — the
  top-level `gradingResult.reason` can be bare "FAIL"), `latencyMs`, `failureReason`.
- Parser must read componentResults reasons, joined. ADJUSTMENT applied to harness.py.

## Judge decision (Step 2.2/2.3 empirical)
- `sumo-rjudge-20b` (reasoning-tier default, 4090): **DISQUALIFIED** — false-FAILs the
  current skill on a row the validated judge grades A/PASS (matches bake-off rejection
  "too strict, 0/3 separation") AND emits bare "FAIL" with zero critique
  (showThinking:false clips analysis) → no ASI for GEPA reflection.
- `gemma4-12b-bounded` (laptop): PASS + full critique paragraph — but it IS the reasoning
  candidate (self-judge) and co-hosts on the laptop (kills pipelining). Reserve as fallback.
- `pi-gpt-oss-20b-16k:latest`: PASS (agrees with validated judge) + per-criterion verdict
  ("A PASS B PASS C NO FAIL"). Same 20b family as the user's chosen judge, non-clipping
  config. **SELECTED** — pinned via SUMO_REASON_JUDGE (defaulted in harness.py).
  Latency ~2m20s/test. .ab separation run (repeat=1): ablations 0/6 pass (clean), B arm
  2/3 pass on the CURRENT skill (candidate wobble at the pass threshold, as documented for
  --repeat 1). Fail-row critiques: per-criterion verdicts, sometimes terse "FAIL" — usable.
  JUDGE CONFIRMED.

## .ab arm encoding + floor decision (Step 2.3, real reasoning-tier report)
- Arms on the PROMPTS axis: labels "A0 - no skill, no catalogues", "A1 - catalogues only,
  no skill", "B - full skill (current)"; rows carry promptIdx. NOT in test descriptions —
  initial desc-regex floor would never fire (fixed in harness.py/scoring.py).
- Ablation rows are candidate-INDEPENDENT (no skill in prompt) — they are a drift guard,
  not a candidate signal.
- Floor rule: B majority-pass (>=2/3) AND all ablations fail. Seed passes (B 2/3, abl 0/6).
- .ab file cost: 9 rows ≈ 7m30s at -j1 (B rows carry the 15.6k-token skill; A rows fast).
- Seed skill = 15,664 tokens (o200k_base); 50% target <= 7,832.

## Scratch mirror coverage (catch #4)
- Eval configs resolve file://../../../{skills,knowledge,standards}/… — the mirror must copy
  knowledge/ and standards/ too, or every referencing row insta-fails with ENOENT
  (measured: .ab 27/27 errors in 23.5s). Fixed in scratch.py + assert in baseline rerun.

## Pipelining (-j2) measurement
- verifier-evidence at -j2: 762.5s / 9 tests = ~85s/test vs ~120s/test at -j1 (ledger) —
  ~30% faster, no pegging/timeouts observed. Candidate(laptop)+judge(pi/4090) overlap works
  as the user's pi experiment claimed. KEEP POC_CONCURRENCY=2.

## Baseline (current skill, repeat=3, reasoning pairing + pi-gpt-oss judge)
- skill-reviewing-before-merge.yaml: 2/3 pass.
- verifier-evidence.yaml: 2/9 pass — local tier grades the CURRENT skill harshly here;
  absolute pass rates are low, the POC signal is RELATIVE (seed vs candidate, same tier).
- .ab (repeat=3, post-mirror-fix): B arm 2/9 pass, ablations 0/18. The seed FAILS a binary
  B-majority floor → control is NOT stark on this tier. DECISION: .ab demoted from binary
  floor to graded signal (ab_score = B pass-rate; seed bar 0.22); ablation-pass now raises
  EnvironmentDrift (halt, never zero the candidate). Doctrine: read lift, not binary.
- Full baseline (seed bars for the valset): core 2/3 (0.67) · verifier-evidence 2/9 (0.22)
  · .ab B-arm 2/9 (0.22). The POC verdict compares candidate vs THESE bars, same tier.
- .ab at repeat=3, -j2: 1180s (~20 min) — valset is expensive; gepa runs it sparingly.

## Per-test latency (reasoning pairing, measured)
- ledger.yaml (1 test): 2m14s–2m24s wall including model warm. Use ~2.3 min/test for
  projections.

## claude -p reflection latency (Step 2.4)
- Small rewrite: 34s, correct fenced markdown output. Full-skill rewrites scale with
  output length; keep the 3–5 min/rollout planning estimate until measured in smoke.
