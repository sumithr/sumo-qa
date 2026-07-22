#!/bin/sh
# PostToolUse prefilter for route-qa-runners.py (see that file for the routing
# contract). The Python hook can only ever route a command containing one of
# the tokens below, so skip the Python interpreter start-up on every other
# Bash call. Over-matching is fine (the Python command-shape gate decides);
# under-matching loses a route - keep the token list a SUPERSET of
# route-qa-runners.py's command shapes (mutmut run / promptfoo eval /
# npm|pnpm|yarn|bun eval scripts, where "eval" covers `npm run eval`).
payload=$(cat)
case "$payload" in
    *mutmut* | *promptfoo* | *eval*)
        printf '%s' "$payload" | "$(dirname "$0")/route-qa-runners.py"
        ;;
esac
exit 0
