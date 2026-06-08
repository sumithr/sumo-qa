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
#   The 5070 laptop hosts the 9B models. The cheap-tier JUDGE is sumo-cheap-judge-9b
#   (qwen3.5:9b, enable_thinking:false -> reasoning OFF, ~3.5s/grade). Reasoning-ON on
#   the 9B was validated and REJECTED for the cheap tier (2026-06-06): it returns the
#   SAME verdict ~25-40x slower (90-140s/grade, 25-40k reasoning chars; OWUI strips
#   max_tokens so the spiral can't be bounded) WITHOUT closing the gap to cloud gpt-5.5
#   (~56% agreement either way). Reasoning grading lives in the reasoning tier instead.
#
#     cheap tier  (gpt-4o-mini files): candidate sumo-cheap-4b (qwen3.5:4b with
#       enable_thinking:false baked into an OWUI workspace model -> reasoning OFF,
#       instant) on the 4060; judge sumo-cheap-judge-9b (qwen3.5:9b, reasoning OFF)
#       on the 5070 laptop. => 4060 + laptop only. NEVER the 4090. Run any time.
#
#     reasoning tier (gpt-5-mini files + .ab controls): candidate = sumo-rcand-9b
#       on the 5070 laptop; judge sumo-rjudge-20b (gpt-oss:20b — bigger + different
#       family, so JUDGE >= CANDIDATE) on the 4090.
#       => laptop + 4090. USES THE 4090 — only run when the 4090 is free.
#
#     quality tier (ALL skills): the SAME laptop-candidate + 4090-judge pairing as the
#       reasoning tier, but applied to EVERY skill-*.yaml — highest fidelity for when the
#       4090 is free (both sides reason, so it's slow). Candidate sumo-rcand-9b (override
#       SUMO_QUALITY_CANDIDATE=sumo-rcand-14b:latest if the laptop holds it); judge
#       sumo-rjudge-20b. => laptop + 4090. USES THE 4090 — only run when it's free.
#
# Why split: the 4090 is a personal machine. `eval:local:cheap` keeps off it;
# `eval:local:reasoning` and `eval:local:quality` are the paths that use it, so you choose when.
#
# Why a 9B reasoner (not the 4B) for the hard tier: the 4B reliably stalls in the
# thinking channel and never emits the verdict on the hardest discovery prompts.
# The 9B delivers a clean verdict; gpt-oss judge (>= candidate) catches its slips.
# Models pinned 2026-06. Tags: sumo-* are single-host (OWUI routes by which box
# holds them). Recreate with: ollama create <name> --from <base> (num_ctx as noted),
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

PROMPTFOO="$ROOT/node_modules/.bin/promptfoo"
[ -x "$PROMPTFOO" ] || PROMPTFOO="promptfoo"

# OpenWebUI proxy + key are loaded by _owui-env.sh in the local branch below
# (single source shared with validate-local-judge/run.sh; key never echoed).

# Per-tier models (override via env if hardware moves). The cheap-tier JUDGE is the
# non-reasoning qwen3.5:9b (sumo-cheap-judge-9b, enable_thinking:false baked into an
# OWUI workspace model). The reasoning 9B (sumo-rcand-9b) is the reasoning-tier CANDIDATE.
CHEAP_CAND="${SUMO_CHEAP_CANDIDATE:-sumo-cheap-4b}"             # OWUI model, reasoning OFF -> 4060
CHEAP_JUDGE="${SUMO_CHEAP_JUDGE:-sumo-cheap-judge-9b}"          # qwen3.5:9b reasoning OFF -> laptop (fast verdict)
REASON_CAND="${SUMO_REASON_CANDIDATE:-sumo-rcand-9b:latest}"    # reasoning 9B -> laptop
REASON_JUDGE="${SUMO_REASON_JUDGE:-sumo-rjudge-20b:latest}"     # gpt-oss:20b reasoning -> 4090
# QUALITY tier (see header): reasoning pairing applied to ALL skills; override candidate to
# sumo-rcand-14b:latest if the laptop holds it.
QUALITY_CAND="${SUMO_QUALITY_CANDIDATE:-sumo-rcand-9b:latest}"  # laptop reasoning candidate
QUALITY_JUDGE="${SUMO_QUALITY_JUDGE:-sumo-rjudge-20b:latest}"   # gpt-oss:20b reasoning -> 4090
# Why thinking OFF (this is BOUNDED reasoning, not "no reasoning") — validated 2026-06-06
# vs STORED gpt-5.5 verdicts. enable_thinking:false keeps the judge's A/B/C analysis +
# score in the OUTPUT channel (bounded, ~3.5s, always a parseable verdict); it only drops
# the <think> channel, which on the 9B spirals 90-140s / 25-40k chars and CANNOT be bounded
# (OWUI strips max_tokens; native num_predict truncates to empty; brevity directives are
# ignored) AND yields the SAME verdict anyway — so it is pure cost. Decent enough for eval
# testing: on gpt-5.5-SEPARATED A0/A1 pairs the bounded judge ranks A1>A0 ~83% and keeps the
# pass/fail split ~75% (the lift signal — use --repeat 3 to settle variance). Absolute cloud
# agreement is ~56%, which is FINE: the cheap tier is a RELATIVE signal and cloud (gpt-5.5)
# stays the merge gate. Heavyweight reasoning grading lives in the reasoning tier (4090).

if [ "$BACKEND" = "cloud" ]; then
  echo "[eval] backend=CLOUD (OpenAI pinned models — authoritative merge gate)"
  files=(); target="${1:-$EVAL_DIR/skill-implementing-with-tdd.yaml}"
  if [ "$target" = "all" ]; then
    for f in "$EVAL_DIR"/skill-*.yaml; do case "$f" in *.gen.yaml) continue;; esac; files+=("$f"); done
  else files=("$target"); fi
  rc=0; for f in "${files[@]}"; do echo "── $f"; "$PROMPTFOO" eval -c "$f" --no-cache || rc=1; done
  exit "$rc"
fi

[ "$BACKEND" = "local" ] || { echo "[eval] ERROR: SUMO_EVAL_BACKEND must be cloud|local" >&2; exit 1; }

TIER="${TIER:-cheap}"
# shellcheck source=/dev/null
. "$EVAL_DIR/_owui-env.sh" || exit 1            # sets OWUI_BASE + OPENWEBUI_API_KEY
export OPENAI_API_KEY="$OPENWEBUI_API_KEY"      # promptfoo's openai provider reads this
export OPENAI_BASE_URL="$OWUI_BASE"

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
    --repeat "$REPEAT" -j 1 \
    --output "$out_html" "$out_json" || rc=1
done
echo "[eval] reports in $REPORT_DIR (HTML + JSON, gitignored). Interactive: npm run eval:view"
exit "$rc"
