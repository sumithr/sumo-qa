# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the deterministic context-cost audit.

The shipped budgets must pass (so the full suite enforces them as well as the
CI job), and a config whose budgets are exceeded must fail naming each area.
An absent budget is report-only.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

from sumo_qa.tool_registry import GROUPS, PROFILE_ENV, PROFILES, TOOLS, profile_tool_names

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
    assert by_area == {
        "bootstrap",
        "tools/list",
        "tool group",
        "root skill",
        "bundle",
        "workflow",
        "end-to-end",
    }
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
tools_list = { core = 10, full = 10 }
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
    assert "FAIL tools/list core" in out
    assert "FAIL tools/list full" in out
    assert "FAIL root skill using-sumo-qa" in out
    assert "FAIL bundle tight" in out
    assert "FAIL workflow broken: bundle failed" in out
    assert "context budget: FAILED" in out


@pytest.fixture(scope="module")
def shipped_rows():
    rows, _ = audit_mod.audit(audit_mod.load_config(REPO / "pyproject.toml"), REPO)
    return rows


def test_tools_list_is_measured_per_profile_with_its_registry_tool_count(shipped_rows):
    lists = {r["profile"]: r for r in shipped_rows if r["area"] == "tools/list"}
    assert set(lists) == set(PROFILES)
    for profile, r in lists.items():
        assert r["name"] == f"{profile}: {len(profile_tool_names(profile))} tools"
        assert r["budget"] is not None  # every profile ships a budget
    assert lists["core"]["tokens"] < lists["full"]["tokens"]


def test_core_budget_fails_one_token_below_its_measurement(shipped_rows, tmp_path):
    # boundary value analysis: a budget equal to the measured core cost passes,
    # one token less fails, and only the core row is named.
    core = next(r for r in shipped_rows if r["area"] == "tools/list" and r["profile"] == "core")
    for budget, failed in ((core["tokens"], False), (core["tokens"] - 1, True)):
        _, failures = audit_mod.audit({"tools_list": {"core": budget}}, REPO)
        assert any(f.startswith("tools/list core:") for f in failures) is failed
        assert not any(f.startswith("tools/list full:") for f in failures)


def test_groups_partition_the_served_full_list(shipped_rows):
    groups = {r["group"]: r for r in shipped_rows if r["area"] == "tool group"}
    assert set(groups) == set(GROUPS)
    for r in groups.values():
        assert r["name"] == f"{r['group']}: {r['tools']} tools ({r['core']} core)"
        assert 0 < r["desc"] < r["tokens"]
        assert 0 < r["schema"] < r["tokens"]
    from sumo_qa.server import build_mcp_server

    served = [t.name for t in asyncio.run(build_mcp_server().list_tools())]
    group_of = {t.name: t.group for t in TOOLS}
    for group, r in groups.items():
        assert r["tools"] == sum(group_of.get(n) == group for n in served)
    assert all(group_of.get(n) in groups for n in served)  # each served tool in one group
    assert sum(r["tools"] for r in groups.values()) == len(served)
    full = next(r for r in shipped_rows if r["area"] == "tools/list" and r["profile"] == "full")
    # the groups partition the full list: their costs sum to it, give or take
    # one token of rounding per group
    assert abs(sum(r["tokens"] for r in groups.values()) - full["tokens"]) <= len(GROUPS)


