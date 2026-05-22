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

exec python -m pytest \
  --override-ini="addopts=" \
  --override-ini="testpaths=" \
  -p no:cacheprovider \
  --check-links --links-ext=md \
  --check-links-ignore '^https?://' \
  --check-links-ignore '^\.\./\.\./(commit|pull|issues)/' \
  "${files[@]}"
