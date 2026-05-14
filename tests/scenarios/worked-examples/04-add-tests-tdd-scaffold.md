# Scenario 04 — Add tests for a new behaviour-driven feature (TDD-scaffold)

> **Summary:** *"the AI didn't scaffold 5 tests up front and walk away. It started with the highest-value boundary test, confirmed it red, then handed off — TDD is one red→green cycle at a time."*
>
> Shows: repo-walk before asking, risk surfaces named *before* assertions, refusal to write 5 tests at once, observable-behaviour assertions (not internal counters), red output shown verbatim, hand-off after red, second cycle only after the first is green.

---

## Turn 1 — User

> I'm adding rate-limiting to the auth service — 100 requests / minute / IP, sliding window. Want to TDD it. Scaffold the failing tests first.

---

## Turn 2 — sumo-qa

*(internal: invokes `sumo-qa-deciding-approach`. Intent shape: new behaviour being added, user asked for TDD. Classification: `business_logic_change` + `new_capability`. Approach: `tdd-scaffold`. Routes to `sumo-qa-implementing-with-tdd`.)*

*(internal: walks the auth service via the host's file tools — does NOT ask "what framework?" or "where do tests live?". Reads `services/auth/app.py`, `services/auth/middleware/`, `services/auth/tests/test_login.py` to detect framework + fixture style.)*

I've walked the auth service. Before I write any test, here's the lay of the land and the risk surfaces I want us to agree on — then I'll write the *first* failing test, not all of them.

**What I found:**

| Path | Relevant detail |
|---|---|
| `services/auth/app.py:14` | FastAPI app; existing middleware mounted via `app.add_middleware(...)` — that's where the rate-limiter attaches |
| `services/auth/middleware/audit.py` | Sibling middleware; same pattern I'd follow for `RateLimitMiddleware` |
| `services/auth/tests/test_login.py` | pytest + `httpx.AsyncClient` against the FastAPI app via `ASGITransport`; `freezegun` already a dep — useful for window-edge tests |
| `services/auth/tests/conftest.py` | `client` fixture builds a fresh app per test; no shared state between tests — good, per-IP isolation tests will be clean |

**Risk surfaces (named before assertions — these drive the test order):**

> **R1 — Boundary at 100 → 101.** The 100th request in the window must succeed; the 101st must be rejected with `429 Too Many Requests`. Off-by-one here is the highest-cost defect — every other test rides on this being right.
>
> **R2 — Sliding-window vs fixed-window edge.** At `t=59.9s` the bucket is "full"; at `t=60.1s` requests from `t=0.1s` have aged out and capacity should partially restore. A fixed-window implementation would hard-reset at `t=60s` and admit 100 fresh requests instantly — exploitable burst.
>
> **R3 — Per-IP isolation.** IP `1.1.1.1` exhausting its 100 must not affect IP `2.2.2.2`. Easy to get wrong with a shared global counter.
>
> **R4 — Clock-skew under load.** If requests arrive faster than the clock source resolves (or the limiter caches `now()`), two requests can share a timestamp and either both pass or both fail depending on the comparator. Risk of non-determinism.
>
> **R5 — Reset-after-window.** After all 100 requests age out, the IP must be admitted again — no permanent lockout.

**The plan:** I'll write **one test at a time**, starting with R1 (the boundary). Once it's red, you implement to green, then we move to R2. TDD is one red→green cycle at a time — scaffolding all five up front would mean four tests that have never failed, which proves nothing.

**The one ambiguous thing I need from you before writing R1's test:**

> **Reset behaviour at the window boundary — sliding (drop the oldest request as the 60s window slides forward) or hard-reset (every 60s real-time, capacity returns to 100 at once)?** You said "sliding window" in the prompt, which I'm reading as the former — but I want to pin it because R2's test depends on it, and a lot of "sliding window" implementations in the wild are actually fixed-window-with-a-different-name.

---

## Turn 3 — User

> Sliding — drop the oldest as the window moves. The 60s boundary should never hand back a fresh 100 in one go.

---

## Turn 4 — sumo-qa

Good — that pins R2 properly when we get to it. Now R1, the boundary test.

**Test idea (R1 — boundary at 100 → 101):**

- **Under test:** `RateLimitMiddleware` mounted on the FastAPI app, hitting any auth endpoint (I'll use `POST /login` since it's the existing one).
- **Input:** 101 requests in rapid succession from the same IP (`X-Forwarded-For: 1.1.1.1`), well inside a single 60s window — `freezegun` to pin the clock so the window can't slide during the test.
- **Assertion:** the first 100 responses return `200` (or whatever `/login` would normally return — `401` is fine, the point is "not 429"); the 101st returns `429`.

**Tautology check:** I am NOT going to assert on `limiter._counter == 100` or `middleware._bucket[ip].size == 100`. That asserts the implementation back at itself — a broken limiter that increments wrongly would pass. The observable behaviour is the **HTTP status** the client sees. That's what consumers care about and what the bug actually changes.

Writing it now.

---

## Turn 5 — sumo-qa (writes test, runs it)

*(internal: step 5 — writes the failing test using the same `httpx.AsyncClient` + `ASGITransport` pattern as `test_login.py`. Step 6 — runs it.)*

Added `services/auth/tests/test_rate_limit.py`:

```python
import pytest
from freezegun import freeze_time
from httpx import ASGITransport, AsyncClient

from services.auth.app import app


@pytest.mark.asyncio
@freeze_time("2026-05-12 09:00:00")
async def test_101st_request_in_window_is_rejected_with_429():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-Forwarded-For": "1.1.1.1"}

        # First 100 requests in the window: must NOT be rate-limited.
        for i in range(100):
            response = await client.post("/login", json={}, headers=headers)
            assert response.status_code != 429, (
                f"request {i + 1} unexpectedly rate-limited inside window"
            )

        # 101st request: must be rejected with 429.
        response = await client.post("/login", json={}, headers=headers)
        assert response.status_code == 429
```

Running it.

```
$ uv run pytest services/auth/tests/test_rate_limit.py -v
============================= test session starts ==============================
collected 1 item

services/auth/tests/test_rate_limit.py::test_101st_request_in_window_is_rejected_with_429 FAILED

=================================== FAILURES ===================================
____________ test_101st_request_in_window_is_rejected_with_429 _________________

    async def test_101st_request_in_window_is_rejected_with_429():
        ...
        response = await client.post("/login", json={}, headers=headers)
>       assert response.status_code == 429
E       assert 401 == 429
E        +  where 401 = <Response [401 Unauthorized]>.status_code

services/auth/tests/test_rate_limit.py:23: AssertionError
=========================== 1 failed in 0.42s ==================================
```

**Red phase confirmed.** The 101st request returns `401` (the unauth response from `/login` itself, because no rate-limiter exists yet) instead of `429`. The test fails for the right reason — the absence of the middleware is exactly what the test catches.

**Hand-off:** implement `RateLimitMiddleware` and mount it on the app so the 101st request gets short-circuited to `429` *before* the login handler sees it. When you're ready, say so and I'll re-run. If you want me to write the production code too, say so explicitly — but the TDD discipline is cleanest if you own the green step.

> Note on what I'm **NOT** doing right now: I'm not writing R2 (sliding-window), R3 (per-IP), R4 (clock-skew), or R5 (reset) yet. Four tests that have never failed are four wishlist assertions. Each gets its own red→green cycle.

---

## Turn 6 — User

> Done — added `RateLimitMiddleware` with a per-IP deque of timestamps, drops entries older than 60s on each request, rejects when len ≥ 100. Re-run.

---

## Turn 7 — sumo-qa

*(internal: step 8 — re-runs the same test. Step 9 — targeted regression around the changed module.)*

Re-running.

```
$ uv run pytest services/auth/tests/test_rate_limit.py -v
============================= test session starts ==============================
collected 1 item

services/auth/tests/test_rate_limit.py::test_101st_request_in_window_is_rejected_with_429 PASSED

============================== 1 passed in 0.38s ==============================
```

Green — and green for the right reason. The 101st request is now intercepted by the middleware before reaching the login handler. The assertion didn't get weakened; the status code genuinely flipped from `401` to `429`.

Targeted regression around the changed code:

```
$ uv run pytest services/auth/tests/ -q
............                                                             [100%]
12 passed in 1.14s
```

No green-to-red elsewhere. `test_login.py` still passes — the middleware isn't accidentally rate-limiting the existing single-request login tests.

**Cycle 1 (R1 — boundary 100 → 101) is complete.**

---

## Turn 8 — sumo-qa (proposes the next cycle)

Next smallest test is **R2 — sliding-window edge.** This is where the design call you made earlier earns its keep.

**Test idea (R2 — sliding-window vs fixed-window):**

- **Under test:** the same middleware, but exercising the window-slide behaviour rather than the in-window cap.
- **Input:** fire 100 requests at `t=0` (fill the bucket exactly). At `t=30s` the bucket should still be full → 1 more request must return `429`. At `t=61s` the original 100 have aged out → a fresh request must succeed (`!= 429`). Critically, at `t=61s` we then fire 99 *more* requests and the 100th of *those* (i.e. request 101 since `t=0`, but only 100 inside the *current* sliding window) must also succeed — proving the limiter is genuinely sliding, not hard-resetting and gifting a fresh batch of 100.
- **Assertion:** mid-window request → `429`; post-window request → `!= 429`; 99 follow-ups → all `!= 429`; the very next one whose own age-1-second-ago neighbour is still in-window → `429` again.
- **Tautology check:** observable HTTP statuses across `freezegun`-controlled timestamps. No peeking at the deque length internally.

This is the test that distinguishes "sliding" from "fixed-window-relabelled". A fixed-window implementation would pass cycle 1 but fail this — exactly what we want a red test for.

**Shall I proceed with R2's failing test?** (And — small heads-up — once we're past R2, R3 per-IP isolation is the natural next cycle, then R4 clock-skew, then R5 reset-after-window. One at a time.)

