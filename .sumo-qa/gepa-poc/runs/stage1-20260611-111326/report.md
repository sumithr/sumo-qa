# GEPA POC — Stage 1 Trajectory Report (2026-06-11)

## Headline
GEPA works end-to-end against the real promptfoo harness, and its first full stage
delivered the POC's most important finding: **the smoke winner's −29.5% was
over-compression.** Stage 1 traded tokens back for behaviour — best candidate is now
**13,491 tokens (−13.9%)** with measurably better quality than the −29.5% seed, but still
below the ORIGINAL skill's quality bar in this regime. The 50% bar is not reachable by
naive whole-document evolution without quality loss; the honest frontier so far sits
between −14% and −29%, closer to −14%.

## Candidate pool (21 metric calls, 6 mutation rounds, 1 promotion)
| Candidate | Tokens | vs orig | Valset (core/verifier/.ab) | Agg |
|---|---|---|---|---|
| ORIGINAL skill (reference) | 15,664 | — | 0.75 / 0.231 / 0.333 (repeat-1, smoke) | **0.389** |
| P0 = seed (smoke winner) | 11,041 | −29.5% | 0.0 / 0.231 / 0.333 | 0.188 |
| **P1 = stage-1 best (iter 5)** | **13,491** | **−13.9%** | 0.0 / **0.486** / 0.333 | **0.273** |
| P2 (iter 6, diversity) | ~13.5k | — | 0.0 / 0.0 / 0.333 | 0.111 |

P1 recovered **unproven-escalation** (the suite's hardest control: 0.0 → 0.819) and
doubled verifier-evidence. Core remains 0.0 for every candidate INCLUDING P0/P1 in this
regime (the original passes it; regime question flagged below).

## Seed damage map (what −29.5% actually lost — parent scores observed in-epoch)
- doc-drift: 0.0 (orig 0.898) — cause identified: compression deleted the WORKED EXAMPLE
  (orig lines ~147–150) while keeping the rules. Examples pin output shape = load-bearing.
- mapping-gap: 0.0
- unproven-escalation: 0.0 (recovered by P1)
- feedback-memory: 0.398 (1/2 tests)
- repo-map: 0.898 (pass); one further file pass (near-miss round, lost by 0.004 penalty)

## Mutation ledger
6 reflections, all well-formed (0 validator retries — last night's brief-instead-of-skill
bug did not recur under the hardened wrapper). 4 rejections (2 destructive probes, 1
no-gradient round, 1 penalty near-miss), 2 minibatch wins, 1 full promotion (P1).

## Infra ledger
- Laptop: 1 sleep (night), 1 self-reboot (13:46) — combined ~1h of dead time + redos. The
  reboot looked like an auto-update restart; worth disabling for long runs.
- Overnight quota outage burned a full 20-call run proposing nothing (gepa swallows
  reflection exceptions) → reflection now blocks-and-waits through outages.
- Watchdog: 3 lives used across the day, every recovery automatic (fastest: 14s).
- Defects caught by the staged gates before they could waste a long run: 7 total
  (clipped 20b judge, prompts-axis .ab parsing, over-strict floor ×2, missing mirror
  dirs, reflection brief-not-skill, error-rows-scored-as-fails) + 1 self-inflicted
  (mid-run GPU probe poisoned a reference — fleet GPUs are read-only during runs, now in
  permanent memory).
- proposals.md: empty (no rubric-tightening suggestions emerged).
- drift-ledger: 1 singleton ablation pass all day (judge wobble at the measured ~3%/row).

## Rebase note
PR #392 merged into main during the run (+6 lines to the live SKILL.md, scorecard).
All POC artifacts reference the pre-#392 text (sha 33c0643…). Any adoption/extension must
rebase the winning edits onto current main and check whether #392 added eval files.

## Open regime question
Core instance: original passes (0.75–0.898) under the same candidate/judge in smoke-era
runs, but every stage-1-era measurement of compressed candidates scores it 0.0
deterministically. Repeat-3 confirm on P1 (and the original, same session) settles
whether this is candidate damage or a regime artifact — required before any cloud gate.

## Options (user decision — per protocol nothing runs without a go)
A. **Extension per protocol**: re-seed from P1, 50% target, reflection preamble gains the
   worked-example-preservation rule. Local ~3–5h free; or cloud inner loop ~1.5–2h,
   ~$5–20 + ~$2–5 fresh cloud anchors (gate independence inverts to the local tier).
B. **Hybrid surgical** (likely fastest to a defensible candidate): hand-restore the
   identified missing pieces onto P1 (doc-drift worked example + mapping-gap material),
   repeat-3 confirm, then a short GEPA polish run for size.
C. **Stop and bank**: report stands — GEPA validated mechanically; −29.5% was illusory;
   honest frontier ≥ −14% so far; per-use skill body cost was previously measured as
   acceptable, so further compression investment may not pay.
