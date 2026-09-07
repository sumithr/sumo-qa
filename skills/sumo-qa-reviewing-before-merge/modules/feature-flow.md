# Reviewing before merge: primary feature flow exercised end-to-end

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** a runtime change serves an identifiable UI / API / CLI / worker / artifact flow and the fresh run may have exercised only a lower-level unit. **Extends:** checklist step 9 (verification-evidence discipline, check ii), Verdict-format item 8, and step 10(e). The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Check (ii): primary feature flow (step 9)

- **(ii) Primary feature flow exercised end-to-end.** Distinct from an UNMET AC (#314): even with NO supplied AC, a change whose **primary FEATURE FLOW** (the closest realistic UI / API / CLI / worker / artifact path the change serves) was never driven this turn — only a lower-level unit ran — is **UNVERIFIED (feature flow)**, a SAFE-blocker. Reuse the MET/UNVERIFIED boundary from the AC rule: do NOT over-fire when a fresh path-matching test genuinely drives that end-to-end flow — that is **VERIFIED, SAFE-eligible on this check**, not UNVERIFIED — and do NOT raise the bar above the flow's own behaviour or manufacture extra blockers beyond the named risks the diff actually carries. **This check DEFERS to the AC rule when host-supplied ACs are present:** if every supplied AC is MET by a fresh path-matching test (per the #314 MET rule — the test asserts the criterion's STATED behaviour, even at the unit level the criterion describes), the feature flow is VERIFIED through those AC tests; do NOT independently re-demand a higher-level end-to-end test than the criterion's own wording requires (a unit asserting `status==422` for an AC that says "rejected with 422" is MET — do not insist on a separate HTTP round-trip). This check is the guard for the case where NO AC pins the behaviour. Host-neutral; graceful fallback: if the realistic path can't be identified from the diff, say so in one line and rest on the other checks.

## Feature-flow line (Verdict-format item 8)

- Feature flow (when a primary feature flow exists): `Feature flow: <the realistic UI/API/CLI/worker/artifact path | NONE identifiable> | Exercised end-to-end this turn: <YES (fresh path-matching test cited) | NO (only <lower-level unit> ran)> | Status: <VERIFIED | UNVERIFIED (feature flow) — SAFE-blocker>`

## Red Flags

| Thought | Reality |
|---|---|
| "A unit test exercised the new code — SAFE" | A unit running is not the primary FEATURE FLOW. If the closest realistic UI/API/CLI/worker/artifact path was never driven end-to-end this turn, that is UNVERIFIED (feature flow), a SAFE-blocker distinct from an UNMET AC. Do NOT over-fire when a fresh path-matching test genuinely drives that flow. |