---

## Why this is senior QA

- **Walks the repo before asking.** FastAPI, pytest, `httpx.AsyncClient`, `freezegun`, `ASGITransport`, `conftest.py` fixture shape — all read from the codebase, none asked.
- **Names risk surfaces *before* writing assertions.** R1–R5 are anchored in observable behaviours, not in implementation hunches. The test order follows the risk priority.
- **Refuses to scaffold all 5 tests up front.** The whole point of TDD is that each test has been red. Five wishlist tests written before any implementation prove nothing — and they create a sunk-cost trap where the implementer optimises against the tests' shape rather than the actual requirement.
- **Observable behaviour, not internal state.** The boundary test asserts `response.status_code == 429`, not `middleware._bucket["1.1.1.1"].size == 100`. The first is what the consumer sees and what the bug changes; the second is a tautology dressed up as a test.
- **Red shown verbatim.** Not "the test failed as expected" — the actual `assert 401 == 429` with the file:line. That's the evidence step 6 of the skill demands.
- **Hard hand-off after red.** No bundling. The user owns the green-making step (or asks for it explicitly). The next cycle's test idea is presented for confirmation, not pre-written.
- **One focused question only.** Sliding vs hard-reset was the *one* thing the code couldn't tell us — everything else was answered by reading the repo.

This is what *"TDD as discipline, not ceremony"* looks like: the red phase is the proof, one cycle at a time, observable behaviour over implementation peeking.
