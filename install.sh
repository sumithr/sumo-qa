#!/usr/bin/env bash
# Sumo QA - one-command installer.
#
# What it does:
#   1. Ensures `uv` (Astral's Python toolchain manager) is installed.
#      uv handles Python version + venv + bin install in one step,
#      and downloads its own Python if your system Python is too old/new.
#   2. Installs this repo as a uv tool, putting `sumo-qa` on your PATH.
#   3. Prints the JSON config block to paste into your MCP host.
#
# What it explicitly avoids:
#   - Touching your system Python.
#   - Mixing with brew / pyenv / system pip in unpredictable ways.
#   - Failing silently when the user's Python is too new (3.14+) or too old.
#
# Usage:
#   ./install.sh           # install from the directory containing this script
#   ./install.sh --force   # reinstall even if already present
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force|-f) FORCE=1 ;;
        --help|-h)
            sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

note()  { printf "\033[0;36m> %s\033[0m\n" "$*"; }
ok()    { printf "\033[0;32m✓ %s\033[0m\n" "$*"; }
warn()  { printf "\033[0;33m! %s\033[0m\n" "$*"; }
fail()  { printf "\033[0;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

# Step 1 — make sure `uv` is on PATH.
if ! command -v uv >/dev/null 2>&1; then
    note "Installing uv (one-time, isolated toolchain manager)..."
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        fail "Could not install uv automatically. Install manually from https://docs.astral.sh/uv/getting-started/installation/ and re-run this script."
    fi
    # Newly-installed uv lands in ~/.local/bin (or the user's cargo dir on some setups).
    # Make it visible for the rest of this script run.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    fail "uv is not on PATH after install. Add \$HOME/.local/bin to your PATH and rerun."
fi
ok "uv is available: $(uv --version)"

# Step 2 — install sumo-qa as a uv tool.
note "Installing sumo-qa from $REPO_DIR ..."
INSTALL_FLAGS=()
if [ "$FORCE" -eq 1 ]; then
    INSTALL_FLAGS+=(--reinstall)
fi
if ! uv tool install "${INSTALL_FLAGS[@]}" "$REPO_DIR"; then
    fail "uv tool install failed. See the error above."
fi

# uv tool installs binaries in a stable location, then symlinks/proxies them.
# Make sure that location is on the user's PATH.
UV_BIN_DIR="$(uv tool dir 2>/dev/null || true)"
if [ -n "$UV_BIN_DIR" ] && [ -d "$UV_BIN_DIR" ]; then
    : # uv knows where binaries go
fi

if ! command -v sumo-qa >/dev/null 2>&1; then
    warn "sumo-qa is installed but not on PATH yet."
    warn "Run 'uv tool update-shell' (it appends the right export to your shell rc),"
    warn "then open a new terminal, then re-run 'which sumo-qa'."
    exit 0
fi

ok "Installed: $(which sumo-qa)"

# Step 3 — install the QA skill files for Claude Code (no-op for other hosts).
# Skills follow the superpowers convention: live under ~/.claude/skills/<name>/SKILL.md.
# We symlink so updates to the repo flow through without re-installing.
SKILL_SOURCE="$REPO_DIR/skills"
SKILL_DEST="$HOME/.claude/skills"
if [ -d "$SKILL_SOURCE" ]; then
    note "Installing QA skills into $SKILL_DEST (Claude Code picks them up automatically)..."
    mkdir -p "$SKILL_DEST"
    INSTALLED=0
    for skill_dir in "$SKILL_SOURCE"/*/; do
        skill_name=$(basename "$skill_dir")
        target="$SKILL_DEST/$skill_name"
        # Replace any prior symlink/dir we own; leave foreign content alone.
        if [ -L "$target" ] || [ ! -e "$target" ]; then
            rm -f "$target"
            ln -s "$skill_dir" "$target"
            INSTALLED=$((INSTALLED + 1))
        else
            warn "Skipping $skill_name: $target exists and is not a symlink we own"
        fi
    done
    ok "Installed $INSTALLED Sumo QA skill(s). Other MCP hosts (IntelliJ AI Assistant, Copilot) get the same discipline via the MCP prompts."
fi

# Step 4 — print the host config the user pastes.
cat <<'JSON'

──────────────────────────────────────────────────────────────────────────────
  Done. Paste this into your MCP host (Claude Code / IntelliJ AI Assistant /
  Cursor / Copilot / Windsurf — any MCP-compliant host):

  {
    "mcpServers": {
      "sumo-qa": {
        "command": "sumo-qa"
      }
    }
  }

  Then ask the host any QA question in natural language, e.g.:
    "review my changes"
    "how do I test a webhook retry that has to be idempotent?"
    "plan QA for: <your story>"
──────────────────────────────────────────────────────────────────────────────
JSON
