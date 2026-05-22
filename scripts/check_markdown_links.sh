#!/usr/bin/env bash
# Pre-commit + CI gate: every relative file link in tracked markdown
# must point at a file that exists. Catches the dev_install.py-shaped
# bug class (referenced file was removed but docs still link to it).
#
# Anchor checking (--check-anchors) is intentionally OFF — pytest-check-links
# 0.10.1 has a known anchor-detection bug (DeprecationWarning at plugin.py:428)
# that produces false positives on parenthesised and backticked headings.
# Re-enable when upstream ships a fix.
#
# External URLs are skipped: pre-commit must stay fast and offline.
# GitHub-relative `../../commit/`, `../../pull/`, `../../issues/` paths
# resolve only on github.com, never on disk, so they're also skipped.
set -euo pipefail

if [ "$#" -gt 0 ]; then
  files=("$@")
else
  # CI path: scan every tracked markdown file. `docs/qa/` and
  # `docs/superpowers/` are gitignored (process artefacts), so
  # `git ls-files` already excludes them.
  mapfile -t files < <(git ls-files '*.md')
fi

if [ "${#files[@]}" -eq 0 ]; then
  echo "check_markdown_links: no markdown files to check"
  exit 0
fi

# Resolve the Python interpreter — probe by *capability*, not by existence.
#
# Why this is non-trivial: the pre-commit hook can launch with cwd != repo
# root, AND $VIRTUAL_ENV may point at an unrelated venv (e.g. a contributor
# working in a worktree while their parent shell has a different .venv
# activated). A naive existence check sends pytest at an interpreter that
# can't import pytest-check-links and fails opaquely.
#
# Strategy: try candidates in order, pick the first one whose `python -c
# 'import pytest_check_links'` succeeds. The script always lives at
# `<repo-root>/scripts/check_markdown_links.sh`, so we resolve repo root
# from its own location, not from cwd.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

candidates=(
  "${REPO_ROOT}/.venv/bin/python"
)
if [ -n "${VIRTUAL_ENV:-}" ]; then
  candidates+=("${VIRTUAL_ENV}/bin/python")
fi
candidates+=("python3" "python")

PYTHON=""
for cand in "${candidates[@]}"; do
  if [ -x "$cand" ] || command -v "$cand" > /dev/null 2>&1; then
    if "$cand" -c "import pytest_check_links" > /dev/null 2>&1; then
      PYTHON="$cand"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "check_markdown_links: no Python interpreter with pytest-check-links found." >&2
  echo "Install dev deps with one of:" >&2
  echo "  uv sync --all-extras" >&2
  echo "  python -m pip install -e \".[dev]\"" >&2
  exit 2
fi

# `|| link_check_exit=$?` is required because `set -e` aborts the script
# on a bare failing command, so a plain `cmd; x=$?` capture never runs.
link_check_exit=0
"$PYTHON" -m pytest \
  --override-ini="addopts=" \
  --override-ini="testpaths=" \
  -p no:cacheprovider \
  --check-links --links-ext=md \
  --check-links-ignore '^https?://' \
  --check-links-ignore '^\.\./\.\./(commit|pull|issues)/' \
  "${files[@]}" || link_check_exit=$?

# Second layer: scan inline code + fenced code blocks for file refs that
# don't resolve (`python scripts/dev_install.py` style). pytest-check-links
# only looks at `[text](path)` markdown syntax; this catches the rest.
#
# Scope: root-level user-facing docs ONLY (README/AGENTS/DEMO/CHANGELOG).
# Everywhere else — docs/*.md, skills/*.md, knowledge/*.md, tests/scenarios/**
# — contains illustrative example paths by design (CONTENT-FORMATS shows
# shapes like `standards/packs/my_team_v1.yml`, worked-examples reference
# fictional services like `services/billing/calculator.py`). A broader scan
# would flood the gate with false positives. The narrow scope still catches
# the headline bug class (canonical install / demo commands referencing a
# file that no longer exists) where it matters most.
user_facing=()
for f in "${files[@]}"; do
  # Resolve to a path relative to the repo root so the case statement is
  # stable regardless of whether pre-commit passes "README.md" or
  # "/absolute/path/README.md".
  rel="$f"
  case "$rel" in
    "$REPO_ROOT"/*) rel="${rel#"$REPO_ROOT"/}" ;;
  esac
  case "$rel" in
    README.md|AGENTS.md|DEMO.md|CHANGELOG.md)
      user_facing+=("$f")
      ;;
  esac
done

codeblock_exit=0
if [ "${#user_facing[@]}" -gt 0 ]; then
  "$PYTHON" "${REPO_ROOT}/scripts/check_codeblock_file_refs.py" \
    "${user_facing[@]}" || codeblock_exit=$?
fi

# Bubble up the worse of the two exits.
if [ "$link_check_exit" -ne 0 ]; then
  exit "$link_check_exit"
fi
exit "$codeblock_exit"
