# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regression tests for .claude/hooks/*.py scripts.

These are standalone Python scripts (not part of the sumo_qa package), so they
are invoked here via subprocess to match how Claude Code actually runs them.
The pattern mirrors tests/test_installer_*.py.

History: PR #100 shipped both hooks with a cwd-anchored path check that
silently no-op'd whenever Claude Code's session cwd was a repo subdirectory.
Codex flagged the bypass; the fix (commit 32f8220) anchors to repo root.
These tests pin the post-fix behaviour so the bypass cannot regress silently.

Technique: equivalence partitioning over (cwd_location × file_location). The
bug lives in exactly one class — cwd in a subdir, file at a repo-relative
protected path outside the cwd subtree — so one representative per relevant
class is enough.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"


def _run_hook(
    hook_name: str, payload: dict, env: dict | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / hook_name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


class TestBlockGeneratedPathsHook:
    """PreToolUse hook: must deny edits to protected paths regardless of cwd."""

    def test_denies_protected_path_when_cwd_is_subdir(self) -> None:
        """Codex's PR #100 reproducer: cwd in subdir, file at protected path.

        Before the fix, `abs_path.relative_to(cwd)` raised ValueError for any
        file not under the session's cwd, the bare-continue caught it, and
        the deny never fired. This test pins that the hook now anchors to
        the repo root and the deny fires regardless of cwd location.
        """
        result = _run_hook(
            "block-generated-paths.py",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "tests" / "fixtures" / "regression-guard.txt"),
                },
                "cwd": str(REPO_ROOT / "skills"),
            },
        )

        assert result.returncode == 0, f"hook crashed: stderr={result.stderr!r}"
        assert result.stdout.strip(), (
            "hook produced empty stdout (silent allow) instead of deny JSON. "
            "This is the PR #100 bypass: cwd-anchored path check let the edit "
            "through. The hook must anchor to repo root."
        )

        output = json.loads(result.stdout)
        spec = output["hookSpecificOutput"]
        assert spec["hookEventName"] == "PreToolUse"
        assert spec["permissionDecision"] == "deny", (
            f"expected deny, got {spec['permissionDecision']!r}. Full output: {output}"
        )
        assert "tests/fixtures/" in spec["permissionDecisionReason"]

    def test_allows_non_protected_path_when_cwd_is_subdir(self) -> None:
        """Same equivalence class shape, opposite axis: confirm fix didn't
        introduce a false-positive that denies legitimate source edits.
        """
        result = _run_hook(
            "block-generated-paths.py",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "src" / "sumo_qa" / "server.py"),
                },
                "cwd": str(REPO_ROOT / "skills"),
            },
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "", (
            f"hook should silently allow non-protected paths; got: {result.stdout!r}"
        )


class TestValidateOnContentEditHook:
    """PostToolUse hook: must run sumo-qa-validate when knowledge/ or
    standards/ files are edited, regardless of cwd."""

    def test_runs_validator_when_cwd_is_subdir(self, tmp_path: Path) -> None:
        """Codex's PR #100 reproducer (validate hook variant): cwd in subdir,
        file in knowledge/. Before the fix, the relative_to(cwd) call raised,
        the bare-continue caught it, and `sumo-qa-validate` was never invoked.

        We can't directly observe "validator ran" without a side-channel, so
        this test installs a stand-in `sumo-qa-validate` at the front of PATH
        that touches a marker file. If the hook reaches its subprocess.run
        call, the marker exists. If the path-resolution bug returns, the
        early-exit fires and the marker does not exist.
        """
        marker = tmp_path / "validator_was_invoked"
        fake_validate = tmp_path / "sumo-qa-validate"
        fake_validate.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
        fake_validate.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

        result = _run_hook(
            "validate-on-content-edit.py",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "knowledge" / "principles.md"),
                },
                "cwd": str(REPO_ROOT / "skills"),
            },
            env=env,
        )

        assert marker.exists(), (
            "validator was not invoked. This is the PR #100 bypass: the hook's "
            "cwd-anchored relative_to() raised ValueError for knowledge/ files "
            "when cwd was a subdir, hit the bare-continue, and silently skipped "
            "the validator. The hook must anchor to repo root.\n"
            f"hook stderr={result.stderr!r}\n"
            f"hook stdout={result.stdout!r}"
        )
        assert result.returncode == 0, (
            f"hook exited non-zero after invoking validator: stderr={result.stderr!r}"
        )

    def test_skips_validator_when_edit_is_outside_watched_dirs(self, tmp_path: Path) -> None:
        """Same equivalence class shape, opposite axis: edits outside
        knowledge/ and standards/ should not trigger the validator."""
        marker = tmp_path / "validator_was_invoked"
        fake_validate = tmp_path / "sumo-qa-validate"
        fake_validate.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
        fake_validate.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

        result = _run_hook(
            "validate-on-content-edit.py",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "src" / "sumo_qa" / "server.py"),
                },
                "cwd": str(REPO_ROOT),
            },
            env=env,
        )

        assert not marker.exists(), (
            "validator was invoked for an edit outside knowledge/ and standards/. "
            "The hook should early-exit and skip the subprocess.run call."
        )
        assert result.returncode == 0
