#!/usr/bin/env bash
#
# sumo-qa one-command install wrapper (macOS / Linux).
#
# THIN ROUTER ONLY. This script delegates to the canonical Python installer
# and adds no install logic of its own:
#
#   python -m pip install sumo-qa      # the package (server + skills + knowledge)
#   python -m sumo_qa.installer        # the canonical host-config writer
#   sumo-qa-doctor                     # read-only post-install verification
#
# It exists so a first-time user runs ONE command instead of learning the
# pip / installer / doctor split. It must never become a second installer
# implementation, and it never bypasses the installer's own validation.
#
# Usage:
#   ./install.sh                 install for every host the installer detects,
#                                then run the doctor
#   ./install.sh --update        upgrade the package, refresh host configs,
#                                then run the doctor
#   ./install.sh --doctor        run the read-only doctor only (no install)
#   ./install.sh --uninstall     print the documented manual uninstall steps
#                                (deferred: see "Uninstall" below)
#   ./install.sh --host HOST     limit install to one verified host:
#                                claude-code | vscode | jetbrains
#   ./install.sh --print-plan …  print the exact commands this script WOULD
#                                run, one per line, and exit without running
#                                anything (used by the test suite and for
#                                auditing what the wrapper does)
#
# Safety: no sudo, no admin escalation, never deletes user-created
# ``.sumo-qa/`` artifacts, never removes host config entries it cannot prove
# it owns. On failure it prints the exact command that failed and the next
# safe manual command to run.
#
# Uninstall is DEFERRED on purpose. The canonical installer has no
# ``--uninstall`` subcommand, and a clean uninstall means editing host
# config files (the ``sumo-qa`` key under ``mcpServers`` / ``servers``) that
# this wrapper cannot prove it owns. Removing them blindly could delete a
# user's unrelated MCP servers. Until the Python installer grows an
# ownership-aware uninstall, the wrapper routes users to the documented
# manual steps in docs/INSTALL.md#uninstall rather than guessing.

set -euo pipefail

# Resolve a Python interpreter. Prefer python3, fall back to python.
PYTHON="${SUMO_QA_PYTHON:-}"
if [[ -z "${PYTHON}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
  else
    echo "ERROR: no python3 or python found on PATH." >&2
    echo "Next: install Python 3, then re-run ./install.sh" >&2
    exit 1
  fi
fi

# Verified hosts the installer can target via a single flag. Keep this in
# lockstep with python -m sumo_qa.installer's host flags; unverified hosts
# are rejected, never passed through as an unknown installer flag.
#
# A case statement (not an associative array) so this stays compatible with
# the stock macOS Bash 3.2 the shebang resolves to — `declare -A` is Bash 4+.
# Prints the installer flag for a verified host on stdout and returns 0;
# returns 1 (no output) for an unverified host.
host_flag() {
  case "$1" in
    claude-code) printf '%s' "--claude-code" ;;
    vscode)      printf '%s' "--vscode" ;;
    jetbrains)   printf '%s' "--jetbrains" ;;
    *)           return 1 ;;
  esac
}

print_plan=0
mode="install"   # install | update | doctor | uninstall
host=""
host_flag_value=""
# Track explicit mode flags so mutually-exclusive modes can be rejected
# (the last one would otherwise silently win — e.g. --uninstall --update
# could trigger an update for a user who asked to uninstall).
mode_flags=""

set_mode() {
  # $1 = mode name, $2 = the flag the user typed (for the error message).
  mode="$1"
  if [[ -n "$mode_flags" ]]; then
    mode_flags="${mode_flags}, $2"
  else
    mode_flags="$2"
  fi
}

usage() {
  sed -n '3,40p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --print-plan)
      print_plan=1
      shift
      ;;
    --update)
      set_mode "update" "--update"
      shift
      ;;
    --doctor)
      set_mode "doctor" "--doctor"
      shift
      ;;
    --uninstall)
      set_mode "uninstall" "--uninstall"
      shift
      ;;
    --host)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --host requires a host name." >&2
        exit 2
      fi
      host="$2"
      if ! host_flag_value="$(host_flag "$host")"; then
        echo "ERROR: unverified host '${host}'." >&2
        echo "Verified hosts: claude-code, vscode, jetbrains." >&2
        echo "Next: re-run with one of those, or configure your host manually" >&2
        echo "      per docs/INSTALL.md (other MCP hosts section)." >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument '$1'." >&2
      echo "Run ./install.sh --help for usage." >&2
      exit 2
      ;;
  esac
done

# Reject mutually-exclusive modes rather than silently letting the last flag
# win. A user who typed --uninstall --update must not get an update.
if [[ "$mode_flags" == *", "* ]]; then
  echo "ERROR: conflicting mode flags: ${mode_flags}." >&2
  echo "Choose exactly one of --update, --doctor, --uninstall." >&2
  exit 2
fi

# SUMO_QA_PYTHON (and the resolved $PYTHON fallback) is a SINGLE interpreter
# path or executable name, NOT a whitespace-split command line. Treat it as
# one argv element so a path containing spaces (e.g.
# "/Applications/Python 3/python") is preserved verbatim and exec'd correctly,
# and so a value like "python *" is never glob-expanded into the argv. On
# macOS/Linux there is no multi-word launcher form to support (the Windows
# "py -3" launcher is handled separately in install.ps1's default resolution).
# Commands run as argv arrays (no eval, no string re-splitting at exec time).
python_argv=("${PYTHON}")

