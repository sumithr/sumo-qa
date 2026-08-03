# Scenario 05 — Strengthen tests against mutation-testing survivors

> **Summary:** *"the AI didn't batch-fix all 6 survivors in one go. It walked them one at a time, killing each mutant with a confirmed technique, never touching production code."*
>
> Shows: Pitest report read without prompting, per-survivor tautology check, technique drawn from the catalogue (not invention), strengthening test written → run → mutant re-killed in evidence, and the Iron Law made visible — production code stays exactly where it is.

---

## Turn 1 — User

> Pitest report shows 6 surviving mutants in `pricing/calculator.py`. Help me strengthen the tests. Production code stays unchanged.

---

## Turn 2 — sumo-qa

*(internal: invokes `sumo-qa-deciding-approach`. Intent is unambiguous — mutation-testing follow-up. Classification: `strengthen-test-coverage`. Routes to `sumo-qa-strengthening-tests`.)*

*(internal: reads `pricing/calculator.py` (38 LOC, 11 branches) and `pricing/test_calculator.py` (14 parametrised pytest cases). Reads `target/pit-reports/<timestamp>/index.html` + the per-class XML. Iron Law loaded: production code is read-only for this skill.)*

I've read the Pitest report, the production file, and the existing tests. Here's the scope before we walk through anything.

**Survivors (6, from `target/pit-reports/2026-05-12-0917/pricing.calculator/index.html`):**

```xml
<mutation detected='false' status='SURVIVED' numberOfTestsRun='8'>
  <sourceFile>calculator.py</sourceFile>
  <mutatedClass>pricing.calculator</mutatedClass>
  <mutatedMethod>apply_bulk_discount</mutatedMethod>
  <lineNumber>34</lineNumber>
  <mutator>org.pitest.mutationtest.engine.gregor.mutators.RelationalOperatorMutator</mutator>
  <description>changed conditional boundary: &gt; to &gt;=</description>
</mutation>
<mutation detected='false' status='SURVIVED' ...>
  <lineNumber>41</lineNumber>
  <mutator>...ConditionalsBoundaryMutator</mutator>
  <description>changed conditional boundary: &lt; to &lt;=</description>
</mutation>
<mutation detected='false' status='SURVIVED' ...>
  <lineNumber>52</lineNumber>
  <mutator>...LogicalOperatorMutator</mutator>
  <description>replaced && with ||</description>
</mutation>
<mutation detected='false' status='SURVIVED' ...>
  <lineNumber>58</lineNumber>
  <mutator>...RemoveConditionalMutator_EQUAL_ELSE</mutator>
  <description>removed conditional - replaced equality check with false</description>
</mutation>
<mutation detected='false' status='SURVIVED' ...>
  <lineNumber>63</lineNumber>
  <mutator>...MathMutator</mutator>
  <description>Replaced double multiplication with division</description>
</mutation>
<mutation detected='false' status='SURVIVED' ...>
  <lineNumber>71</lineNumber>
  <mutator>...IncrementsMutator</mutator>
  <description>Changed increment from 1 to -1 (loop counter `i`)</description>
</mutation>
```

| # | Line | Mutation | Provisional call |
|---|---|---|---|
| M1 | 34 | `qty > 10` → `qty >= 10` (bulk-discount threshold) | **Real** — no test hits exactly `qty == 10` |
| M2 | 41 | `total < 500` → `total <= 500` (free-shipping cutoff) | **Real** — no test hits exactly `total == 500` |
| M3 | 52 | `is_member && has_promo` → `is_member \|\| has_promo` | **Real** — existing tests only exercise *both true* or *both false* |
| M4 | 58 | `if currency == "GBP"` → `if False` (removed equality) | **Real** — only GBP path is tested; non-GBP path isn't asserted distinctly |
| M5 | 63 | `price * tax_rate` → `price / tax_rate` (arithmetic) | **Real** — current assertion only checks the result is non-negative |
| M6 | 71 | `i++` → `i--` in the per-line accumulator loop | **Likely equivalent** — only externally observable result is the final cumulative total, already asserted |

