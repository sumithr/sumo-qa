#!/usr/bin/env bash
#
# Eval runner for the promptfoo skill-eval matrix. Two backends:
#
#   CLAUDE (default)     the Claude pair, through the local Claude Code CLI
#                        (providers/claude_cli.py -> `claude -p` on the account's
#                        subscription; no API key). Candidate claude-haiku-4-5
#                        (providers/claude-candidate.yaml), judge claude-opus-5
#                        (providers/claude-judge.yaml). This is the MERGE GATE.
#
#   LOCAL (via OpenWebUI proxy at $SUMO_OWUI_BASE): an unmetered iteration option,
#     NOT a merge gate. Promptfoo talks to ONE endpoint (OWUI); OWUI routes each
#     model id to the box that holds it (single-host tags) and applies model-level
#     params. We grade message.content only (showThinking:false) so a candidate can
#     REASON (body-faithful discrimination) while the judge sees a clean verdict.
#
# The OpenAI cloud backend was removed in #682 (epic #660 retired that gate);
# SUMO_EVAL_BACKEND=cloud now fails and names the valid backends.
#
#   The cheap-tier JUDGE is gemma4-12b-bounded (bounded Gemma 4 12B on the 5070 laptop),
#   picked by the 2026-06 judge/candidate bake-off: 92% absolute agreement with the
#   then-gate OpenAI judge gpt-5.5 (vs ~56% for the old reasoning-off qwen3.5:9b) and
#   binary-deterministic on fixed input. It reasons (think=medium), so it is slower per
#   grade than the old 9B; the instant reasoning-off sumo-cheap-judge-9b is still
#   available via SUMO_CHEAP_JUDGE if you need speed over fidelity.
#
#     cheap tier (configs WITHOUT the `# local-tier: reasoning` marker): candidate
#       gemma4-e4b-bounded (bounded Gemma 4 e4b) on the 4060; judge gemma4-12b-bounded
#       (bounded Gemma 4 12B) on the 5070 laptop. Bake-off winner (best 4060+laptop
#       pairing; the e4b candidate is the only 4060 model that lifts the hard
#       unproven-escalation control). => 4060 + laptop only. NEVER the 4090.
#
#     reasoning tier (configs WITH the `# local-tier: reasoning` marker, the ones the
#       OpenAI tier ran on its gpt-5-mini reasoning candidate): candidate =
#       gemma4-12b-bounded (OWUI workspace alias -> gemma4-12b-bounded:latest)
#       on the 5070 laptop; judge sumo-rjudge-20b (gpt-oss:20b, bigger + different
#       family, so JUDGE >= CANDIDATE) on the 4090.
#       => laptop + 4090. USES THE 4090: only run when the 4090 is free.
#
#     quality tier (ALL configs): the SAME laptop-candidate + 4090-judge pairing as the
#       reasoning tier, applied to EVERY skill-*.yaml. Highest local fidelity for when
#       the 4090 is free (both sides reason, so it's slow). => laptop + 4090.
#
# Why split: the 4090 is a personal machine. `eval:local:cheap` keeps off it;
# `eval:local:reasoning` and `eval:local:quality` are the paths that use it, so you choose when.
#
# Why Gemma 4 12B for the hard tier: it completed the bounded reasoning suite 5/5.
# The tuned Qwen 3.5 9B completed 4/5 and exhausted its output budget on the
# inconsistent-constraints case. The gpt-oss judge remains larger and cross-family.
# Models pinned 2026-06. Tags are single-host (OWUI routes by which box holds them).
# gemma4-12b-bounded is an OWUI workspace alias that persists think=medium and wraps the
# laptop-only gemma4-12b-bounded:latest tag (128k context, 4096-token output cap).
# Recreate tags with: ollama create <name> --from <base> (num_ctx as noted),
# and sumo-cheap-4b is an OWUI workspace model on sumo-cand-4b-32k with
# params.chat_template_kwargs.enable_thinking=false.
#
# Usage:
#   bash run-eval.sh                         # Claude pair, skill-implementing-with-tdd.yaml
#   bash run-eval.sh <config.yaml>           # Claude pair, one config
#   bash run-eval.sh all                     # Claude pair, every skill-*.yaml
#   SUMO_EVAL_BACKEND=local TIER=cheap     bash run-eval.sh        # 4060+laptop
#   SUMO_EVAL_BACKEND=local TIER=reasoning bash run-eval.sh        # laptop+4090 (marked configs)
#   SUMO_EVAL_BACKEND=local TIER=quality   bash run-eval.sh        # laptop+4090 (ALL configs)
#   (npm: eval / eval:all / eval:local:cheap / eval:local:reasoning / eval:local:quality)
#
#   SUMO_EVAL_DRY_RUN=1 prints each promptfoo command instead of running it (the CLI and
#   key-file preflights still run; no model is called), to check what a run resolves to.
#   Unset or empty is a real run; any other value is rejected, so `0` or `false` cannot
#   silently turn the gate into a run that calls no model.
#
# Exit codes (Claude backend):
#   0  every config ran and passed
#   1  a preflight or setting failed, or a config had failing test cases
#   3  ABORT: a readable report carried provider or judge errors (stats.errors > 0 or a
#      metadata.graderError); not a skill verdict
#   4  ERROR: promptfoo wrote no readable report (a missing config, malformed YAML, a
#      missing included file, an unwritable output); a harness or config error, not a
#      skill verdict and not a provider error
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
EVAL_DIR="$ROOT/tests/evals/promptfoo"
BACKEND="${SUMO_EVAL_BACKEND:-claude}"
REPEAT="${SUMO_EVAL_REPEAT:-3}"            # relative-lift signal -> repeat for variance
# Concurrency (-j): number of test cases in flight, 1 by default on both backends. Raising
# it does NOT help the single-GPU LOCAL tiers: -j>1 stacks several concurrent *reasoning*
# generations onto the one candidate GPU (and grades onto the one judge GPU), which thrashes
# them. Verified 2026-06-08: at -j3 the laptop reasoning candidate pegged and never finished a
# generation while the 4090 judge sat idle. The gen/grade host-overlap can't be isolated from
# same-GPU stacking via -j, so local stays 1. Override with SUMO_EVAL_CONCURRENCY.
CONCURRENCY="${SUMO_EVAL_CONCURRENCY:-1}"

