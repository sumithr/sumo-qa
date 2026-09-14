# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The promptfoo eval harness defaults to the Claude pair (#682).

Epic #660 retired the OpenAI eval gate, and #679 put the matrix on the Claude
subscription behind an opt-in backend. These tests pin the defaults that make
the Claude pair the gate everywhere a contributor starts an eval:

* every `skill-*.yaml` config pins the Claude candidate + judge provider files,
  so a bare `promptfoo eval -c <config>` never reaches an OpenAI model;
* `npm run eval` / `npm run eval:all` go through `run-eval.sh` on its default
  backend, which is `claude` (one config, and the full matrix respectively);
* the removed `cloud` backend fails loudly, naming the valid backends;
* the local OpenWebUI tiers still resolve their providers and file split.

The run-eval.sh cases use its `SUMO_EVAL_DRY_RUN=1` mode, which prints each
promptfoo command instead of running it, with a stand-in `claude` on PATH for
the CLI preflight. No model is called.

Technique: equivalence partitioning over the backend input (unset / claude /
local / cloud / garbage) and over the target argument (none / one config /
`all`), plus checklist-based testing over every config file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"
RUN_EVAL = EVAL_DIR / "run-eval.sh"

CANDIDATE_FILE = "providers/claude-candidate.yaml"
JUDGE_FILE = "providers/claude-judge.yaml"
REASONING_MARKER = re.compile(r"^# local-tier: reasoning\b", re.MULTILINE)

_posix_only = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="run-eval.sh is a bash script",
)


def _configs() -> list[Path]:
    """The configs run-eval.sh runs: every skill-*.yaml except generated datasets."""
    return sorted(
        p
        for p in EVAL_DIR.glob("skill-*.yaml")
        if not p.name.endswith((".gen.yaml", ".generated-tests.yaml"))
    )


def _file_ref_target(ref: object) -> str | None:
    """The provider file a `file://` reference resolves to by default.

    Plain configs write `file://providers/x.yaml`; the `.ab` controls write
    `file://{{ env.SUMO_EVAL_CANDIDATES_FILE | default('providers/x.yaml') }}`
    so the bake-off can swap providers. Both default to the same file.
    """
    if not isinstance(ref, str) or not ref.startswith("file://"):
        return None
    body = ref.removeprefix("file://")
    templated = re.fullmatch(r"\{\{\s*env\.\w+\s*\|\s*default\('([^']+)'\)\s*\}\}", body)
    return templated.group(1) if templated else body


# --------------------------------------------------------------------------- #
# Config pins                                                                 #
# --------------------------------------------------------------------------- #


class TestConfigsPinTheClaudePair:
    def test_configs_exist(self) -> None:
        assert len(_configs()) > 10, "expected the skill eval matrix under tests/evals/promptfoo"

    @pytest.mark.parametrize("config", _configs(), ids=lambda p: p.name)
    def test_candidate_is_the_claude_candidate(self, config: Path) -> None:
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        providers = data.get("providers")
        assert isinstance(providers, list) and len(providers) == 1, (
            f"{config.name}: expected exactly one candidate provider, got {providers!r}"
        )
        assert _file_ref_target(providers[0]) == CANDIDATE_FILE, (
            f"{config.name}: the candidate must default to {CANDIDATE_FILE} so a bare "
            f"`promptfoo eval -c` runs on the Claude pair; got {providers[0]!r}"
        )

    @pytest.mark.parametrize("config", _configs(), ids=lambda p: p.name)
    def test_judge_is_the_claude_judge(self, config: Path) -> None:
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        judge = ((data.get("defaultTest") or {}).get("options") or {}).get("provider")
        assert _file_ref_target(judge) == JUDGE_FILE, (
            f"{config.name}: defaultTest.options.provider must default to {JUDGE_FILE}; "
            f"without it an llm-rubric falls back to promptfoo's own default grader. "
            f"got {judge!r}"
        )

    @pytest.mark.parametrize("config", _configs(), ids=lambda p: p.name)
    def test_no_openai_model_id_anywhere(self, config: Path) -> None:
        text = config.read_text(encoding="utf-8")
        hits = re.findall(r"^\s*(?:-\s+)?(?:id|provider):\s*openai:\S+", text, re.MULTILINE)
        assert hits == [], f"{config.name} still pins an OpenAI provider: {hits}"

    def test_cloud_provider_files_are_removed(self) -> None:
        leftovers = sorted(p.name for p in (EVAL_DIR / "providers").glob("cloud-*.yaml"))
        assert leftovers == [], f"the OpenAI cloud tier is removed; found {leftovers}"


class TestNpmScripts:
    def _scripts(self) -> dict[str, str]:
        return json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]

    def test_eval_runs_one_config_through_run_eval_on_the_default_backend(self) -> None:
        script = self._scripts()["eval"]
        assert script.strip() == "bash tests/evals/promptfoo/run-eval.sh", script

    def test_eval_all_runs_the_matrix_through_run_eval_on_the_default_backend(self) -> None:
        script = self._scripts()["eval:all"]
        assert script.strip() == "bash tests/evals/promptfoo/run-eval.sh all", script


# --------------------------------------------------------------------------- #
# run-eval.sh resolution (dry run, no model call)                             #
# --------------------------------------------------------------------------- #


