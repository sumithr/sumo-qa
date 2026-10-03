# Reviewing before merge: adversarial discovery probes

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff touches any runtime (executable) file. **Extends:** checklist step 4 (adversarial discovery pass); the root's rules apply unchanged.

## Code-shape probes (step 4)

- **Reordered statements in a write/persist path** → an intermediate state is now observable or persisted; on partial failure it can leave invalid/partial state (rollback / data-loss).
- **A removed, loosened, or inverted guard/conditional** → the path it blocked is reachable; name what that exposes.
- **A rollback / cleanup / undo path** → does it RESTORE overwritten or pre-existing state, or does it `unlink`/clobber it? Deleting a destination that pre-existed is data loss, not rollback. Probe the whole path the diff touches, not the delta: an equivalent or tidier rewrite of a path that loses data still ships the loss.
- **A documented count/name/inventory, a version bump or dependency/tool/runtime constraint, or a generated artifact (manifest, lockfile, sidecar)** → search all supplied repo state, hidden config too, for stale copies (a constraint: `mirrored-constraints`, else `inventory-drift`); for generated files, was the generator re-run and the output committed?
- **A spawned tool that can inherit redirecting vars** (e.g. hooks and git wrappers can export an absolute `GIT_DIR`/`GIT_INDEX_FILE`, so any git they reach is exposed; `VIRTUAL_ENV`; `PYTHONPATH`/`PYTHONHOME`; `PATH`; its own config namespace, `PIP_*`, `UV_*`, `npm_config_*`) → `hermetic subprocess environment`: without an explicitly constructed env it hits the caller's repo, venv or config; only a test with them set to a throwaway value covers it. No hit only if it reads none of them, its own namespace included (`-I` strips only `PYTHON*`, `sys.executable` only `PATH`).
- **A file/path enumeration (`git ls-files`, glob, walk)** → does it include entries it must not — tracked-but-deleted, ignored, suffix-variant, hidden?
- **A path check compared against `cwd` or a relative root** → should it anchor to the repo/project root? cwd-relative checks are bypassable from a subdirectory (security boundary).
- **A platform/OS branch (`sys.platform`, symlink-vs-copy, path separators, spaces in paths)** → is every branch's inverse/cleanup symmetric, and is each branch actually exercised?
- **A widened type/schema (bare `dict`/`Any`/`object`, new optional union, relaxed validation)** → does it weaken a previously-constrained contract or a published/derived schema into an unconstrained branch?
- **A retry / async / timeout / teardown / shutdown path** → idempotency across retries, poison-message parking, and teardown-after-assert that raises and errors a passing test (cleanup flakiness).
- **A CI / merge-gate change (required checks, admin-merge, wait conditions)** → does it wait on ALL required checks (the full matrix), or can it proceed before some finish?
- **A weakened test assertion (substring/presence-only replacing exact/structural)** → would it still pass if the contract under test were removed? (tautology — a test-only-change SAFE-blocker).

The security-relevant surface, external-output, declared-invariant and fence-parser probes live in `security-relevance`, `external-contract` and `contract-and-fence-probes`, and a command/string classifier predicate takes the command/input-classifier probe in `runtime-scope`; load them when the diff shows that shape. A line/character loop storing or toggling open/close marker state (`inFence = !inFence`) always takes `contract-and-fence-probes`, in runtime code, test helper or eval assertion alike; a "fence-aware" comment is not proof.

**Discovery → verdict (pinned).** A defect this sweep surfaces that the fresh tests do not cover is a NAMED RISK, mapped through the coverage ledger (step 9) as UNPROVEN (with its 2b line) when path-matching fresh tests ran, even if the guard or behaviour is missing outright, and UNCOVERED only when none ran, exactly as `coverage-ledger` defines them. It is a SAFE-blocker → NOT SAFE TO MERGE. A defect the old code shared counts too: "pre-existing" or "not worsened by this diff" never demotes it, because SAFE certifies the changed path as it will ship, not the delta. Do NOT demote a discovered latent defect to a "residual concern" under a SAFE verdict, and do NOT call it COVERED because a green test runs nearby: a green run that uses a happy fixture, ingests into an empty target, runs from the repo root, or hits only one platform/matrix leg does NOT cover the overwrite / deleted-entry / subdirectory / other-OS path, yet when path-matching fresh tests ran it stays listed in that risk's row, which makes the row UNPROVEN, never UNCOVERED. This demotion is the exact failure this pass exists to prevent.

The sweep produces 3–7 named risks, each citing a specific file + line + the domain meaning, NOT generic ("edge cases", "untested paths"). **Skip the sweep only for the trivial-change exemption in `runtime-scope`**; running it there manufactures phantom runtime risk.

## The two-pass split (steps 4 and 9)

**The two-pass split (pinned).** In the `/work-issue` pipeline this review is pass 1; a second adversarial pass (`/code-review` in a context that did not write the code) follows. The catch this skill must NOT outsource: when it can name a precision/recall risk and the technique has a catalogued failure mode, it prescribes the discriminating input ITSELF (step 9 / 2b). The second pass is never the only source of that input.

## Red Flags

| Thought | Reality |
|---|---|
| "Latent issue, tests green, pre-existing: SAFE with a residual note" | A sweep hit is a NAMED RISK, UNPROVEN or UNCOVERED per `coverage-ledger`: NOT SAFE. |
| "Clean refactor: skip the sweep" | Mandatory for any runtime diff: cwd bypass, rollback data-loss, schema widening and partial CI gates hide in clean-looking diffs. |
