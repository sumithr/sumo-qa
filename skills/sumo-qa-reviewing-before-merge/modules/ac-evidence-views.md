# Reviewing before merge: AC evidence: MET vs UNVERIFIED, and the AC ledger view

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** acceptance criteria are supplied (with `acceptance-criteria`) and either a MET/UNVERIFIED boundary call is close, or the user wants the AC map as a paste-into-PR table. **Extends:** the `acceptance-criteria` module and the `ledger-appendix` module. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Worked contrast: MET vs UNVERIFIED

**Worked contrast — MET vs UNVERIFIED (the line is which behaviour the fresh test asserts).** Criterion: *"GET /api/v1/quota returns the caller's remaining quota."* Diff adds `return QuotaResponse(remaining=quota_for(token))`; fresh `tests/api/test_quota.py::test_quota_returns_remaining` asserts `...json()["remaining"] == 100`.
- GOOD (MET): "AC: …returns the caller's remaining quota | Classification: MET | Anchor: app/api/quota.py:1 + tests/api/test_quota.py::test_quota_returns_remaining asserts `remaining == 100`." The criterion's stated behaviour is implemented and asserted by a fresh path-matching test. (That the test doesn't prove per-token discrimination is a separate named risk, NOT an AC downgrade.)
- BAD (over-firing UNVERIFIED): "AC: …returns the caller's remaining quota | Classification: UNVERIFIED — the test doesn't prove per-token mapping." This raises the AC bar above the criterion's wording. SHAPE FAIL.
- Genuine UNVERIFIED, by contrast: criterion *"failed deliveries are retried up to 3 times on 5xx"*, diff adds the retry loop, but the only fresh test asserts the backoff-delay calculator (`_backoff_delay(2) == 2.0`) — NO fresh test drives `deliver()` against a 5xx receiver → UNVERIFIED, correctly.

## AC-coverage view (same ledger schema, no new tool)

**AC-coverage view (same schema, no new tool).** The per-criterion AC lines in the verdict (Verdict-format item 7) are mandatory whenever ACs are supplied — this OPTIONAL appendix is only the paste-into-PR projection of that same map, never a substitute for the inline lines and never the trigger for surfacing the MET criteria. When acceptance criteria were supplied and the user wants the structured artifact, project the AC-coverage map (step 9) through the SAME `sumo_qa_format_risk_ledger` and append it as a second table below the risk ledger — one row per criterion, NOT a parallel structure: `risk_id`=`AC1…`, `risk`=the criterion text, `source_anchor`=the diff file:line / behaviour satisfying it (or the AC text when unmet), `test`=the covering fresh test id or a `planned: …` phrase, `evidence_status`=`passing` (MET) / `planned` (UNVERIFIED — plausibly addressed but no fresh evidence either way) / `planned` (UNMET, no diff change), `residual`=`accepted` for MET, `blocker` for every UNMET/UNVERIFIED. The tool's `uncovered_blocker_count` then enforces the AC gate the same way it enforces the risk gate — it must be 0 before SAFE. Worked rows (one met, one unmet):
`| AC1 | Skill checks each host-supplied criterion vs diff + fresh tests | skills/sumo-qa-reviewing-before-merge/SKILL.md:88 | tests/evals/promptfoo/skill-reviewing-before-merge-ac-coverage.yaml::ac-unmet | passing | accepted |`
`| AC2 | Refuses SAFE while any criterion is UNMET | step 10(d) | planned: scenario asserting NOT SAFE on an unmet AC | planned | blocker |`

## Red Flags

| Thought | Reality |
|---|---|
| "The fresh test doesn't prove every nuance of the AC — I'll mark it UNVERIFIED to be safe" | If a fresh path-matching test asserts the criterion's STATED behaviour, the AC is MET — the unproven nuance is a separate named risk, not an AC downgrade. UNVERIFIED is only for when the criterion's behaviour was never driven this turn. Over-firing UNVERIFIED is a SHAPE FAIL. |
