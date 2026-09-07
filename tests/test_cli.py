# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.cli — the product-grade `analyze` / `status` commands.

The CLI wraps the same #155 service code (`scan_repo`, `load_repo_map`,
`_build_scan_summary`) the MCP tools use; these tests cover success, a
missing-artifact `status`, a stale artifact, and `--json` schema stability.
"""

from __future__ import annotations

import json
import os
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
