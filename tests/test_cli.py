# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.cli — the product-grade `analyze` / `status` commands.

The CLI wraps the same #155 service code (`scan_repo`, `load_repo_map`,
`_build_scan_summary`) the MCP tools use; these tests cover success, a
missing-artifact `status`, a stale artifact, and `--json` schema stability.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys as _sys
from pathlib import Path

import pytest

from sumo_qa import cli
from sumo_qa.repo_map_validation import load_repo_map


def _clean_git_env() -> dict[str, str]:
    """Strip GIT_* so a parent process's GIT_DIR / GIT_WORK_TREE (pre-commit's
    stash on `git push`) can't redirect the subprocess's cwd to the wrong repo.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git_init_commit(path: Path) -> str:
    env = _clean_git_env()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], cwd=path, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "commit", "--no-verify", "-q", "-m", "init", "--no-gpg-sign"],
        cwd=path,
        check=True,
        env=env,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, check=True, env=env
    )
    return head.stdout.decode().strip()


def _make_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# demo\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def test_analyze_writes_artifact_and_reports_next_command(tmp_path, capsys):
    """analyze generates a schema-valid `.sumo-qa/repo-map.json` and points the
    user at `sumo-qa status` as the next command."""
    _make_repo(tmp_path)
    rc = cli.main(["analyze", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    assert artifact.is_file()
    # Re-load through the #155 validator: the written artifact must be schema-valid.
    repo_map = load_repo_map(artifact)
    assert repo_map.schema_version == "1.0"
    assert any(n.path == "src/calc.py" for n in repo_map.nodes)
    # Human output names the artifact and the next command.
    assert ".sumo-qa/repo-map.json" in out
    assert "sumo-qa status" in out


def test_analyze_next_command_carries_analyzed_path(tmp_path, monkeypatch, capsys):
    """analyze on an explicit path (!= cwd) suggests `sumo-qa status <that path>`,
    so the next command inspects the repo just analyzed rather than cwd."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo)
    # Run from the parent dir and pass a RELATIVE path, so the only way the
    # suggestion can name the right repo is by resolving it to an absolute path
    # before embedding — proving resolution, not mere string passthrough.
    monkeypatch.chdir(tmp_path)
    rel = "repo"
    resolved = repo.resolve().as_posix()

    # JSON next_command must carry the RESOLVED absolute root, not the relative arg.
    rc = cli.main(["analyze", rel, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["next_command"].startswith("sumo-qa status ")
    suggested = payload["next_command"].split("sumo-qa status ", 1)[1]
    assert suggested == resolved
    # The bare relative arg would NOT inspect the analyzed repo from another cwd.
    assert suggested != rel
    assert Path(suggested).is_absolute()

    # Human "next:" line carries the resolved path too.
    rc = cli.main(["analyze", rel])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"sumo-qa status {resolved}" in out


def test_analyze_json_is_schema_stable(tmp_path, capsys):
    """`analyze --json` emits a parseable document with the stable keys
    automation depends on (artifact_path, schema_version, node counts)."""
    _make_repo(tmp_path)
    rc = cli.main(["analyze", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["command"] == "analyze"
    assert payload["schema_version"] == "1.0"
    assert payload["artifact_path"].endswith(".sumo-qa/repo-map.json")
    assert payload["node_count"] >= 1
    assert isinstance(payload["nodes_by_type"], dict)


def test_analyze_missing_repo_is_actionable(tmp_path, capsys):
    """analyze on a non-existent path exits non-zero with an actionable message,
    not a traceback."""
    missing = tmp_path / "does-not-exist"
    rc = cli.main(["analyze", str(missing)])
    err = capsys.readouterr().err

    assert rc != 0
    assert str(missing) in err
    assert "director" in err.lower()  # "directory" / "not a directory"


def test_analyze_defaults_to_cwd(tmp_path, monkeypatch, capsys):
    """analyze with no path argument scans the current working directory."""
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["analyze"])
    capsys.readouterr()

    assert rc == 0
    assert (tmp_path / ".sumo-qa" / "repo-map.json").is_file()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_missing_artifact_points_at_analyze(tmp_path, capsys):
    """status on a repo with no artifact reports absence and tells the user to
    run `sumo-qa analyze` — the actionable next command."""
    _make_repo(tmp_path)
    rc = cli.main(["status", str(tmp_path)])
    out = capsys.readouterr().out

    # Absent artifact is a reportable state, not a crash.
    assert rc == 0
    assert "sumo-qa analyze" in out
    assert "repo-map.json" in out


def test_status_missing_repo_is_actionable(tmp_path, capsys):
    """status on a non-existent directory is a usage error (exit 2) with an
    actionable message — NOT a "no artifact" report under a dir that doesn't
    exist. Mirrors analyze's guard, for both human and --json modes."""
    missing = tmp_path / "does-not-exist"

    rc = cli.main(["status", str(missing)])
    captured = capsys.readouterr()
    assert rc == 2
    assert str(missing) in captured.err
    assert "director" in captured.err.lower()
    # The misleading "no artifact" state must NOT be emitted to stdout.
    assert captured.out == ""

    # --json mode behaves identically (no JSON "no artifact" envelope emitted).
    rc = cli.main(["status", str(missing), "--json"])
    captured = capsys.readouterr()
    assert rc == 2
    assert str(missing) in captured.err
    assert "director" in captured.err.lower()
    assert captured.out == ""


def test_status_present_fresh_artifact(tmp_path, capsys):
    """status reports schema version and a fresh artifact when the recorded
    git_commit matches HEAD."""
    _make_repo(tmp_path)
    head = _git_init_commit(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    capsys.readouterr()  # drain analyze output

    rc = cli.main(["status", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "1.0" in out
    assert "fresh" in out.lower()
    # Sanity: the artifact really did record the committed HEAD.
    assert load_repo_map(tmp_path / ".sumo-qa" / "repo-map.json").project.git_commit == head


def test_status_stale_artifact_is_flagged_and_suggests_reanalyze(tmp_path, capsys):
    """When the artifact's recorded git_commit differs from HEAD, status flags
    the map as stale and points the user back at `sumo-qa analyze`."""
    _make_repo(tmp_path)
    _git_init_commit(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    capsys.readouterr()
    # Advance HEAD so the recorded commit goes stale.
    (tmp_path / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    second = _git_init_commit(tmp_path)

    rc = cli.main(["status", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "stale" in out.lower()
    assert "sumo-qa analyze" in out
    assert second  # HEAD advanced


def test_status_json_is_schema_stable(tmp_path, capsys):
    """`status --json` emits a parseable document with stable keys
    (artifact_present, schema_version, is_stale, next_command)."""
    _make_repo(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    capsys.readouterr()

    rc = cli.main(["status", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["command"] == "status"
    assert payload["artifact_present"] is True
    assert payload["schema_version"] == "1.0"
    assert "is_stale" in payload
    assert "next_command" in payload


def test_status_corrupt_artifact_reports_and_points_at_analyze(tmp_path, capsys):
    """A present-but-unreadable artifact (schema_version drift) is reported with
    its validation-error kind, and status still points the user at analyze
    instead of crashing."""
    _make_repo(tmp_path)
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    # A structurally-JSON artifact whose schema_version this build rejects.
    artifact.write_text(json.dumps({"schema_version": "9.9"}), encoding="utf-8")

    rc = cli.main(["status", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "could not read" in out.lower()
    assert "sumo-qa analyze" in out


def test_status_corrupt_artifact_json_surfaces_validation_error(tmp_path, capsys):
    """`status --json` on a corrupt artifact sets validation_error to the stable
    error kind and keeps artifact_present True."""
    _make_repo(tmp_path)
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps({"schema_version": "9.9"}), encoding="utf-8")

    rc = cli.main(["status", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["artifact_present"] is True
    assert payload["validation_error"] == "schema_version_mismatch"
    assert payload["schema_version"] is None


def test_status_json_missing_artifact(tmp_path, capsys):
    """`status --json` on a repo with no artifact reports artifact_present=False
    and a next_command without crashing."""
    _make_repo(tmp_path)
    rc = cli.main(["status", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["artifact_present"] is False
    assert payload["schema_version"] is None
    assert "analyze" in payload["next_command"]


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def test_report_persists_run_summary_and_second_run_shows_delta(tmp_path, capsys):
    """Each report run persists a compact run summary; the next run reads it
    and the page carries the run-over-run delta line."""
    _make_repo(tmp_path)
    assert cli.main(["report", str(tmp_path)]) == 0
    summary = tmp_path / ".sumo-qa" / "qa-report-summary.json"
    assert summary.is_file()
    capsys.readouterr()
    assert cli.main(["report", str(tmp_path)]) == 0
    html = (tmp_path / ".sumo-qa" / "qa-report.html").read_text(encoding="utf-8")
    assert 'class="delta"' in html


def test_report_writes_html_artifact_and_reports_next_command(tmp_path, capsys):
    """report generates `.sumo-qa/qa-report.html` and points the user at the
    next command; a repo with no artifacts still succeeds (exit 0) with honest
    not-available states — never an error."""
    _make_repo(tmp_path)
    rc = cli.main(["report", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    artifact = tmp_path / ".sumo-qa" / "qa-report.html"
    assert artifact.is_file()
    assert artifact.read_text(encoding="utf-8").lower().startswith("<!doctype html>")
    assert ".sumo-qa/qa-report.html" in out
    # No repo-map yet → the actionable next step is analyze.
    assert "sumo-qa analyze" in out
    assert "insufficient evidence" in out.lower()


def test_report_json_is_schema_stable(tmp_path, capsys):
    """`report --json` emits a parseable document with the stable keys
    automation depends on."""
    _make_repo(tmp_path)
    rc = cli.main(["report", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["command"] == "report"
    for key in (
        "root",
        "artifact_path",
        "artifact_bytes",
        "readiness_state",
        "readiness_reasons",
        "artifacts",
        "changed_component_count",
        "affected_component_count",
        "related_test_count",
        "risk_count",
        "uncovered_blocker_count",
        "warning_count",
        "next_command",
        "summary",
    ):
        assert key in payload, f"missing stable key {key!r}"
    assert payload["artifact_path"].endswith(".sumo-qa/qa-report.html")
    assert payload["artifacts"]["repo_map"] == "missing"
    assert payload["readiness_state"] == "insufficient_evidence"


def test_report_after_analyze_consumes_the_repo_map(tmp_path, capsys):
    """report on an analyzed repo marks the repo-map available and suggests
    status (artifacts are fresh enough to inspect)."""
    _make_repo(tmp_path)
    _git_init_commit(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    capsys.readouterr()

    rc = cli.main(["report", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["artifacts"]["repo_map"] == "available"
    assert payload["next_command"] == f"sumo-qa status {tmp_path.resolve().as_posix()}"


def test_report_flags_stale_repo_map_and_suggests_reanalyze(tmp_path, capsys):
    """A stale repo-map (recorded commit != HEAD) is flagged in the inventory
    and the next command points back at analyze. Readiness stays
    insufficient_evidence here (no risk ledger / context bundle to assess)."""
    _make_repo(tmp_path)
    _git_init_commit(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    capsys.readouterr()
    (tmp_path / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    _git_init_commit(tmp_path)

    rc = cli.main(["report", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["artifacts"]["repo_map"] == "stale"
    assert payload["readiness_state"] == "insufficient_evidence"
    assert payload["next_command"] == f"sumo-qa analyze {tmp_path.resolve().as_posix()}"


def test_report_missing_repo_is_actionable(tmp_path, capsys):
    """report on a non-existent directory is a usage error (exit 2) with an
    actionable message on stderr, both human and --json modes."""
    missing = tmp_path / "does-not-exist"

    rc = cli.main(["report", str(missing)])
    captured = capsys.readouterr()
    assert rc == 2
    assert str(missing) in captured.err
    assert "director" in captured.err.lower()
    assert captured.out == ""

    rc = cli.main(["report", str(missing), "--json"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""


def test_report_defaults_to_cwd(tmp_path, monkeypatch, capsys):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["report"])
    capsys.readouterr()

    assert rc == 0
    assert (tmp_path / ".sumo-qa" / "qa-report.html").is_file()


def test_report_overwrites_previous_report(tmp_path, capsys):
    """qa-report.html is a regenerated artifact (like repo-map.json): a second
    run replaces it rather than refusing."""
    _make_repo(tmp_path)
    assert cli.main(["report", str(tmp_path)]) == 0
    first = (tmp_path / ".sumo-qa" / "qa-report.html").read_text(encoding="utf-8")
    assert cli.main(["report", str(tmp_path)]) == 0
    second = (tmp_path / ".sumo-qa" / "qa-report.html").read_text(encoding="utf-8")
    capsys.readouterr()
    assert first and second  # both runs produced a page


# ---------------------------------------------------------------------------
# dispatch / host-neutrality
# ---------------------------------------------------------------------------


def test_no_subcommand_prints_help_nonzero(capsys):
    """Bare `sumo-qa` (no subcommand) prints usage and exits non-zero, rather
    than silently doing nothing."""
    rc = cli.main([])
    combined = capsys.readouterr()
    assert rc != 0
    assert "analyze" in (combined.out + combined.err)
    assert "status" in (combined.out + combined.err)


def test_console_main_bare_launches_mcp_server(monkeypatch):
    """Bare `sumo-qa` (no args) must still launch the MCP stdio server — the
    host launch contract `sumo-qa-doctor` and every host config depend on."""
    calls: list[str] = []
    monkeypatch.setattr(_sys, "argv", ["sumo-qa"])
    import sumo_qa.server as server

    monkeypatch.setattr(server, "main", lambda: calls.append("server"))
    cli.console_main()
    assert calls == ["server"]


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_console_main_help_flag_dispatches_to_argparse_not_server(flag, monkeypatch, capsys):
    """`sumo-qa --help` / `-h` must reach argparse (exit 0, prints usage) and
    must NOT fall through to launching the stdio MCP server — which would block
    reading stdin and leave a terminal user with a silent hang."""
    calls: list[str] = []
    monkeypatch.setattr(_sys, "argv", ["sumo-qa", flag])
    import sumo_qa.server as server

    monkeypatch.setattr(server, "main", lambda: calls.append("server"))
    with pytest.raises(SystemExit) as exc:
        cli.console_main()
    out = capsys.readouterr().out
    # argparse prints usage to stdout and exits 0 for an explicit help request.
    assert exc.value.code == 0
    assert "usage" in out.lower()
    assert "analyze" in out
    assert "status" in out
    # The server launch path was never taken.
    assert calls == []


def test_console_main_unknown_token_errors_not_server(monkeypatch, capsys):
    """A mistyped subcommand reaches argparse (exit 2, usage error on stderr),
    not the stdio server — so the user sees an error instead of a silent hang."""
    calls: list[str] = []
    monkeypatch.setattr(_sys, "argv", ["sumo-qa", "analzye"])  # typo
    import sumo_qa.server as server

    monkeypatch.setattr(server, "main", lambda: calls.append("server"))
    with pytest.raises(SystemExit) as exc:
        cli.console_main()
    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "usage" in err.lower()
    assert calls == []


def test_console_main_routes_product_subcommand_to_cli(tmp_path, monkeypatch, capsys):
    """`sumo-qa analyze <path>` is dispatched to the product CLI, not the
    server, and exits 0."""
    _make_repo(tmp_path)
    monkeypatch.setattr(_sys, "argv", ["sumo-qa", "analyze", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        cli.console_main()
    assert exc.value.code == 0
    assert (tmp_path / ".sumo-qa" / "repo-map.json").is_file()


def test_messages_do_not_assume_a_specific_host(tmp_path, capsys):
    """The CLI must not imply a host-specific plugin is installed (AC: host
    neutral). No mention of Claude/Codex/VS Code in analyze/status/report output."""
    _make_repo(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    cli.main(["status", str(tmp_path)])
    cli.main(["report", str(tmp_path)])
    # Scrub the echoed repo path: a tmp dir can itself live under a host-named
    # folder (e.g. /private/tmp/claude-501/...), which is the user's path, not
    # the CLI's own prose. The AC is about the CLI not naming a host of its own.
    text = capsys.readouterr().out.lower().replace(str(tmp_path).lower(), "<root>")
    for host in ("claude", "codex", "vs code", "vscode", "jetbrains", "plugin"):
        assert host not in text


def test_report_unverifiable_bundle_reads_the_same_in_cli_json_and_html(tmp_path, capsys):
    """#401: a non-git root with a fresh-passing bundle that names a head_sha is
    unverifiable. The CLI payload, the human line, and the written HTML all
    carry the same insufficient_evidence state and the same "not verified"
    reason — never ready, never "stale"."""
    bundle = {
        "schema_version": "1.0",
        "head_sha": "a" * 40,
        "test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"},
    }
    target = tmp_path / ".sumo-qa" / "context-bundle.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(bundle), encoding="utf-8")

    assert cli.main(["report", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["readiness_state"] == "insufficient_evidence"
    reasons = " | ".join(payload["readiness_reasons"])
    assert "not verified" in reasons
    assert "stale relative" not in reasons
    assert payload["warning_count"] == 1

    html = (tmp_path / ".sumo-qa" / "qa-report.html").read_text(encoding="utf-8")
    assert "not verified" in html
    assert "could not be determined" in html

    assert cli.main(["report", str(tmp_path)]) == 0
    human = capsys.readouterr().out
    assert "readiness: insufficient evidence" in human
    assert "not verified against the local tree" in human


# ---------------------------------------------------------------------------
# check (#407) — side-effect-free CI readiness gate
# ---------------------------------------------------------------------------

_PASSING_ROW = {
    "risk_id": "R1",
    "risk": "demo regression",
    "source_anchor": "src/demo.py:1",
    "test": "tests/test_demo.py::test_demo",
    "evidence_status": "passing",
    "residual": "mitigated",
}
_ACCEPTED_ROW = {**_PASSING_ROW, "risk_id": "R2", "evidence_status": "accepted_residual",
                 "residual": "accepted"}  # fmt: skip
_BLOCKER_ROW = {**_PASSING_ROW, "risk_id": "R3", "evidence_status": "planned",
                "residual": "blocker", "test": "planned: boundary sweep"}  # fmt: skip


def _write_sumo(root: Path, name: str, payload: dict) -> None:
    target = root / ".sumo-qa" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _fresh_bundle(head_sha: str | None = None) -> dict:
    bundle: dict = {
        "schema_version": "1.0",
        "test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"},
        "ci_status": {"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    }
    if head_sha is not None:
        bundle["head_sha"] = head_sha
    return bundle


def _seed_state(root: Path, state: str) -> None:
    """Seed ``.sumo-qa`` so the scorecard derives ``state`` on a non-git root.
    A bundle with no head_sha has nothing to verify, so a fresh pass is usable."""
    rows = {
        "ready": [_PASSING_ROW],
        "ready_with_accepted_residuals": [_PASSING_ROW, _ACCEPTED_ROW],
        "blocked": [_BLOCKER_ROW],
    }
    if state == "insufficient_evidence":
        return  # an empty repository: nothing to derive readiness from
    _write_sumo(root, "risk-ledger.json", {"schema_version": "1.0", "rows": rows[state]})
    _write_sumo(root, "context-bundle.json", _fresh_bundle())


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# Decision table: readiness state x policy -> passed (issue #407 Policies).
_POLICY_TABLE = [
    ("ready", "strict", True),
    ("ready_with_accepted_residuals", "strict", False),
    ("blocked", "strict", False),
    ("insufficient_evidence", "strict", False),
    ("ready", "allow-accepted-residuals", True),
    ("ready_with_accepted_residuals", "allow-accepted-residuals", True),
    ("blocked", "allow-accepted-residuals", False),
    ("insufficient_evidence", "allow-accepted-residuals", False),
]


# The human messages are part of the output contract alongside the codes.
_CLAUSE_MESSAGES = {
    "accepted_residuals_not_allowed": (
        "accepted residual risks are present; pass --policy allow-accepted-residuals to accept them"
    ),
    "readiness_blocked": "readiness is blocked",
    "readiness_insufficient_evidence": "readiness evidence is missing, stale or unverifiable",
}


@pytest.mark.parametrize("state,policy,passed", _POLICY_TABLE)
def test_evaluate_policy_decision_table(state, policy, passed):
    """Technique: decision tables. Every state x policy cell is pinned; a failed
    result names exactly one stable clause code, a passed one names none."""
    result = cli.evaluate_policy(state, policy)
    assert result.passed is passed
    assert result.policy == policy
    assert result.readiness_state == state
    if passed:
        assert result.failed_clauses == ()
    else:
        expected_code = {
            "ready_with_accepted_residuals": "accepted_residuals_not_allowed",
            "blocked": "readiness_blocked",
            "insufficient_evidence": "readiness_insufficient_evidence",
        }[state]
        assert [c.code for c in result.failed_clauses] == [expected_code]
        assert [c.message for c in result.failed_clauses] == [_CLAUSE_MESSAGES[expected_code]]


@pytest.mark.parametrize("state,policy,passed", _POLICY_TABLE)
def test_check_end_to_end_exit_code_per_state_and_policy(state, policy, passed, tmp_path, capsys):
    _seed_state(tmp_path, state)
    code = cli.main(["check", str(tmp_path), "--policy", policy, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == (0 if passed else 1)
    assert payload["passed"] is passed
    assert payload["readiness_state"] == state
    assert payload["policy"] == policy


def test_check_default_policy_is_strict(tmp_path, capsys):
    _seed_state(tmp_path, "ready_with_accepted_residuals")
    assert cli.main(["check", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["policy"] == "strict"
    assert payload["accepted_residual_count"] == 1
    assert [c["code"] for c in payload["failed_clauses"]] == ["accepted_residuals_not_allowed"]


def test_check_empty_repository_fails_with_complete_versioned_json(tmp_path, capsys):
    assert cli.main(["check", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == cli.CHECK_SCHEMA_VERSION
    assert payload["command"] == "check"
    assert payload["root"] == str(tmp_path.resolve())
    assert payload["passed"] is False
    assert payload["readiness_state"] == "insufficient_evidence"
    assert payload["readiness_reasons"]
    assert payload["failed_clauses"] == [
        {
            "code": "readiness_insufficient_evidence",
            "message": payload["failed_clauses"][0]["message"],
        }
    ]
    assert payload["artifacts"]["risk_ledger"] == "missing"
    assert payload["uncovered_blocker_count"] == 0
    assert payload["accepted_residual_count"] == 0
    assert payload["warnings"] == []
    # Nothing on disk to refresh: no command is invented for missing risk analysis.
    assert payload["corrective_commands"] == []


def test_check_blocked_counts_uncovered_blockers(tmp_path, capsys):
    _seed_state(tmp_path, "blocked")
    assert cli.main(["check", str(tmp_path), "--json", "--policy", "allow-accepted-residuals"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["uncovered_blocker_count"] == 1
    assert [c["code"] for c in payload["failed_clauses"]] == ["readiness_blocked"]


@pytest.mark.parametrize("policy", ["strict", "allow-accepted-residuals"])
def test_check_unverifiable_local_head_fails_both_policies(policy, tmp_path, capsys):
    """#401: a fresh-passing bundle naming a head_sha on a non-git root cannot
    be verified against the local tree, so it cannot pass either policy."""
    _write_sumo(tmp_path, "risk-ledger.json", {"schema_version": "1.0", "rows": [_PASSING_ROW]})
    _write_sumo(tmp_path, "context-bundle.json", _fresh_bundle("a" * 40))
    assert cli.main(["check", str(tmp_path), "--policy", policy, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["readiness_state"] == "insufficient_evidence"
    assert payload["warnings"]
    assert cli.main(["check", str(tmp_path), "--policy", policy]) == 1
    human = capsys.readouterr().out.splitlines()
    for warning in payload["warnings"]:
        assert f"  warning: {warning}" in human


def test_check_stale_bundle_evidence_fails(tmp_path, capsys):
    """A fresh-passing ledger cannot carry a bundle whose test evidence is stale."""
    _write_sumo(tmp_path, "risk-ledger.json", {"schema_version": "1.0", "rows": [_PASSING_ROW]})
    bundle = _fresh_bundle()
    bundle["test_evidence"]["freshness"] = "stale"
    _write_sumo(tmp_path, "context-bundle.json", bundle)
    for policy in ("strict", "allow-accepted-residuals"):
        assert cli.main(["check", str(tmp_path), "--policy", policy, "--json"]) == 1
        assert json.loads(capsys.readouterr().out)["readiness_state"] == "insufficient_evidence"


def test_check_mismatched_bundle_head_fails(tmp_path, capsys):
    _make_repo(tmp_path)
    _git_init_commit(tmp_path)
    _write_sumo(tmp_path, "risk-ledger.json", {"schema_version": "1.0", "rows": [_PASSING_ROW]})
    _write_sumo(tmp_path, "context-bundle.json", _fresh_bundle("b" * 40))
    assert cli.main(["check", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["readiness_state"] == "insufficient_evidence"


@pytest.mark.parametrize("freshness", [None, "stale"])
def test_check_optional_coverage_and_mutation_never_fail(freshness, tmp_path, capsys):
    """Coverage/mutation are reported, never gated: absent or stale, a ready
    repo still passes."""
    _seed_state(tmp_path, "ready")
    if freshness is not None:
        base = {"schema_version": "1.0", "generated_at": "2026-06-08T00:00:00Z",
                "freshness": freshness}  # fmt: skip
        _write_sumo(tmp_path, "coverage.json",
                    {**base, "source_tool": "pytest-cov", "line_percent": 40.0})  # fmt: skip
        _write_sumo(tmp_path, "mutation.json",
                    {**base, "source_tool": "mutmut", "survivors": 9, "killed": 1})  # fmt: skip
    assert cli.main(["check", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    expected = "missing" if freshness is None else "stale"
    assert payload["artifacts"]["coverage"] == expected
    assert payload["artifacts"]["mutation"] == expected


def _write_stale_repo_map(root: Path) -> None:
    _make_repo(root)
    _git_init_commit(root)
    repo_map = {
        "schema_version": "1.0",
        "project": {"root": str(root), "name": "demo", "git_commit": "c" * 40,
                    "generated_at": "2026-06-01T12:00:00+00:00", "generator_version": "0"},
        "nodes": [], "edges": [], "commands": [], "warnings": [],
    }  # fmt: skip
    _write_sumo(root, "repo-map.json", repo_map)


def test_check_stale_repo_map_names_the_refresh_command(tmp_path, capsys):
    _write_stale_repo_map(tmp_path)
    assert cli.main(["check", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts"]["repo_map"] == "stale"
    analyze = f"sumo-qa analyze {tmp_path.resolve().as_posix()}"
    assert payload["corrective_commands"] == [analyze]
    assert cli.main(["check", str(tmp_path)]) == 1
    assert f"  next: {analyze}" in capsys.readouterr().out.splitlines()


def test_check_invalid_repo_map_names_the_refresh_command(tmp_path, capsys):
    (tmp_path / ".sumo-qa").mkdir()
    (tmp_path / ".sumo-qa" / "repo-map.json").write_text("{not json", encoding="utf-8")
    assert cli.main(["check", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts"]["repo_map"] == "invalid"
    assert payload["corrective_commands"] == [f"sumo-qa analyze {tmp_path.resolve().as_posix()}"]


def test_check_corrective_command_quotes_a_path_with_shell_metacharacters(tmp_path, capsys):
    """Copied into a shell, the command still targets the one repository path."""
    root = tmp_path / "my repo $HOME"
    root.mkdir()
    _write_stale_repo_map(root)
    assert cli.main(["check", str(root), "--json"]) == 1
    [command] = json.loads(capsys.readouterr().out)["corrective_commands"]
    assert shlex.split(command) == ["sumo-qa", "analyze", root.resolve().as_posix()]


def test_every_next_command_quotes_a_path_with_shell_metacharacters(tmp_path, capsys):
    """status, analyze and report suggest follow-ups the same way check does."""
    root = tmp_path / "my repo $HOME"
    root.mkdir()
    path = root.resolve().as_posix()
    for argv, expected in (
        (["status"], ["sumo-qa", "analyze", path]),
        (["analyze"], ["sumo-qa", "status", path]),
        (["report"], ["sumo-qa", "status", path]),
    ):
        assert cli.main([*argv, str(root), "--json"]) == 0
        assert shlex.split(json.loads(capsys.readouterr().out)["next_command"]) == expected


def test_check_passing_policy_suggests_no_command_even_with_a_stale_repo_map(tmp_path, capsys):
    """The repo-map is inventory, not a gate: a stale map neither fails a ready
    repo nor attaches a corrective command to a pass."""
    _write_stale_repo_map(tmp_path)
    _seed_state(tmp_path, "ready")
    assert cli.main(["check", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts"]["repo_map"] == "stale"
    assert payload["corrective_commands"] == []


@pytest.mark.parametrize("state", ["ready", "insufficient_evidence", "blocked"])
def test_check_performs_no_writes(state, tmp_path):
    _seed_state(tmp_path, state)
    before = _snapshot(tmp_path)
    cli.main(["check", str(tmp_path)])
    cli.main(["check", str(tmp_path), "--json"])
    assert _snapshot(tmp_path) == before
    if state == "insufficient_evidence":
        assert not (tmp_path / ".sumo-qa").exists()


def test_check_human_output_projects_the_same_result_as_json(tmp_path, capsys):
    _seed_state(tmp_path, "blocked")
    assert cli.main(["check", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert cli.main(["check", str(tmp_path)]) == 1
    human = capsys.readouterr().out
    first = human.splitlines()[0]
    assert first.startswith("FAIL")
    assert "policy: strict" in first
    assert "readiness: blocked" in first
    for clause in payload["failed_clauses"]:
        assert clause["message"] in human
    for reason in payload["readiness_reasons"]:
        assert reason in human
    assert "next:" not in human  # no corrective command is known here


def test_check_human_pass_line(tmp_path, capsys):
    _seed_state(tmp_path, "ready")
    assert cli.main(["check", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        "PASS sumo-qa check (policy: strict, readiness: ready)"
    )


def test_check_missing_directory_exits_2(tmp_path, capsys):
    assert cli.main(["check", str(tmp_path / "nope"), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not a directory" in captured.err