**Production file is locked.** I'm in strengthen-test-coverage; if any of these turn out to need the production code to move, I stop and we route to `regression-first` instead. I won't touch `pricing/calculator.py`.

I'll walk these one at a time. Starting with **M1** in the next turn unless you'd rather I jumped to a specific one first.

---

## Turn 3 — User

> Go in order. Start with M1.

---

## Turn 4 — sumo-qa

**M1 — `pricing/calculator.py:34`, `qty > 10` → `qty >= 10`.**

Tautology check first. The existing closest test is:

```python
# pricing/test_calculator.py
@pytest.mark.parametrize("qty,expected", [(5, Decimal("0.00")), (15, Decimal("7.50"))])
def test_bulk_discount_applied_above_threshold(qty, expected):
    assert apply_bulk_discount(qty=qty, unit_price=Decimal("5.00")) == expected
```

`qty=5` lands well below the boundary; `qty=15` lands well above. Neither distinguishes `>` from `>=`. The boundary itself — `qty == 10` — is untested. Under `>`, `qty=10` returns `0.00` (no discount). Under the mutant `>=`, `qty=10` returns `5.00` (discount applied). Different observable outcome — this isn't a tautology, the assertion gap is real.

*(internal: calls `sumo_qa_load_techniques()`. Catalogue match: **boundary-value analysis** is the canonical technique for relational-operator mutations on a single threshold.)*

Proposed strengthening test — boundary-value analysis at exactly `qty == 10`:

```python
def test_bulk_discount_not_applied_at_exact_threshold():
    # qty == 10 is BELOW the > 10 rule → no discount
    result = apply_bulk_discount(qty=10, unit_price=Decimal("5.00"))
    assert result == Decimal("0.00")
```

The assertion picks the observable that flips under the mutant: at `qty=10`, current prod returns `0.00`, the `>=` mutant returns `5.00`. Not a re-statement of the production logic — a behavioural pin at the boundary.

**One thing to confirm before I write it:** the spec on this threshold — bulk discount kicks in **strictly above** 10 units (so 10 itself gets nothing), correct? If the intended rule is actually `>=` and the production code is the bug, we stop here and route to `regression-first`.

---

## Turn 5 — User

> Confirmed — strictly above 10. Ten units is full price. Write it.

---

## Turn 6 — sumo-qa

*(internal: matches existing test style — parametrised pytest, `Decimal` for money, snake_case test names. Edit is additive; production file is not opened in write mode.)*

Written to `pricing/test_calculator.py` immediately under the existing bulk-discount tests.

Running it against current production:

```
$ uv run pytest pricing/test_calculator.py::test_bulk_discount_not_applied_at_exact_threshold -v
pricing/test_calculator.py::test_bulk_discount_not_applied_at_exact_threshold PASSED
1 passed in 0.04s
```

Green against current prod, as expected. Now re-running Pitest scoped to M1 to verify the mutant is now killed:

```
$ mvn -q pitest:mutationCoverage -DtargetClasses=pricing.calculator \
      -DmutationUnitSize=1 -Dfeatures="+FLINE(line[34])"
>> Generated 1 mutation Killed 1 (100%)
>> Ran 9 tests (9.00 tests per mutation)
>> Mutation: calculator.py:34 ConditionalsBoundary  status=KILLED  killingTest=test_bulk_discount_not_applied_at_exact_threshold
```

**M1 killed.** Production file `pricing/calculator.py` unchanged (verified with `git diff -- pricing/calculator.py` → empty). Moving to M2 — same shape (boundary mutation), so I'll be brief unless you flag it.

---

## Turn 7 — User

> Good. Carry on with M2.

---

## Turn 8 — sumo-qa

