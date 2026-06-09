#!/usr/bin/env bash
# Bake-off: rank (4060 candidate, laptop judge) combos by closeness to the gpt-defined
# A0-FAIL/A1-PASS split on the binary-lift .ab controls. Judge-OUTER so each laptop judge
# loads once and is reused across both candidates; candidate (4060) and judge (laptop/4090)
# are always on different boxes, so grading overlaps generation. NOT merge-authoritative.
#
# Usage:  bash run-bakeoff.sh            # full 8-combo matrix over the 3 lift controls
#         CONTROLS_ONLY=fence bash run-bakeoff.sh   # smoke: fence-parser only
#         JUDGES_ONLY=qwen9b-roff CANDS_ONLY=gemma4-e4b bash run-bakeoff.sh  # single combo
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
EVAL_DIR="$ROOT/tests/evals/promptfoo"
OUT="$ROOT/tests/evals/results/bakeoff"; mkdir -p "$OUT"
# shellcheck source=/dev/null
. "$EVAL_DIR/_owui-env.sh"
export OPENAI_API_KEY="$OPENWEBUI_API_KEY" OPENAI_BASE_URL="$OWUI_BASE"
export PROMPTFOO_EVAL_TIMEOUT_MS="${PROMPTFOO_EVAL_TIMEOUT_MS:-600000}"
PF="$ROOT/node_modules/.bin/promptfoo"; [ -x "$PF" ] || PF=promptfoo
REPEAT="${SUMO_EVAL_REPEAT:-3}"

CONTROLS=(
  skill-reviewing-before-merge-fence-parser
  skill-reviewing-before-merge-runtime-scope
  skill-reviewing-before-merge-unproven-escalation
)
# label|candidate-provider-file
CANDIDATES=(
  "gemma4-e4b|providers/local-4060-gemma-candidate.yaml"
  "qwen35-4b|providers/local-4060-qwen-candidate.yaml"
)
# label|judge-provider-file|owui-model-to-warm
JUDGES=(
  "qwen9b-roff|providers/local-laptop-qwen-judge.yaml|sumo-cheap-judge-9b"
  "gemma12b|providers/local-laptop-gemma-judge.yaml|gemma4-12b-bounded"
  "qwen9b-bounded|providers/local-laptop-qwen-bounded-judge.yaml|qwen3.5-9b-bounded:latest"
  "gptoss20b-4090|providers/local-4090-judge.yaml|sumo-rjudge-20b:latest"
)

warm() {  # cold-load guard: abort loudly if a model won't load
  local code; code=$(curl -s --max-time 300 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $OPENAI_API_KEY" -H 'Content-Type: application/json' \
    "$OWUI_BASE/chat/completions" -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"warmup\"}],\"max_tokens\":1}")
  [ "$code" = 200 ] || { echo "  ERROR: $1 failed to load (HTTP $code)"; return 1; }
}

match() { [ -z "${2:-}" ] || [[ ",$2," == *",$1,"* ]]; }

for J in "${JUDGES[@]}"; do
  IFS='|' read -r jlabel jfile jmodel <<<"$J"
  match "$jlabel" "${JUDGES_ONLY:-}" || continue
  # On warm failure the control loop (and its per-$out rm) is skipped — clear THIS judge's
  # stale outputs so a prior run's JSON isn't consumed as if this judge had produced it.
  echo "=== JUDGE $jlabel ($jmodel) ==="; warm "$jmodel" || { echo "  skip judge $jlabel (cleared stale outputs)"; rm -f "$OUT"/*__*__"$jlabel".json; continue; }
  for C in "${CANDIDATES[@]}"; do
    IFS='|' read -r clabel cfile <<<"$C"
    match "$clabel" "${CANDS_ONLY:-}" || continue
    cmodel="$(grep -m1 'id: openai:chat:' "$EVAL_DIR/$cfile" | sed 's/.*openai:chat://')"
    echo "  -- candidate $clabel ($cmodel)"; warm "$cmodel" || { echo "    skip candidate $clabel (cleared stale outputs)"; rm -f "$OUT"/*__"$clabel"__"$jlabel".json; continue; }
    for ctrl in "${CONTROLS[@]}"; do
      case "$ctrl" in *"${CONTROLS_ONLY:-}"*) ;; *) continue;; esac
      out="$OUT/${ctrl}__${clabel}__${jlabel}.json"
      echo "     $ctrl -> $(basename "$out")"
      # Stale-output guard: filenames are deterministic, so a FAILED rerun after an earlier
      # success would leave the prior JSON in place and falsely report `ok` (aggregator then
      # scores stale measurements as this run's). Delete it before promptfoo writes.
      # NOTE: deterministic + unlocked paths => run bake-offs SEQUENTIALLY (the single shared
      # GPU enforces that anyway); concurrent same-variant runs would race on this file.
      rm -f "$out"
      # promptfoo exits 100 when ANY test fails — but that's the bake-off DATA (A0 is meant to
      # FAIL), and --output is written regardless. So success = a valid JSON file, not rc==0.
      # MUST disable errexit around it: under `set -e`, exit 100 would abort the whole sweep.
      set +e
      SUMO_EVAL_CANDIDATES_FILE="$cfile" SUMO_EVAL_JUDGE_FILE="$jfile" \
        "$PF" eval -c "$EVAL_DIR/$ctrl.ab.yaml" --no-cache --repeat "$REPEAT" -j 1 \
        --output "$out" >/dev/null 2>&1
      rc=$?
      set -e
      if [ -s "$out" ] && python3 -c "import json;json.load(open('$out'))" 2>/dev/null; then
        echo "       ok (rc=$rc)"
      else
        echo "       RUN ERROR (rc=$rc, no valid output): $out"
      fi
    done
  done
done
echo "[bakeoff] JSON in $OUT"
echo "[bakeoff] aggregate: python3 $EVAL_DIR/bakeoff/aggregate_bakeoff.py"
