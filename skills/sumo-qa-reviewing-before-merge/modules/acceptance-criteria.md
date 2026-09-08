# Reviewing before merge: acceptance-criteria coverage

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the host supplies acceptance criteria (pasted by the user or carried in a context bundle). **Extends:** checklist step 9 (AC-coverage check), Verdict-format item 7, and step 10(d); the MET-vs-UNVERIFIED worked contrast and the AC ledger view live in `ac-evidence-views`. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Acceptance-criteria coverage (step 9)

**Acceptance-criteria coverage (pinned).** "Correct code" and "the *right* code" are distinct questions — a green, fully risk-covered diff can still not deliver what the ticket asked for. When the host supplies acceptance criteria (the user pastes them, or the host hands them in a context bundle), check EACH criterion against the diff + this turn's fresh test evidence and classify it — exactly the risk→test traceability move of step 9, but AC→evidence. **Surfacing every supplied criterion is MANDATORY, not verdict-conditional:** whenever ACs are present you MUST emit one AC line per criterion with its classification AND its cited anchor — including the MET ones on an all-MET SAFE path. Surfacing only the UNMET/UNVERIFIED criteria (or only when a blocker exists or a ledger artifact is requested) is a discipline violation: the contract is that EACH supplied criterion is checked and cited, regardless of verdict. Classify each:

- **MET** — a diff change AND a fresh path-matching test assert the criterion's *stated* behaviour; cite the file + fully-qualified test + verbatim assertion (the same proof bar as COVERED). The test must prove what the criterion *says*, not every downstream nuance: if the criterion is "returns the caller's remaining quota" and a fresh test asserts the endpoint returns the `remaining` value, that is MET — a separately-unproven nuance (e.g. per-token discrimination) is a named *risk* (step 4 / the coverage ledger), NOT a reason to downgrade the AC to UNVERIFIED. Do not raise the AC bar above the criterion's own wording.
- **UNMET** — nothing in the diff satisfies it, or it is contradicted; a SAFE-blocker.
- **UNVERIFIED** — the diff plausibly addresses it (the implementing change exists) but NO fresh test exercises the criterion's own behaviour this turn — only an adjacent or lower-level unit ran (e.g. a backoff-delay calculator unit when the criterion is end-to-end retry-on-5xx). UNVERIFIED is for "the criterion's behaviour was never driven," NOT for "the behaviour was asserted but one nuance is unproven." If a fresh path-matching test asserts the criterion's stated behaviour, it is MET, not UNVERIFIED. A SAFE-blocker until proven, like an UNPROVEN risk.

This is **host-neutral and host-supplied**: NEVER fetch an issue, call `gh`, or hit any tracker/API — the host identifies the criteria, you check/cite them, same data-ownership split as the risk ledger. **Graceful explicit fallback:** when no criteria are supplied, say so in the exact one-line fallback pinned in the root's Verdict-format item 7 and fall back to the normal verdict — NEVER fabricate criteria and NEVER silently drop the check.

## AC lines (Verdict-format item 7)

**AC lines (whenever acceptance criteria were supplied — step 9).** One line per supplied criterion, regardless of verdict, in this exact shape — the MET ones are emitted too, never dropped on an all-MET SAFE path:
`AC<n>: <criterion text> | Classification: <MET | UNMET | UNVERIFIED> | Anchor: <diff file:line + fully-qualified fresh test::name and verbatim assertion for MET; the criterion / the missing behaviour for UNMET/UNVERIFIED>`
Every UNMET/UNVERIFIED line is a SAFE-blocker (step 10(d)). The verdict names each unmet/unverified criterion. When no criteria were supplied, emit the root's pinned one-line fallback instead.

## Red Flags

| Thought | Reality |
|---|---|
| "Tests green and risks covered — SAFE, even though one acceptance criterion isn't delivered" | Green + risk-covered answers "correct code", not "the right code". A supplied AC that is UNMET or UNVERIFIED is a SAFE-blocker exactly like an uncovered risk — NOT SAFE until met with cited evidence. |
| "No ACs were pasted, so I'll skip the AC check silently" | Say so in one line and fall back to the risk-coverage verdict. Silent skip hides that the right-code question went unanswered; fabricating criteria is worse. |
| "The host should fetch the issue's ACs for me" | Never. Host-neutral: the host SUPPLIES the criteria; the skill never calls `gh` / a tracker / an API. Same data-ownership split as the risk ledger. |
