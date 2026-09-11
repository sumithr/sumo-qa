# Claude eval runner

The replacement for the OpenAI + promptfoo skill-eval gate (epic #660).
Slice 1 (#661) built the offline half - everything provable with zero model
calls. Slice 2 (#662) added the half that grades: a candidate that answers
each assembled prompt and a judge that scores it against the config's rubric.

promptfoo is untouched and still authoritative. It is retired in slice 4,
gated on a parity run in slice 3.

## It runs on your Claude subscription, not on a metered API key

Issue #662 originally specified the Anthropic SDK and `ANTHROPIC_API_KEY`.
That was reversed on 2026-09-10, before any of it shipped, for the reason the
epic exists: the old gate stopped being runnable when metered credit ran out,
and buying tokens for its replacement would rebuild the same trap.

So the runner drives the local **Claude Code CLI** in headless mode
(`claude -p --output-format json`), which authenticates against the account's
existing Claude subscription. There is no API key, no `anthropic` dependency,
and nothing in the package speaks HTTP - `tests/test_claude_eval_runner.py`
fails the build if a module imports a model SDK or opens a socket, and
`provider.py` is the only module permitted to create a child process at all.

**Spending is opt-in.** An invocation with no mode flag performs the dry run
and calls nothing; `--live` is what grades. The full matrix is over 200 cases
at two model calls each (218 in a fresh clone; 229 in a checkout where the
test generator has run and the two gitignored `*.generated-tests.yaml`
includes are present), so the mode you get by accident had better be the free
one. That default has already earned itself: an existing test called `main()`
with no flag, and under an earlier draft where live was the default it
launched the whole matrix against the real account.

## What it does

It reads the **existing** promptfoo configs in
[`../promptfoo/`](../promptfoo/) rather than a hand-converted copy, and for
each one produces a fully-resolved list of
`(prompt_label, rendered_prompt, assertions)` tuples.

The selection is `skill-*.yaml` minus `*.gen.yaml` (two generator seeds whose
headers say they are not for running evals) minus `*.generated-tests.yaml`
(gitignored `tests:` include payloads - bare YAML lists, not configs). That is
**61 configs**. A fresh clone holds 63 tracked `*.yaml` here - the 61 plus the
two generator seeds - and a maintainer checkout where the generator has run
holds 65, the extra two being the gitignored include payloads.

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
| `models.py` | The **only** place a model id appears. Candidate and judge, nothing else. |
| `provider.py` | The single call path to a model: the CLI argv, the retry policy, usage capture. The one module allowed to start a process. |
| `errors.py` | Which failures abort the run and which are retried. Fail-closed. |
| `judge.py` | `llm-rubric` grading: build the judge prompt, read the verdict. |
| `report.py` | The JSON report's shape, and the rule that it is written once or not at all. |
| `runner.py` | Drives cases through candidate then judge, `--repeat` times each. |
| `cli.py` | `--live`, `--dry-run`, `--skill`, `--config`, `--repeat`, `--report`. |

## Running it

```bash
# Free. Assembles every prompt, estimates tokens, calls nothing.
uv run python ../run_claude_eval.py
uv run python ../run_claude_eval.py --skill implementing-with-tdd

# Grades. Spends subscription allowance.
uv run python ../run_claude_eval.py --live --config skill-using-sumo-qa.yaml
uv run python ../run_claude_eval.py --live --skill reviewing-before-merge --repeat 3 \
  --report /tmp/eval-report.json
```

The dry run's token figure is an **estimate**: `ceil(len(text) / 4)`, the
usual character-based approximation, because an offline runner has no
tokenizer. A live run reports the CLI's **measured** usage instead, so the two
are never confused.

Scope every run you can. `--skill` picks up every variant config for one
skill; `--config` takes a filename or a glob. The judge tier dominates the
cost, so grading three configs instead of sixty-one is the difference between
a couple of minutes and an hour.

### Exit codes

| Code | Meaning | On disk |
|---|---|---|
| 0 | Every case passed, or the dry run completed. | Report written (live). |
| 1 | The run finished; some cases failed. | Report written. |
| 2 | Bad invocation: nothing matched, `--repeat` below 1, CLI missing, or a selected config is malformed. | Nothing. |
| 3 | **Aborted** on quota, usage limit, or any non-retryable failure. | **Nothing.** |

Exit 3 is the #651 regression. The old baseline script turned that situation
into a zero-passed snapshot on disk, which read as a catastrophic skill
regression and became the number the next run compared against.

A malformed config exits 2, not 3, because every selected config is loaded and
its cases built before the first model call. The distinction is the point: 2
means the run never started and cost nothing, 3 means it started, spent, and
was abandoned. The config-error handling is scoped to that pre-flight and
nowhere else, so a file error raised LATER - the technique catalogue is read
lazily, on first evaluation of a `cites-catalogue-technique` assert - still
propagates rather than being reported as having cost nothing.

## Keeping the candidate clean

Claude Code normally wraps a prompt in a large system prompt, a full tool
catalogue, the user's settings and CLAUDE.md files, and any MCP servers
configured on the machine. All of that is contamination for an isolation
eval - and one of those MCP servers is sumo-qa itself, which would have the
candidate grading the skills with the skills.

Every call therefore passes the same five flags. Measured on one machine,
2026-09-10, Claude Code 2.1.267:

| Flags | Scaffolding tokens |
|---|---|
| `--system-prompt` only | ~19,500 |
| `+ --setting-sources ""` | ~1,900 |
| `+ --tools ""` (the full set) | **~390** |

`--tools ""` accounts for ~16,800 of the saving and `--setting-sources ""` for
~1,500. `--strict-mcp-config` (with no `--mcp-config`) and
`--disable-slash-commands` keep MCP servers and host skills out.
`--system-prompt` REPLACES the default rather than appending to it. ~390
residual tokens against prompts of 3,000-22,000 is close enough to clean that
slice 3's parity comparison can carry it as a documented constant.

## Grading, and where it diverges from promptfoo

The judge reproduces promptfoo's `llm-rubric`: the config's own
`options.rubricPrompt` is rendered against the case vars plus `output` and
`rubric` (all 61 live configs declare one; several embed the loaded catalogues
into the judge context that way), and promptfoo's built-in
`DEFAULT_GRADING_PROMPT` is the fallback, reproduced verbatim from
promptfoo 0.121.20. A stringly boolean is coerced by promptfoo's own anchored
rule, a missing `score` is derived from `pass`, and an assertion `threshold`
demotes a pass below it.

Assertion outcomes in the report carry one of three `kind` values, and the
third is load-bearing: `llm-rubric` (the judge graded it), `javascript` (a
Python port evaluated it offline), and `javascript-unported` (the runner has
no port, so it could not grade the assert at all). The last one fails, but it
is a gap in the **harness**, not a regression in a **skill** - and an epic
that exists because a tooling failure was misread as a collapse in skill
quality should not ship a second way to make that mistake.

One thing is **deliberately different**. promptfoo does:

```js
let pass = parsed.pass ?? true;   // src/matchers/rubric.ts
```

A judge reply with no `pass` key therefore PASSES. That is how a judge that
has drifted, truncated, or answered in prose becomes a green gate, so this
runner fails it instead and carries the raw reply into the reason. The judge
is also called with `--json-schema`, which constrains the reply to the verdict
shape; the tolerant parser stays as the second line of defence.

### The full divergence list

Slice 3's parity run should expect these and no others. An earlier version of
this section claimed there was only the first, which would have had slice 3
classify the rest as noise.

| # | Divergence | Direction |
|---|---|---|
| 1 | A reply with no `pass` key fails here; promptfoo passes it. | Stricter |
| 2 | A non-finite `score` or `pass` is refused outright; promptfoo grades it. | Stricter |
| 3 | A verdict preceded by an opener consumed as string content is refused. promptfoo scans from every `{`, appends missing braces and parses with `yaml.load`, so it recovers some of these. | Stricter |
| 4 | `output` and `rubric` win over a case var of the same name. promptfoo spreads `...vars` last, so there a case var shadows the candidate's answer. | Differs; latent, no live config declares either name |

Three earlier differences were **removed** rather than documented, because
each made this runner LOOSER than the gate it replaces: `"1"` and padded
strings such as `" yes "` counted as a pass, a numeric `pass` counted as a
pass, and a present-but-junk `score` (`null`, `""`, `[]`) fell back to the
boolean instead of scoring 0. All three now match promptfoo exactly.

## Cost, and what the dollar figure means

The CLI reports real token usage and a `costUSD` per model at published list
rates, and those are the numbers the report carries - there is no rate card in
this package, because a second copy of one goes stale silently and makes every
report wrong without failing anything.

The run is covered by the subscription, so the dollars are **notional**: the
list-price equivalent of the tokens consumed. `cost_basis: "list"` in the
report says so. It is the right number for comparing the candidate tier
against the judge tier, and the wrong number to read as an invoice.

Usage is recorded per model id rather than per tier, because a call made with
one model can report two: Claude Code runs a small model for its own
background work, and that usage lands in the same envelope.

### Measured, one config, 2026-09-10

`--live --config skill-using-sumo-qa.yaml`, one case, one candidate call and
one judge call:

| Model | Input | Output | Notional USD |
|---|---|---|---|
| judge | 4,791 | 883 | $0.1285 |
| candidate | 13,479 | 539 | $0.0228 |
| **total** | **18,270** | **1,422** | **$0.1513** |

The judge is 85% of the cost on one case, which is what `--skill` and
`--config` scoping exist for.

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
  `Process.start` (which under the `spawn` and `forkserver` contexts reaches
  no patched entry point in THIS process), and each of
  `os.system`, `os.execv(e)`, `os.spawnv(e)`, `os.posix_spawn(p)`, `os.fork`,
  `os.forkpty` and `os.startfile` that the running platform exposes - the last
  four of those are platform-specific, while `os.spawnv(e)` exists on both. That covers the primitives every other `os.exec*`
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
