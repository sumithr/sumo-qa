# Development

Local dev guide for sumo-qa.

## Prerequisites

- **Python 3.10 or newer** (no upper cap; see `pyproject.toml`'s `requires-python`)
- **Node.js 22.22+** (minimum; we use 24, the current LTS): only needed if you run the LLM eval harness (`tests/evals/promptfoo/`). Promptfoo is a Node CLI; we pin it as a local devDependency in `package.json`. Skip this if you don't touch evals.

Python tooling: pick whichever installer you already use, `pip`, `uv`, `pipx`, conda. Examples below use `pip` because it ships with every Python install; `uv` users can swap in equivalent commands.

Node tooling: `nvm` (or any Node version manager) handles the version requirement cleanly. `nvm use 24` works.

## Setup

```bash
git clone <repo>
cd sumo-qa
python -m venv .venv                                # any venv tool works; uv users: `uv venv`
source .venv/bin/activate                           # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev,treesitter]"        # package + pytest, ruff, mypy, pre-commit; treesitter enables the repo-map import-edge tests
pre-commit install --install-hooks                  # ruff + hygiene on every commit; pytest suite + scoped mutmut gate on push
```

The config's `default_install_hook_types` makes that one install add both the commit and the push hooks. If `ls "$(git rev-parse --git-path hooks/pre-push)"` finds no push hook (the check works in a worktree too), re-run `pre-commit install --install-hooks` once.

Pushing over SSH also needs keepalives, once per clone (worktrees share it). git opens the connection to GitHub before the push hooks run, and GitHub closes an idle connection long before a full mutmut pass ends:

```bash
git config core.sshCommand "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=120"
```

The `treesitter` extra installs the tree-sitter parser that backs the repo-map
`imports` edge layer. It is optional at runtime (the scan degrades gracefully
without it), but the full pytest suite's 100% coverage gate exercises the
import-edge code paths, so a local `[dev]`-only install will fall short of 100%
on those modules; install `[dev,treesitter]` (or `uv sync --all-extras`) to run
the whole suite green.

If you already use [uv](https://docs.astral.sh/uv/), the equivalent setup is:

```bash
uv sync --all-extras
uv run pre-commit install --install-hooks
```

### Markdown drift gate

Every commit that touches a `.md` file runs [`scripts/check_markdown_links.sh`](../scripts/check_markdown_links.sh): a thin wrapper that fails the commit if any markdown link or root-level user-facing code-block file ref points at a file that doesn't exist. CI runs the same script across every tracked markdown file on every PR via the `markdown-links` job in [`.github/workflows/lint.yml`](../.github/workflows/lint.yml).

Two layers run in sequence:

1. **`pytest-check-links`** for markdown link syntax (every tracked `.md`). Catches `[label](path/to/file)` after the target file is removed or renamed. Runs across the whole repo with high precision (zero false positives in practice).
2. **`scripts/check_codeblock_file_refs.py`** for inline-code and fenced-code file refs in **root-level user-facing docs only** (`README.md`, `AGENTS.md`, `DEMO.md`, `CHANGELOG.md`). Catches commands like `python scripts/<removed>.py` whose file no longer exists. Narrower scope by design: `docs/*.md` contains lots of illustrative example paths and would generate too many false positives. Gitignored paths (intentional runtime outputs) are skipped automatically via `git check-ignore`.

What the gate does **not** catch (yet):

- Broken section anchors (`#some-heading`). `pytest-check-links` 0.10.1 has a known anchor-detection bug; the gate runs with `--check-anchors` OFF. Revisit when `> 0.10.x` ships.
- Broken external URLs. Skipped intentionally: pre-commit must stay fast and offline.
- GitHub-relative URLs like `../../commit/<sha>` or `../../pull/<n>`. These only resolve on github.com; pattern-skipped in the wrapper.
- Code-block file refs inside `docs/*.md`, `skills/*.md`, `knowledge/*.md`, or `tests/scenarios/**/*.md`. These docs are full of illustrative paths by design; scanning them would flood the gate with false positives.

To run the whole gate manually from the repo root, invoke `scripts/check_markdown_links.sh` with no args to scan every tracked `.md`, or pass explicit paths to limit scope.

### Eval harness (Node-only, skip if you don't touch evals)

```bash
nvm use 24             # current LTS; any Node 22.22+ also works
npm install            # installs promptfoo from package.json
npm run eval           # the TDD skill eval on the Claude pair via `claude -p` (no API key)
npm run eval:all       # every skill config on the Claude pair (the full matrix)
```

The evals run on your Claude subscription through the Claude Code CLI, so `claude` must be on your PATH and signed in. The local OpenWebUI tiers (`npm run eval:local:*`) are an unmetered iteration option, not a merge gate.

See [`tests/evals/promptfoo/README.md`](../tests/evals/promptfoo/README.md) for full eval usage + cost notes.

To put `sumo-qa` on your PATH for ad-hoc use (optional):

```bash
pip install -e .                  # editable install in the active venv, or
uv tool install --from . sumo-qa  # installs into uv's tool dir
```

### Try this branch as a "real user" (without publishing)

The contributor workflow above gives you an **editable** install, perfect for live edits but distinct from what an end-user gets via `pip install sumo-qa` or `claude plugin install sumithr/sumo-qa`. Two helpers cover the two install vectors:

**`scripts/dev_install.py`**, pip-install path (the canonical PyPI flow):

```bash
python scripts/dev_install.py                # full canonical flow: pip install + sumo-qa-install + doctor
python scripts/dev_install.py --claude-code  # only configure Claude Code
python scripts/dev_install.py --skip-installer   # just refresh the wheel
python scripts/dev_install.py --help         # full flag matrix
```

Runs `pip install --upgrade --force-reinstall .` against the active interpreter, then `python -m sumo_qa.installer` (passing through any host flags you provide), then `python -m sumo_qa.doctor`. Bootstraps pip automatically via `ensurepip` when the target venv lacks it (e.g. uv-created venvs). Full write-up: [docs/INSTALL.md#wheel-from-clone-matches-canonical-pypi-install](INSTALL.md#wheel-from-clone-matches-canonical-pypi-install).

**Claude Code plugin path**, use Claude Code's `--plugin-dir` flag (the [official local-dev mechanism](https://code.claude.com/docs/en/plugins#test-your-plugins-locally)):

```bash
claude --plugin-dir /path/to/sumo-qa
```

That loads the plugin directly from the directory, no marketplace, no install step. `/reload-plugins` inside Claude Code picks up edits without restarting. The plugin's `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` so `uvx` resolves the local checkout's Python source, `claude --plugin-dir` invocations run THIS branch's code end-to-end (skills + hooks + MCP server tools).

> **`--plugin-dir` is session-scoped, not a persistent install.** The flag must be passed on every `claude` invocation; it isn't recorded anywhere. Plain `claude` (no flag) starts a session with no sumo-qa loaded, even if a previous session had it. Persistent install requires `claude plugin install sumithr/sumo-qa` once the plugin is published to a marketplace, until then, `--plugin-dir` is the only vehicle for local-dev iteration.
>
> Likewise `uv` must be on PATH **before** `claude --plugin-dir` launches: Claude Code captures `PATH` at process start and `/reload-plugins` does not refresh it. If you install uv mid-session, `/quit`, source your shell rc (or open a fresh tab), and relaunch.

For the plugin's own doctor, inside the Claude Code session just type `!sumo-qa-doctor`, the plugin ships a `bin/sumo-qa-doctor` wrapper that's on the Bash tool's PATH while the plugin is enabled (Anthropic's [documented `bin/` mechanism](https://code.claude.com/docs/en/plugins-reference#plugin-directory-structure)). From outside Claude Code:

```bash
uvx --from /path/to/sumo-qa sumo-qa-doctor
```

Reversal: `pip install --upgrade sumo-qa==<previous-version>` restores the PyPI build for the pip path; exit the Claude Code session to drop the `--plugin-dir` plugin.

## Local verification, automatic via git hooks

The repo uses [pre-commit](https://pre-commit.com/) to enforce the same checks CI runs.
Once installed (above), you get them for free on every `git commit` / `git push`:

| Trigger | What runs | Speed | Why |
|---|---|---|---|
| `git commit` | `ruff check --fix`, `ruff format`, `actionlint` on changed workflows, trailing-whitespace / EOL / YAML / TOML / JSON / merge-conflict / large-file hooks | ~1s | Auto-fixes 95% of CI lint failures before the commit lands. |
| `git push` | the full `pytest` suite at 100% coverage across pytest-xdist workers, printing its counts; the mutmut gate (see [Mutation testing](#mutation-testing) for its triggers and scope); and every other hook without a commit-only stage, on the pushed files (the fixers among them can rewrite a file and stop the push) | minutes | Stops broken or under-tested commits reaching the remote. |

The pytest hook runs in pre-commit's own isolated venv, built from the explicit `additional_dependencies` pins in `.pre-commit-config.yaml` (where a hook and `pyproject.toml` pin the same package, `tests/test_toolchain_pin_lockstep.py` keeps the two in lockstep), so it's not coupled to whichever `python` happens to be on your PATH. The first `git push` after install is slower while pre-commit builds that venv; later pushes reuse it.

**On-demand runs** (without committing/pushing):

```bash
pre-commit run --all-files                          # ruff + hygiene
pre-commit run --all-files --hook-stage pre-push    # the push-stage hooks
```

**Skipping hooks** (rare): `git commit --no-verify` or `git push --no-verify`. CI will still catch anything you skipped, use this only for genuine emergencies.

Hooks are pinned in `.pre-commit-config.yaml` and mirror `.github/workflows/lint.yml`, so passing them locally clears the ruff gates. The pytest hook runs the full suite with the 100% coverage gate on your one Python and OS; `.github/workflows/test.yml` runs it across the OS and Python matrix (with the coverage gate on one job), so CI can still fail on a platform the hook did not cover. One CI lint gate is intentionally not a hook, `mypy` (see [Type checking](#type-checking)): to keep `git push` fast; run `python -m mypy` before pushing to clear it too.

## Test suite

```bash
pytest        # or `uv run pytest`
```

The full suite covers:

- `test_knowledge_loaders.py`: 7 catalogue loaders return canonical entries
- `test_skill_conformance.py`: every `skills/*/SKILL.md` has the required structure
- `test_review_skill_modules.py`: the `sumo-qa-reviewing-before-merge` root + lazy `modules/*.md` split (#451): every routing-table id exists and every module is routed, each load-bearing rule has one canonical copy, each pinned rule keeps its body, no module points "below"/"above"/at a root line number, the root and module token budgets hold, and every `skill-reviewing-before-merge*.yaml` assembles root + declared modules only with `defaultTest.options.disableVarExpansion: true`
- `test_skill_md_description_vs_body.py`: every `skills/*/SKILL.md` frontmatter `description` that names a catalogue (classifications, approaches, principles, techniques, standards, rules) must back it with a `sumo_qa_load_<catalogue>` call in the body, catches description-vs-body drift (the #188 `sumo-qa-deciding-approach` over-claim of `rules` + `standards`). Matches the prefixed call form, not bare `load_<catalogue>` prose mentions of other skills' loads
- `test_skill_prompts.py`: every skill registers as an MCP tool (function name is historical; tools, not prompts)
- `test_phase3_e2e_skill_path.py`: end-to-end smoke through the new surface
- `test_token_weight_regression.py`: per-call and per-flow token budgets (the IntelliJ-SSE regression test)
- `test_audit_context_budget.py`: the shipped `[tool.sumo-qa.context-budget]` budgets hold, an exceeded budget fails naming its area, the `core` tools/list budget fails one token below its measurement, the capability groups partition the `full` list, and every review workflow costs less end to end under `core` than under `full`. The audit itself is `python scripts/audit_context_budget.py`: it prints chars and estimated tokens (`(chars + 3) // 4`) for the SessionStart bootstrap, the tools/list surface per profile (`tools_list = { core = ..., full = ... }`), each capability group (tool count, core count, description vs name/schema tokens), every root skill, each configured review workflow run on the `core` server (per-loader chain vs one bundled call, with call counts and a re-sent estimate), and each workflow's end-to-end total per profile (bootstrap + that profile's tools/list + the bundled results), then exits 1 when a budget is exceeded or a workflow or bundle fails (an unservable tool is named with its profile), and 2 on a config error (every budget must be a positive integer, and each workflow needs `name`, `skill` and `classification`; a malformed or missing config table is also a config error; the tests pin each rejection, that a non-config `ValueError` propagates, and, on mcp versions that provide `UnexpectedToolError` (2.1 and later), that a crash inside a tool is not reported as unservable; on earlier allowed versions a crash surfaces as a tool failure). An absent budget (the root-skill one) is report-only. CI runs it as the `context token budget` job in `lint.yml`
- `test_server.py`: tool registration, checked by exact equality against the hand-maintained name groups in that file
- `test_tools_list_contract.py`: the committed `tests/fixtures/mcp_tools_list_snapshot.json` must name exactly the live `tools/list` of the default (`full`) profile, and its `core_tools` must name exactly the `core` profile's list. Each core tool must be served identically to its full counterpart, an explicit `SUMO_QA_MCP_PROFILE=full` must serve the default list unchanged, and an unknown profile must fail at launch. Adding, removing or renaming ANY MCP tool (a skill or a plain `@mcp.tool` in `server.py`) fails it until `uv run python scripts/regen_tools_list_snapshot.py` is run: the local guard reads the working tree, so it passes once the snapshot is regenerated there, and CI checks the pushed commit, so the regenerated snapshot must be committed in the same PR. Schema changes are warn-only
- `test_tool_registry.py`: every registered tool has an entry in `src/sumo_qa/tool_registry.py` (a tool without one fails this test; at runtime the server warns on stderr and serves it under `full` only), the `core`/`full` profiles derive from it, external and open-world tools stay out of `core`, each `open_world` flag matches the tool's annotation, and every tool a core skill names is itself core. A new tool or skill needs a registry entry in the same PR
- `test_skill_triggering.py`: deterministic, host-neutral assertion that every skill tool is registered AND that its MCP description contains at least one of the natural-language trigger phrases pinned for the prompts that should route to it (fixture: `tests/fixtures/skill_triggers.yaml`). Phrase presence is a necessary (not sufficient) condition for the host LLM to pick the right tool by description alone; the harness catches the silent regression where a description rewording drops a trigger phrase. Behavioural quality is judged by the optional LLM evals under `tests/evals/promptfoo/`
- `test_tdm.py`: test-data tools
- `test_tools.py`: service factory
- `test_standards.py`, `test_rules.py`: file loading
- `test_debug_capture.py`: `SUMO_QA_DEBUG_DIR` capture
- `test_conformance_transcript_validator.py`: deterministic, no-LLM cross-model conformance (issue #214). Scores a captured host/tool-call transcript against machine-readable fixtures (`tests/scenarios/conformance/scenarios.yaml`, seeded from `SCENARIOS.md` + `TOOL-SELECTION.md`) via `src/sumo_qa/conformance.py`, and proves a synthetic bad transcript fails on each contract axis: wrong skill routing, missing required tool call, forbidden tool call, forbidden output claim. See `tests/scenarios/CONFORMANCE.md`. Complements `test_skill_triggering.py` (trigger-phrase presence) by checking what the host actually did across the turn
- `test_toolchain_pin_lockstep.py`: fails when any pre-commit hook `additional_dependencies` entry, or the ruff-pre-commit `rev:`, disagrees with the matching `pyproject.toml` declaration (see [Toolchain pin lockstep](#toolchain-pin-lockstep))
- `test_mutmut_subprocess_exclusions.py`: loud guard that every subprocess-spawning test which imports a mutated module is excluded from the mutation gate and marked (see [Mutation testing](#mutation-testing)). Runs in the ordinary suite, so it fails at the PR that introduces an unmarked/unignored test, not later against an unrelated change

## Type checking

The package ships the PEP 561 marker `src/sumo_qa/py.typed`, so the
`Typing :: Typed` classifier in `pyproject.toml` is real, downstream
type-checkers honour sumo-qa's annotations. `tests/test_wheel_packaging.py`
builds the wheel and asserts the marker is inside it, so a packaging change
that dropped it would fail the suite.

Run the static type checker from the repo root:

```bash
python -m mypy        # or `uv run mypy`
```

Configuration lives in `[tool.mypy]` in `pyproject.toml` (targets Python 3.10,
the lowest supported runtime; checks `src/sumo_qa` only, tests are out of
scope). The `mypy` job in [`.github/workflows/lint.yml`](../.github/workflows/lint.yml)
runs the same command on every PR. The few dynamic surfaces (MCPServer decorator
returns, a Pydantic opt-out attribute) carry narrow `# type: ignore[<code>]`
comments with rationale; `warn_unused_ignores` is on, so a suppression that
stops being needed fails the check until removed.

## Mutation testing

A nightly [`.github/workflows/mutation.yml`](../.github/workflows/mutation.yml) job
mutates the parser/decision modules listed under `source_paths` in
`[tool.mutmut]` (`pyproject.toml`) and enforces a strict 100% kill rate. A
scheduled-run failure files a `mutation-gate` issue (deduped against any open
one) so a red nightly lands in the backlog instead of going unnoticed. A
pre-push hook re-runs the gate locally when a diff touches one of the mutated
modules or any test file. Always invoke it via the `mutmut run` console
script, never `python -m mutmut` (the `-m` form re-runs `set_start_method('fork')`
and crashes the trampoline). On macOS the fork-based runner can segfault, the
faithful run is the Linux CI one; the local hook uses `--max-children 1` to reduce
flakiness.

The local hook passes `--changed-only`, which scopes the pass to what the push
touches instead of running every mutant on any test edit (a cold full pass is
15+ minutes at `--max-children 1`). The changed files are the union of
`git diff --name-only --no-renames origin/main...<to>` (what the branch changes;
`<to>` is the `PRE_COMMIT_TO_REF` pre-commit exports, the revision actually
being pushed) and `<to>...<from>` when `PRE_COMMIT_FROM_REF` is a real sha
(whatever a force-push removes from the remote). A changed `source_paths`
module selects `sumo_qa.<module>.*`; a changed test file selects one glob per
mutated function that `mutants/mutmut-stats.json` maps it to, so mutmut also
limits its clean-test pass to those tests. A test file the stats pass ran (or
mutmut ignores) that maps to nothing exercises no mutated function and selects
nothing. Nothing selected means the hook exits 0 without running mutmut.

The full pass still runs when the scope cannot be trusted: a test edit on a
cold cache (no stats file, as in a fresh worktree); a changed test file the
stats have never seen (new since the last pass, or a rename target; renames
are diffed with `--no-renames`, so the old path also keeps its functions in
scope); any change to `pyproject.toml`, `conftest.py`, or non-test support code
under `tests/` (helpers and fixtures never appear in the map, yet can weaken
many tests); or git failing to diff. Only in-scope modules are judged, the
rest print `SKIPPED` and the pass is reported as scoped, never as "all
modules". The nightly job never passes the flag, so CI is always the full gate.

Both the nightly job and the pre-push hook compute their verdict with
[`scripts/check_mutation_gate.py`](../scripts/check_mutation_gate.py)
(tested by `tests/test_check_mutation_gate.py`). The verdict is read from
mutmut's `.meta` files, never from `mutmut run`'s exit status: mutmut exits
0 even when mutants survive, so a bare `mutmut run` hook can never fail on
a survivor-introducing push (root-caused 2026-07-13).

mutmut is pinned to one minor in both `pyproject.toml`'s dev
extra and the pre-push hook's `additional_dependencies`; the two must stay in
lockstep (see [Toolchain pin lockstep](#toolchain-pin-lockstep)). The floor is
the minor whose mutant set the committed `mutmut-baseline.json` was generated
from: an older engine generates fewer mutants, so a range spanning two minors
would let it resolve and report a DROP even with every mutant killed. The
ceiling keeps one minor per baseline, because mutmut minors move the mutant
set and the pragma rules (see below), so a bump is a
re-run-the-gate-and-re-baseline task that moves floor and ceiling together,
not a range edit. Versions below 3.7 must never be admitted: 3.6.0's
`record_trampoline_hit` resolved its relative `source_paths` against the live
cwd with `strict=True`, so any test that `chdir`s away and then calls a
mutated-module function crashed the stats-collection run and zero mutants
executed ("failed to collect stats").

`tree-sitter-language-pack` (the `[treesitter]` extra) follows the same
lockstep rule: `pyproject.toml` and the pre-push `pytest` hook's
`additional_dependencies` carry identical pins, and both
`tests/test_treesitter_pins.py` and the general
[Toolchain pin lockstep](#toolchain-pin-lockstep) guard fail if they differ
(Dependabot only edits `pyproject.toml`). The range excludes 1.14.1 and 1.14.2, which shipped without
the `windows-x86_64` prebuilt parsers, so every repo-map test failed on Windows
with `DownloadError: No pre-built parsers available for platform
'windows-x86_64'` (#595). 1.14.3 restored them
([upstream #174](https://github.com/xberg-io/tree-sitter-language-pack/issues/174)),
so this is a point exclusion rather than a ceiling: later releases resolve
normally. Windows `pytest` is not a required check, so a red Windows leg on
every PR is a signal to read, not background noise.

**Pragma placement.** Under the pinned mutmut, `# pragma: no mutate` is read
only as a trailing comment on a *statement* or a compound-statement header
(`with …:`, `if …:`, `def …:`); it suppresses the mutants whose node starts on
that statement's first line. A pragma on a continuation line inside an
expression (a comprehension clause, a kwarg line of a multi-line call) is
ignored. For a multi-line call whose Call-level mutants (kwarg→None,
kwarg-drop) are equivalent, put the pragma after the closing paren: it
silences the Call node's mutants and leaves the inner kwarg-value mutants
live. Pair every
pragma with a one-line rationale naming why the mutation is equivalent.


### macOS fork noise: the local gate is advisory

An intermittent macOS failure used to block clean pushes outright. When the
fork-based runner wipes out, its mutants produce no verdict at all: either a
segfault (`-11`/`-9`), or the `null` that mutmut pre-populates
`exit_code_by_key` with at generation time and never fills in because the run
aborted before executing them. Neither is in `KILLED_EXIT_CODES` nor equals
`0`, so both collapsed to `killed=0`/`survived=0` and reported **every** module
`DROPPED` on a clean tree. An enforced-but-flaky gate trains people to
`--no-verify` past it, which defeats the point of enforcing it.

`check_mutation_gate.py --run-mutmut` now:

- On darwin sets `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` in the child
  environment (extending `os.environ`, so `PATH` still resolves the `mutmut`
  console script). Off darwin no env override is passed at all.
- Runs mutmut **exactly once** and reads exactly one metadata snapshot.
- Reports any module with an un-judged mutant as `NOT-MEASURED`, whatever its
  kill count, and does not block. **Exit 0 there means "not blocking", never
  "gate passed"**, and the output says so.

**One snapshot per verdict, by design.** An earlier revision retried a noisy
run and folded the passes together to recover a strict local verdict. That fold
produced an unearned "strict gate passed" in five consecutive review rounds
through five structurally different holes, because the data cannot support it:
combining a kill count observed in one pass with a completeness observed in
another asserts something no single observation made. The invariant is now
trivial to keep true, and there is no cross-pass arithmetic to get wrong. What
is given up is recovering a strict local verdict after a transient noisy pass;
in exchange a local run costs ~6 minutes rather than up to ~12.

**Why there is no noise threshold either.** `mutmut-baseline.json` stores kill
*counts*, not mutant identities, so a shortfall can never be attributed to the
mutants that went un-judged. Every threshold fails on one side or the other:
above it, a single un-judged mutant excuses an unrelated real regression in the
same module; below it, partial fork noise on a clean tree still reports
`DROPPED`, the original bug. So the local run makes no attribution claim at all.

**The tolerance is local-only, and that is the safety net.** `evaluate()` takes
`tolerate_unjudged`, default `False`, enabled only for a darwin `--run-mutmut`
invocation. The nightly workflow runs this script without `--run-mutmut`, so
the authoritative Linux gate keeps the original strict semantics: a kill-count
drop the local run could not judge is still a hard `DROPPED` there. A real
surviving mutant fails on both paths, always.

If you see `NOT-MEASURED`, the local run did not gate those modules. Run
`gh workflow run mutation.yml --ref <branch>` for a verdict.

### Subprocess-spawning tests (the marker convention)

mutmut mutates a function by injecting a *trampoline* into it; when the function
runs, the trampoline reads the `MUTANT_UNDER_TEST` env var that the mutmut runner
sets. A test that spawns a **fresh Python interpreter** (`subprocess` running
`sys.executable -m sumo_qa` / `-c "import sumo_qa.knowledge_loaders; ..."`) starts
a process the runner did NOT launch, so that var is absent and the trampoline
crashes the moment a mutated function is called:

```
KeyError: 'MUTANT_UNDER_TEST'
```

(Older mutmut releases surfaced this as `AttributeError: 'NoneType' object has no
attribute 'max_stack_depth'`, same root cause.) The crash used to be *silent*:
the pre-push hook only fires on a mutated-module/test-file diff, so a new
subprocess-spawning test sat latent until some unrelated later change tripped the
hook, at which point the failure looked like it belonged to that change.

If you add a test that spawns a Python subprocess importing the `sumo_qa` package
or a mutated module, do **both**:

1. Add `# mutmut-subprocess-spawning: <one-line reason>` near the top of the test
   file (the verbatim token `mutmut-subprocess-spawning` is what the guard scans
   for).
2. Add `"--ignore=tests/<your_test>.py"` to `[tool.mutmut].pytest_add_cli_args`
   in `pyproject.toml`.

You don't have to remember this from tribal knowledge:
`tests/test_mutmut_subprocess_exclusions.py` runs in the **ordinary** pytest
suite and fails **loudly and immediately**, at the PR that introduces the test:
if a subprocess-spawning test is added without being marked AND ignored, and
reciprocally if the `--ignore` list grows a stale or unjustified entry (which
would quietly shrink mutation coverage). The guard is a static AST check, so it
runs on every platform without invoking mutmut.

The guard's classifier recognises the hazard whether the `-c` body is an inline
literal or built in a separate variable (`code = textwrap.dedent("...import
sumo_qa.knowledge_loaders..."); subprocess.run([sys.executable, "-c", code])`),
and whether `-m` targets the full package or any `sumo_qa.<sub>` submodule that
transitively imports a mutated module (e.g. `sumo_qa.server`, `sumo_qa.ingest`).
A `-c` body is dedented and parsed as Python, and each `sumo_qa` module it
imports (`from sumo_qa import conformance` counts as `sumo_qa.conformance`) is
flagged when a static walk of `src/`'s imports reaches a mutated module from it
(`sumo_qa.conformance` reaches `knowledge_loaders`); a body that does not parse,
such as an f-string fragment, falls back to matching the module named right
after `from` or `import`. Any string naming `sumo_qa.<mutated>` or containing
`import <mutated>` is also flagged outright, so dynamic imports
(`importlib.import_module("sumo_qa.rules")`, `__import__`, `exec`) are caught;
the price is that a body merely mentioning such a name is flagged too. It also
handles the `shell=True` single-string form
(`subprocess.run("python -m sumo_qa", shell=True)`): a one-string command is
shlex-tokenised so it is classified like the equivalent argv list, rather than
slipping past as one un-split token. No `sumo_qa.<sub>` entry point is exempt:
every one, `sumo_qa.installer` and `sumo_qa.doctor` included, reaches a mutated
module, so `-m sumo_qa.installer --help` style spawns are flagged in both the
argv and shell-string forms. Its classifications are pinned by real fixture
meta-tests in `tests/fixtures/mutmut_guard/`.

## Toolchain pin lockstep

pre-commit hook venvs install from PyPI, so a hook that needs project
dependencies repeats them in its `additional_dependencies`, and ruff is pinned
both as `ruff==X` in the dev extra and as the ruff-pre-commit `rev: vX`.
Dependabot only edits `pyproject.toml`, so each bump it raises for a package a
hook also lists is half a change until the hook moves too.

`tests/test_toolchain_pin_lockstep.py` runs in the required pytest jobs and
enforces these rules:

- **Which entries.** A hook with an inline `language` other than `python`
  (`system`, `node`, ...) is skipped. Every other hook, including a
  remote-repo hook whose manifest declares its language, has each
  `additional_dependencies` entry checked on its own: an entry that does not
  parse as a PEP 508 requirement is skipped, and a parsed entry is compared
  only when `pyproject.toml` declares its package.
- **Same pin.** Every compared entry whose package `pyproject.toml` also
  declares carries the same specifier set and the same direct-reference URL.
  Environment markers and extras are ignored, since a marker says where a
  dependency installs rather than which versions it allows. Hook entries for
  packages `pyproject.toml` does not declare are out of scope.
- **Source precedence.** Hooks mirror the dev tooling, so an entry is compared
  first with the optional-extra sources: `[project.optional-dependencies]`
  groups, PEP 735 `[dependency-groups]` (string entries; `include-group`
  tables are ignored) and `[tool.uv].dev-dependencies`. Only a package none of
  those declare falls back to `[project].dependencies`. Different specifiers
  across the optional sources fail as ambiguous, as do two different
  `[project].dependencies` pins under the same environment marker. In the
  fallback, entries under different markers (a marker split) are all
  candidates, and the hook entry passes when it matches any one of them.
- **Required mirrors.** `REQUIRED_MIRRORS` in the test names the pairs that
  must exist, so deleting one side cannot turn the check into a silent pass:
  `mutmut` must be declared exactly once in `pyproject.toml` and exactly once
  in the `mutmut` hook. A new must-exist mirror is one row in that table.
- **ruff.** Exactly one ruff-pre-commit repo entry must exist, its `rev:` must
  be a `v<version>` tag, and that version must equal the `ruff==` pin.

The test hard-codes no version and lists every mismatch in one failure,
naming both files, the hook id, the hook value and every candidate
`pyproject.toml` declaration, so a bump edits the pins and nothing else.

## Release supply chain

- **Action pins.** Every `uses:` in `.github/workflows/` names a full commit
  SHA with a `# vX.Y.Z` comment; `tests/test_workflow_expression_lint.py`
  fails on a tag, branch or short SHA. Dependabot's `github-actions` entry
  bumps the SHA and the comment together. To pin a new action, resolve the
  tag's commit with `git ls-remote https://github.com/<owner>/<repo> 'refs/tags/<tag>^{}'`
  (or `refs/tags/<tag>` for a lightweight tag).
- **Workflow lint.** The `actionlint` pre-commit hook (pinned `rev`) runs on
  changed workflows, and the `actionlint` job in `lint.yml` runs the same hook.
- **Release build lock.** `.github/release/requirements.in` names the release
  build tools; `.github/release/requirements.txt` is the hashed lock compiled
  from it (regenerate with the command in its header). `release.yml` installs
  it with `--require-hashes` and builds with `--no-isolation`, so the lock is
  the whole set of build inputs. Dependabot watches `/.github/release`.
- **Release evidence.** `release.yml` adds `sbom.cdx.json`, `build-info.json`
  and `SHA256SUMS` next to the wheel and sdist, attests build provenance and
  the SBOM, and gates publishing on `scripts/release_evidence.py verify` plus
  `gh attestation verify` (`tests/test_release_evidence.py` covers the
  negative cases). Run the workflow from the Actions tab
  (`workflow_dispatch`) for a dry run that builds, attests and verifies
  without publishing. [`SECURITY.md`](../.github/SECURITY.md) has the consumer
  verification commands.

## Branch workflow

Feature work goes on a feature branch off `main`. Don't push without explicit
review approval.

## When sumo-qa tools are missing from your session

A healthy install (`sumo-qa-doctor` passes) does not mean the current agent
session has the sumo-qa tools attached; a session keeps the tool list it
started with. Contributor workflows that route through sumo-qa check the
session's tool list once before dispatching any work, and when the tools are
absent they switch every worker to one declared source-tree degraded mode
pinned to a single commit. The preflight, the degraded route, and its limits
are defined in
[`.claude/README.md`](../.claude/README.md#qa-tool-availability-preflight-and-source-tree-degraded-mode).

## Editing skills

Plain markdown. Edit `skills/<name>/SKILL.md`, or one of its lazy `skills/<name>/modules/*.md`
when the skill ships modules (`sumo-qa-reviewing-before-merge` does). Conformance tests catch structural
drift (Iron Law section, Checklist ≥4 items, graphviz dot block, Red Flags table); for a
module-split skill, `tests/test_review_skill_modules.py` also enforces one canonical copy per
rule, a routing table that lists every module, named (never "below"/"above") cross-references,
and the root/module token budgets.

## Editing knowledge catalogues

Plain markdown under `knowledge/`. The LLM picks from what these files say.
Adding a new technique, classification, or specialty tool = editing one file.

## Adding a new skill

1. Create `skills/<new-name>/SKILL.md` following the template in `docs/SKILLS.md`.
2. `register_skills_as_prompts` (server startup) picks it up automatically.
3. Conformance tests parametrise over `skills/*/SKILL.md`: they run on the new skill too.
4. If the skill is meant to auto-trigger in Claude Code, the frontmatter `description` is what the host LLM uses to route.
5. Add a trigger row to [`tests/fixtures/skill_triggers.yaml`](../tests/fixtures/skill_triggers.yaml) pinning at least one natural-language prompt to the new skill: [`tests/test_skill_triggering.py`](../tests/test_skill_triggering.py) fails on any registered skill tool that lacks a fixture row, and on any pinned phrase that doesn't appear in the skill's description. Edit the fixture, not the test.
6. Add the skill's tool name (directory name with `-` replaced by `_`) to `_SKILL_TOOL_NAMES` in [`tests/test_server.py`](../tests/test_server.py): `test_registers_only_test_data_knowledge_and_skill_tools` compares the registered tools to that set by exact equality.
7. Add the tool name from step 6 to `TOOLS` in `src/sumo_qa/tool_registry.py` with its capability group and `core` flag; `test_tool_registry.py` fails on an unlisted tool (the server itself only warns and keeps it out of `core`). Then run `uv run python scripts/regen_tools_list_snapshot.py` and commit the regenerated `tests/fixtures/mcp_tools_list_snapshot.json`. Every skill registers an MCP tool, and [`tests/test_tools_list_contract.py`](../tests/test_tools_list_contract.py) requires the snapshot's tool names (`required_tools` and the `schemas` keys) to equal the live `tools/list` exactly, so adding or renaming a skill fails it until the snapshot is regenerated in the same PR. The test reads the working tree, not commit state: the server lists skills from `src/sumo_qa/_data/skills` when that directory exists, else from repo-root `skills/`, so a stale `_data/skills` copy shadows the working tree for everything that resolves skills through `skill_prompts._skills_dir()` (the server and its tests, the regen script, the installer's derived `REQUIRED_TOOL_NAMES`, and `registered_entry_skills()` in `src/sumo_qa/conformance.py`). Tests that read repo-root `skills/` directly, such as `tests/test_skill_conformance.py` and `tests/test_skill_md_token_budget.py`, see the working tree, so a stale `_data/skills` shows up as server-backed tests failing while those pass. Schema changes are warn-only.
8. Fit the token budgets. In [`tests/test_skill_md_token_budget.py`](../tests/test_skill_md_token_budget.py), add a `SKILL_TOKEN_BUDGETS` entry for the new root `SKILL.md`; a root over `GLOBAL_ROOT_SKILL_TOKEN_BUDGET` (3000) also needs a justified `DOCUMENTED_ROOT_BUDGET_EXCEPTIONS` entry. Every skill's description also grows the all-skill manifest, which [`tests/test_skill_modules.py`](../tests/test_skill_modules.py) caps with `COMPACT_MANIFEST_TOKEN_BUDGET` (shipped compact default) and `FULL_INDEX_TOKEN_CEILING` (full-index opt-in). Trim the description first; raise a constant only with a comment naming the skill that moved it.
9. Add the skill's tool to the "Available skills" list in [`.github/copilot-instructions.md`](../.github/copilot-instructions.md), in the same one-line style as its neighbours: Copilot has no other way to see the skill surface, so that list stays enumerated, and `test_instruction_surface_names_only_registered_tools` in [`tests/test_server.py`](../tests/test_server.py) fails on any `_SKILL_TOOL_NAMES` entry missing from that list's bullets (a mention elsewhere in the file does not count). `README.md`, `docs/SKILLS.md`, and `docs/TOOLS.md` stay at capability-altitude (no skill/tool counts or name-lists) and point to `skills/` and the host's MCP tool list; only a genuine *capability* change (a new kind of workflow, a changed contract) warrants an edit there.

## Editing plugin packaging (host adapters)

Plugin-format hosts (Claude Code, Codex) consume `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` at the repo root. These folders, along with `.mcp.json`, `hooks/hooks.json`, `hooks/hooks-codex.json`, `docs/host-adapters.md`, and the runtime snapshot at `src/sumo_qa/_data/plugin_metadata.json`, are **generated** from `pyproject.toml`'s `[tool.sumo-qa.plugin]` overlay. Do not hand-edit them.

```bash
# After bumping any plugin metadata in [tool.sumo-qa.plugin]:
python -m plugin_packaging.plugin_generator sync

# Before pushing, the pre-commit drift hook re-runs:
python -m plugin_packaging.plugin_generator check

# Schema correctness (Claude Code manifest + Codex hooks):
python -m plugin_packaging.validate_plugins
```

The `plugin-packaging` CI workflow runs both gates on every PR. If `pyproject.toml`'s plugin overlay changes without a matching `sync`, the drift check fails.

### Adding a new host adapter

1. Add `plugin_packaging/templates/<host>.py` exposing `render(plugin: CanonicalPlugin) -> dict`.
2. Wire it into `plugin_packaging.plugin_generator._build_outputs`.
3. Run `python -m plugin_packaging.plugin_generator sync` and commit the generated folder.
4. If the host publishes a JSON Schema, vendor it under `plugin_packaging/schemas/` and add a `validate_<host>` call to `plugin_packaging/validate_plugins.py`. Otherwise extend the `plugin-dir-handshake` matrix in `.github/workflows/install-smoke.yml`.

See [host-adapters.md](host-adapters.md) for the full architecture rationale.

### Marketplace copy and assets

Marketplace copy (`short_description`, `long_description`, `category`) is canonical in `pyproject.toml` `[tool.sumo-qa.plugin]`, the same overlay as everything above, regenerated by the same `sync` command. The canonical loader caps `short_description` at 200 characters.

The visual assets in `assets/` beyond `logo.png` are also generated, by `scripts/generate_marketplace_assets.py` (stdlib-only; commit the regenerated artifacts together with any script change, never hand-edit them):

```bash
# Icon (512x512, derived from assets/logo.png) + preview SVG from the
# committed capture — deterministic, safe to run anywhere:
python scripts/generate_marketplace_assets.py all

# Refresh the doctor capture itself (runs the real `sumo-qa-doctor` on
# YOUR machine, sanitises home paths) — only when the doctor's output
# format or checks change. This also re-renders preview-doctor.svg from
# the fresh capture, so the txt and SVG never drift apart:
python scripts/generate_marketplace_assets.py capture
```

`tests/test_marketplace_assets.py` pins the icon dimensions, the path sanitisation, and the no-pictograms brand rule.

## Scheduled CI workflows (opt-in, off the PR critical path)

Three workflows run on a weekly schedule (Monday mornings UTC) and on
`workflow_dispatch`, but never on `push` or `pull_request`, so they
exercise external surfaces without becoming required PR checks:

- [`.github/workflows/tdm-freshness.yml`](../.github/workflows/tdm-freshness.yml): checks every known-good test-data URL still returns 2xx. Opens a `tdm-freshness` issue on failure. (06:00 UTC.)
- [`.github/workflows/external-skills-smoke.yml`](../.github/workflows/external-skills-smoke.yml): runs `tests/test_external_skills.py::test_search_external_skills_real_cli_smoke` and `::test_install_external_skill_real_cli_smoke` against the real upstream Skills CLI at its pinned version (on Node 24, per the package's `engines`). Together they prove the pinned version still resolves and reports itself, `find` still returns output, and `skills add <absolute path>` still installs sumo-qa's local checkout so the recorded commit and digest verify at execution. The install smoke only runs when `SUMO_QA_REAL_CLI_SMOKE=1`, which this workflow sets and PR CI does not. The mocked coverage in `tests/test_external_skills.py` runs on every PR via `test.yml`; this workflow exists so format drift in the upstream Skills CLI surfaces on a low cadence without coupling required CI to npm / network / upstream uptime. (06:00 UTC.)
- [`.github/workflows/upgrade-smoke.yml`](../.github/workflows/upgrade-smoke.yml): installs **whatever sumo-qa is currently published on PyPI** into a temp HOME, configures Claude Code + VS Code, then upgrades to **this checkout's source** and re-runs the installer against the **same** HOME. This rehearses the real deployment path, *current live release → the build we're about to ship*, so that when this source is eventually published, upgrading onto an existing install is proven not to break. Asserts the re-install-over-existing-state stayed clean: exactly one `sumo-qa` MCP entry per host, no dangling skill symlinks, all five console-script entry points present, and `tools/list` (from the upgraded host config) is still a superset of the committed snapshot. This is the upgrade transition [`install-smoke.yml`](../.github/workflows/install-smoke.yml) can't see, that workflow always starts from a fresh, empty HOME. The baseline defaults to the current latest PyPI release (resolved at runtime); a `workflow_dispatch` input can override it with a specific published version to rehearse a particular upgrade path. There is **no** version-ordering check, the local checkout has no real version until release-please assigns one, so the delta under test is the code, not a version number. First matrix is Linux + macOS (the upgrade-cleanup logic in `installer.py` is OS-independent; Windows clean-install paths are already covered by `install-smoke.yml`). (06:30 UTC.)

### Interpreting an external-skills-smoke run

| Outcome | Meaning | Action |
|---|---|---|
| GREEN, pytest reports `2 passed` | Upstream CLI reachable at the pinned version; the MCP-owned search shape contract (keys present, non-empty `raw_output`, ANSI stripped) still holds, and a pinned install from a local checkout records provenance that verifies at execution. | None. |
| RED in the `Verify npx is on PATH` step | `actions/setup-node` regressed or its cache is corrupt. | Bump the action version or pin a different `node-version`. Not an `external_skills.py` bug. |
| RED in the `Run external Skills CLI smoke` step | Genuine MCP-shape regression: the CLI returned, but the wrapper in `sumo_qa.external_skills` dropped a key, leaked an ANSI sequence into `raw_output`, or returned empty text. | Fix in `src/sumo_qa/external_skills.py`; the failing assertions in the test name the broken contract. Do **not** loosen the assertions, they're the only thing standing between us and silent upstream-format coupling. |
| RED in the `Fail if smoke was skipped` step | The test self-skipped via `pytest.skip(...)`. Because the workflow's earlier `Verify npx is on PATH` step rules out `NodeNotFoundError`, the only paths to a skip here are the CLI timing out or the CLI exiting nonzero, both surfaced as `ExternalSkillCLIError`. Skips are deliberately elevated to failures so a permanent silent skip (e.g. the upstream `skills find` command renamed) cannot defeat the workflow's purpose. | Read the `SKIPPED` line in the pytest log (the `-rs` flag prints the reason). A `timed out after Ns` reason is likely transient, re-run the workflow. A `skills CLI exited N` reason is real upstream drift, inspect `npx --yes skills@<version> find mypy` locally and adjust `src/sumo_qa/external_skills.py` if the CLI's contract changed. |

To trigger the workflow on demand (e.g. before bumping the
`sumo_qa.external_skills` wrapper): GitHub → Actions →
`external-skills-smoke` → **Run workflow**.

### Skills CLI pin

The external-skill tools run one exact Skills CLI version,
`SKILLS_CLI_VERSION` in `src/sumo_qa/external_skills.py`. The command
builder refuses anything that is not an exact `X.Y.Z` version, so npx can
never resolve a range or dist-tag such as `latest`, and each process checks
that the CLI reports the pinned version before running it. Moving the pin is a
reviewed dependency change, made in its own PR:

1. Read the new release's changes in the published package
   (`npm pack skills@<version>`) before trusting it. Confirm `add <absolute
   path>` still installs a local source by copying it (sumo-qa hands the CLI
   only its own checkout and deletes it afterwards) and that `--version`
   still prints the bare version.
2. Update `SKILLS_CLI_VERSION` and the literal in
   `tests/test_external_skills_provenance.py::test_pin_is_an_exact_reviewed_version`
   together, plus the pinned argv in the schema fixtures.
3. Run `external-skills-smoke` on the branch (**Run workflow**) so the real
   CLI proves the new version resolves, reports itself, and still returns
   search output.

A `SkillsCLIVersionError` (the CLI reported another version) points at an npx
shim or an npm config override, not a sumo-qa bug; never work around it by
unpinning.

### Interpreting an upgrade-smoke run

| Outcome | Meaning | Action |
|---|---|---|
| GREEN | A real PyPI release installed cleanly into a temp HOME, the source build upgraded over the same HOME, and the post-upgrade host config is duplicate-free with no dangling skill symlinks. | None. |
| RED in `Resolve published baseline` | PyPI was unreachable, or a `workflow_dispatch` `previous_version` override named a version that isn't a published release. | Re-run if PyPI was transiently down; if overriding, pass a version that exists on PyPI (omit the input to use the current latest automatically). |
| RED in `Pre-upgrade install` | The currently-published release no longer installs cleanly on the runner Python (e.g. a dependency it pinned has yanked a compatible wheel). | This is published-release rot in the live version, not a source regression, usually transient or a dependency-pin issue worth a follow-up; it does not block the source under test. |
| RED in `Post-upgrade install` with a duplicate-entry / dangling-symlink failure | A genuine upgrade regression: re-running the installer over an existing HOME left a duplicate `sumo-qa` MCP entry, leaked the legacy `mcpServers` key into VS Code, or left a broken skill symlink. Clean-install CI can't catch this. | Fix the cleanup logic in `installer.py` (`_install_claude_code_skills_per_dir` for symlinks, `_setup_claude_code` / `_setup_vscode_copilot` for the single-entry write). The failure message names the broken assertion. Add a unit case to `tests/test_installer_idempotency.py`. |
| RED in `Post-upgrade entry points` or `tools/list superset contract` | The upgraded build dropped a console-script wrapper or a pinned tool. | Same root cause as the equivalent `install-smoke.yml` failures, fix `pyproject.toml` entry points / the tool registration, regenerate the snapshot with `scripts/regen_tools_list_snapshot.py` only if the removal is deliberate. |
| `::warning` "Skill-pack drift" annotation (still GREEN) | A skill present in the previous release is absent (removed/renamed) in source. Not a failure, a legitimate release decision, but surfaced so it can't ship silently. | Confirm the removal is intended and call it out in the release notes. |

To trigger on demand (e.g. before a release, or to validate an
installer change): GitHub → Actions → `upgrade-smoke` → **Run workflow**.
By default it upgrades from the current latest PyPI release; optionally set
`previous_version` to rehearse the upgrade from a specific published version.

## Reinstalling locally

```bash
pip install -e .                              # if you're using a plain venv
# or
uv tool install --from . sumo-qa --reinstall  # if you're using uv's tool dir
```

Picks up server.py changes. For skill edits, no reinstall needed, Claude Code reads each
`~/.claude/skills/<name>/` directory via the per-skill symlinks `sumo-qa-install` set up
(no wrapper directory; Claude Code doesn't recurse), and the MCP server reads
`skills/*/SKILL.md` fresh on each tool invocation.
