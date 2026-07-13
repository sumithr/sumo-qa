# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the shared mutation-gate verdict script.

The gate script exists because `mutmut run` exits 0 even when mutants
survive (root-caused 2026-07-13; PR #302's 47 survivors reached main through
a pre-push hook that trusted mutmut's exit code). These tests pin the verdict
semantics both the nightly workflow and the pre-push hook rely on: a wrong
verdict here silently greenlights weak tests.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


def _load_gate():
    path = _repo_root() / "scripts" / "check_mutation_gate.py"
    spec = importlib.util.spec_from_file_location("check_mutation_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _write_fixtures(tmp_path, baseline, metas):
    baseline_path = tmp_path / "mutmut-baseline.json"
    baseline_path.write_text(json.dumps({"per_module": baseline}), encoding="utf-8")
    meta_root = tmp_path / "mutants" / "src" / "sumo_qa"
    meta_root.mkdir(parents=True)
    for module, exit_codes in metas.items():
        (meta_root / f"{module}.py.meta").write_text(
            json.dumps({"exit_code_by_key": exit_codes}), encoding="utf-8"
        )
    return ["--baseline", str(baseline_path), "--meta-root", str(meta_root)]


def test_all_killed_at_baseline_passes(tmp_path, capsys):
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 2}},
        {"mod": {"m1": 1, "m2": 3}},
    )
    assert gate.main(argv) == 0
    out = capsys.readouterr().out
    assert "| mod | 2 | 2 | 0 | OK |" in out
    assert "Strict gate passed" in out


def test_survivor_fails_and_is_named(tmp_path, capsys):
    """The load-bearing case: mutmut itself exits 0 on survivors, so the gate
    MUST fail from the .meta contents alone."""
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 1}},
        {"mod": {"m_killed": 1, "m_survivor": 0}},
    )
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "| mod | 1 | 1 | 1 | SURVIVED |" in out
    assert "100% kill rate required" in out
    assert "m_survivor" in out  # triage can start without re-running mutmut


def test_killed_drop_below_baseline_fails(tmp_path, capsys):
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 3}},
        {"mod": {"m1": 1, "m2": 34}},  # 1 killed, 1 skipped
    )
    assert gate.main(argv) == 1
    assert "killed dropped from 3 -> 1" in capsys.readouterr().out


def test_missing_meta_file_fails(tmp_path, capsys):
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 1}}, {})
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "| mod | 1 | 0 | 0 | MISSING |" in out
    assert "did mutmut run complete" in out


def test_skipped_and_timeout_codes_do_not_count_as_survivors(tmp_path, capsys):
    """Only exit code 0 is a survivor; 34 (skipped) and 36 (timeout) are not,
    and the full killed set is exactly {1, 3, -24}."""
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 3}},
        {"mod": {"m1": 1, "m2": 3, "m3": -24, "m4": 34, "m5": 36}},
    )
    assert gate.main(argv) == 0
    assert "| mod | 3 | 3 | 0 | OK |" in capsys.readouterr().out


def test_github_step_summary_written_when_env_set(tmp_path, monkeypatch):
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 1}}, {"mod": {"m1": 1}})
    assert gate.main(argv) == 0
    assert "## Mutation gate" in summary_file.read_text(encoding="utf-8")


def test_crashed_mutmut_run_propagates_without_judging_stale_meta(tmp_path, monkeypatch, capsys):
    """--run-mutmut with a non-zero mutmut exit must NOT read .meta files:
    a crashed run leaves stale results, and judging them is a false verdict."""
    calls = {}

    def fake_run(cmd):
        calls["cmd"] = cmd

        class R:
            returncode = 7

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    # No baseline/meta fixtures on purpose: reading them would raise.
    assert gate.main(["--run-mutmut", "--max-children", "1"]) == 7
    assert calls["cmd"] == ["mutmut", "run", "--max-children", "1"]
    assert "not judging stale .meta files" in capsys.readouterr().err
