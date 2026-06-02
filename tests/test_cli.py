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
    neutral). No mention of Claude/Codex/VS Code in analyze/status output."""
    _make_repo(tmp_path)
    cli.main(["analyze", str(tmp_path)])
    cli.main(["status", str(tmp_path)])
    # Scrub the echoed repo path: a tmp dir can itself live under a host-named
    # folder (e.g. /private/tmp/claude-501/...), which is the user's path, not
    # the CLI's own prose. The AC is about the CLI not naming a host of its own.
    text = capsys.readouterr().out.lower().replace(str(tmp_path).lower(), "<root>")
    for host in ("claude", "codex", "vs code", "vscode", "jetbrains", "plugin"):
        assert host not in text
