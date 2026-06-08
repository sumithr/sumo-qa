#!/usr/bin/env bash
# Resolve + load OpenWebUI creds for the local-eval scripts (key NEVER echoed).
# `source` this; it sets OWUI_BASE and exports OPENWEBUI_API_KEY. Callers re-export
# for their own client (e.g. promptfoo wants OPENAI_API_KEY=$OPENWEBUI_API_KEY).
# Single source of the key-file path + proxy URL — used by run-eval.sh and
# validate-local-judge/run.sh so they can't drift. Returns non-zero on failure.
OWUI_KEY_FILE="${SUMO_OWUI_KEY_FILE:-$HOME/.config/owui.env}"
[ -f "$OWUI_KEY_FILE" ] || { echo "ERROR: OWUI key file not found: $OWUI_KEY_FILE" >&2; return 1; }
set -a
# shellcheck source=/dev/null
. "$OWUI_KEY_FILE"
set +a
[ -n "${OPENWEBUI_API_KEY:-}" ] || { echo "ERROR: OPENWEBUI_API_KEY missing in $OWUI_KEY_FILE" >&2; return 1; }
export OPENWEBUI_API_KEY
export OWUI_BASE="${SUMO_OWUI_BASE:-http://192.168.50.3:3535/api}"
export SUMO_OWUI_BASE="$OWUI_BASE"
