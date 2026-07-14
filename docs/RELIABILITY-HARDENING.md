# Reliability hardening control matrix (epic #211)

sumo-qa keeps deterministic Python tools thin and puts QA orchestration in host-neutral
skills. That design is portable, but quality then depends on prompt adherence, host-model
variance, context budget, and how much host activity can be observed. Epic #211 hardened
the four weaknesses that follow from that design. The goal was never deterministic LLM
behavior: each weakness gets a concrete merged control, proof artifacts, a documented
residual limit, and a backward-compatible default.

A maintainer re-running the original four-risk analysis against current `main` should be
able to classify every item below as MITIGATED (control merged, proof cited) or
INTENTIONALLY BOUNDED (residual named and accepted), never open or unaddressed.

## Control matrix

### 1. Prompt dependence / host-model variance

- **Classification:** mitigated (drift is measured, not eliminated).
- **Control (merged):** machine-readable conformance fixtures plus a deterministic
  transcript validator: order-aware entry-skill routing with a mis-route set derived from
  the registered skill-tool surface, required/forbidden tool-call checks, and
  required/forbidden output markers. Skill (routing) tools are capture-wrapped so a real
  `SUMO_QA_DEBUG_DIR` capture records the entry-skill calls the contracts check.
  Provider-backed variance measurement stays with the manual promptfoo layer by policy.
- **Owner / delivery:** issue #214, PR #476 (merged 2026-07-13).
- **Evidence:** `src/sumo_qa/conformance.py`; the fixture
  `tests/scenarios/conformance/scenarios.yaml` (11 scenarios covering the five required
  workflow families); `tests/test_conformance_transcript_validator.py` (the validator
  provably fails synthetic bad transcripts on every contract axis);
  `tests/scenarios/CONFORMANCE.md` (format and run instructions); provider-backed path
  documented in `tests/evals/promptfoo/README.md` with `tests/evals/promptfoo/aggregate.py`
  for scenario-level verdict-flip rates. Live merge-gate proof: a real capture driven
  through the MCP dispatch scored scenario S01 PASS with two demonstrated fail paths
  (wrong routing, forbidden output marker); see the batch proof comment on PR #476.
- **Default / compatibility:** capture activates only when `SUMO_QA_DEBUG_DIR` is set;
  the served skill bodies and the `using_sumo_qa` router output were verified
  byte-identical to the pre-change serving path at merge time.
- **Residual limit:** host-model behavior still varies; the deterministic layer measures
  routing/contract drift rather than eliminating it. Required-tool matching is set-based
  (a documented first-slice limit). Provider-backed runs are manual and paid.

### 2. Verbosity fatigue

