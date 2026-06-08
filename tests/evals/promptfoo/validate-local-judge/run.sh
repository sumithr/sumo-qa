#!/usr/bin/env bash
#
# Validate a LOCAL promptfoo judge against the STORED cloud verdicts in
# ~/.promptfoo/promptfoo.db. Sources the OpenWebUI key (never echoed) and runs
# validate_local_judge.py. Re-run whenever the local judge model or hardware
# changes — determinism/agreement/discrimination are per (model, num_ctx, GPU).
#
# Usage:
#   bash run.sh                                   # all checks, default judge
#   bash run.sh --mode determinism --reps 5
#   bash run.sh --judge sumo-cheap-judge-9b --mode discrimination --pairs 12
#   (npm: npm run eval:validate-judge -- <flags>)
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
. "$HERE/../_owui-env.sh" || exit 1   # sets OWUI_BASE + OPENWEBUI_API_KEY (key never echoed)

exec python3 "$HERE/validate_local_judge.py" "$@"
