# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regression tests for .claude/hooks/*.py scripts.

The PreToolUse `block-generated-paths` hook is tested via subprocess because
its output (deny JSON on stdout) is directly observable that way.

The PostToolUse `validate-on-content-edit` hook is tested via importlib +
monkeypatch on `subprocess.run` because the bug it guards against is
"did the hook reach subprocess.run with the right cwd?" — observable by
recording the call, not by side-effect detection. This avoids the
platform-specific shell-script fake the earlier version relied on (which
failed on Windows because `#!/bin/sh` shebangs and `touch` are not native).

History: PR #100 shipped both hooks with a cwd-anchored path check that
silently no-op'd whenever Claude Code's session cwd was a repo subdirectory.
Codex flagged the bypass; the fix (commit 32f8220) anchors to repo root.
These tests pin the post-fix behaviour so the bypass cannot regress silently.

Technique: equivalence partitioning over (cwd_location × file_location) for
the path-resolution tests; checklist-based testing for the binary
discoverability smoke test.
"""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"


def _import_hook(hook_filename: str) -> ModuleType:
    """Import a .claude/hooks/*.py file as a Python module despite the
    dash-containing filename. The hook is a script with a module-level
    `main()`; importing it executes top-level definitions only (no
    `if __name__ == "__main__"` side-effects).
    """
    path = HOOKS_DIR / hook_filename
    module_name = hook_filename.removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {hook_filename} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_subprocess_hook(
    hook_name: str, payload: dict, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Subprocess invocation, used for the block-generated-paths hook
    whose output is directly observable as stdout JSON."""
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
        result = _run_subprocess_hook(
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
        result = _run_subprocess_hook(
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
    """PostToolUse hook: must invoke sumo-qa-validate with cwd=repo_root when
    knowledge/ or standards/ files are edited, regardless of session cwd."""

    @staticmethod
    def _run_hook_with_payload(monkeypatch, payload: dict) -> list[dict]:
        """Import the hook, monkeypatch its stdin and subprocess.run, call
        main(). Returns the list of recorded subprocess.run invocations."""
        hook = _import_hook("validate-on-content-edit.py")

        calls: list[dict] = []

        def record(cmd, **kwargs):
            calls.append({"cmd": cmd, "cwd": kwargs.get("cwd")})
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(hook.subprocess, "run", record)
        monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(payload)))

        exit_code = hook.main()
        assert exit_code == 0, f"hook exited non-zero: {exit_code}"
        return calls

    def test_runs_validator_with_repo_root_cwd_when_session_cwd_is_subdir(
        self, monkeypatch
    ) -> None:
        """Codex's PR #100 reproducer (validate hook variant). Before the fix,
        `Path(raw).resolve().relative_to(cwd)` raised ValueError for files
        outside the session cwd's subtree, the bare-continue caught it, and
        the validator was never invoked. This pins that the hook now resolves
        paths against the repo root and runs the validator from there.

        Observability: monkeypatch subprocess.run to record the cmd+cwd it
        gets called with, then assert on the recording. No PATH manipulation,
        no platform-specific fake — same logic exercised on every OS.
        """
        calls = self._run_hook_with_payload(
            monkeypatch,
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "knowledge" / "principles.md"),
                },
                "cwd": str(REPO_ROOT / "skills"),
            },
        )

        assert len(calls) == 1, (
            f"hook should invoke validator exactly once for a knowledge/ edit, "
            f"got: {calls}. The pre-fix bug skipped this invocation because "
            f"relative_to(cwd=subdir) raised ValueError for the knowledge/ path."
        )
        assert calls[0]["cmd"] == ["sumo-qa-validate"]
        assert Path(calls[0]["cwd"]) == REPO_ROOT, (
            f"validator must run from repo root, not session cwd. "
            f"Got cwd={calls[0]['cwd']!r}. Running from the session subdir "
            f"makes the validator scan the wrong tree."
        )

    def test_skips_validator_when_edit_is_outside_watched_dirs(self, monkeypatch) -> None:
        """Same equivalence class shape, opposite axis: edits outside
        knowledge/ and standards/ should not trigger the validator."""
        calls = self._run_hook_with_payload(
            monkeypatch,
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "src" / "sumo_qa" / "server.py"),
                },
                "cwd": str(REPO_ROOT),
            },
        )

        assert calls == [], (
            f"hook should skip subprocess.run for edits outside watched dirs; got: {calls}"
        )


def test_sumo_qa_validate_is_discoverable_on_path() -> None:
    """Smoke test: the binary the validate hook shells out to must be on PATH.

    The hook does `subprocess.run(["sumo-qa-validate"], ...)`. That relies on
    pip's console-script wrapper being on PATH:
      - Unix: `sumo-qa-validate` (extensionless, executable bit set)
      - Windows: `sumo-qa-validate.exe` (PATHEXT resolution)

    If pip's wrapper generation breaks for any reason, the hook silently fails
    in production and the cwd-vs-repo-root tests above (which monkeypatch
    subprocess.run) wouldn't catch it. This test is the deployment-contract
    check that the binary is actually discoverable on each platform CI covers.

    Technique: checklist-based testing — verify the dependency contract from
    `.pre-commit-config.yaml:133` (sumo-qa-validate must be installed) and
    `AGENTS.md` (`pip install sumo-qa` must produce a callable binary).
    """
    resolved = shutil.which("sumo-qa-validate")
    assert resolved is not None, (
        "sumo-qa-validate not on PATH. The validate-on-content-edit hook "
        "will silently fail in production. On Windows this typically means "
        "pip didn't generate the .exe wrapper; on Unix the script wasn't "
        "installed with executable bit. Confirm `pip install -e .` ran "
        f"successfully. Current PATH={sys.executable!r}'s sys.path may help "
        "diagnose."
    )
