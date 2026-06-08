#!/usr/bin/env bash
#
# Eval runner: cloud (authoritative) OR local-via-OpenWebUI, SPLIT into two tiers
# so the 4090 is only touched when you run the high-reasoning checks.
#
#   CLOUD (default)      each skill-*.yaml's pinned OpenAI models (gpt-4o-mini /
#                        gpt-5-mini candidate, gpt-5.5 judge). The MERGE GATE.
#
#   LOCAL (via OpenWebUI proxy at $SUMO_OWUI_BASE) — NOT merge-authoritative.
#     Promptfoo talks to ONE endpoint (OWUI); OWUI routes each model id to the
#     box that holds it (single-host tags) and applies model-level params. We
#     grade message.content only (showThinking:false) so a candidate can REASON
#     (body-faithful discrimination) while the judge sees a clean verdict.
#
#   The cheap-tier JUDGE is gemma4-12b-bounded (bounded Gemma 4 12B on the 5070 laptop),
#   picked by the 2026-06 judge/candidate bake-off: 92% absolute agreement with cloud
#   gpt-5.5 (vs ~56% for the old reasoning-off qwen3.5:9b) and binary-deterministic on
#   fixed input. It reasons (think=medium), so it is slower per grade than the old 9B —
#   the instant reasoning-off sumo-cheap-judge-9b is still available via SUMO_CHEAP_JUDGE
#   if you need speed over fidelity.
#
#     cheap tier  (gpt-4o-mini files): candidate gemma4-e4b-bounded (bounded Gemma 4 e4b)
#       on the 4060; judge gemma4-12b-bounded (bounded Gemma 4 12B) on the 5070 laptop.
#       Bake-off winner (best 4060+laptop pairing vs gpt-5.5; the e4b candidate is the
#       only 4060 model that lifts the hard unproven-escalation control). => 4060 + laptop
#       only. NEVER the 4090. Run any time (gemma12b reasons -> slower than the old 9B).
#
#     reasoning tier (gpt-5-mini files + .ab controls): candidate =
#       gemma4-12b-bounded (OWUI workspace alias -> gemma4-12b-bounded:latest)
#       on the 5070 laptop; judge sumo-rjudge-20b (gpt-oss:20b — bigger + different
#       family, so JUDGE >= CANDIDATE) on the 4090.
#       => laptop + 4090. USES THE 4090 — only run when the 4090 is free.
#
#     quality tier (ALL skills): the SAME laptop-candidate + 4090-judge pairing as the
#       reasoning tier, but applied to EVERY skill-*.yaml — highest fidelity for when the
#       4090 is free (both sides reason, so it's slow). Candidate gemma4-12b-bounded; judge
#       sumo-rjudge-20b. => laptop + 4090. USES THE 4090 — only run when it's free.
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
#   bash run-eval.sh                         # cloud, default single file
#   bash run-eval.sh all                     # cloud, every skill-*.yaml
#   SUMO_EVAL_BACKEND=local TIER=cheap     bash run-eval.sh        # 4060+laptop
#   SUMO_EVAL_BACKEND=local TIER=reasoning bash run-eval.sh        # laptop+4090 (gpt-5-mini files)
#   SUMO_EVAL_BACKEND=local TIER=quality   bash run-eval.sh        # laptop+4090 (ALL skills)
#   (npm: eval:local:cheap / eval:local:reasoning / eval:local:quality)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
EVAL_DIR="$ROOT/tests/evals/promptfoo"
BACKEND="${SUMO_EVAL_BACKEND:-cloud}"
REPEAT="${SUMO_EVAL_REPEAT:-3}"            # relative-lift signal -> repeat for variance
# Concurrency (-j): number of test cases in flight. Raising it does NOT help the single-GPU
# LOCAL tiers: -j>1 stacks several concurrent *reasoning* generations onto the one candidate
# GPU (and grades onto the one judge GPU), which thrashes them. Verified 2026-06-08: at -j3 the
# laptop reasoning candidate pegged and never finished a generation while the 4090 judge sat
# idle. The gen/grade host-overlap can't be isolated from same-GPU stacking via -j, so local
# stays 1. Cloud has no single-GPU limit (OpenAI fleet) -> default 4 (= promptfoo's own eval
# default), bounded only by the OpenAI rate-limit (429), not compute.
if [ "$BACKEND" = cloud ]; then CONCURRENCY="${SUMO_EVAL_CONCURRENCY:-4}"; else CONCURRENCY="${SUMO_EVAL_CONCURRENCY:-1}"; fi

