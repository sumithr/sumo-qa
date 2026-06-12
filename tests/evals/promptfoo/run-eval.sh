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
#   Models are the `pi-*` raw single-host Ollama tags from the 2026-06-09 pi gen/grade
#   experiment — the validated best candidate/judge balance. Raw tags (not OWUI
#   workspace aliases) so a vanished alias can't break the tier; each bakes bounded
#   num_ctx/num_predict in its modelfile.
#
#     cheap tier  (gpt-4o-mini files): candidate pi-qwen35-4b-32k (Qwen3.5 4b, 32k ctx)
#       on the 4060; judge pi-gemma4-12b-16k (Gemma 4 12B, 16k ctx) on the 5070 laptop.
#       Cross-family pairing, JUDGE > CANDIDATE. => 4060 + laptop
#       only. NEVER the 4090. Run any time.
#
#     reasoning tier (gpt-5-mini files + .ab controls): candidate =
#       pi-gemma4-12b-16k (Gemma 4 12B) on the 5070 laptop; judge pi-gpt-oss-20b-16k
#       (gpt-oss:20b — bigger + different family, so JUDGE >= CANDIDATE) on the 4090.
#       => laptop + 4090. USES THE 4090 — only run when the 4090 is free.
#
#     quality tier (ALL skills): the SAME laptop-candidate + 4090-judge pairing as the
#       reasoning tier, but applied to EVERY skill-*.yaml — highest fidelity for when the
#       4090 is free (both sides reason, so it's slow). Candidate pi-gemma4-12b-16k; judge
#       pi-gpt-oss-20b-16k. => laptop + 4090. USES THE 4090 — only run when it's free.
#
# Why split: the 4090 is a personal machine. `eval:local:cheap` keeps off it;
# `eval:local:reasoning` and `eval:local:quality` are the paths that use it, so you choose when.
#
# Models pinned 2026-06-12 (pi experiment pairing; judge pi-gpt-oss-20b-16k graded the
# 2026-06-10 reviewing-before-merge reasoning runs). Tags are single-host (OWUI routes
# by which box holds them). Recreate with: ollama create <name> --from <base>
# (PARAMETER num_ctx/num_predict per the -16k/-32k suffix) on the host noted above.
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

# Per-tier models (override via env if hardware moves). Pinned 2026-06-12 to the
# `pi-*` raw single-host Ollama tags from the pi gen/grade experiment — the pairing
# the user validated as the best candidate/judge balance. Raw tags also remove the
# OWUI *workspace-alias* dependency: the `gemma4-12b-bounded` alias silently vanished
# from OWUI ("Model not found" while still listed), which broke every cheap-tier run;
# a raw tag routes as long as its host is up. Each pi tag bakes bounded params in its
# modelfile (num_ctx/num_predict); the provider configs below still force temp 0.
CHEAP_CAND="${SUMO_CHEAP_CANDIDATE:-pi-qwen35-4b-32k:latest}"     # Qwen3.5 4b, 32k ctx -> 4060
CHEAP_JUDGE="${SUMO_CHEAP_JUDGE:-pi-gemma4-12b-16k:latest}"       # Gemma 4 12B, 16k ctx -> laptop
REASON_CAND="${SUMO_REASON_CANDIDATE:-pi-gemma4-12b-16k:latest}"  # Gemma 4 12B, 16k ctx -> laptop
REASON_JUDGE="${SUMO_REASON_JUDGE:-pi-gpt-oss-20b-16k:latest}"    # gpt-oss:20b, 16k ctx -> 4090
# QUALITY tier (see header): reasoning pairing applied to ALL skills.
QUALITY_CAND="${SUMO_QUALITY_CANDIDATE:-pi-gemma4-12b-16k:latest}"  # Gemma 4 12B -> laptop
QUALITY_JUDGE="${SUMO_QUALITY_JUDGE:-pi-gpt-oss-20b-16k:latest}"    # gpt-oss:20b -> 4090
# History: the 2026-06 bake-off (tooling in bakeoff/ + validate-local-judge/, results
# gitignored) picked gemma4-e4b (4060 candidate) + gemma4-12b-bounded (laptop judge,
# 92% gpt-5.5 agreement) via OWUI workspace aliases; the 2026-06-09 pi experiment then
# proved candidate-host and judge-host run concurrently and settled the pi-tag pairing
# above (judge pi-gpt-oss-20b-16k graded the 2026-06-10 reviewing-before-merge runs).
# Candidate-side rep-to-rep wobble near the pass threshold remains -> keep --repeat 3
# majority. Still a RELATIVE signal; cloud (gpt-5.5) stays the merge gate.

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

# select files for this tier: quality = ALL; reasoning = pins gpt-5-mini OR the cloud-reasoning-candidate
# provider (the provider extraction moved gpt-5-mini out of the .ab configs into the file); cheap = the rest
files=()
for f in "$EVAL_DIR"/skill-*.yaml; do
  case "$f" in *.gen.yaml|*.generated-tests.yaml) continue;; esac
  # anchor on the provider id / file, not a bare 'gpt-5-mini' — a cheap config can mention
  # gpt-5-mini in a COMMENT (e.g. skill-implementing-with-tdd.yaml) and must stay cheap.
  if grep -qE 'openai:chat:gpt-5-mini|cloud-reasoning-candidate' "$f"; then is_reason=1; else is_reason=0; fi
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