# The command plan is built as a flat argv array: each command's words are
# appended, followed by a sentinel record-separator. This lets us both print
# a human-readable plan (--print-plan) and execute each command directly as
# argv (no eval / no string re-splitting at exec time). The sentinel is an
# internal token that never appears in a real argument.
CMD_SEP=$'\x1f'   # ASCII unit separator — not a valid argv word here
plan_argv=()

# add_cmd <word>...  — append one command (its words) plus the separator.
add_cmd() {
  local w
  for w in "$@"; do
    plan_argv+=("$w")
  done
  plan_argv+=("$CMD_SEP")
}

case "$mode" in
  install)
    add_cmd "${python_argv[@]}" -m pip install sumo-qa
    if [[ -n "$host" ]]; then
      add_cmd "${python_argv[@]}" -m sumo_qa.installer "$host_flag_value"
    else
      add_cmd "${python_argv[@]}" -m sumo_qa.installer
    fi
    add_cmd sumo-qa-doctor
    ;;
  update)
    add_cmd "${python_argv[@]}" -m pip install --upgrade sumo-qa
    if [[ -n "$host" ]]; then
      add_cmd "${python_argv[@]}" -m sumo_qa.installer "$host_flag_value"
    else
      add_cmd "${python_argv[@]}" -m sumo_qa.installer
    fi
    add_cmd sumo-qa-doctor
    ;;
  doctor)
    add_cmd sumo-qa-doctor
    ;;
  uninstall)
    # Deferred: print the documented manual steps, run nothing destructive.
    if [[ "$print_plan" -eq 1 ]]; then
      echo "# uninstall is deferred — no automated uninstall command is run."
      echo "# See docs/INSTALL.md#uninstall for the manual steps."
      exit 0
    fi
    cat >&2 <<'EOF'
Automated uninstall is not available yet.

A clean uninstall edits host config files (the "sumo-qa" entry under
mcpServers / servers) that this wrapper cannot prove it owns, so it will not
guess and risk removing your other MCP servers.

Follow the documented manual steps instead:

  docs/INSTALL.md#uninstall

In short: `pip uninstall sumo-qa`, then remove the "sumo-qa" entry from each
host config you configured (Claude Code, Claude Desktop, VS Code, JetBrains).
Your `.sumo-qa/` repo artifacts are yours to keep or delete; the uninstall
never touches them.
EOF
    exit 0
    ;;
esac

# Walk the flat plan_argv array one command at a time. `cmd_words` collects
# the argv of the current command until the sentinel record-separator, then
# `run` is invoked with that command. Keeps print + exec on one source of
# truth, with no eval anywhere.
cmd_words=()

# print_cmd: emit one command as a human-readable, copy-pasteable line (used
# by --print-plan and by the "+ ..." exec echo). Any token containing
# whitespace is single-quoted so the printed plan matches what is executed —
# e.g. an interpreter path "/Applications/Python 3/python" renders as a single
# quoted token, not two words that would exec the wrong path.
print_cmd() {
  local out="" word
  for word in "$@"; do
    case "$word" in
      # Quote any token with whitespace OR an embedded single quote, escaping
      # the quote via the '\'' idiom so the printed plan is valid, copy-paste
      # shell even for an odd interpreter path like /O'Brien/python.
      *[[:space:]]*|*\'*) word="'${word//\'/\'\\\'\'}'" ;;
    esac
    if [[ -n "$out" ]]; then
      out="${out} ${word}"
    else
      out="$word"
    fi
  done
  # 2>/dev/null: when the plan is piped to a consumer that closes the pipe
  # early (e.g. `--print-plan | grep -q`), this write hits a broken pipe.
  # Swallow that error message; the SIGPIPE/errexit guard below the loop keeps
  # the broken pipe from failing the script.
  printf '%s\n' "$out" 2>/dev/null
}

# run_cmd: execute the current command as argv. Captures the REAL exit code
# of the delegated command (errexit is disabled just around the call so the
# failing command's status reaches us instead of the negation's), then
# surfaces the friendly failure message and propagates that exact code.
run_cmd() {
  printf '+ '
  print_cmd "$@"
  set +e
  "$@"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "" >&2
    echo "ERROR: command failed (exit ${status}):" >&2
    echo "  $*" >&2
    echo "" >&2
    echo "Next safe step: run that command yourself to see the full error," >&2
    echo "then check docs/INSTALL.md for the per-host manual install path." >&2
    echo "Nothing was deleted; re-running ./install.sh is safe." >&2
    exit "$status"
  fi
}

# --print-plan only PRINTS the commands and exits 0 — it never executes. A
# reader auditing the plan with `grep -q`/`head` closes the pipe after the
# first match, so a later write gets SIGPIPE (exit 141) or a broken-pipe
# error that errexit would turn into a failure. Ignore SIGPIPE and drop
# errexit for the print walk so an early-closing consumer can never make an
# audit fail. The exec path keeps errexit (run_cmd manages its own toggling).
if [[ "$print_plan" -eq 1 ]]; then
  trap '' PIPE
  set +e
fi

for word in "${plan_argv[@]}"; do
  if [[ "$word" == "$CMD_SEP" ]]; then
    if [[ "$print_plan" -eq 1 ]]; then
      print_cmd "${cmd_words[@]}"
    else
      run_cmd "${cmd_words[@]}"
    fi
    cmd_words=()
  else
    cmd_words+=("$word")
  fi
done

if [[ "$print_plan" -eq 1 ]]; then
  exit 0
fi

echo ""
echo "Done. If a host was configured, restart it (or open a fresh chat) so it"
echo "picks up the sumo-qa MCP server and skills."
