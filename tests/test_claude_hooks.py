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

import pytest

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

    Skipped when sumo-qa is not pip-installed in the active interpreter
    (e.g. pre-commit's hook venv uses `pythonpath = ["src"]` instead of
    pip-installing the project, and the pre-push pytest run happens there
    — the console-script contract doesn't apply in that mode). Same
    resilience pattern as ``test_python_version_reports_interpreter_and_package``
    in tests/test_doctor.py (commit 4d4a19a).

    Technique: checklist-based testing — verify the dependency contract from
    `.pre-commit-config.yaml:133` (sumo-qa-validate must be installed) and
    `AGENTS.md` (`pip install sumo-qa` must produce a callable binary).
    """
    import importlib.metadata as _imd

    try:
        _imd.version("sumo-qa")
    except _imd.PackageNotFoundError:
        pytest.skip(
            "sumo-qa is not pip-installed in the active interpreter "
            "(running via PYTHONPATH — e.g. pre-commit's hook venv). The "
            "console-script discoverability contract only applies to "
            "pip/uv-installed environments; CI exercises that path."
        )

    resolved = shutil.which("sumo-qa-validate")
    assert resolved is not None, (
        "sumo-qa-validate not on PATH. The validate-on-content-edit hook "
        "will silently fail in production. On Windows this typically means "
        "pip didn't generate the .exe wrapper; on Unix the script wasn't "
        "installed with executable bit. Confirm `pip install -e .` ran "
        f"successfully. Current PATH={sys.executable!r}'s sys.path may help "
        "diagnose."
    )


class TestBlockGeneratedPathsMultiEditAndPycache:
    """Codex review findings P1#1 and P2#5: MultiEdit schema mis-read,
    root-level __pycache__/ not matched by `**/__pycache__/**` fnmatch."""

    def test_multiedit_denies_protected_path(self) -> None:
        """P1: MultiEdit's schema has `file_path` at TOP LEVEL; `edits` is an
        array of `{old_string, new_string}` pairs without `file_path`. The
        v1 hook looked for per-edit `file_path` and found nothing, silently
        allowing MultiEdit of protected paths.
        """
        result = _run_subprocess_hook(
            "block-generated-paths.py",
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "tests" / "fixtures" / "regression-guard.txt"),
                    "edits": [
                        {"old_string": "before", "new_string": "after"},
                    ],
                },
                "cwd": str(REPO_ROOT),
            },
        )

        assert result.stdout.strip(), (
            "hook produced empty stdout (silent allow) for MultiEdit of a "
            "protected path. The hook must read MultiEdit's top-level "
            "file_path, not per-edit file_path."
        )
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_root_pycache_is_denied(self) -> None:
        """P2: `**/__pycache__/**` under Python's fnmatch does NOT match
        `__pycache__/foo.pyc` at the repo root (the leading `**/` requires
        at least one parent directory). The deny list should cover both.
        """
        result = _run_subprocess_hook(
            "block-generated-paths.py",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(REPO_ROOT / "__pycache__" / "regression.pyc"),
                },
                "cwd": str(REPO_ROOT),
            },
        )

        assert result.stdout.strip(), (
            "hook produced empty stdout (silent allow) for a root-level "
            "__pycache__ path. The DENY_PATTERNS list needs a "
            "`__pycache__/**` entry alongside the existing `**/__pycache__/**`."
        )
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestValidateOnContentEditMultiEdit:
    """Codex review finding P1#2: validate hook same MultiEdit schema bug."""

    def test_multiedit_runs_validator_for_knowledge_edit(self, monkeypatch) -> None:
        """P1: MultiEdit on knowledge/ files must trigger sumo-qa-validate.
        v1 hook returned no candidate paths for MultiEdit, so the validator
        was never called.
        """
        hook = _import_hook("validate-on-content-edit.py")

        calls: list[dict] = []

        def record(cmd, **kwargs):
            calls.append({"cmd": cmd, "cwd": kwargs.get("cwd")})
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(hook.subprocess, "run", record)
        payload = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": str(REPO_ROOT / "knowledge" / "principles.md"),
                "edits": [
                    {"old_string": "old", "new_string": "new"},
                ],
            },
            "cwd": str(REPO_ROOT),
        }
        monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(payload)))

        exit_code = hook.main()
        assert exit_code == 0
        assert len(calls) == 1, f"validator must run for MultiEdit of knowledge/, got: {calls}"
        assert calls[0]["cmd"] == ["sumo-qa-validate"]
        assert Path(calls[0]["cwd"]) == REPO_ROOT


