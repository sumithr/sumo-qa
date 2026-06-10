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
declare -A HOST_FLAG=(
  [claude-code]="--claude-code"
  [vscode]="--vscode"
  [jetbrains]="--jetbrains"
)

print_plan=0
mode="install"   # install | update | doctor | uninstall
host=""

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
      mode="update"
      shift
      ;;
    --doctor)
      mode="doctor"
      shift
      ;;
    --uninstall)
      mode="uninstall"
      shift
      ;;
    --host)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --host requires a host name." >&2
        exit 2
      fi
      host="$2"
      if [[ -z "${HOST_FLAG[$host]:-}" ]]; then
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

# Build the command plan as an array of strings, one command per element.
plan=()

case "$mode" in
  install)
    plan+=("${PYTHON} -m pip install sumo-qa")
    if [[ -n "$host" ]]; then
      plan+=("${PYTHON} -m sumo_qa.installer ${HOST_FLAG[$host]}")
    else
      plan+=("${PYTHON} -m sumo_qa.installer")
    fi
    plan+=("sumo-qa-doctor")
    ;;
  update)
    plan+=("${PYTHON} -m pip install --upgrade sumo-qa")
    if [[ -n "$host" ]]; then
      plan+=("${PYTHON} -m sumo_qa.installer ${HOST_FLAG[$host]}")
    else
      plan+=("${PYTHON} -m sumo_qa.installer")
    fi
    plan+=("sumo-qa-doctor")
    ;;
  doctor)
    plan+=("sumo-qa-doctor")
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

if [[ "$print_plan" -eq 1 ]]; then
  printf '%s\n' "${plan[@]}"
  exit 0
fi

# Execute the plan. On failure, surface the exact failing command and the
# next safe manual step, then stop.
for cmd in "${plan[@]}"; do
  echo "+ ${cmd}"
  if ! eval "${cmd}"; then
    status=$?
    echo "" >&2
    echo "ERROR: command failed (exit ${status}):" >&2
    echo "  ${cmd}" >&2
    echo "" >&2
    echo "Next safe step: run that command yourself to see the full error," >&2
    echo "then check docs/INSTALL.md for the per-host manual install path." >&2
    echo "Nothing was deleted; re-running ./install.sh is safe." >&2
    exit "${status}"
  fi
done

echo ""
echo "Done. If a host was configured, restart it (or open a fresh chat) so it"
echo "picks up the sumo-qa MCP server and skills."
