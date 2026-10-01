# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Exact process exit codes and stdout for ``sumo-qa check`` (#407).

Kept apart from tests/test_cli.py so that module stays inside the mutation gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# mutmut-subprocess-spawning: spawns ``python -m sumo_qa.cli`` from a fresh
# interpreter, so it MUST be excluded from the mutmut gate via
# [tool.mutmut].pytest_add_cli_args in pyproject.toml. Otherwise the subprocess
# imports trampoline-injected modules without MUTANT_UNDER_TEST and crashes.


_SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # The pre-commit hook venv imports sumo_qa from the source tree, not an
    # install, so the child interpreter needs src/ on its path too.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_SRC}{os.pathsep}{existing}" if existing else _SRC
    return subprocess.run(
        [sys.executable, "-m", "sumo_qa.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _seed_ready(root: Path) -> None:
    sumo = root / ".sumo-qa"
    sumo.mkdir(parents=True)
    row = {
        "risk_id": "R1",
        "risk": "demo regression",
        "source_anchor": "src/demo.py:1",
        "test": "tests/test_demo.py::test_demo",
        "evidence_status": "passing",
        "residual": "mitigated",
    }
    fresh = {"result": "passing", "freshness": "fresh"}
    bundle = {
        "schema_version": "1.0",
        "test_evidence": {**fresh, "source": "local_git"},
        "ci_status": {**fresh, "source": "ci_provider"},
    }
    (sumo / "risk-ledger.json").write_text(json.dumps({"schema_version": "1.0", "rows": [row]}))
    (sumo / "context-bundle.json").write_text(json.dumps(bundle))


def test_check_policy_failure_exits_1_with_complete_json(tmp_path):
    result = _run_cli("check", str(tmp_path), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert payload["readiness_state"] == "insufficient_evidence"


def test_check_policy_pass_exits_0(tmp_path):
    _seed_ready(tmp_path)
    result = _run_cli("check", str(tmp_path), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["passed"] is True


def test_check_unknown_policy_exits_2_without_a_result(tmp_path):
    result = _run_cli("check", str(tmp_path), "--policy", "no-blockers")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_check_missing_directory_exits_2(tmp_path):
    result = _run_cli("check", str(tmp_path / "nope"), "--json")
    assert result.returncode == 2
    assert result.stdout == ""
