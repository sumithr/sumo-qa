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

The selection is `skill-*.yaml` minus `*.gen.yaml` (two generator seeds whose
headers say they are not for running evals) minus `*.generated-tests.yaml`
(gitignored `tests:` include payloads - bare YAML lists, not configs). That is
**61 configs**, not the 65 `*.yaml` files on disk.

That rule is deliberately **stricter** than `npm run eval:all`. The shell
script globs `skill-*.yaml` and skips only `*.gen.yaml`, so its own glob
matches `skill-*.generated-tests.yaml` and would hand `promptfoo eval -c` a
file that is not a config, which promptfoo errors on. Excluding non-configs is
the correct behaviour; being bug-compatible with the shell script would not be
parity. On every real config the two selections agree, which is what slice 3
compares.

| Module | Responsibility |
|---|---|
| `loader.py` | Reads the promptfoo YAML, resolves `file://` vars against the **config's own directory**, honours `disableVarExpansion`, carries the `defaultTest.options` judge overrides, flattens `tests:` includes, renders each case's rubric values, assembles cases. |
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

The rubric **value** is rendered against the case's resolved vars when the
case is built, because promptfoo renders an assertion's `value:` before
grading it (`renderedValue = nunjucks.renderString(renderedValue,
resolvedVars)`); 65 of the 66 live rubrics carry `{{expected_shape}}` or
`{% for ap in anti_patterns %}` syntax, so an unrendered rubric would hand
the judge placeholder text. The judge-time `rubricPrompt` is deliberately
left alone: its `{{rubric}}` and `{{output}}` are filled by the grader in
slice 2.

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

## Matching promptfoo's var handling

`renderPrompt` in promptfoo 0.121.20 does three things to a var that this
loader reproduces, because the rendered prompt is what slice 3 diffs:

- a `file://` target ending `.yaml`/`.yml` is **parsed and re-emitted as
  compact JSON** (`JSON.stringify(loadYaml(...))`, document key order,
  literal Unicode) - not injected as raw YAML text;
- every other `file://` target is injected as raw text with JavaScript's
  `.trim()` applied;
- every string var then loses **one** terminal newline
  (`replace(/\n$/, '')`) - a single chop, not a trim, so an inner blank
  line survives.

Ported regexes compile with `re.ASCII`, because Python's Unicode defaults are
not JavaScript's: Python's `re.IGNORECASE` folds `ſ` onto `s` where JS `/i`
refuses to, and Python's `\b`/`\w` are Unicode-aware where JS's are ASCII.

`\s`/`\S` need the opposite treatment - `re.ASCII` narrows them *below* JS's
whitespace set, and the live retrospective gate is built out of
`git\s+show\s+\S+:\S+\s*>\s*\S+` and friends, so an answer separated by a
non-breaking space would pass in JavaScript and fail here. Every lifted
pattern therefore has its `\s`/`\S` **substituted for an explicit
JavaScript-whitespace character class** before it is compiled, which gives JS
semantics on all three axes at once. `\S` inside a character class has no
Python translation (it would need set subtraction) and raises
`UnportableJavascriptPatternError`; no live pattern uses it.

## Guarantees this slice holds

Enforced by [`tests/test_claude_eval_runner.py`](../../test_claude_eval_runner.py):

- every real config loads, and neither a generator seed nor a generated-tests
  payload is ever counted as one;
- a YAML whose top level is not a mapping fails with an error naming the
  file, never a bare `AttributeError` - including every *falsy* top level
  (`[]`, `false`, `0`, `""`, `null`, an empty file), which must not be
  coerced to an empty config and counted as one. An empty `tests:` include is
  the opposite case and legitimately contributes zero tests;

- a `.yaml` file var's `.nan`/`.inf`/`-.inf` serialise as `null`, the way
  `JSON.stringify` writes them, not as the non-standard `NaN`/`Infinity`
  tokens `json.dumps` defaults to;
- `file://` resolution is relative to the config directory, including paths
  that escape it, and never to the process cwd;
- no rubric reaches a case with template syntax still in it;
- `disableVarExpansion` keeps a list-valued var intact instead of exploding
  into one test per item;
- every `javascript` assert in the matrix maps to a Python evaluator, with a
  passing and a failing output for each;
- the `--dry-run` makes zero network calls: the test poisons `socket.socket`,
  `socket.create_connection`, `socket.getaddrinfo`, both `http.client`
  connection constructors, and the process-spawning entry points
  (`subprocess.Popen`, `os.system`, `os.posix_spawn(p)`, `os.execv(e)`,
  `os.fork`) for the duration of the run, so an out-of-process escape is
  refused too;
- no module in the package imports an HTTP client, a model SDK, or a
  process/socket module - checked by walking each module's parsed AST, so a
  `from anthropic import Anthropic` cannot slip past a substring grep.

## Why it lives here

Under `tests/evals/` rather than `src/`: the harness is not part of the
shipped wheel, and keeping the whole of `tests/evals/` movable in one piece
keeps the private-split plan viable. It is importable as `claude` because
`tests/evals` is on `[tool.pytest.ini_options].pythonpath`; the
`run_claude_eval.py` entry point does the same bootstrap for command-line
use. It is deliberately outside `--cov=src/sumo_qa`, like the rest of
`tests/`.
