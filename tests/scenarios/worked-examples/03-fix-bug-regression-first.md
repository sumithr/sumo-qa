# Scenario 03 — Fix a production bug regression-first

> **Demo arc:** *"the AI didn't write the test AND the fix in one shot — it proved the test catches the bug FIRST, then handed off. The red-then-green cycle is non-negotiable."*
>
> Shows: repo-walk before any questions, ONE focused product question, tautology check (a wrong assertion is rejected before it's written), HARD GATE refusing to write production code alongside the failing test, verbatim red output, then verbatim green + targeted regression after handoff.

---

## Turn 1 — User

> Fix the VIP-customer double-discount bug regression-first. The discount stacks twice when a VIP gets a promo code applied. Logic is in `pricing/discount_calculator.py`.

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-deciding-approach`. Intent: bug fix on existing code. Classification: `business_logic_change` + `bug_fix`. Approach: `regression-first`. Routes to `qa-implementing-with-tdd`.)*

*(internal: walks the repo with the host's file tools — reads `pricing/discount_calculator.py`, locates `pricing/test_discount_calculator.py`, scans two sibling test files to fix the framework and fixture style. Does NOT ask the user "what test framework do you use?")*

I've read the calculator and the sibling tests. Here's the lay of the land and the one product call I need from you before I write the failing test.

**Where the bug lives:**

| File | What it does |
|---|---|
| `pricing/discount_calculator.py:34` | `apply_discounts(order)` — iterates `order.applicable_discounts`, subtracts each in turn. No tier-vs-promo precedence rule. |
| `pricing/discount_calculator.py:51` | `_vip_discount(order)` — returns 10% off when `order.customer.tier == "VIP"`. |
| `pricing/discount_calculator.py:62` | `_promo_discount(order)` — returns the promo amount when `order.promo_code` is set and valid. |
| `pricing/test_discount_calculator.py` | pytest, uses an `Order` dataclass fixture from `pricing/fixtures.py`, parametrised with `@pytest.mark.parametrize`. |

**What I think is happening:** for an `Order` with `customer.tier == "VIP"` AND a valid `promo_code`, both `_vip_discount` and `_promo_discount` return a non-zero amount, and `apply_discounts` subtracts both from `order.subtotal`. The order pays VIP-discount AND promo-discount stacked — that's the double-discount.

**Smallest failing test idea:** call `apply_discounts(order)` on an order with `subtotal=£100`, `customer.tier="VIP"` (10% off → £10), and `promo_code="WELCOME10"` (£10 off), and assert `order.total == £90.00`.

**The one thing I can't read from the code:** **is £90.00 the right expected total — i.e. VIP overrides promo entirely (only the larger discount applies), or do they stack but cap at one tier? The product rule isn't expressed anywhere in the file.**

---

## Turn 3 — User

> VIP overrides promo entirely. Only the larger of the two applies — never both. So yes, £90.00 is right.

---

## Turn 4 — sumo-qa

Good — that pins the assertion. Quick sanity check before I write it, because I want to flag what I'm *not* going to assert:

> I'm **not** going to write `assert order.total == order.subtotal - max(vip_discount, promo_discount)`. That re-states the production logic — the broken code computing `subtotal - vip - promo` would also pass once we "fix" it that way, and worse, a future regression that brings stacking back wouldn't necessarily fail this assertion if someone tweaked the helpers. It's a tautology dressed up as a test.
>
> Instead I'll assert the **observable outcome**: `order.total == Decimal("90.00")`. That's a concrete number the bug currently violates (it'll produce £80.00) and that the fix has to deliver. If the rule ever changes, the test breaks loudly and a human reads it.

Writing the test now against `pricing/test_discount_calculator.py`, same pytest + `Order` fixture style as the siblings. No production code touched.

---

## Turn 5 — sumo-qa (writes the test, runs it)

Added the regression test:

```python
# pricing/test_discount_calculator.py

def test_vip_with_promo_does_not_stack_discounts():
    """Regression: VIP tier + promo code must not stack — VIP wins outright."""
    order = Order(
        subtotal=Decimal("100.00"),
        customer=Customer(tier="VIP"),
        promo_code="WELCOME10",  # £10 flat off, currently valid
        applicable_discounts=["vip", "promo"],
    )

    apply_discounts(order)

    assert order.total == Decimal("90.00"), (
        f"VIP should override promo entirely; expected £90.00, got £{order.total}"
    )
```

Running it:

```
$ uv run pytest pricing/test_discount_calculator.py::test_vip_with_promo_does_not_stack_discounts -v
============================= test session starts ==============================
collected 1 item

pricing/test_discount_calculator.py::test_vip_with_promo_does_not_stack_discounts FAILED [100%]

=================================== FAILURES ===================================
______________ test_vip_with_promo_does_not_stack_discounts ___________________

    def test_vip_with_promo_does_not_stack_discounts():
        order = Order(
            subtotal=Decimal("100.00"),
            customer=Customer(tier="VIP"),
            promo_code="WELCOME10",
            applicable_discounts=["vip", "promo"],
        )

        apply_discounts(order)

>       assert order.total == Decimal("90.00"), (
            f"VIP should override promo entirely; expected £90.00, got £{order.total}"
        )
E       AssertionError: VIP should override promo entirely; expected £90.00, got £80.00
E       assert Decimal('80.00') == Decimal('90.00')

pricing/test_discount_calculator.py:47: AssertionError
=========================== short test summary info ============================
FAILED pricing/test_discount_calculator.py::test_vip_with_promo_does_not_stack_discounts
============================== 1 failed in 0.18s
```

### Red phase confirmed.

The test fails for the right reason: `apply_discounts` produced **£80.00** (both discounts stacked: 100 − 10 VIP − 10 promo) where the contract says **£90.00** (VIP only). That's the bug, reproduced as a failing test, anchored at `pricing/test_discount_calculator.py:47`.

> **HARD GATE — I'm stopping here.** I will NOT write the production fix in the same turn as the failing test. The red phase is the proof: it shows the test catches *this* bug, it shows what "fixed" has to deliver, and it'll fail again if the regression returns. If I bundle red and green you lose that proof — what's left is a test that's never been seen to fail.
>
> **Over to you.** Implement so VIP-tier customers get only the larger of (VIP discount, promo discount) applied — never both. Sketch of where to make the change: `pricing/discount_calculator.py:34` (`apply_discounts`) needs a precedence step before iterating `applicable_discounts`, OR `_promo_discount` short-circuits to 0 when `customer.tier == "VIP"`. Pick whichever fits the rest of the calculator's shape.
>
> Tell me when you're ready and I'll re-run the test. If you'd rather I write the production code, say so explicitly — but I'd rather you own the green-making step so the discipline holds.

---

## Turn 6 — User

> Done. I added a precedence step at the top of `apply_discounts` — when the customer is VIP, the promo discount is zeroed out before iteration. Re-run it.

---

## Turn 7 — sumo-qa

Re-running the regression test, then a targeted sweep around the changed file.

```
$ uv run pytest pricing/test_discount_calculator.py::test_vip_with_promo_does_not_stack_discounts -v
============================= test session starts ==============================
collected 1 item

pricing/test_discount_calculator.py::test_vip_with_promo_does_not_stack_discounts PASSED [100%]

============================== 1 passed in 0.09s
```

Green — and green for the right reason: `order.total == Decimal("90.00")` now holds, which means the precedence step is producing the VIP-only outcome the contract asks for. The assertion didn't move; the production behaviour did.

Targeted regression on the discount module and its closest siblings:

```
$ uv run pytest pricing/ -v
============================= test session starts ==============================
collected 23 items

pricing/test_discount_calculator.py::test_no_discount_when_subtotal_zero PASSED
pricing/test_discount_calculator.py::test_vip_discount_alone_applies PASSED
pricing/test_discount_calculator.py::test_promo_discount_alone_applies PASSED
pricing/test_discount_calculator.py::test_invalid_promo_is_ignored PASSED
pricing/test_discount_calculator.py::test_vip_with_promo_does_not_stack_discounts PASSED
pricing/test_discount_calculator.py::test_non_vip_with_promo_applies_promo PASSED
pricing/test_discount_calculator.py::test_expired_promo_falls_back_to_vip PASSED
pricing/test_pricing_engine.py::test_engine_applies_discount_pipeline PASSED
pricing/test_pricing_engine.py::test_engine_rounds_to_minor_unit PASSED
... [14 more]

============================== 23 passed in 0.42s
```

23 passed, 0 failed, no green-to-red anywhere in `pricing/`. The fix is local — nothing in the engine or rounding paths flinched.

**Risk → covering test map for this cycle:**

| Risk | Covering test | Status |
|---|---|---|
| VIP + promo double-stack regression | `test_vip_with_promo_does_not_stack_discounts` | ✅ green (was red pre-fix) |
| Non-VIP + promo still applies promo | `test_non_vip_with_promo_applies_promo` | ✅ green |
| Expired promo on VIP falls back cleanly | `test_expired_promo_falls_back_to_vip` | ✅ green |
| VIP alone, no promo | `test_vip_discount_alone_applies` | ✅ green |

The two siblings on rows 2–3 are worth flagging: they exercise the precedence rule from the *other* direction (non-VIP path still works; VIP without a valid promo still works). If your change had accidentally zeroed promo for everyone, `test_non_vip_with_promo_applies_promo` would have caught it. It didn't — that path is intact.

### Cycle complete.

Red → green → targeted regression, all evidence on screen. The bug has a named regression test that will fail again if it returns.

**Next step:** I'd recommend handing off to `qa-reviewing-before-merge` before this lands — there's an open question about whether any downstream consumer (the loyalty service, the invoicing report) assumes VIP-and-promo can co-occur on a line item, and the review skill is the right place to read the diff in full and run the wider suite. Want me to route there?

---

## Why this is "senior QA" — what to point at in the demo

- **Repo-walk before any questions.** The user didn't say "use pytest" or "the fixtures are dataclasses" — the AI read the sibling tests and surfaced what it found. The only question asked is one the code genuinely *can't* answer: the product rule for VIP-vs-promo precedence.
- **One focused product question, not four.** *"VIP overrides entirely, or stack-but-cap?"* — and that's it. No interrogation about frameworks, file locations, or assertion libraries.
- **Tautology check before writing.** The AI explicitly rejects `assert total == subtotal - max(vip, promo)` as a re-statement of production logic, and explains why the concrete value `£90.00` is the right shape of assertion. That's the difference between a regression guard and a wishlist.
- **HARD GATE on the red→green split.** *"I will NOT write the production fix in the same turn as the failing test."* The user is offered the green-making step explicitly, with a reason: the red phase is the proof, and bundling destroys it.
- **Red output shown verbatim.** Not *"the test fails as expected"* — the actual `AssertionError: ... Decimal('80.00') == Decimal('90.00')` at `pricing/test_discount_calculator.py:47`. Real evidence, not a vibe.
- **Green confirmed for the right reason.** *"The assertion didn't move; the production behaviour did."* That's the discipline — the test wasn't weakened to pass.
- **Targeted regression catches what local re-runs miss.** Two sibling tests (non-VIP-with-promo, expired-promo-falls-back-to-VIP) confirm the precedence rule didn't over-apply. The AI calls those out by name.
- **Refuses to claim safe-to-merge.** That verdict belongs to `qa-reviewing-before-merge`, and the handoff is offered cleanly. This skill's job ends at "regression test in place, green, surrounding suite still green."

This is what *"shift-left QA"* looks like in practice: the test exists *because* it caught the bug; the fix exists *because* the test demanded it; and the next time the regression tries to return, the suite will see it before a customer does.
