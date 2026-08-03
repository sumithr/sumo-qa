: << 'CMDBLOCK'
@echo off
REM PostToolUse prefilter for route-qa-runners.py (see that file for the routing
REM contract). Polyglot, same trick as hooks/run-hook.cmd: cmd.exe runs the
REM batch block below, POSIX sh treats it as a heredoc and runs the shell body
REM after CMDBLOCK.
REM
REM Windows takes NO shortcut: it pipes straight to the Python hook, which is
REM exactly what settings.json did before the prefilter existed, so a Windows
REM contributor keeps the routing they always had. The prefilter's whole point
REM is skipping a Python start-up, and on Windows the only interpreter that can
REM run the shell body is Git Bash, which is not guaranteed and whose `python3`
REM often does not exist. Correct-and-unoptimised beats clever-and-broken.
REM
REM The file is named .cmd, not .sh, for two reasons: cmd.exe will only execute
REM a batch file by that extension, and Claude Code's Windows handling prepends
REM `bash` to any command containing ".sh", which would defeat the batch block.
REM
REM No usable interpreter is a silent exit 0, never an error: this hook is
REM advisory, and it must never disturb the Bash result it observes.
REM Each candidate is PROBED, not merely located on PATH. A bare existence
REM check passes on the Windows Store alias stub (a zero-byte python.exe that
REM opens the Store and runs nothing) and on a Python 2, either of which would
REM consume the branch and drop the payload. The probe runs the interpreter and
REM makes it prove it is Python 3, so an unusable candidate falls through to
REM the next one instead of swallowing the route.
setlocal
python -c "import sys;sys.exit(sys.version_info[0]-3)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python "%~dp0route-qa-runners.py"
    exit /b 0
)
py -3 -c "import sys;sys.exit(sys.version_info[0]-3)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 "%~dp0route-qa-runners.py"
    exit /b 0
)
python3 -c "import sys;sys.exit(sys.version_info[0]-3)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python3 "%~dp0route-qa-runners.py"
    exit /b 0
)
exit /b 0
CMDBLOCK

# POSIX branch: the actual prefilter. The Python hook can only ever route a
# command containing one of the tokens below, so skip the Python interpreter
# start-up on every other Bash call. Over-matching is fine (the Python
# command-shape gate decides); under-matching loses a route - keep the token
# list a SUPERSET of route-qa-runners.py's command shapes (mutmut run /
# promptfoo eval / npm|pnpm|yarn|bun eval scripts, where "eval" covers
# `npm run eval`).
#
# Known and accepted limitation, and the one exception to the superset rule:
# this matches the RAW payload text, whereas the Python hook shlex-parses the
# command. A shell-quoted spelling of a routing command (`mut""mut run`)
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