def _run_eval(
    tmp_path: Path, *args: str, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok=True)
    claude = fakebin / "claude"
    claude.write_text("#!/bin/sh\necho 'stand-in claude must not be called' >&2\nexit 97\n")
    claude.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("SUMO_", "OPENAI_", "OPENWEBUI_")) and k != "TIER"
    }
    env["PATH"] = f"{fakebin}{os.pathsep}{env.get('PATH', '')}"
    env["SUMO_EVAL_DRY_RUN"] = "1"
    env.update(env_overrides or {})
    return subprocess.run(
        ["bash", str(RUN_EVAL), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
    )


def _dry_run_commands(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("[eval] dry-run:")]


def _config_of(command: str) -> str:
    match = re.search(r"eval -c (\S+)", command)
    assert match, f"no -c <config> in dry-run command: {command!r}"
    return Path(match.group(1)).name


@_posix_only
class TestRunEvalClaudeDefault:
    def test_no_env_no_args_runs_the_tdd_config_on_the_claude_pair(self, tmp_path: Path) -> None:
        result = _run_eval(tmp_path)
        assert result.returncode == 0, result.stderr
        assert "backend=CLAUDE" in result.stdout, result.stdout
        commands = _dry_run_commands(result.stdout)
        assert [_config_of(c) for c in commands] == ["skill-implementing-with-tdd.yaml"], (
            result.stdout
        )
        assert f"--providers file://{EVAL_DIR}/{CANDIDATE_FILE}" in commands[0]
        assert f"--grader file://{EVAL_DIR}/{JUDGE_FILE}" in commands[0]

    def test_all_resolves_the_full_matrix_on_the_claude_pair(self, tmp_path: Path) -> None:
        result = _run_eval(tmp_path, "all")
        assert result.returncode == 0, result.stderr
        commands = _dry_run_commands(result.stdout)
        assert sorted(_config_of(c) for c in commands) == [p.name for p in _configs()]
        for command in commands:
            assert f"--providers file://{EVAL_DIR}/{CANDIDATE_FILE}" in command, command
            assert f"--grader file://{EVAL_DIR}/{JUDGE_FILE}" in command, command

    def test_explicit_config_runs_only_that_config(self, tmp_path: Path) -> None:
        target = EVAL_DIR / "skill-finding-test-data.yaml"
        result = _run_eval(tmp_path, str(target))
        assert result.returncode == 0, result.stderr
        assert [_config_of(c) for c in _dry_run_commands(result.stdout)] == [target.name]

    def test_default_path_reads_no_openai_key(self, tmp_path: Path) -> None:
        """No OPENAI_API_KEY in the environment, and the run still resolves."""
        result = _run_eval(tmp_path)
        assert result.returncode == 0, result.stderr
        assert "OPENAI_API_KEY" not in result.stdout + result.stderr


@_posix_only
class TestRunEvalRejectsUnknownBackends:
    @pytest.mark.parametrize("backend", ["cloud", "openai", "bogus"])
    def test_invalid_backend_fails_naming_the_valid_ones(
        self, tmp_path: Path, backend: str
    ) -> None:
        result = _run_eval(tmp_path, env_overrides={"SUMO_EVAL_BACKEND": backend})
        assert result.returncode != 0
        assert "claude|local" in result.stderr, result.stderr
        assert _dry_run_commands(result.stdout) == []


@_posix_only
class TestRunEvalLocalTier:
    def _key_file(self, tmp_path: Path) -> Path:
        key = tmp_path / "owui.env"
        key.write_text("OPENWEBUI_API_KEY=test-not-a-real-key\n")
        return key

    def _local(self, tmp_path: Path, tier: str, *args: str) -> subprocess.CompletedProcess:
        return _run_eval(
            tmp_path,
            *args,
            env_overrides={
                "SUMO_EVAL_BACKEND": "local",
                "TIER": tier,
                "SUMO_OWUI_KEY_FILE": str(self._key_file(tmp_path)),
                "SUMO_OWUI_BASE": "http://owui.invalid/api",
            },
        )

    def _reasoning_configs(self) -> set[str]:
        return {
            p.name for p in _configs() if REASONING_MARKER.search(p.read_text(encoding="utf-8"))
        }

    def test_cheap_tier_resolves_local_providers_and_the_unmarked_configs(
        self, tmp_path: Path
    ) -> None:
        result = self._local(tmp_path, "cheap")
        assert result.returncode == 0, result.stderr
        assert "backend=LOCAL tier=CHEAP" in result.stdout
        commands = _dry_run_commands(result.stdout)
        expected = {p.name for p in _configs()} - self._reasoning_configs()
        assert {_config_of(c) for c in commands} == expected
        assert all("--providers file://" in c and "--grader file://" in c for c in commands)
        assert "http://owui.invalid/api" in result.stdout

    def test_reasoning_tier_selects_exactly_the_marked_configs(self, tmp_path: Path) -> None:
        reasoning = self._reasoning_configs()
        assert reasoning, "no config carries the `# local-tier: reasoning` marker"
        result = self._local(tmp_path, "reasoning")
        assert result.returncode == 0, result.stderr
        assert {_config_of(c) for c in _dry_run_commands(result.stdout)} == reasoning

    def test_quality_tier_selects_every_config(self, tmp_path: Path) -> None:
        result = self._local(tmp_path, "quality")
        assert result.returncode == 0, result.stderr
        assert sorted(_config_of(c) for c in _dry_run_commands(result.stdout)) == [
            p.name for p in _configs()
        ]

    def test_missing_key_file_fails_the_preflight(self, tmp_path: Path) -> None:
        result = _run_eval(
            tmp_path,
            env_overrides={
                "SUMO_EVAL_BACKEND": "local",
                "TIER": "cheap",
                "SUMO_OWUI_KEY_FILE": str(tmp_path / "absent.env"),
            },
        )
        assert result.returncode != 0
        assert "OWUI key file not found" in result.stderr