PROMPTFOO="$ROOT/node_modules/.bin/promptfoo"
[ -x "$PROMPTFOO" ] || PROMPTFOO="promptfoo"

# SUMO_EVAL_DRY_RUN=1: print the promptfoo command (shell-quoted) instead of running it.
# Only the value 1 enables it; unset or empty is a real run; anything else stops here.
DRY_RUN="${SUMO_EVAL_DRY_RUN:-}"
case "$DRY_RUN" in
  ''|1) ;;
  *) echo "[eval] ERROR: SUMO_EVAL_DRY_RUN accepts only '1' (print the promptfoo commands); leave it unset or empty for a real run (got '$DRY_RUN')." >&2
     exit 1;;
esac
run_promptfoo() {
  if [ -n "$DRY_RUN" ]; then
    printf '[eval] dry-run:'; printf ' %q' "$PROMPTFOO" "$@"; printf '\n'
    return 0
  fi
  "$PROMPTFOO" "$@"
}

# OpenWebUI proxy + key are loaded by _owui-env.sh in the local branch below
# (single source shared with validate-local-judge/run.sh; key never echoed).

# Per-tier models (override via env if hardware moves). Cheap-tier models are the
# 2026-06 bake-off winners: gemma4-e4b candidate (4060) + gemma4-12b-bounded judge
# (laptop). gemma4-12b-bounded is also the reasoning/quality-tier CANDIDATE.
CHEAP_CAND="${SUMO_CHEAP_CANDIDATE:-gemma4-e4b-bounded}"        # bounded Gemma 4 e4b -> 4060 (bake-off winner)
CHEAP_JUDGE="${SUMO_CHEAP_JUDGE:-gemma4-12b-bounded}"           # bounded Gemma 4 12B -> laptop (92% agreement with the former gpt-5.5 gate)
REASON_CAND="${SUMO_REASON_CANDIDATE:-gemma4-12b-bounded}"      # OWUI alias -> bounded Gemma 4 12B on laptop
REASON_JUDGE="${SUMO_REASON_JUDGE:-sumo-rjudge-20b:latest}"     # gpt-oss:20b reasoning -> 4090
# QUALITY tier (see header): reasoning pairing applied to ALL skills.
QUALITY_CAND="${SUMO_QUALITY_CANDIDATE:-gemma4-12b-bounded}"    # OWUI alias -> bounded Gemma 4 12B on laptop
QUALITY_JUDGE="${SUMO_QUALITY_JUDGE:-sumo-rjudge-20b:latest}"   # gpt-oss:20b reasoning -> 4090
# Cheap-tier models picked by the 2026-06 judge/candidate bake-off (results gitignored;
# tooling in bakeoff/ + validate-local-judge/). Headline vs STORED gpt-5.5 verdicts:
# gemma4-12b-bounded judges at 92% absolute agreement and is binary-deterministic on fixed
# input; the gemma4-e4b candidate is the only 4060 model that lifts all three .ab control
# types. The rep-to-rep wobble is CANDIDATE-side (the e4b regenerates near the pass
# threshold at temp 0), so --repeat 3 majority is needed to settle it. Still a RELATIVE
# signal; the Claude pair is the merge gate. The 4090 gpt-oss:20b judge was tested and
# REJECTED for now (too strict: 0/3 separation, beaten by the laptop gemma12b) — revisit
# with a tuned 20B judge (showThinking:false may be clipping its analysis).

