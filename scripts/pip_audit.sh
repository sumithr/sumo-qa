#!/usr/bin/env bash
# Dependency-vulnerability gate. Run by BOTH the local `pip-audit` pre-commit
# hook (.pre-commit-config.yaml) and the `pip-audit` CI job (.github/workflows/
# lint.yml), so the suppression list below is single-sourced and local always
# matches the pipeline. The caller provisions pip-audit (uv `--with` locally,
# pip-installed in CI); this script owns the audit invocation and the ignores.
#
# pip-audit 2.10.1 has no config/ignore-file support (only `--ignore-vuln`
# flags), which is why this wrapper exists. To suppress an advisory, add its ID
# below WITH a dated rationale; never inline `--ignore-vuln` at a call site.
set -euo pipefail

# Advisories suppressed because they are not remediable by upgrading. Each entry
# must justify why. Revisit when the named blocker clears.
IGNORES=(
  # PYSEC-2025-183: disputed PyJWT advisory (caller-chosen weak HMAC key length,
  # argued to be the application's responsibility). OSV lists every version 0+
  # as affected with no fixed event, so an upgrade cannot remediate it.
  PYSEC-2025-183
  # CVE-2025-71176: pytest local tmpdir symlink priv-esc/DoS, fixed in pytest
  # 9.0.3. Dev/test-only (never in the shipped wheel) and the markdown-link
  # gate's pytest-check-links 0.10.1 hard-caps pytest<9, so the fix is
  # unreachable here. Revisit when a pytest>=9 link-checker ships.
  CVE-2025-71176
)

args=()
for id in "${IGNORES[@]}"; do
  args+=(--ignore-vuln "$id")
done

exec pip-audit --strict "${args[@]}" "$@"
