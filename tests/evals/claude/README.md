# Claude eval runner: offline core

Slice 1 of the epic that retires the OpenAI + promptfoo skill-eval gate
(issue #661, epic #660). This package is the **offline half** of the
replacement runner: everything that can be written, tested and proven with
zero API calls.

promptfoo is untouched and still authoritative. It is retired in slice 4,
gated on a parity run in slice 3.

## What it does

It reads the **existing** promptfoo configs in
[`../promptfoo/`](../promptfoo/) rather than a hand-converted copy, and for
each one produces a fully-resolved list of
`(prompt_label, rendered_prompt, assertions)` tuples.

| Module | Responsibility |
|---|---|
| `loader.py` | Reads the promptfoo YAML, resolves `file://` vars against the **config's own directory**, honours `disableVarExpansion`, carries the `defaultTest.options` judge overrides, flattens `tests:` includes, assembles cases. |
| `templating.py` | The nunjucks subset the matrix actually uses: `{{ var }}` and `{% for x in list %}`. Value-to-string rules mirror JavaScript (`a,b` for a list, lowercase booleans), not Python. |
| `assertions.py` | The assertion model, plus Python ports of the deterministic `javascript` asserts. |
| `tokens.py` | The dry run's offline input-token estimate. |
| `cli.py` | `--dry-run`, `--skill`, `--config-glob`. |

## Running it

```bash
uv run python ../run_claude_eval.py --dry-run
uv run python ../run_claude_eval.py --dry-run --skill implementing-with-tdd
uv run python ../run_claude_eval.py --dry-run --config-glob '*.ab.yaml'
```

`--dry-run` is the only mode in this slice. It assembles every prompt for
every selected config, estimates input tokens, prints a per-config and total
summary, and exits zero. The Claude candidate/judge tier is slice 2 (#662).

The token figure is an **estimate**: `ceil(len(text) / 4)`, the usual
character-based approximation, because an offline runner has no tokenizer.
Slice 2 reports the API's measured usage for live runs; the dry run keeps the
estimate so the two are never confused.

## Assertions

The live matrix uses exactly two assertion types.

**`llm-rubric`** is parsed into a structured object carrying the rubric body
and the per-config judge overrides (`options.rubricPrompt`,
`options.provider`), and is **never executed here**. Asking for an evaluator
raises `RubricNotExecutableError`.

**`javascript`** asserts are ported to Python. Each port derives its
parameters *from the JS source* rather than restating them, so editing the
regex in a config changes the Python gate too:

| Kind | JS shape |
|---|---|
| `regex-test` | `/<pattern>/<flags>.test(output)` announce-line gates |
| `security-relevance` | `securityTerms` + `context.vars.security_must_appear` |
| `cites-catalogue-technique` | the shared `asserts/cites-catalogue-technique.js` |
| `retrospective-restore` | the scoped-restore / return-reverse git mechanic |

`cites-catalogue-technique` derives its accepted set from the level-3
headings of [`knowledge/techniques.md`](../../../knowledge/techniques.md) at
runtime, never a hardcoded allowlist (#350): adding a technique to the
catalogue widens what every eval accepts, with no eval edit.

A `javascript` assert whose shape has no port raises
`UnportedJavascriptAssertionError`, so a new inline assert cannot enter the
matrix ungated.

**The runner never executes an assertion's `value:`.** It only ever parses
it. A config edit (or a `file://` target pointed outside the repo) must not
become code execution inside CI.

## Guarantees this slice holds

Enforced by [`tests/test_claude_eval_runner.py`](../../test_claude_eval_runner.py):

- every config in the matrix loads, and the `.ab.yaml` subset is identified;
- `file://` resolution is relative to the config directory, including paths
  that escape it, and never to the process cwd;
- `disableVarExpansion` keeps a list-valued var intact instead of exploding
  into one test per item;
- every `javascript` assert in the matrix maps to a Python evaluator, with a
  passing and a failing output for each;
- the `--dry-run` makes zero network calls: the test poisons `socket.socket`,
  `socket.create_connection`, `socket.getaddrinfo` and both
  `http.client` connection constructors for the duration of the run;
- no module in the package imports an HTTP client or a model SDK.

## Why it lives here

Under `tests/evals/` rather than `src/`: the harness is not part of the
shipped wheel, and keeping the whole of `tests/evals/` movable in one piece
keeps the private-split plan viable. It is importable as `claude` because
`tests/evals` is on `[tool.pytest.ini_options].pythonpath`; the
`run_claude_eval.py` entry point does the same bootstrap for command-line
use. It is deliberately outside `--cov=src/sumo_qa`, like the rest of
`tests/`.