if [ "$BACKEND" = "claude" ]; then
  # Claude subscription via the local Claude Code CLI (providers/claude_cli.py): no API key.
  # One pass by default; set SUMO_EVAL_REPEAT for variance runs. With no argument this runs
  # the single default config; `all` runs the matrix.
  REPEAT="${SUMO_EVAL_REPEAT:-1}"
  command -v claude >/dev/null || { echo "[eval] ERROR: claude CLI not on PATH" >&2; exit 1; }
  echo "[eval] backend=CLAUDE (merge gate; subscription via claude -p)  repeat=$REPEAT  -j $CONCURRENCY"
  files=(); target="${1:-$EVAL_DIR/skill-implementing-with-tdd.yaml}"
  if [ "$target" = "all" ]; then
    for f in "$EVAL_DIR"/skill-*.yaml; do case "$f" in *.gen.yaml|*.generated-tests.yaml) continue;; esac; files+=("$f"); done
  else files=("$target"); fi
  REPORT_DIR="$ROOT/tests/evals/results/claude-reports"; mkdir -p "$REPORT_DIR"
  rc=0
  for f in "${files[@]}"; do
    # absolute: promptfoo runs from $EVAL_DIR. A missing directory is left for promptfoo to
    # report, so it lands in the no-readable-report branch below like a missing file.
    if d="$(cd "$(dirname "$f")" 2>/dev/null && pwd)"; then f="$d/$(basename "$f")"; fi
    base="$(basename "$f" .yaml)"; out_json="$REPORT_DIR/${base}.json"
    echo "── $base   → report: $out_json"
    [ -n "$DRY_RUN" ] || rm -f "$out_json"   # a stale report must not pass the error check below for a crashed run
    # provider paths (providers/claude_cli.py) resolve against the eval dir
    pf_rc=0
    ( cd "$EVAL_DIR" && run_promptfoo eval -c "$f" --no-cache \
        --providers "file://$EVAL_DIR/providers/claude-candidate.yaml" \
        --grader "file://$EVAL_DIR/providers/claude-judge.yaml" \
        --repeat "$REPEAT" -j "$CONCURRENCY" --output "$out_json" ) || pf_rc=$?
    [ "$pf_rc" = 0 ] || rc=1
    [ -z "$DRY_RUN" ] || continue
    # No readable report means promptfoo stopped before grading anything: nothing to
    # classify as a provider error or a skill verdict. Exit 4, not the ABORT code.
    # A report with no results at all is the same case (no test case ran).
    # A provider error (usage limit, quota, CLI failure) stops the run: an error is not a
    # skill verdict, and reporting it as one is the #651 failure. promptfoo
    # counts a candidate-side error in stats.errors, but a JUDGE that fails or returns no
    # parseable verdict becomes a failed assertion tagged metadata.graderError, so count
    # those too.
    errors=$(node -e '
      let r;
      try { r = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).results; }
      catch (e) { console.log("unreadable"); process.exit(0); }
      if (!r || !Array.isArray(r.results) || !r.results.length || !r.stats) {
        console.log("unreadable"); process.exit(0);
      }
      const graderErrors = r.results
        .flatMap((x) => (x.gradingResult && x.gradingResult.componentResults) || [])
        .filter((c) => c.metadata && c.metadata.graderError).length;
      console.log((Number(r.stats.errors) || 0) + graderErrors);' "$out_json" 2>/dev/null || echo unreadable)
    if [ "$errors" = unreadable ]; then
      echo "[eval] ERROR: $f produced no readable report (promptfoo exit $pf_rc); harness or config error, not a skill verdict and not a provider error. Check the config path and its YAML in the promptfoo output above." >&2
      exit 4
    fi
    if [ "$errors" != 0 ]; then
      echo "[eval] ABORT: $base had provider or judge errors (errors=$errors); see $out_json. Not a skill verdict." >&2
      exit 3
    fi
  done
  exit "$rc"
