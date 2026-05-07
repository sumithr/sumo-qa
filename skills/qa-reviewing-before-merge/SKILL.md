---
name: qa-reviewing-before-merge
description: Use when the user asks "review my changes / is this safe to merge / what could break". Calls sumo_qa_review_local_change, surfaces the verdict, and refuses to claim 'safe to merge' without addressing the findings.
---

## When to load

Load this skill when the user is at the **end** of an implementation and is asking for QA sign-off. Triggers:
- "review my changes"
- "is this safe to merge"
- "what could break if I ship this"
- "did I miss any tests"
- "look at my diff and tell me what to test"

Do NOT load this skill at the START of a piece of work — that's `qa-deciding-approach` → `qa-implementing-with-tdd`. This is the gate before merge.

## The Iron Law

```
NO 'SAFE TO MERGE' WITHOUT VERDICT == 'qa-risk-acceptable-for-phase-1-input' (or explicit waiver)
```

If `sumo_qa_review_local_change` returns `verdict: "needs-test-evidence"` or `"review-risk-before-handoff"`, the change is NOT ready to merge. Do not paraphrase the verdict away. Do not tell the user "looks fine" when the tool says otherwise.

## Checklist

- [ ] Gather the change context: change summary, touched files (let the tool run `git diff` if not supplied)
- [ ] Call `sumo_qa_review_local_change(change_summary=..., touched_files=[...], test_evidence=[...])`
- [ ] Read these fields, in order:
  - [ ] `verdict` — the headline call
  - [ ] `change_classification.primary` and `primary_confidence`
  - [ ] `local_diff.missing_test_levels` — what's NOT covered
  - [ ] `qa_findings` — each with `severity`, `category`, `finding`, and `recommended_test_path` if present
  - [ ] `top_risks` (highest-severity first)
  - [ ] `recommended_approach` — does it match the user's intent?
  - [ ] `specialty_testing_needs` — anything to pull in?
- [ ] **Surface the verdict literally**, not paraphrased. Lead with `VERDICT: <verdict>`.
- [ ] If verdict is `needs-test-evidence`:
  - [ ] List every `qa_findings[].recommended_test_path` with its severity
  - [ ] Recommend writing those tests OR explicitly waiving with a reason
  - [ ] Do NOT say "looks fine"
- [ ] If verdict is `review-risk-before-handoff`:
  - [ ] List the `qa_findings` and `top_risks`
  - [ ] Recommend addressing or accepting them with explicit reasoning
- [ ] If verdict is `qa-risk-acceptable-for-phase-1-input`:
  - [ ] State that as the conclusion
  - [ ] Still surface any remaining `missing_information` so nothing is hidden

## Red Flags — STOP

| Thought | Reality |
|---------|---------|
| "Verdict says needs-test-evidence but tests pass locally; I'll soften it" | The tool sees missing test LEVELS, not just whether tests pass. It's saying "you have unit but not contract" or "you have no tests for the touched file". Read `missing_test_levels`. |
| "User said 'just confirm it's safe' — I'll say yes if no obvious problems" | Confirming-without-evidence is the failure mode this whole MCP exists to prevent. Surface the verdict literally. |
| "I'll downgrade severity from 'high' to 'medium' because the user is in a rush" | Severity comes from rules, not vibes. Don't rewrite. |
| "I'll skip the recommended_test_path because it's just a suggestion" | The path is concrete because the tool wants you to act on it. Surface it. |
| "Verdict isn't ready but I'll say 'mostly safe' to soften the message" | Use the literal verdict string. The user can override; the tool won't soften for you. |
| "specialty_testing_needs says pull in Cypress; we don't have Cypress, skip it" | Surface the recommendation. The user might add Cypress (or accept the gap explicitly). Don't decide for them. |
| "applied_rules has 12 items, I'll summarise the top 3" | Read `top_risks`. The MCP already did the picking. |

## Output shape

When you respond to the user:

```
VERDICT: <literal verdict from the tool>

<headline from the tool>

Findings:
- [<severity>] <finding> (suggested: <recommended_test_path>)
- ...

Top risks:
- [<severity>] <category> — <description>
- ...

Need: <missing_information items, joined>

(if specialty needs) Pull in:
- <approach> — e.g. <well-known tools>
```

Then ask the user one of:
- "Want me to scaffold the missing tests?" — if `verdict: needs-test-evidence`
- "Which finding do you want to tackle first?" — if `review-risk-before-handoff`
- "Anything you want to dig into before merge?" — if `qa-risk-acceptable-for-phase-1-input`

## Examples

### Verdict: needs-test-evidence

User: *"review my changes; touched src/orders/api.py"*

Tool returns:
```json
{
  "verdict": "needs-test-evidence",
  "headline": "No test evidence found for src/orders/api.py...",
  "qa_findings": [
    {"severity": "high", "category": "missing-evidence", "finding": "No test evidence or nearby test file was found for the local change."},
    {"severity": "medium", "category": "missing-test-level", "finding": "Expected contract coverage from change rules, but no clear evidence was found.", "recommended_test_path": "tests/orders/test_api_contract.py"}
  ],
  "top_risks": [
    {"severity": "high", "category": "api_contract_change", "description": "Consumer behavior can break if payload shape or validation changes silently. Touched: src/orders/api.py."}
  ],
  "missing_information": ["test evidence", "contract"]
}
```

Your response:
```
VERDICT: needs-test-evidence

No test evidence found for src/orders/api.py. Add or name a test before merging.

Findings:
- [high] No test evidence or nearby test file was found for the local change.
- [medium] Expected contract coverage from change rules, but no clear evidence was found. (suggested: tests/orders/test_api_contract.py)

Top risks:
- [high] api_contract_change — Consumer behavior can break if payload shape or validation changes silently. Touched: src/orders/api.py.

Need: test evidence; contract

Want me to scaffold the missing contract test? (would call sumo_qa_scaffold_tests)
```

### Verdict: qa-risk-acceptable-for-phase-1-input

Same flow; surface the verdict literally even though there's nothing to fix; offer to dig into anything still flagged in `missing_information`.

## Final rule

```
Surface the verdict literally. Never claim safe to merge unless the tool says so.
```
