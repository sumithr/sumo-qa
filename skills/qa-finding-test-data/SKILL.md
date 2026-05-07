---
name: qa-finding-test-data
description: Use when the user asks about test data — "what data do I need to test X", "find me a known-good record", "is this entry still valid", "save this as known-good". Routes between sumo_qa_explain_test_data_requirements, sumo_qa_find_test_data, sumo_qa_validate_test_data, and sumo_qa_register_known_good_test_data.
---

## When to load

Triggers:
- "what test data do I need for X" → `sumo_qa_explain_test_data_requirements`
- "find me a known-good record / SKU / postcode for X" → `sumo_qa_find_test_data`
- "is this test data still valid / is entry X still good" → `sumo_qa_validate_test_data`
- "save this as known-good / register this fixture" → `sumo_qa_register_known_good_test_data`

If the user is asking about test data IN THE CONTEXT of planning or scaffolding a piece of work, the parent skill (`qa-implementing-with-tdd`) handles routing.

## The Iron Law

```
TEST DATA IS PART OF THE TEST. Honour freshness, ownership, and validity.
```

Three sub-rules:
1. **Stale data is a defect**, not a footnote — flag it, don't paper over it.
2. **Owned data wins over found-by-search data** — registered known-good entries are first-class.
3. **High confidence requires validation** — never claim a fixture is solid without checking freshness.

## Decision flow

```
Is the user asking what data they NEED?     → sumo_qa_explain_test_data_requirements
Is the user asking where to FIND it?         → sumo_qa_find_test_data
Is the user CHECKING a specific entry?       → sumo_qa_validate_test_data
Is the user CONTRIBUTING a known-good?       → sumo_qa_register_known_good_test_data
```

## Sub-flows

### "What test data do I need for X"

1. Call `sumo_qa_explain_test_data_requirements(question=..., environment=..., domain=...)`.
2. Read the response:
   - `required_product_characteristics`
   - `stock_conditions` / `fulfilment_conditions`
   - `downstream_dependencies`
   - `edge_case_recommendations`
   - `what_not_to_use` ← surface this prominently
3. Surface the requirements as an actionable shopping list.
4. Offer to chain to `sumo_qa_find_test_data` if the user says "now find me one".

### "Find me a known-good record for X"

1. Call `sumo_qa_find_test_data(environment=..., domain=..., scenario_tags=[...], known_valid_for=[...])`.
2. Read `results[]` (already ranked by confidence + freshness):
   - Lead with the top match's `entry`, `validation.confidence`, `validation.freshness`, `suitability_reason`.
3. If `results == []`, surface `missing_information` — it includes filter-too-narrow hints.
4. NEVER fabricate an entry that isn't in the catalogue. If nothing matches, recommend registering one OR widening the filter.

### "Is this test data still valid"

1. Call `sumo_qa_validate_test_data(entry_id=...)` or `sumo_qa_validate_test_data(entry={...})`.
2. Read `validation`:
   - `valid` — boolean
   - `confidence.level` — high/medium/low
   - `freshness.status` — fresh / aging / stale / unknown / not_applicable
   - `issues[]` — the plausibility checks (future timestamps, high-confidence-without-validation, etc.)
3. **If `valid: false`, lead with that.** Do not soften it. List the specific `issues[]` so the user can fix them.

### "Save this as known-good"

1. Call `sumo_qa_register_known_good_test_data(entry={...})`.
2. Read `action`: `created` / `updated` / `duplicate`.
3. If `duplicate`, surface `duplicate_of` so the user sees they're re-adding existing data.
4. The MCP rejects entries with `confidence: "high"` and no `last_validated_at`. If the user wants high confidence, they need to validate first; surface the rejection's `ValueError` message verbatim.

## Red Flags — STOP

| Thought | Reality |
|---------|---------|
| "results is empty; I'll suggest a SKU I made up" | Catalogue-only. Recommend registering a known-good or widening the filter. |
| "The entry is stale, I'll downgrade the warning" | Stale = defect. Flag prominently. |
| "User wants high-confidence, I'll register with confidence: high anyway" | The MCP refuses. Tell the user "validate first, then promote to high". |
| "freshness.status: unknown — I'll ignore it" | Unknown = never validated = not valid. Surface it. |
| "User said 'find me anything reasonable', I'll skip filters" | Empty filters return everything; ranking is degraded; user gets noise. Make the user state at least one constraint. |
| "I'll combine results from multiple find calls into one synthetic answer" | Don't aggregate. The ranking the MCP returns is honest about confidence and freshness; aggregating loses signal. |

## Examples

### Need a fixture for out-of-area pricing

User: *"what test data do I need to test out-of-area fulfilment pricing?"*

→ `sumo_qa_explain_test_data_requirements(question="out-of-area fulfilment pricing", environment="integration", domain="fulfilment")`.

Surface:
```
For out-of-area fulfilment pricing tests:
- Required: stable product identifier, product active in target environment, location outside configured fulfilment coverage, clear expected rejection reason.
- Stock conditions: known stock state before test execution.
- Fulfilment conditions: location outside configured fulfilment coverage, borderline postcode near service boundary, eligible product with ineligible address.
- Downstream dependencies: product catalogue, pricing service, fulfilment eligibility service.
- Edge cases: borderline postcode near service boundary, eligible product with ineligible address.
- What NOT to use: products that fail because of stock rather than area eligibility.

Want me to find a matching known-good record? (would call sumo_qa_find_test_data)
```

### Validate a specific entry

User: *"is entry stock-pricing-validation-001 still good?"*

→ `sumo_qa_validate_test_data(entry_id="stock-pricing-validation-001")`.

If `valid: true, freshness: "aging", confidence.level: "medium"`:
```
Valid (with caveats):
- freshness: aging — validated 16 days ago; refresh before release sign-off.
- confidence: medium.
- No plausibility issues.
```

If `valid: false`:
```
NOT valid:
- issues: <list each issue verbatim>
- freshness: <status>
- confidence: low
Fix the listed issues OR re-validate before using.
```

## Final rule

```
Test data has a lifecycle. Honour freshness, ownership, validity. Never invent entries.
```