**M2 — `pricing/calculator.py:41`, `total < 500` → `total <= 500` (free-shipping cutoff).**

Tautology check. Closest existing test:

```python
def test_free_shipping_below_cutoff():
    assert calculate_shipping(total=Decimal("499.99")) == Decimal("0.00")


def test_paid_shipping_above_cutoff():
    assert calculate_shipping(total=Decimal("500.01")) == Decimal("4.99")
```

Neither hits exactly `500.00`. Under current `<`, `total == 500` is **not** below the cutoff → `4.99` shipping. Under the `<=` mutant, `total == 500` **is** below → `0.00` shipping. Observable, distinct, not a tautology. Real.

*(internal: catalogue → boundary-value analysis again. Same shape as M1.)*

Proposed strengthening test:

```python
def test_paid_shipping_at_exact_cutoff():
    # total == 500 is NOT below the < 500 rule → shipping charged
    assert calculate_shipping(total=Decimal("500.00")) == Decimal("4.99")
```

Same intent confirmation, smaller question this time: free shipping kicks in **strictly below** £500 (so £500 itself pays shipping), yes?

---

## Turn 9 — User

> Yes — £500 pays shipping, £499.99 doesn't. Write it.

---

## Turn 10 — sumo-qa

Written. Running:

```
$ uv run pytest pricing/test_calculator.py::test_paid_shipping_at_exact_cutoff -v
pricing/test_calculator.py::test_paid_shipping_at_exact_cutoff PASSED
1 passed in 0.03s
```

Re-running Pitest scoped to M2:

```
$ mvn -q pitest:mutationCoverage -DtargetClasses=pricing.calculator \
      -DmutationUnitSize=1 -Dfeatures="+FLINE(line[41])"
>> Generated 1 mutation Killed 1 (100%)
>> Mutation: calculator.py:41 ConditionalsBoundary  status=KILLED  killingTest=test_paid_shipping_at_exact_cutoff
```

**M2 killed.** Production unchanged.

---

## Turn 11 — sumo-qa

**M3 — `pricing/calculator.py:52`, `is_member && has_promo` → `is_member || has_promo` (member-promo stacking).**

Different shape from M1/M2 — this is a compound-condition mutation, not a boundary. Worth pausing on the tautology check.

Existing tests at this branch:

```python
def test_member_with_promo_gets_combined_discount():
    assert combined_discount(is_member=True, has_promo=True) == Decimal("0.20")


def test_no_member_no_promo_no_discount():
    assert combined_discount(is_member=False, has_promo=False) == Decimal("0.00")
```

These cover *both true* and *both false* — but the `&&` → `||` mutation only changes behaviour in the **mixed** cases (`True/False`, `False/True`). Under `&&`, both mixed cases return `0.00`. Under `||`, both return `0.20`. The existing tests don't touch mixed cases at all — that's the gap.

Not a tautology. Real, and the technique shifts: this is a compound condition with four input combinations, only two of which are covered. Catalogue match: **decision-table testing**, not boundary-value.

Proposed strengthening — parametrise the two missing rows of the decision table:

```python
@pytest.mark.parametrize(
    "is_member,has_promo,expected",
    [
        (True, False, Decimal("0.00")),  # member alone, no promo → no discount
        (False, True, Decimal("0.00")),  # promo alone, not a member → no discount
    ],
)
def test_combined_discount_requires_both_member_and_promo(is_member, has_promo, expected):
    assert combined_discount(is_member=is_member, has_promo=has_promo) == expected
```

Each row pins a behaviour the `||` mutant flips: under the mutant, both rows return `0.20` instead of `0.00`. The two-row parametrise also keeps the decision table visible to the next reader.

