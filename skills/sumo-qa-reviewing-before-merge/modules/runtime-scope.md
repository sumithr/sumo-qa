# Reviewing before merge: runtime scope and the trivial-change exemption

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** deciding whether a diff is a runtime change (executable behaviour, not path prefix) or qualifies for the trivial-change exemption; always load for a diff touching hooks, scripts, CI/workflow steps, automation, or docs/static config. **Extends:** the runtime-change trigger in Verdict-format discipline and checklist step 4. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## What counts as a runtime change (pinned)

**What counts as a runtime change (pinned — behaviour, not path prefix):** any diff touching **executable code with a behavioural surface** — code that *runs* and can branch, parse a command, gate an action, transform input, or persist state, producing a wrong observable result. Keyed on what the file *does*, NOT on `app/`/`src/`/`lib/` location. It includes executable code OUTSIDE those dirs — a hook under `.claude/hooks/`, a `scripts/` script, a `.claude/` automation or generated runner, a CI/release workflow shell step, a Makefile/justfile recipe, a git hook — the moment it carries branching or command logic (broadens the trigger; the source-dir paths stay runtime too). So an executable hook with command-parsing logic gets the full sweep + coverage ledger like any library module; a pure metadata bump (version string, name list) stays the inventory-drift rule's, not promoted to runtime on its own.

## Trivial-change exemption (pinned)

**Trivial-change exemption (pinned):** for **genuinely non-executable diffs**, NOT "anything outside `app`/`src`/`lib`". A diff qualifies only when it touches solely docs (`docs/`, markdown), static/inert config (YAML/TOML/JSON read as data, not executed — formatter/linter ignore lists, editor config), or other files with **no executable behavioural surface**. Path is irrelevant — an executable hook/script/automation under `.claude/hooks/`, `scripts/`, or `.claude/` is a runtime change despite sitting outside the source dirs, so it does NOT qualify (run the full sweep + ledger). When the diff DOES qualify: SKIP item 2; the verification command (linter/formatter/build) IS the coverage, so mark those anchors `COVERED BY VERIFICATION`. Items 1, 3, 4, 5, 6 still required. `Touched files:` and `Change shape:` are mandatory in both modes; citing the verification command's file argument does not discharge `Touched files:`.

## Red Flags

| Thought | Reality |
|---|---|
| "This hook/script is under `.claude/hooks/` or `scripts/`, not `app/src/lib`, so it's trivial — skip the sweep" | Wrong — the runtime trigger keys on executable behaviour, not path prefix. An executable hook/script with branching or command-parsing logic is runtime wherever it lives; run the full sweep + ledger. The command-parsing defects (echo-token, flag-arity, quote-splitting) hiding in such hooks are exactly the sweep's target class. |
