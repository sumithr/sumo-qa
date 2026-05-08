# Development

Local dev, render preview, evaluation suite.

## Setup

Python 3.10+ is supported.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
sumo-qa-eval
```

Or with `uv`:

```bash
uv sync
uv run pytest
uv run sumo-qa-eval
```

## Local rendering preview

When iterating on the `presentation` hints, the response shape, or the headline copy, don't loop through a real MCP host — you'll burn tokens watching the host model expand structured fields into wall-of-text essays.

Use the bundled `sumo-qa-render` CLI. It calls a tool, applies the response's `presentation.render_instructions` exactly the way a well-behaved host should, and prints the rendered text plus a word count. Zero tokens, deterministic, ~50ms per call.

```bash
sumo-qa-render prepare --work-item "add bundle variant validation"
sumo-qa-render review --change-summary "Changed API payload" --touched-files src/orders/api.py
sumo-qa-render question --question "How do I test a webhook retry?"
sumo-qa-render testplan --work-item "Add bundle variant validation API" --scope-size medium \
    --acceptance-criteria "Invalid bundle variants are blocked at write time."
sumo-qa-render scaffold --work-item "Add bundle variant validation API" \
    --test-condition "Valid bundle passes" \
    --test-condition "Missing variant id is blocked" \
    --target-path src/orders/api.py
sumo-qa-render decide --intent "fix the broken oauth refresh in production" \
    --target-path src/auth/refresh.py
```

Each command prints something like:

```
VERDICT: needs-test-evidence

No test evidence found for src/orders/api.py. Add or name a test before merging.

Findings:
- [high] No test evidence or nearby test file was found...
- [medium] Expected contract coverage... (tests/orders/test_api_contract.py)
...

--- 131 words (cap 160) ---
```

Pass `--raw` to also print the underlying JSON.

The same scenarios are pinned as `pytest tests/test_render_preview.py`, which fails when:

- the rendered output exceeds the response's `max_words` cap, or
- it omits the headline / verdict / short-answer, or
- it contains essay markers (`## `, `### `, `Decision-boundary tests`, etc.).

So `pytest tests/test_render_preview.py` is your fast feedback loop. The only thing it can't catch is "the real host model ignores the hint" — that's a single binary check at the end via your real host, not a per-iteration concern.

## Evaluation

Fixtures live under:

- [`evaluation/fulfilment/`](../evaluation/fulfilment/)
- [`evaluation/stock/`](../evaluation/stock/)

Each fixture defines input, expected risks, expected test types, and expected confidence. The eval harness scores each scenario against the ISTQB-grade rubric defined in [`src/sumo_qa/rubric.py`](../src/sumo_qa/rubric.py).

Run:

```bash
sumo-qa-eval
```

or:

```bash
python -m sumo_qa.evaluation
```

The current eval suite is 28/28 across 4 fixture YAMLs.

For repo-level scenario evaluation against a real codebase, see [`evaluation/repo_scenarios.py`](../evaluation/repo_scenarios.py) and set `SUMO_QA_TARGET_REPO` (see [docs/CONFIGURATION.md](CONFIGURATION.md)).
