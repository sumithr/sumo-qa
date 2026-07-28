#!/bin/sh
# PostToolUse prefilter for route-qa-runners.py (see that file for the routing
# contract). The Python hook can only ever route a command containing one of
# the tokens below, so skip the Python interpreter start-up on every other
# Bash call. Over-matching is fine (the Python command-shape gate decides);
# under-matching loses a route - keep the token list a SUPERSET of
# route-qa-runners.py's command shapes (mutmut run / promptfoo eval /
# npm|pnpm|yarn|bun eval scripts, where "eval" covers `npm run eval`).
#
# Known and accepted limitation, and the one exception to the superset rule
# above: this matches the RAW payload text, whereas the Python hook shlex-parses
# the command. A shell-quoted spelling of a routing command (`mut""mut run`)
# therefore passes the Python gate but has no contiguous token here, so its
# route is dropped. Closing that hole would mean re-implementing shlex in sh,
# reintroducing much of the start-up cost this prefilter exists to avoid, to
# cover a spelling that is unlikely in practice. The cost of a miss is one lost
# advisory reminder: the Python hook only ever adds context and always exits 0.
payload=$(cat)
case "$payload" in
    *mutmut* | *promptfoo* | *eval*)
        printf '%s' "$payload" | "$(dirname "$0")/route-qa-runners.py"
        ;;
esac
exit 0