def test_workflow_calling_a_tool_not_served_under_core_fails_a_named_row():
    from sumo_qa.server import build_mcp_server

    full_only = sorted(profile_tool_names("full") - profile_tool_names("core"))[0]
    with mock.patch.dict(os.environ, {PROFILE_ENV: "full"}):
        full_served = {t.name for t in asyncio.run(build_mcp_server().list_tools())}
    assert full_only in full_served  # the live full server serves it, so the failure is the profile
    assert full_only not in profile_tool_names("core")
    wf = {
        "name": "unservable",
        "skill": full_only.replace("_", "-"),  # the chain calls skill.replace("-", "_")
        "classification": "test_change",
    }
    _, failures = audit_mod.audit({"workflow": [wf]}, REPO)
    assert any(
        f.startswith("workflow unservable:")
        and f"tool {full_only} failed" in f
        and "profile core" in f
        and "Unknown tool" in f
        for f in failures
    )


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"tools_list": 9400}, "must be a table keyed by profile"),
        ({"tools_list": {"core": 1, "huge": 2}}, r"unknown profile\(s\) huge"),
        ({"tools_list": {"core": "9400"}}, "tools_list core must be a positive integer"),
        ({"bootstrap": "1000"}, "bootstrap must be a positive integer"),
        ({"root_skill": 0}, "root_skill must be a positive integer"),
        (
            {"workflow": [{"name": "w", "skill": "s", "classification": "c", "bundle": "x"}]},
            r"workflow\[0\] bundle must be a positive integer",
        ),
        ({"workflow": [{"name": "w", "skill": "s"}]}, "requires a non-empty string classification"),
        ({"workflow": {"name": "w"}}, "workflow must be an array of tables"),
        ({"workflow": ["w"]}, r"workflow\[0\] must be a table"),
        (
            {"workflow": [{"name": "w", "skill": "s", "classification": "c", "modules": ["m"]}]},
            r"workflow\[0\] modules must be a string",
        ),
        (
            {"workflow": [{"name": "w", "skill": "", "classification": "c"}]},
            "requires a non-empty string skill",
        ),
        ({"workflow": [{"name": "w", "classification": "c"}]}, "requires a non-empty string skill"),
        ({"workflow": [{"skill": "s", "classification": "c"}]}, "requires a non-empty string name"),
    ],
)
def test_invalid_config_is_a_clear_error_before_anything_runs(config, message, monkeypatch):
    def must_not_run(*_args, **_kwargs):
        pytest.fail("validation must run before anything is measured or built")

    monkeypatch.setattr(audit_mod, "measure_bootstrap", must_not_run)
    monkeypatch.setattr("sumo_qa.server.build_mcp_server", must_not_run)
    with pytest.raises(audit_mod.ConfigError, match=message):
        audit_mod.audit(config, REPO)


def test_invalid_config_exits_with_a_config_error(tmp_path, capsys):
    config = tmp_path / "budget.toml"
    config.write_text('[tool.sumo-qa.context-budget]\ntools_list = { core = "9400" }\n')
    assert audit_mod.main(["--config", str(config)]) == 2
    assert "config error: context-budget tools_list core must be" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("tools_list = {", "is not valid TOML"),
        ("[tool.other]\nx = 1\n", r"no \[tool.sumo-qa.context-budget\] table"),
    ],
)
def test_unreadable_config_file_exits_with_a_config_error(text, message, tmp_path, capsys):
    config = tmp_path / "budget.toml"
    config.write_text(text)
    assert audit_mod.main(["--config", str(config)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("config error:")
    assert re.search(message, err)


@pytest.mark.parametrize(
    "text",
    [None, "tool = 1\n", "[tool]\nsumo-qa = 1\n", "[tool.sumo-qa]\ncontext-budget = 5\n"],
    ids=["missing-file", "tool-not-table", "sumo-qa-not-table", "budget-not-table"],
)
def test_malformed_config_shape_exits_with_a_config_error(text, tmp_path, capsys):
    config = tmp_path / "budget.toml"
    if text is not None:
        config.write_text(text)
    assert audit_mod.main(["--config", str(config)]) == 2
    assert capsys.readouterr().err.startswith("config error:")


@pytest.mark.skipif(
    audit_mod.UnexpectedToolError is None,
    reason="mcp.server.mcpserver.exceptions has no UnexpectedToolError on this mcp version",
)
def test_a_crash_inside_a_tool_is_not_reported_as_unservable():
    class Crashing:
        async def call_tool(self, name, args):
            raise audit_mod.UnexpectedToolError("boom")

    with pytest.raises(audit_mod.UnexpectedToolError):
        audit_mod._run(Crashing(), [("t", {})], "core")


def test_a_non_config_value_error_propagates(monkeypatch):
    def boom(*_args):
        raise ValueError("hook output was not JSON")

    monkeypatch.setattr(audit_mod, "measure_bootstrap", boom)
    with pytest.raises(ValueError, match="hook output") as exc:
        audit_mod.main([])
    assert not isinstance(exc.value, audit_mod.ConfigError)


def test_end_to_end_workflow_costs_less_under_core(shipped_rows):
    e2e = [r for r in shipped_rows if r["area"] == "end-to-end"]
    flows = {r["workflow"] for r in e2e}
    assert flows == {w["name"] for w in audit_mod.load_config(REPO / "pyproject.toml")["workflow"]}
    for flow in flows:
        by_profile = {r["profile"]: r for r in e2e if r["workflow"] == flow}
        assert set(by_profile) == set(PROFILES)
        assert by_profile["core"]["calls"] == by_profile["full"]["calls"]
        assert by_profile["core"]["tokens"] < by_profile["full"]["tokens"]
        assert by_profile["core"]["resent"] < by_profile["full"]["resent"]
