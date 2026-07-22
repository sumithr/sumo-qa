## Precision contracts for review edge cases

Apply these only when the supplied change shape or requested artifact matches.

### Acceptance criteria

When acceptance criteria are supplied, emit one line for every criterion:
`AC<n>: <criterion> | Classification: <MET | UNMET | UNVERIFIED> | Anchor: <evidence>`.
MET requires both an implementing diff anchor and a fresh test ID/assertion proving the
criterion's stated behavior. UNMET means the behavior is absent from the diff. UNVERIFIED
means the diff plausibly implements it but fresh path-matching evidence is missing. Every
UNMET or UNVERIFIED criterion blocks SAFE; all-MET criteria do not create an extra blocker.
Never fetch, infer, or add criteria that the host did not supply. If none were supplied, say
the AC check was skipped and do not turn a feature-flow gap into an UNMET criterion.

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

### External-output producer and evidence

First identify the producer. The external-contract axis fires only for output produced by a
tool, CLI, API, subprocess, or foreign file outside the changed code's control. A fixture
traceable to a cited real/minimal run discharges this axis; do not require another fresh run
or speculate about unrelated format variants. A hand-authored fixture without provenance is
UNPROVEN.

If the changed code is the sole producer and consumer, explicitly decline the axis:
`External-contract axis: NOT FIRED (internal/self-produced) | Value: <concrete value> | Producer: <function/module> | Consumer: <function/module> | No external source: confirmed`.
Ordinary internal parsing risks may remain, but they are not external-contract risks.

### Feature-flow evidence

When a primary UI/API/CLI/worker/artifact flow exists, report it separately from acceptance
criteria: `Feature flow: <path> | Exercised end-to-end this turn: <YES with fresh test | NO with only lower-level evidence> | Status: <VERIFIED | UNVERIFIED (feature flow) — SAFE-blocker>`.
A green unit for a helper does not prove the realistic flow. If no acceptance criteria were
supplied, say so; never fabricate an AC to describe the feature-flow gap.

### Review-feedback memory

Use saved review feedback only when it is actually supplied and its trigger matches this
diff. Quote the supplied trigger and probe when used. If none is supplied, state exactly:
`no saved review feedback supplied — advisory-hint check skipped`, then perform ordinary
discovery without attributing any risk to memory or a previous review.

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
