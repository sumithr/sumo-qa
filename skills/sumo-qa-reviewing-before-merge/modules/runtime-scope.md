# Reviewing before merge: runtime scope and the trivial-change exemption

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** deciding whether a diff is a runtime change (executable behaviour, not path prefix) or qualifies for the trivial-change exemption; always load for a diff touching hooks, scripts, CI/workflow steps, automation, or docs/static config. **Extends:** the runtime-change trigger in Verdict-format discipline and checklist step 4. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## What counts as a runtime change (pinned)

**What counts as a runtime change (pinned — behaviour, not path prefix):** any diff touching **executable code with a behavioural surface** — code that *runs* and can branch, parse a command, gate an action, transform input, or persist state, producing a wrong observable result. Keyed on what the file *does*, NOT on `app/`/`src/`/`lib/` location. It includes executable code OUTSIDE those dirs — a hook under `.claude/hooks/`, a `scripts/` script, a `.claude/` automation or generated runner, a CI/release workflow shell step, a Makefile/justfile recipe, a git hook — the moment it carries branching or command logic (broadens the trigger; the source-dir paths stay runtime too). So an executable hook with command-parsing logic gets the full sweep + coverage ledger like any library module; a pure metadata bump (version string, name list) stays the inventory-drift rule's, not promoted to runtime on its own.

## Command/input-classifier probe (pinned)

**Command/input-classifier probe (pinned):** when the change adds or edits a predicate that classifies a command or string (`split()` plus token membership, `in`, `startswith`, a regex), probe it BOTH ways against the function's stated PURPOSE, not its mechanism line. False positive: the token as an argument or inside echoed or quoted text (`echo "run pytest later"`, `grep pytest log`). False negative: an equivalent form the match misses (alternate or legacy entrypoint, path-prefixed or suffixed token such as `/usr/bin/pytest`, the `python -m` form). A docstring or comment restating the naive rule describes the defect; it is not a spec that clears it. Each confirmed mis-classification is a named risk with its own ledger row. A green test feeding only the canonical command is path-matching but not at the failure mode, so that risk is UNPROVEN, never a residual concern. `Named risks: None` on a command-parsing change is the waved-through failure.

## Location claim (pinned)

**Location claim (pinned):** when the requester or PR calls a change trivial, tooling, or non-runtime because of WHERE it lives ("just a hook", "not under src", "only a script"), answer that claim in one line of the review: location does not decide runtime scope, executable behaviour does, then name the behaviour that makes THIS change runtime (e.g. the hook parses every Bash command and gates it). Running the sweep without saying so leaves the requester's rule standing for the next diff; silence is not a rebuttal.

## Trivial-change exemption (pinned)

**Trivial-change exemption (pinned):** for **genuinely non-executable diffs**, NOT "anything outside `app`/`src`/`lib`". A diff qualifies only when it touches solely docs (`docs/`, markdown), static/inert config (YAML/TOML/JSON read as data, not executed — formatter/linter ignore lists, editor config), or other files with **no executable behavioural surface**. Path is irrelevant — an executable hook/script/automation under `.claude/hooks/`, `scripts/`, or `.claude/` is a runtime change despite sitting outside the source dirs, so it does NOT qualify (run the full sweep + ledger). When the diff DOES qualify: SKIP item 2; the verification command (linter/formatter/build) IS the coverage, so mark those anchors `COVERED BY VERIFICATION`. Items 1, 3, 4, 5, 6 still required. `Touched files:` and `Change shape:` are mandatory in both modes; citing the verification command's file argument does not discharge `Touched files:`.

## Red Flags

| Thought | Reality |
|---|---|
| "This hook/script is under `.claude/hooks/` or `scripts/`, not `app/src/lib`, so it's trivial — skip the sweep" | Wrong — the runtime trigger keys on executable behaviour, not path prefix. An executable hook/script with branching or command-parsing logic is runtime wherever it lives; run the full sweep + ledger. The command-parsing defects (echo-token, flag-arity, quote-splitting) hiding in such hooks are exactly the sweep's target class. |