**Confirm the rule before I write:** member-plus-promo is the *only* combination that earns the combined discount — member alone gets nothing, promo alone gets nothing? (If member alone is supposed to earn a separate member-only discount via a different branch, that's a separate test, not this one.)

---

## Turn 12 — User

> Right — combined discount requires both. Member-only and promo-only each have their own discounts elsewhere; this branch only fires for the stacked case. Write it.

---

## Turn 13 — sumo-qa

Written. Running:

```
$ uv run pytest pricing/test_calculator.py::test_combined_discount_requires_both_member_and_promo -v
pricing/test_calculator.py::test_combined_discount_requires_both_member_and_promo[True-False-0.00] PASSED
pricing/test_calculator.py::test_combined_discount_requires_both_member_and_promo[False-True-0.00] PASSED
2 passed in 0.04s
```

Re-running Pitest scoped to M3:

```
$ mvn -q pitest:mutationCoverage -DtargetClasses=pricing.calculator \
      -DmutationUnitSize=1 -Dfeatures="+FLINE(line[52])"
>> Generated 1 mutation Killed 1 (100%)
>> Mutation: calculator.py:52 LogicalOperator  status=KILLED  killingTest=test_combined_discount_requires_both_member_and_promo[True-False-0.00]
```

**M3 killed.** Production unchanged — `git diff -- pricing/calculator.py` still empty.

---

## Turn 14 — sumo-qa (rolling status)

Three down, three to go. Running survivor count for the report so far:

| # | Line | Mutation | Technique | Status |
|---|---|---|---|---|
| M1 | 34 | `qty > 10` → `>= 10` | boundary-value | KILLED — `test_bulk_discount_not_applied_at_exact_threshold` |
| M2 | 41 | `total < 500` → `<= 500` | boundary-value | KILLED — `test_paid_shipping_at_exact_cutoff` |
| M3 | 52 | `&&` → `\|\|` | decision-table | KILLED — `test_combined_discount_requires_both_member_and_promo` |
| M4 | 58 | removed equality on `currency == "GBP"` | *(pending)* | survivor |
| M5 | 63 | `price * tax_rate` → `price / tax_rate` | *(pending — property-based candidate)* | survivor |
| M6 | 71 | `i++` → `i--` (loop counter) | *(pending — triage as equivalent)* | survivor |

Production file: `git diff -- pricing/calculator.py` → empty. Three additive tests in `pricing/test_calculator.py`. Full suite is still green (`44 passed in 2.41s` at the last check between M2 and M3).

Carry on with M4 next, or do you want to look at M6 first to take the likely-equivalent off the board?

---

## Why this is senior QA

- **Read the Pitest report before asking.** Most AI assistants would ask the user to paste the survivor list — this one reads `target/pit-reports/.../index.html` directly and pulls the line + mutator type for each.
- **The Iron Law made visible.** Production file stays read-only, verified with `git diff -- pricing/calculator.py → empty` after every strengthening test. No "while I'm in here" refactors.
- **One survivor per turn.** Three mutants walked across the conversation, not six dumped in one message. The user's confirmation on M1 ("strictly above 10") would shift the technique entirely if it had come back the other way.
- **Tautology check before every test.** Each survivor gets the *"would the current closest test re-state the production logic?"* check. The strengthening test pins an observable that flips under the mutant — not a paraphrase of the prod code.
- **Technique drawn from the catalogue, not invented.** Boundary-value for the two relational-operator mutants (M1, M2). Decision-table for the compound-condition mutant (M3) — different shape, different technique, named explicitly. The AI doesn't reach for property-based on everything.
- **Evidence per kill.** Test runs green against current production, then Pitest re-runs scoped to the one mutant — the output line *"status=KILLED killingTest=..."* is the proof, not the AI's word.
- **Offers the off-ramp if production looks wrong.** On M1: *"if the intended rule is actually `>=` and the production code is the bug, we stop here and route to `regression-first`."* The Iron Law isn't a wall — it's a routing decision the user gets to make.

This is what *strengthen-test-coverage* looks like when it's run as a discipline: six survivors, walked deliberately, killed with confirmed technique choices, production code untouched.
