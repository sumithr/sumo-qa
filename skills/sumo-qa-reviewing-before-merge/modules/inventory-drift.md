# Reviewing before merge: documented-inventory drift

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff changes a documented count, name, inventory, public-surface name, schema field, version, or a generated artifact (manifest, lockfile, sidecar); a dependency/tool/runtime constraint also takes `mirrored-constraints`. **Extends:** checklist step 9 (documented-inventory drift rule) and Verdict-format item 2a. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Documented-inventory drift rule (step 9)

**Documented-inventory drift rule (pinned).** When the diff changes a documented count, inventory, public-surface name, or schema field — the documented-inventory-drift probe — the obvious doc the diff touches is rarely the only stale spot. Before the verdict, search the supplied ground-truth context (any `rg`/grep listing, "Other repo state" section, etc.) for the OLD value (a dependency constraint: by dependency identity, hidden config included, anchoring only the stale mirrors `mirrored-constraints` classifies); each path it surfaces is a separate UNCOVERED anchor that needs its own ledger row (format in this module's 2a row). Generic guidance, anchoring only on the obvious doc, or naming one stale path is UNCOVERED. If the ground-truth context names zero stale paths, say so explicitly; do NOT silently default to "covered".

**Not a drift anchor (pinned).** An occurrence that merely still carries the old constraint text, but is not a declared mirror, still shares versions with the diff's range and meets no other stale test in `mirrored-constraints` step 3, is not a drift anchor: no 2a row, no item-8 line, no residual. Matching the old text, or sitting beside a stale declared mirror, does not make it a copy of the diff's requirement. Anchoring it anyway is the over-trigger: it manufactures a sync requirement the diff never created and blocks a verdict on it.

**Worked contrast (not an anchor).** The manifest raises a cap `<2` → `<3`; a hook whose block says to keep it in sync still reads `<2`; a CI install with no such statement also reads `<2`.
- BAD: a 2a row, a `Risk N:` line, a `Surface verifier:` line or a blocker for the CI install because its text matches the stale hook's or it is an isolated environment. Its `<2` shares every version below 2 with the new range and admits nothing the diff excludes: there is nothing to fix or verify.
- GOOD: one 2a row and one item-8 line for the hook only, and one relationship line for the CI install: `<ci file>:<line> <2: undeclared range, shares versions with <3, compatible, no finding`.

**Residual concerns on a constraint diff (pinned).** Stale mirror or not, the root's one concrete `Residual concerns:` item comes from an unexercised code path or input of the changed code, never from history, a lock, or differing caps, syntax or bounds among compatible occurrences. BAD: `CHANGELOG still names the old version`; `upper bounds diverge, align them before the next release`. GOOD: `<changed function> never ran on <an input the fresh tests skip> (<file:line>)`.

## Inventory-drift ledger rows (Verdict-format item 2a)

- **2a. Inventory-drift extension.** For an inventory-drift risk (see step 9), the item-2 risk row (`coverage-ledger`) is not sufficient. Emit ONE additional ledger row per stale path the supplied ground-truth context names — never crammed into one row or shoved into the risk row's `Required update:` field. Each row uses this exact shape (the `<old> → <new>` value pair must appear inline):
  `Inventory drift anchor: <path>:<line> (<old> → <new>) | Required update: this file | Diff updated it: <YES if the diff touches this exact path; NO otherwise> | Coverage: <COVERED if the diff updates this exact file; UNCOVERED if it does not>`
  Each UNCOVERED row is a SAFE-blocker. The verdict line must name every UNCOVERED stale path explicitly — not "documentation needs updating". Zero stale paths supplied → emit `Inventory drift anchor: NONE supplied | Coverage: N/A` rather than silently defaulting to covered.

  **Worked contrast (one row per stale path, value pair inline).** Two stale paths surfaced (`docs/INSTALL.md:17`, `.github/ISSUE_TEMPLATE/qa_output_quality.yml:22`), old `28` → new `29`:
  - BAD (single crammed row, no value pair): `Risk: Documented-inventory drift | Anchor: README.md:42 | Required update: docs/INSTALL.md, .github/ISSUE_TEMPLATE/qa_output_quality.yml | Coverage: UNCOVERED` — collapses both paths into one row, anchors on the obvious doc, omits `(28 → 29)`. SHAPE FAIL.
  - GOOD (one row per stale path, value pair inline):
    `Inventory drift anchor: docs/INSTALL.md:17 (28 → 29) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`
    `Inventory drift anchor: .github/ISSUE_TEMPLATE/qa_output_quality.yml:22 (28 → 29) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`