fi

[ "$BACKEND" = "local" ] || {
  echo "[eval] ERROR: SUMO_EVAL_BACKEND must be claude|local (got '$BACKEND'). The OpenAI cloud backend was removed; the Claude pair (default) is the merge gate." >&2
  exit 1
}

TIER="${TIER:-cheap}"
# shellcheck source=/dev/null
. "$EVAL_DIR/_owui-env.sh" || exit 1            # sets OWUI_BASE + OPENWEBUI_API_KEY
export OPENAI_API_KEY="$OPENWEBUI_API_KEY"      # promptfoo's openai provider reads this
export OPENAI_BASE_URL="$OWUI_BASE"
# Prevent promptfoo from deferring all model-graded assertions until candidate
# generation completes. A generous per-row timeout keeps the judge active between
# candidate rows without raising same-GPU candidate concurrency above 1.
export PROMPTFOO_EVAL_TIMEOUT_MS="${PROMPTFOO_EVAL_TIMEOUT_MS:-600000}"

# tier -> models + file filter + box note
case "$TIER" in
  cheap)
    CAND="$CHEAP_CAND"; JUDGE="$CHEAP_JUDGE"; FILTER='cheap'
    echo "[eval] backend=LOCAL tier=CHEAP  (4060 + laptop — NO 4090)";;
  reasoning)
    CAND="$REASON_CAND"; JUDGE="$REASON_JUDGE"; FILTER='reasoning'
    echo "[eval] backend=LOCAL tier=REASONING  (laptop + 4090 — USES THE 4090)";;
  quality)
    CAND="$QUALITY_CAND"; JUDGE="$QUALITY_JUDGE"; FILTER='all'
    echo "[eval] backend=LOCAL tier=QUALITY  (laptop candidate + 4090 judge, ALL skills — USES THE 4090)";;
  *) echo "[eval] ERROR: TIER must be cheap|reasoning|quality (got '$TIER')" >&2; exit 1;;
