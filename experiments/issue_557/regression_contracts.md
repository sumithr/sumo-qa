## Precision contracts for review edge cases

Apply these only when the supplied change shape or requested artifact matches.

### Mandatory grounding

Before the verdict, repeat the exact supplied file path plus line, symbol, or changed
construct for every material finding. Identifying the right defect without its supplied
anchor is not enough. When diff-impact or repo-map evidence is supplied, explicitly name
each relevant `risk_surface` path and `related_tests` lead; a mapping lead is not coverage,
so reconcile it with the fresh run. When sibling changes share a verifier surface, name the
changed surface path and the full verifier-config path as well as runtime, key, scope, and
combined-tree status.
Every verdict direction must also quote the supplied verification command, exact
pass/fail/skip counts, and the relevant fully-qualified test IDs; do not omit them on a NOT
SAFE path.

### Acceptance criteria

When acceptance criteria are supplied, emit one line for every criterion:
`AC<n>: <criterion> | Classification: <MET | UNMET | UNVERIFIED> | Anchor: <evidence>`.
MET requires both an implementing diff anchor and a fresh test ID/assertion proving the
criterion's stated runtime behavior. A documentation-only or inert-artifact criterion is
MET when the supplied diff directly shows the required content at the exact artifact anchor;
do not demand a runtime test for that criterion. UNMET means the behavior is absent from the
diff. UNVERIFIED means the diff plausibly implements it but fresh path-matching evidence is
missing. Every UNMET or UNVERIFIED criterion blocks SAFE; all-MET criteria do not create an
extra blocker. Never fetch, infer, or add criteria that the host did not supply. If none were
supplied, say the AC check was skipped and do not turn a feature-flow gap into an UNMET
criterion.

### Executable scope and inert configuration

Classify by behavior, not directory. Executable hooks, scripts, CI commands, and automation
outside `app`/`src`/`lib` receive the runtime risk sweep. For each runtime risk, emit:
`Risk: <name> | Anchor: <file:line> | Required test path: <path mirroring the executable anchor, such as tests/hooks/ for .claude/hooks/> | Fresh matching tests: <fully-qualified IDs or NONE> | Coverage: <COVERED | UNPROVEN | UNCOVERED>`.
Conversely, a docs-only or inert formatter/linter/editor configuration change has no runtime
consumer: do not invent runtime risks. A fresh configuration verifier can make that narrow
change SAFE-eligible.

### Eval validity

For a changed load-bearing A/B eval, a single A0 failure and A1 pass is insufficient. State
whether A0 is structurally incapable of satisfying the rubric: the PASS condition must need
guidance unique to A1 and not be reachable through a pre-existing general rule. Also verify
that every rubric-credited input actually makes the broken and correct implementations
produce different observable results. If a generic existing rule can satisfy the rubric, or
the credited input is non-discriminating, label the A/B control UNPROVEN and block SAFE.
When the supplied context identifies that existing path as generic rule 2b, name it exactly
as the `generic 2b prescribed-discriminating-input requirement`; shorthand such as `rule 2b`
is insufficient.

### External-output producer and evidence

First identify the producer. The external-contract axis fires only for output produced by a
tool, CLI, API, subprocess, or foreign file outside the changed code's control. A fixture
traceable to a cited real/minimal run discharges this axis; do not require another fresh run
or speculate about unrelated format variants. A hand-authored fixture without provenance is
UNPROVEN.

If the changed code is the sole producer and consumer, explicitly decline the axis:
`External-contract axis: NOT FIRED (internal/self-produced) | Value: <concrete value> | Producer: <function/module> | Consumer: <function/module> | No external source: confirmed`.
Ordinary internal parsing risks may remain, but they are not external-contract risks.
A named tool, CLI, API, or subprocess such as `mutmut` is always external to the changed
consumer. Never emit the internal/self-produced declination when such a source is the
producer, and never pair `NOT FIRED` with a tool/CLI producer.
When a real-run-traceable fixture is exercised through the actual matcher by fresh tests,
that external flow is verified for the supplied cases. Do not manufacture a separate
feature-flow blocker merely because the surrounding hook/CLI invocation was not rerun.

### Feature-flow evidence

When a primary UI/API/CLI/worker/artifact flow exists, report it separately from acceptance
criteria: `Feature flow: <path> | Exercised end-to-end this turn: <YES with fresh test | NO with only lower-level evidence> | Status: <VERIFIED | UNVERIFIED (feature flow) — blocks SAFE>`.
A green unit for a helper does not prove the realistic flow. If no acceptance criteria were
supplied, say so; never fabricate an AC to describe the feature-flow gap.

### Surface-specific verifier evidence

