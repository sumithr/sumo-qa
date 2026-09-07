# Reviewing before merge: adversarial discovery probes

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff touches any runtime (executable) file; this is the step-4 sweep every runtime review runs. **Extends:** checklist step 4 (adversarial discovery pass). The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Code-shape probes (step 4)

The probes below map a code-shape signal to the defect class to suspect:

- **Reordered statements in a write/persist path** → an intermediate state is now observable or persisted; on partial failure it can leave invalid/partial state (rollback / data-loss).
- **A removed, loosened, or inverted guard/conditional** → the path it blocked is now reachable; name what that exposes.
- **A rollback / cleanup / undo path** → does it RESTORE overwritten or pre-existing state, or does it `unlink`/clobber it? Deleting a destination that pre-existed is data loss, not rollback.
- **A documented count/name/inventory, a version bump, or a generated artifact (manifest, lockfile, sidecar)** → search the supplied repo state repo-wide for stale copies of the old value; for generated files, was the generator re-run and the output committed? (the documented-inventory / generated-artifact drift probe — see step 9).
- **A file/path enumeration (`git ls-files`, glob, walk)** → does it include entries it must not — tracked-but-deleted, ignored, suffix-variant, hidden?
- **A path check compared against `cwd` or a relative root** → should it anchor to the repo/project root? cwd-relative checks are bypassable from a subdirectory (security boundary).
- **A platform/OS branch (`sys.platform`, symlink-vs-copy, path separators, spaces in paths)** → is every branch's inverse/cleanup symmetric, and is each branch actually exercised?
- **A widened type/schema (bare `dict`/`Any`/`object`, new optional union, relaxed validation)** → does it weaken a previously-constrained contract or a published/derived schema into an unconstrained branch?
- **A retry / async / timeout / teardown / shutdown path** → idempotency across retries, poison-message parking, and teardown-after-assert that can raise and error a logically-passing test (cleanup flakiness).
- **A CI / merge-gate change (required checks, admin-merge, wait conditions)** → does it wait on ALL required checks (the full matrix), or can it proceed before some finish?
- **A weakened test assertion (substring/presence-only replacing exact/structural)** → would it still pass if the contract under test were removed? (tautology — a test-only-change SAFE-blocker).

The security-relevant surface, external-output, declared-invariant, and fence-parser probes are their own modules (`security-relevance`, `external-contract`, `contract-and-fence-probes`); load them when the diff shows that shape.

**Discovery → verdict (pinned).** A defect this sweep surfaces that the fresh tests do not cover is a NAMED RISK, mapped through the coverage ledger (step 9) as UNCOVERED. It is a SAFE-blocker → NOT SAFE TO MERGE. Do NOT demote a discovered latent defect to a "residual concern" under a SAFE verdict, and do NOT call it covered because a green test runs nearby — a green run that uses a happy fixture, ingests into an empty target, runs from the repo root, or hits only one platform/matrix leg does NOT cover the overwrite / deleted-entry / subdirectory / other-OS path. Treating it as coverage is the bypass that ships these defects; this demotion is the exact failure this pass exists to prevent.

The sweep produces 3–7 named risks, each citing a specific file + line + the domain meaning — NOT generic ("edge cases", "untested paths"). **Skip the sweep only for the trivial-change exemption below** (genuinely non-executable diffs — docs, and tool-only / static config with no runtime consumer); running it there manufactures phantom runtime risk, the negative-control failure mode. The sweep keys on **executable behaviour, not path prefix** (see the runtime-change definition in *Verdict-format discipline*): an executable hook/script/automation under `.claude/hooks/`, `scripts/`, or any non-`src/` location gets the same mandatory sweep as a library module.

## The two-pass split (step 10)

**The two-pass split (pinned).** In the `/work-issue` pipeline this review is pass 1; an adversarial codex pass runs after it. The catch this skill must NOT outsource: when it can name a precision/recall risk and the technique has a catalogued failure mode, it prescribes the discriminating input ITSELF (step 9 / 2b) — it does not defer that to codex. Pushing the catch into this phase is what makes the review scale when codex isn't available (CI-only runs, limited codex tokens). Codex remains a second independent check, never the only place an UNPROVEN risk gets a discriminating input.

## Red Flags

| Thought | Reality |
|---|---|
| "I spotted a latent issue but tests are green — SAFE, with a residual note" | The discovery sweep's hits are NAMED RISKS, not residual notes. A discovered defect the fresh tests don't exercise is UNCOVERED = NOT SAFE. Demoting it to a residual concern is the gap step 4 closes. |
| "I'll skip the discovery sweep — looks like a clean refactor" | The sweep is mandatory for any runtime diff. Codex-class defects (cwd bypass, rollback data-loss, schema widening, partial CI gate) hide in clean-looking diffs and pass green suites. Only genuinely non-executable diffs (docs / static config) are exempt. |