esac
echo "[eval]   candidate=$CAND  judge=$JUDGE  via OWUI $OWUI_BASE  repeat=$REPEAT"
echo "[eval]   NOT a merge gate: relative lift only; the Claude pair (npm run eval) is the gate."

# select files for this tier: quality = ALL; reasoning = configs carrying the `# local-tier: reasoning`
# marker line (the configs the removed OpenAI tier ran on its gpt-5-mini candidate); cheap = the rest
files=()
for f in "$EVAL_DIR"/skill-*.yaml; do
  case "$f" in *.gen.yaml|*.generated-tests.yaml) continue;; esac
  # anchored at line start, so prose that merely mentions the marker does not select a config
  if grep -qE '^# local-tier: reasoning( |$)' "$f"; then is_reason=1; else is_reason=0; fi
  if [ "$FILTER" = all ] \
     || { [ "$FILTER" = reasoning ] && [ "$is_reason" = 1 ]; } \
     || { [ "$FILTER" = cheap ] && [ "$is_reason" = 0 ]; }; then
    files+=("$f")
  fi
done
[ "${1:-}" != "" ] && [ "${1:-}" != "all" ] && files=("$1")   # allow one explicit file

# candidate + judge provider files (showThinking:false -> grade clean content)
CAND_PF="$(mktemp -t sumo-cand-XXXX).yaml"; JUDGE_PF="$(mktemp -t sumo-judge-XXXX).yaml"
trap 'rm -f "$CAND_PF" "$JUDGE_PF"' EXIT
cat > "$CAND_PF" <<YAML
- id: openai:chat:$CAND
  config:
    apiBaseUrl: $OWUI_BASE
    showThinking: false
    temperature: 0
    seed: 42
    max_tokens: 16000
YAML
cat > "$JUDGE_PF" <<YAML
id: openai:chat:$JUDGE
config:
  apiBaseUrl: $OWUI_BASE
  showThinking: false
  temperature: 0
  max_tokens: 8000
YAML

# --- preload: Ollama unloads idle models (~5-min keep-alive), so the first eval
#     call cold-starts and can stall long enough to look like a hang. Warm this
#     tier's models via OWUI BEFORE promptfoo runs, and abort LOUDLY if one won't
#     load (better a clear error than promptfoo sitting on a dead model). ---
warm() {
  echo "[eval]   warming $1 ..."
  local code
  code=$(curl -s --max-time 240 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $OPENAI_API_KEY" -H 'Content-Type: application/json' \
    "$OWUI_BASE/chat/completions" \
    -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"warmup\"}],\"max_tokens\":1}")
  if [ "$code" = 200 ]; then echo "[eval]   $1 ready"; else
    echo "[eval] ERROR: $1 failed to load via OWUI (HTTP $code) — fix before running" >&2; return 1
  fi
}
if [ -z "$DRY_RUN" ]; then
  warm "$CAND"  || exit 1
  warm "$JUDGE" || exit 1
fi

# Per-run readable reports (gitignored) — open the .html in a browser, or run
# `npm run eval:view` for the interactive UI over ALL past runs.
REPORT_DIR="$ROOT/tests/evals/results/local-reports"; mkdir -p "$REPORT_DIR"

rc=0
for f in "${files[@]}"; do
  base="$(basename "$f" .yaml)"
  out_html="$REPORT_DIR/${base}.${TIER}.html"
  out_json="$REPORT_DIR/${base}.${TIER}.json"
  echo "── $base   → report: $out_html"
  run_promptfoo eval -c "$f" --no-cache \
    --providers "file://$CAND_PF" --grader "file://$JUDGE_PF" \
    --repeat "$REPEAT" -j "$CONCURRENCY" \
    --output "$out_html" "$out_json" || rc=1
done
echo "[eval] reports in $REPORT_DIR (HTML + JSON, gitignored). Interactive: npm run eval:view"
exit "$rc"