Infer the required verifier from the changed behavior surface, not merely from commands
already listed in the verification record. A changed `SKILL.md` plus its promptfoo eval YAML
requires that exact eval file to run. When the complete record contains no promptfoo run,
name Node 24 plus the configured provider key as missing required execution context.
Name both changed paths and the full eval path. If the complete verification record lists
only review, Codex, lint, pytest, token-budget, or CI checks, state that the promptfoo eval
was not run. Emit:
`Surface verifier: <full eval path> | Ran: NO | Runtime/key: Node 24 + configured provider key NOT EVIDENCED | Status: UNVERIFIED — blocks SAFE`.
Classify the surface verifier UNVERIFIED and block SAFE. When a promptfoo command and result
are supplied, do not invalidate that run merely because its runtime or key were not repeated;
require more only when the supplied context identifies a wrong runtime, key, scope, or tree.
For sibling changes to
the same behavior surface, isolated branch runs do not replace a combined-tree verifier run.
When the supplied combined-tree run includes the correct runtime, key, scope, and pass
counts, treat the verifier as discharged and do not demand a redundant rerun.

### Review-feedback memory

Use saved review feedback only when it is actually supplied and its trigger matches this
diff. Quote the supplied trigger and probe when used. If none is supplied, state exactly:
`no saved review feedback supplied, advisory-hint check skipped`, then perform ordinary
discovery without attributing any risk to memory or a previous review.
The present and absent branches are mutually exclusive. When matching feedback is supplied,
emit `advisory hint from saved review feedback (trigger: <verbatim trigger>): <verbatim
recommended probe>` as a separate line and never emit the absent-memory line.

### Stateful fence parser

A fence parser that stores only the marker character and not the opening run length is
UNPROVEN even when 3-character happy paths pass. Prescribe this discriminating input: a
4-backtick outer fence wrapping a 3-backtick inner block, followed inside the outer block by
a `## heading`-looking line. The char-only implementation closes early at the inner
3-backtick line and wrongly indexes that heading; the length-aware implementation keeps the
outer fence open and skips it. Require a fresh regression test before SAFE. Do not substitute
tilde-vs-backtick or unclosed-EOF cases: those do not discriminate this length bug.

### Readiness scorecard

When requested, lead with the prose review and verdict, then append the scorecard. It is an
evidence summary, never a predictive or invented numeric/percentage quality score. Derive
its recommendation from the same risk/AC evidence: uncovered blockers yield `blocked`, and
stale or incomplete evidence yields `insufficient_evidence`; neither may read ready. Include
coverage or mutation signals only if they actually ran. Otherwise report each as
`not measured`, never green or passing.

### Inventory and repo-map evidence

For documented inventory drift, emit one line per supplied stale path with the exact
`<old> → <new>` pair and whether that path was updated. Every unchanged stale path is
UNCOVERED and an explicit SAFE-blocker; state that merge is blocked until every named stale
document is updated. Use one row per path:
`Inventory drift anchor: <path>:<line> (<old> → <new>) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`.
Copy the supplied `<old> → <new>` pair verbatim in every row; never paraphrase it as
`still <old>` or `correct <new>`.
For a probable mapping gap, acknowledge the flagged source path but never use the map as the
coverage verdict. If a fresh matching test directly asserts the changed behavior, mark the
risk COVERED, cite that test ID and counts, and do not invent a stricter downstream nuance.
Do not say that the repo-map reported no tests or describe a tooling/mapping gap in this
covered result; lead directly with the changed source and fresh discriminating test.
For a normal repo-map risk surface, explicitly mark every source path with no fresh matching
test UNCOVERED even when an unrelated `related_tests` lead passed.

### UNPROVEN status and failure mode

When the failure path lacks a discriminating assertion, explicitly write `Coverage:
UNPROVEN` (or `UNCOVERED` when no matching test ran); `NONE` is not a coverage status. Name
the catalogued failure mode. A substring matcher must say `substring/token confusion`. A
limit boundary must say `boundary off-by-one` and identify the observed comparator mismatch,
such as `<` rejecting the limit where `<=` should allow it, before giving boundary inputs and
broken-versus-correct results.

### Requested risk ledger

When the user asks for a ledger, finish the prose review including its literal verdict line
first, then append the ledger. The required order is literally:
`<prose review>`, then `Verdict: <SAFE TO MERGE | NOT SAFE TO MERGE>`, then `Risk ledger:`,
then the table. Emit exactly one verdict line and do not place it after the table. Use exactly
these columns:
`| Risk | Statement | Source | Test / check | Evidence | Residual |`.
Evidence vocabulary is `passing`, `failing`, `planned`, `stale`, or `accepted_residual`.
Every cell is filled. A covered risk uses `passing` and residual `accepted`/`mitigated`; an
UNCOVERED or UNPROVEN risk uses `planned` and residual `blocker`.