- **Classification:** intentionally bounded, with the boundary now MEASURED (#528):
  serve-time overlays cannot reduce end-to-end session cost; the profile's honest
  contract is decisive, low-ceremony output plus a lean tool path, with no cost claim.
- **Control (merged):** `SUMO_QA_OUTPUT_PROFILE=concise|default|strict` serve-time
  overlays on the single skill-serving path. Every overlay restates the never-optional
  floor (Iron Law, HARD-GATE, evidence for claims, confirmation before writes/installs).
  Unrecognised values fall back to `default`; the overlay rides the oversize pointer only
  when the combination itself fits the token cap.
- **Owner / delivery:** issue #215, PR #471 (merged 2026-07-13).
- **Evidence:** `src/sumo_qa/skill_prompts.py`; the profile suite in
  `tests/test_skill_prompts.py` (14 tests: byte-for-byte default through the real
  registration path, overlay prepending, env-var call-time selection, invalid fallback,
  mandatory-gate preservation, token-cap degradation); documentation contract in
  `docs/CONFIGURATION.md`, `docs/TOOLS.md`, `docs/SKILLS.md`, and `docs/ARCHITECTURE.md`.
  Live merge-gate proof: sha256-verified byte identity of default serving and the router
  against the pre-change code, overlay heads with the gate language intact; see the batch
  proof comment on PR #471.
- **Default / compatibility:** `default` serves every body byte-for-byte. The overlay
  applies to the skill-tool surface only; `sumo_qa_load_skill_context` and the
  `sumoqa://` resources always serve the canonical body so `content_hash`
  change-detection stays stable across profiles.
- **Residual limit (measured twice, #528):** the discharge A/Bs ran on 2026-07-14 with
  a real headless agent. First (same v0.55.0 build, env var only, neutral empty cwd,
  n=2): concise sessions cost roughly 2x with longer answers, confounded by the default
  legs stalling in the ungrounded workspace. Second (post-fix overlay with the
  tool-budget clause, grounded fixture repo via the harness's --run-cwd, n=3): parity
  within noise (means ~744k concise vs ~694k default), full-quality answers on both
  sides, no stalls (the earlier ungrounded-cwd anomaly did not reproduce). Conclusion:
  session cost is dominated by the mandatory flow's tool traffic and per-turn context,
  which prepended prose cannot shrink, so `concise` carries NO cost claim. What it
  measurably changes is behavior: findings-over-process decisiveness, plus the #528
  lean-tool hygiene (load only what the gates require, skip supplementary loads, never
  re-load loaded content), pinned by the serve-path suite. Cost reduction, if pursued,
  needs flow/surface changes (for example progressive-manifest serving), a deliberate
  future design, not an overlay tweak.

### 3. Enforcement uncertainty (unsupported workflow claims)

- **Classification:** mitigated on the structured path; intentionally bounded on the
  transcript path (a lint, not a proof).
- **Control (merged):** a typed gate-evidence model: `passed`/`failed`/`blocked` claims
  must cite at least one evidence item, `unverified` must cite none (the honest
  cannot-claim state), `skipped` may cite none. A structured loader exposes stable error
  kinds; a negation-aware transcript lint flags evidence-free "tests passed" /
  "safe to merge" phrasing including copula variants. Four skills (reviewing-before-merge,
  finishing-qa-work, executing-qa-rollout, creating-test-plan) require labeled evidence
  citations for gate claims, and two promptfoo rubrics reject evidence-free pass claims.
- **Owner / delivery:** issue #213, PR #486 (merged 2026-07-13).
- **Evidence:** `src/sumo_qa/gate_evidence_models.py` and
  `src/sumo_qa/gate_evidence_validation.py` (both at 100% coverage);
  `tests/test_gate_evidence_models.py` plus `tests/test_gate_evidence_validation.py`
  (roughly 80 discriminating tests across the status/evidence matrix, error kinds, and
  lint positive/negative/negation cases); the tracked contract in
  `docs/GATE-EVIDENCE.md`. Eval gate at delivery: 4/4 pass after strengthening the
  reviewing-before-merge skill (the rubric was never loosened). Live merge-gate proof:
  structured accept/reject and lint behavior observed on real runs; see the batch proof
  comment on PR #486.
- **Default / compatibility:** the existing MCP `isError` envelope behavior is untouched;
  the schema is deliberately not wired into tool output (an explicit acceptance
  criterion of #213).
- **Residual limit:** host-side actions are only partially observable; the transcript
  lint catches blatant evidence-free claims, while the structured path is the rigorous
  one. Follow-up: #488 (add the gate-evidence modules to the mutation gate's
  `paths_to_mutate`).

### 4. Shallow static-analysis integration

- **Classification:** mitigated for the delivered scope (Python-first), intentionally
  bounded elsewhere via explicit fallbacks.
- **Control (merged):** a typed semantic-analysis adapter layer that normalizes analysis
  signals into recommendation evidence: changed-symbol extraction from real unified
  diffs (including deletion seams), likely-owning-test mapping, cross-file impact reach
  over the epic #353 repo-map imports graph, and coverage/mutation artifact ingestion.
  Every degraded path records an explicit `AnalysisFallback` instead of failing.
- **Owner / delivery:** issue #212, PR #490 (merged 2026-07-13).
- **Evidence:** the `src/sumo_qa/analysis/` package (contracts, registry, python adapter,
  diff, references, impact, artifacts, test mapping, normalize, analyzer); roughly 95
  tests in `tests/test_analysis_contracts.py`, `tests/test_analysis_python_adapter.py`,
  `tests/test_analysis_registry.py`, `tests/test_analysis_diff.py`,
  `tests/test_analysis_references.py`, `tests/test_analysis_impact.py`,
  `tests/test_analysis_artifacts.py`, `tests/test_analysis_test_mapping.py`,
  `tests/test_analysis_normalize.py`, and `tests/test_analysis_analyzer.py`;
  integration boundaries documented in `docs/ARCHITECTURE.md` and
  `docs/CONFIGURATION.md`. Live merge-gate proof: a real git diff mapped to the changed
  symbol, its owning test at high confidence with a stated reason, concrete citations,
  and explicit fallbacks; see the batch proof comment on PR #490.
- **Default / compatibility:** purely additive (no MCP surface change; `server.py` and
  `server_schemas.py` untouched); the lightweight core install is preserved because the
  adapter uses stdlib `ast` and the optional imports graph degrades to a recorded
  fallback when the `[treesitter]` extra is absent.
- **Residual limit:** unsupported languages and missing optional dependencies fall back
  cleanly to skill-driven behavior; deletion-seam attribution is deliberately
  conservative and can over-flag a neighbouring symbol (documented in the module).
  The imports-graph input grows with epic #353 (open follow-ups #483 and #484).

## Verifying this matrix

Run against merged `main`:

```sh
uv run pytest -q
uv run pytest -q tests/test_conformance_transcript_validator.py tests/test_skill_prompts.py \
  tests/test_gate_evidence_models.py tests/test_gate_evidence_validation.py \
  tests/test_skill_md_token_budget.py "tests/test_analysis_analyzer.py"
```

Provider-backed promptfoo runs stay manual (`tests/evals/promptfoo/README.md`); they are
deliberately not part of PR CI.

Delivered across releases 0.52.0 through 0.55.0 (2026-07-13). Epic #211 records the
audit trail; each child issue carries the merged proof comment for its row.
