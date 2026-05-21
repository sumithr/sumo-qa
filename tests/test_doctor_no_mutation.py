# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Doctor must never mutate host config files.

Snapshots every host-config path before invoking ``main()``, runs doctor,
snapshots again, and asserts no diff. Catches accidental regressions —
e.g. someone refactors and accidentally wires installer's mutating
``_setup_claude_code`` into the doctor's collect step.

This is a smoke-grade invariant test: it doesn't simulate every check
state, just that across one realistic ``main()`` run with a populated
fake $HOME, no file on disk is touched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sumo_qa import doctor


def _snapshot(paths: list[Path]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for p in paths:
        if p.exists():
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            out[str(p)] = None
    return out


def _stub_handshake_ok(_cmd: Any) -> tuple[doctor.CheckResult, doctor.CheckResult]:
    """Replace ``run_mcp_probe`` so the no-mutation test doesn't spawn a
    subprocess. The subprocess path is exhaustively covered in
    ``test_doctor.py`` via _FakeProc.
    """
    return (
        doctor.CheckResult("mcp_handshake", "OK", "stub"),
        doctor.CheckResult("tools_list_complete", "OK", "stub"),
    )


def test_doctor_does_not_mutate_host_configs(tmp_path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    # Populate every config the doctor inspects, with realistic shapes.
    claude_code_cfg = home / ".config" / "claude" / "claude_desktop_config.json"
    claude_code_cfg.parent.mkdir(parents=True)
    claude_code_cfg.write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": "/missing"}}}),
        encoding="utf-8",
    )
    (home / ".claude").mkdir()

    # On case-insensitive filesystems (macOS default APFS, Windows NTFS), the
    # Claude Code path (.config/claude/) and Claude Desktop path (.config/Claude/)
    # collide and resolve to the same directory. Use exist_ok=True so the test
    # is portable across both case-sensitive (most Linux) and case-insensitive
    # filesystems — the invariant we want to assert (no mutation) holds either way.
    claude_desktop_cfg = home / ".config" / "Claude" / "claude_desktop_config.json"
    claude_desktop_cfg.parent.mkdir(parents=True, exist_ok=True)
    if not claude_desktop_cfg.exists():
        claude_desktop_cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    vscode_cfg = workspace / ".vscode" / "mcp.json"
    vscode_cfg.parent.mkdir(parents=True)
    vscode_cfg.write_text(json.dumps({"servers": {}}), encoding="utf-8")

    user_vscode_cfg = home / ".vscode" / "mcp.json"
    user_vscode_cfg.parent.mkdir(parents=True)
    user_vscode_cfg.write_text("{}", encoding="utf-8")

    jb_options = home / ".config" / "JetBrains" / "IntelliJIdea2026.1" / "options"
    jb_options.mkdir(parents=True)

    monitored = [
        claude_code_cfg,
        claude_desktop_cfg,
        vscode_cfg,
        user_vscode_cfg,
    ]

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(doctor, "run_mcp_probe", _stub_handshake_ok)

    before = _snapshot(monitored)
    doctor.main(["--workspace", str(workspace)])
    after = _snapshot(monitored)

    capsys.readouterr()  # consume stdout
    assert before == after, "doctor mutated one or more host config files"


def test_doctor_does_not_create_files(tmp_path, monkeypatch, capsys) -> None:
    """The complement of the snapshot test: doctor must not CREATE new
    config files either. Records every direct child of ``home`` and
    ``workspace`` before and after, asserts the lists match.
    """
    home = tmp_path / "home2"
    home.mkdir()
    workspace = tmp_path / "ws2"
    workspace.mkdir()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(doctor, "run_mcp_probe", _stub_handshake_ok)

    before_home = sorted(p.name for p in home.iterdir())
    before_ws = sorted(p.name for p in workspace.iterdir())

    doctor.main(["--workspace", str(workspace)])
    capsys.readouterr()

    after_home = sorted(p.name for p in home.iterdir())
    after_ws = sorted(p.name for p in workspace.iterdir())
    assert before_home == after_home, "doctor created files in $HOME"
    assert before_ws == after_ws, "doctor created files in workspace"
