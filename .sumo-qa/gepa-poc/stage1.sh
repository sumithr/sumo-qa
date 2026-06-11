#!/usr/bin/env bash
# Stage-1 watchdog: runs GEPA (20 metric calls) and AUTO-RESUMES from checkpoint on
# transient infra failure (laptop sleep, Ollama restart, OWUI blip) instead of
# halting for a human. Same --run-dir across attempts = gepa state reload, no redo.
set -u
cd "$(dirname "$0")" || exit 1
RUN_DIR="runs/stage1-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
log() { echo "[watchdog] $(date '+%H:%M:%S') $*" | tee -a "$RUN_DIR/watchdog.log"; }

for attempt in 1 2 3 4 5 6 7 8; do
  log "attempt $attempt starting (run_dir=$RUN_DIR)"
  if venv/bin/python run_poc.py --metric-calls 20 --run-dir "$RUN_DIR" "$@" \
       >> "$RUN_DIR/stage1.log" 2>&1; then
    log "stage 1 COMPLETED OK"
    exit 0
  fi
  log "run exited nonzero; probing candidate model before resume"
  # shellcheck source=/dev/null
  . ../../tests/evals/promptfoo/_owui-env.sh || { log "owui env failed"; sleep 120; continue; }
  for i in $(seq 1 30); do
    code=$(curl -s --max-time 60 -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer $OPENWEBUI_API_KEY" -H 'Content-Type: application/json' \
      "$OWUI_BASE/chat/completions" \
      -d '{"model":"gemma4-12b-bounded","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' || true)
    if [ "${code:-000}" = 200 ]; then log "candidate model back (probe $i)"; break; fi
    sleep 60
  done
done
log "EXHAUSTED 8 attempts — giving up; resume manually with --run-dir $RUN_DIR"
exit 1
