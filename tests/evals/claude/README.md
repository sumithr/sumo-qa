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

**`javascript`** asserts are ported to Python.

| Kind | JS shape | parameters |
|---|---|---|
| `regex-test` | `/<pattern>/<flags>.test(output)` announce-line gates | lifted from the JS |
| `security-relevance` | `securityTerms` + `context.vars.security_must_appear` | lifted from the JS |
| `cites-catalogue-technique` | the shared `asserts/cites-catalogue-technique.js` | read from the catalogue |
| `retrospective-restore` | the scoped-restore / return-reverse git mechanic | **transcribed by hand** |

Three of the four derive their parameters rather than restating them. The
`regex-test` and `security-relevance` ports lift the regex **literal out of
the config text**, so editing the regex in a config changes the Python gate
too. `cites-catalogue-technique` derives its accepted set from the level-3
headings of [`knowledge/techniques.md`](../../../knowledge/techniques.md) at
runtime, never a hardcoded allowlist (#350): adding a technique to the
catalogue widens what every eval accepts, with no eval edit.

**`retrospective-restore` does not.** Its nine regexes are **transcribed by
hand** from the inline JavaScript in
[`skill-implementing-with-tdd-retrospective.yaml`](../promptfoo/skill-implementing-with-tdd-retrospective.yaml)
into class constants on `RetrospectiveRestoreEvaluator`, and dispatch selects
them on the mere *presence* of the string `hasScopedRestore` in the source -
it never parses the patterns out. The nine are verified equal to Node's today
(0 mismatches across the differential), but the cost is real and worth stating
plainly: **an edit to the inline JavaScript will not move the Python gate, and
the two can drift apart silently.** Someone tightening the destructive-command
list in the YAML would change promptfoo's verdict and not this runner's, with
nothing failing to say so.

A cheap guard would close that, and is deliberately **not** built here: lift
every `/.../` literal out of that config's JS with the same
`_JS_REGEX_BODY` reader the other two ports already use, and assert the set
equals the transcribed constants. That is a test, not a re-engineering of the
port - it needs no new translation path and would fail the moment the two
copies diverge.

A `javascript` assert whose shape has no port raises
`UnportedJavascriptAssertionError`, so a new inline assert cannot enter the
matrix ungated. A lifted regex using any construct outside the ported set
raises `UnportableJavascriptPatternError` - see [the portability
guard](#the-portability-guard) below, which is **closed by default**.

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

## The portability guard

A JavaScript regex lifted into Python is not a Python regex. Some constructs
Python simply rejects, which is harmless - it fails loudly. The dangerous ones
**compile in Python and match a different set**: no error, no warning, just a
verdict that quietly disagrees with promptfoo. In a runner whose entire value
is fidelity, that is the worst outcome available.

### What the guard claims, and what it does not

This module **ports the specific patterns the sumo-qa eval matrix uses**. It
is **not** a general JavaScript-to-Python regex translator, and it does not
claim that an arbitrary lifted pattern matches the same set in both engines.

It used to claim exactly that, and could not honour it: the guard translated
the constructs it recognised and trusted everything else, so the promise was a
claim about the whole ECMAScript regex grammar. Four review rounds each found
a new corner where it failed (a legacy octal escape `\351`; the Python-only
`\N{...}` and `\U........` forms; astral characters, where JavaScript consumes
UTF-16 code units and Python code points, so `/^.$/` against an emoji is
`false` in Node and `true` here; and malformed literal syntax like `/x/i/`,
a JavaScript `SyntaxError` that the dispatch regex reinterpreted as the valid
pattern `x/i`). None was reachable from the live matrix. Each was patched;
the next round found another.

So the guard is now **closed by default**. It admits exactly the constructs
the live matrix uses and **refuses everything else**, which closes those
corners structurally rather than one at a time - an octal escape, `\N{...}`,
`\U........`, an astral-sensitive `.` and any unrecognised escape all simply
fail the allowlist. A future assert that needs one gets a loud, actionable
refusal telling its author to extend the port, which is the correct outcome:
extending the port is the only way to know the two engines agree.

**The refusal is the guarantee.** Within the allowlist each construct is
translated into Python that matches the same set; a construct outside it is
refused by the walker and never reaches `re.compile` at all.

That guarantee is about **constructs, not whole patterns**. The walker admits
each construct individually, so two admitted constructs can still be
*assembled* into something the two engines read differently - and one of them
was. Stacking a second quantifier on a first (`a++`, `a*+`, `a?+`,
`a{1,2}+`) is a `SyntaxError: Nothing to repeat` in Node and a **possessive
quantifier** in Python, which compiled here perfectly happily until it was
refused explicitly. Combinations Python's own parser rejects - whether or not
Node would - already fail loudly and are re-raised as the guard's own error.
So the allowlist closes the construct axis; the combination axis is closed
case by case, and this is the case that was found.

### The allowlist

Derived from the **15 regex instances** the 10 live `javascript` asserts
compile (3 announce-line literals, 3 `securityTerms` bodies, 9
retrospective-gate literals) - not chosen. Every row below is present in a
live pattern; every construct absent from all 15 is refused.

| construct | a live instance |
|---|---|
| printable-ASCII literal | `git`, `HEAD`, `--`, `:`, `>`, `idor` |
| `^` start anchor | `^[\s>*_"']{0,8}closing one qa gap at a time` |
| `\|` alternation | `(security\|securit\|vulnerab\|...)` |
| `(`…`)` capturing group | the `securityTerms` body |
| `(?!`…`)` negative lookahead | `git\s+checkout\s+(?!--\s\|HEAD\s+--)[^\n]*` |
| quantifier, greedy or lazy | `\s+`, `[^\n]*?`, `{0,8}` |
| `\s`, `\S` | `git\s+show\s+\S+:\S+\s*>\s*\S+` |
| `\b` | `\bxss\b`, `git\s+clean\b` |
| `\n` inside a class | `[^\n]` |
| `[`…`]` / `[^`…`]` of literals, `\s`, `\n` | `[\s>*_"']`, `[^\n]` |
| flag `i`, or no flags | the three announce literals; everything else |

Quantifiers are admitted as **one** construct (the ECMA-262 `Quantifier`
production: `*`, `+`, `?`, `{m}`, `{m,}`, `{m,n}`, each optionally lazy)
because both grammars define the whole production identically - it is
parameterised by a repeat bound, not by a meaning. **One** is the operative
word: the production allows exactly one quantifier per atom, so a second
stacked on the first is refused (see the note under *the refusal is the
guarantee*), while a lazy `?` following a quantifier stays admitted. Escapes and flags are
admitted **individually**, because each carries its own semantics and its own
chance of disagreeing.

Two admitted constructs are **rewritten** rather than copied:

| construct | JavaScript | Python, untranslated | translation |
|---|---|---|---|
| `\s`, `\S` | 25 code points | `re.ASCII` narrows it to 6 | explicit class |
| `\s` inside a class | a member set | a nested `[...]` would make `[`/`]` literal members | the class **body**, spliced in |

`\s` is the one a live pattern really leans on: the retrospective gate is
built out of `git\s+show\s+\S+:\S+\s*>\s*\S+` and friends, so an answer
separated by a non-breaking space would pass in JavaScript and fail here.

Ported regexes compile with `re.ASCII`, because Python's Unicode defaults are
not JavaScript's: Python's `re.IGNORECASE` folds `ſ` onto `s` where JS `/i`
refuses to, and Python's `\b`/`\w` are Unicode-aware where JS's are ASCII.
That argument only holds for an ASCII pattern, which is one reason the walker
admits no non-ASCII character at all.

### What is refused

Everything off the table above, including several constructs that compile in
Python perfectly happily: `.`, `$`, `[]`, `[^]`, `\d`, `\w`, `\uXXXX`, `\xXX`,
legacy octal escapes, `\N{...}`, `\U........`, `(?:`, lookahead, lookbehind,
backreferences, class ranges, a quantifier stacked on a quantifier, and any
non-ASCII character. Some of those would
match a different set than Node; the rest are simply unproven. The guard does
not distinguish, which is the point - it cannot be wrong about a construct it
never accepts.

Flags are **translated or refused**, never dropped. The flag allowlist is
derived the same way, and the live matrix uses `i` and nothing else:

| flag | verdict | why |
|---|---|---|
| `i` | translated | `re.ASCII \| re.IGNORECASE` folds only ASCII, which *is* JS `/i` for an ASCII pattern - and the walker admits no non-ASCII character, so that argument cannot be stretched past where it holds. |
| `s` | refused | dotAll only ever changes what `.` matches, and `.` is off the allowlist, so `/s` could only qualify a construct already refused. |
| `m` | refused | JS anchors `^`/`$` at `\r`, U+2028 and U+2029; `re.MULTILINE` only at `\n`. A silent mismap is worse than a refusal. |
| `g` | refused | load-bearing state: `.test` advances `lastIndex`. |
| `y` | refused | sticky; `/x/y.test("ax")` is `false` in Node. |
| `u`, `v` | refused | change escape and class grammar wholesale, and re-define case folding. |
| `d` | refused | only adds match indices, which `.test` never reads - honouring it would assert a no-op nobody has proved. |

Both lifted-regex paths (`regex-test` and `securityTerms`) run through the
same helper, so they cannot drift into disagreeing about any of it. Both also
read their regex **literal** with the same strictness: the body may not
contain an unescaped `/` or a line terminator, and the flags must come from
JavaScript's own alphabet (`dgimsuvy`). A malformed literal is refused, never
reinterpreted - `/x/i/.test(output)` is a `SyntaxError` in JavaScript, so
promptfoo would never have produced a verdict for it either.

Allowlisted constructs can still be *assembled* into something Python's parser
rejects (an unbalanced group, a quantifier with nothing to quantify). That
already fails loudly; it is re-raised as the guard's own error, naming the
pattern and the config.

### The one exemption

`cites-catalogue-technique` compiles an alternation of `re.escape`d headings
with `IGNORECASE | ASCII` and does **not** go through the guard, deliberately:
it is not a lifted JavaScript pattern but Python assembled from `re.escape`,
whose identity escapes (`\-`, `\&`) the allowlist refuses on purpose. Routing
it through would mean re-admitting exactly what was just closed.

What it does borrow is the guard's standard. `IGNORECASE | ASCII` folds case
the way JS `/i` does *only while every heading is ASCII* - and the headings
come from [`knowledge/techniques.md`](../../../knowledge/techniques.md), which
anyone can edit. A cased non-ASCII heading would diverge: Python with those
flags will not match `CAFÉ` against `café`, where Node's `/i` does. So the
evaluator **fails loudly on a non-ASCII heading** rather than assuming the
invariant, and a suite test pins that all 21 live headings are ASCII today.

### How it is checked

Two ways, and they cover different things.

**Offline, in this suite:** the allowlist is pinned from both sides - every
admitted construct is exercised on an output it must accept *and* one it must
reject, and every refused construct is asserted to raise with an actionable
message. `test_every_live_lifted_pattern_survives_the_completed_guard` pins
all 15 live instances against the closed guard.

**Against real Node, out of tree:** a differential harness lifts the same 15
instances straight out of the configs, translates each with the guard, and
scores the Python verdict against `new RegExp(pattern, flags).test(input)` in
Node over a corpus built from the JS whitespace and line-terminator sets plus
astral, case-folding and anchor probes - checking `.replace(/…/g, '')` against
`re.sub` separately, since the evaluator drops that `g` on the argument that
`re.sub` is already global.

That harness is **deliberately not committed**, because this suite must stay
offline and Node-free, so **its result is not reproducible from this repo**.
Treat the offline tests above as the reproducible evidence and the harness as
a development tool: the constructs it found are recorded as unit tests, which
is what survives. Its most recent run over the closed guard scored 2,700
`.test` comparisons and 180 `.replace` comparisons at **0 mismatches and 0
refusals**; the same corpus against an *unguarded* raw lift of those patterns
produces 84 mismatches, which is what stops the run being a tautology.

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
  connection constructors, and the process-creation entry points: for the
  duration of the run it poisons `subprocess.Popen`, `multiprocessing`'s
  `Process.start` (which reaches neither of the others), and each of
  `os.system`, `os.execv(e)`, `os.spawnv(e)`, `os.posix_spawn(p)`, `os.fork`,
  `os.forkpty` and `os.startfile` that the running platform exposes - the last
  five are platform-specific. That covers the primitives every other `os.exec*`
  and `os.spawn*` wrapper delegates to, so an out-of-process escape - which
  would also escape the socket poisoning - is refused. It is a guard on the
  entry points named here, not a proof that no child can ever be created;
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
