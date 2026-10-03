# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the deterministic context-cost audit.

The shipped budgets must pass (so the full suite enforces them as well as the
CI job), and a config whose budgets are exceeded must fail naming each area.
An absent budget is report-only.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the audit runs the bash SessionStart hook (Linux/macOS CI)",
)


def _repo_root() -> Path:
    """Anchor on ``.git`` so the mutmut copy under ``mutants/`` still finds the
    real hooks/ and skills/ (see tests/test_check_no_em_dashes.py)."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


REPO = _repo_root()


def _load_audit():
    path = REPO / "scripts" / "audit_context_budget.py"
    spec = importlib.util.spec_from_file_location("audit_context_budget", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_mod = _load_audit()


def test_resent_tokens_counts_each_result_on_every_later_turn():
    # results of 1, 2, 3 tokens: turn 1 sends 1, turn 2 sends 1+2, turn 3 sends 1+2+3.
    assert audit_mod.resent_tokens([1, 2, 3]) == 1 + 3 + 6


def test_bootstrap_measurement_does_not_depend_on_the_clone_path(tmp_path):
    measured = []
    for clone in (tmp_path / "a", tmp_path / "a-much-longer-clone-directory-name"):
        shutil.copytree(REPO / "hooks", clone / "hooks")
        skill = clone / "skills" / "using-sumo-qa"
        skill.mkdir(parents=True)
        shutil.copy(REPO / "skills" / "using-sumo-qa" / "SKILL.md", skill / "SKILL.md")
        measured.append(audit_mod.measure_bootstrap(clone, "compact"))
    assert measured[0] == measured[1]
    assert f"{audit_mod.STAND_IN_ROOT}/skills/using-sumo-qa/SKILL.md" in measured[0]


def test_shipped_budgets_pass_and_report_every_area(capsys):
    assert audit_mod.main([]) == 0
    out = capsys.readouterr().out
    assert "context budget: OK" in out

    rows, failures = audit_mod.audit(audit_mod.load_config(REPO / "pyproject.toml"), REPO)
    assert not failures
    by_area = {r["area"] for r in rows}
    assert by_area == {"bootstrap", "tools/list", "root skill", "bundle", "workflow"}
    compact = next(r for r in rows if r["name"] == "compact (default)")
    assert compact["tokens"] <= 1000
    roots = [r for r in rows if r["area"] == "root skill"]
    assert {r["name"] for r in roots} == {p.parent.name for p in REPO.glob("skills/*/SKILL.md")}
    assert all(r["budget"] is None for r in roots)  # no root budget shipped: report-only
    flows = [r for r in rows if r["area"] == "workflow"]
    for per_loader, bundled in zip(flows[::2], flows[1::2], strict=True):
        assert bundled["calls"] < per_loader["calls"]
        assert bundled["resent"] < per_loader["resent"]


def test_exceeded_budgets_fail_naming_each_area(tmp_path, capsys):
    config = tmp_path / "budget.toml"
    config.write_text(
        """
[tool.sumo-qa.context-budget]
bootstrap = 10
tools_list = 10
root_skill = 10

[[tool.sumo-qa.context-budget.workflow]]
name = "tight"
skill = "sumo-qa-reviewing-before-merge"
classification = "test_change"
modules = "test-only-diff"
bundle = 10

[[tool.sumo-qa.context-budget.workflow]]
name = "broken"
skill = "sumo-qa-reviewing-before-merge"
classification = "test_change"
modules = "no-such-module"
""",
        encoding="utf-8",
    )
    assert audit_mod.main(["--config", str(config)]) == 1
    out = capsys.readouterr().out
    assert "FAIL bootstrap compact (default)" in out
    assert "FAIL tools/list" in out
    assert "FAIL root skill using-sumo-qa" in out
    assert "FAIL bundle tight" in out
    assert "FAIL workflow broken: bundle failed" in out
    assert "context budget: FAILED" in out