class TestScaffoldScriptSlugValidation:
    """Codex review finding P2#3: scaffold.py doesn't validate --name,
    allowing path traversal via separators / `..`."""

    SCAFFOLD = (
        REPO_ROOT / ".claude" / "skills" / "scaffold-sumo-qa-skill" / "scripts" / "scaffold.py"
    )

    def _make_tmp_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "skills").mkdir()
        (tmp_path / "knowledge").mkdir()
        (tmp_path / "tests" / "evals" / "promptfoo").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
        (tmp_path / "knowledge" / "approaches.md").write_text(
            "# Approaches\n\n## existing\nTest.\n"
        )
        return tmp_path

    def test_rejects_name_with_path_separator(self, tmp_path: Path) -> None:
        """A name containing `/` or `..` must be rejected before any file
        is written. Otherwise an attacker (or accidentally-malformed input)
        could write outside the intended skills/ tree.
        """
        repo = self._make_tmp_repo(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                str(self.SCAFFOLD),
                "--name",
                "../escape",
                "--description",
                "test",
                "--approach-tag",
                "test-tag",
                "--repo-root",
                str(repo),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0, (
            f"script accepted name with `..` separator: stdout={result.stdout!r}"
        )
        # Nothing outside the repo should exist
        assert not (tmp_path.parent / "escape").exists()
        assert not (repo / "skills" / "sumo-qa-..").exists()

    def test_rejects_name_with_slash(self, tmp_path: Path) -> None:
        repo = self._make_tmp_repo(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                str(self.SCAFFOLD),
                "--name",
                "foo/bar",
                "--description",
                "test",
                "--approach-tag",
                "test-tag",
                "--repo-root",
                str(repo),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0, (
            f"script accepted name with `/` separator: stdout={result.stdout!r}"
        )


class TestRunBaselineScriptSlugValidation:
    """Codex review finding P2#4: run_baseline.py doesn't validate --skill
    or --label, allowing path traversal in the snapshot filename."""

    RUN_BASELINE = (
        REPO_ROOT / ".claude" / "skills" / "regen-eval-baseline" / "scripts" / "run_baseline.py"
    )

    def test_rejects_skill_with_path_separator(self, tmp_path: Path) -> None:
        """A --skill containing `..` must be rejected before any file is
        written. The script computes
        `docs/qa/runs/eval-baselines/<date>-skill-<skill>-<label>.json`,
        so a malicious value can escape that directory."""
        (tmp_path / "tests" / "evals" / "promptfoo").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")

        import os as _os

        env = _os.environ.copy()
        env["OPENAI_API_KEY"] = "dummy-not-used-because-validation-rejects-first"

        result = subprocess.run(
            [
                sys.executable,
                str(self.RUN_BASELINE),
                "--skill",
                "../escape",
                "--label",
                "test",
                "--repo-root",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0, (
            f"script accepted --skill with `..` separator: stdout={result.stdout!r}"
        )

    def test_rejects_label_with_path_separator(self, tmp_path: Path) -> None:
        (tmp_path / "tests" / "evals" / "promptfoo").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
        # Need the YAML to exist so we don't fail on the earlier check.
        (tmp_path / "tests" / "evals" / "promptfoo" / "skill-real.yaml").write_text("")

        import os as _os

        env = _os.environ.copy()
        env["OPENAI_API_KEY"] = "dummy"

        result = subprocess.run(
            [
                sys.executable,
                str(self.RUN_BASELINE),
                "--skill",
                "real",
                "--label",
                "../escape",
                "--repo-root",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0, (
            f"script accepted --label with `..` separator: stdout={result.stdout!r}"
        )