PROMPTFOO="$ROOT/node_modules/.bin/promptfoo"
[ -x "$PROMPTFOO" ] || PROMPTFOO="promptfoo"

# OpenWebUI proxy + key are loaded by _owui-env.sh in the local branch below
# (single source shared with validate-local-judge/run.sh; key never echoed).

# Per-tier models (override via env if hardware moves). Cheap-tier models are the
# 2026-06 bake-off winners: gemma4-e4b candidate (4060) + gemma4-12b-bounded judge
# (laptop). gemma4-12b-bounded is also the reasoning/quality-tier CANDIDATE.
CHEAP_CAND="${SUMO_CHEAP_CANDIDATE:-gemma4-e4b-bounded}"        # bounded Gemma 4 e4b -> 4060 (bake-off winner)
CHEAP_JUDGE="${SUMO_CHEAP_JUDGE:-gemma4-12b-bounded}"           # bounded Gemma 4 12B -> laptop (92% gpt-5.5 agreement)
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
# signal; cloud (gpt-5.5) stays the merge gate. The 4090 gpt-oss:20b judge was tested and
# REJECTED for now (too strict: 0/3 separation, beaten by the laptop gemma12b) — revisit
# with a tuned 20B judge (showThinking:false may be clipping its analysis).

if [ "$BACKEND" = "cloud" ]; then
  echo "[eval] backend=CLOUD (OpenAI pinned models — authoritative merge gate)"
  files=(); target="${1:-$EVAL_DIR/skill-implementing-with-tdd.yaml}"
  if [ "$target" = "all" ]; then
    for f in "$EVAL_DIR"/skill-*.yaml; do case "$f" in *.gen.yaml) continue;; esac; files+=("$f"); done
  else files=("$target"); fi
  rc=0; for f in "${files[@]}"; do echo "── $f"; "$PROMPTFOO" eval -c "$f" --no-cache -j "$CONCURRENCY" || rc=1; done
  exit "$rc"
fi

[ "$BACKEND" = "local" ] || { echo "[eval] ERROR: SUMO_EVAL_BACKEND must be cloud|local" >&2; exit 1; }

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
echo "[eval]   NOT merge-authoritative — relative lift only; cloud stays the gate."

# select files for this tier: quality = ALL; reasoning = pins gpt-5-mini (discovery + .ab); cheap = the rest
files=()
for f in "$EVAL_DIR"/skill-*.yaml; do
  case "$f" in *.gen.yaml|*.generated-tests.yaml) continue;; esac
  if grep -q 'gpt-5-mini' "$f"; then is_reason=1; else is_reason=0; fi
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
warm "$CAND"  || exit 1
warm "$JUDGE" || exit 1

# Per-run readable reports (gitignored) — open the .html in a browser, or run
# `npm run eval:view` for the interactive UI over ALL past runs.
REPORT_DIR="$ROOT/tests/evals/results/local-reports"; mkdir -p "$REPORT_DIR"

rc=0
for f in "${files[@]}"; do
  base="$(basename "$f" .yaml)"
  out_html="$REPORT_DIR/${base}.${TIER}.html"
  out_json="$REPORT_DIR/${base}.${TIER}.json"
  echo "── $base   → report: $out_html"
  "$PROMPTFOO" eval -c "$f" --no-cache \
    --providers "file://$CAND_PF" --grader "file://$JUDGE_PF" \
    --repeat "$REPEAT" -j "$CONCURRENCY" \
    --output "$out_html" "$out_json" || rc=1
done
echo "[eval] reports in $REPORT_DIR (HTML + JSON, gitignored). Interactive: npm run eval:view"
exit "$rc"
