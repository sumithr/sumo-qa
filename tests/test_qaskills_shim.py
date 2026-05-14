# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from sumo_qa import qaskills


def _completed_process(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_is_available_returns_true_when_npx_present() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx") as mock_which:
        assert qaskills.is_available() is True
    mock_which.assert_called_once_with("npx")


def test_is_available_returns_false_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        assert qaskills.is_available() is False


def test_search_parses_json_output_into_matches() -> None:
    fake_stdout = json.dumps(
        [
            {"name": "playwright-e2e", "publisher": "thetestingacademy", "score": 92, "description": "Playwright E2E"},
            {"name": "cypress-e2e", "publisher": "someoneelse", "score": 84, "description": "Cypress E2E"},
        ]
    )
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(fake_stdout)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        matches = qaskills.search("e2e playwright")

    assert len(matches) == 2
    assert matches[0].name == "playwright-e2e"
    assert matches[0].publisher == "thetestingacademy"
    assert matches[0].score == 92
    assert matches[0].description == "Playwright E2E"


def test_search_raises_node_not_found_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        with pytest.raises(qaskills.NodeNotFoundError):
            qaskills.search("anything")


def test_search_raises_cli_error_on_nonzero_exit() -> None:
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("", returncode=2, stderr="boom")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.search("anything")
    assert "boom" in str(exc_info.value)


def test_search_handles_non_json_stdout_gracefully() -> None:
    # Defensive: if the CLI ever drops a non-JSON line, we surface a clean error
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("not json")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError):
            qaskills.search("anything")


def test_info_returns_full_skill_record() -> None:
    fake_stdout = json.dumps(
        {
            "name": "playwright-e2e",
            "publisher": "thetestingacademy",
            "score": 92,
            "description": "Playwright E2E",
            "skill_md": "---\nname: playwright-e2e\n---\n# Body\n",
            "mcp_servers": ["playwright-mcp"],
        }
    )
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(fake_stdout)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        info = qaskills.info("playwright-e2e")

    assert info.name == "playwright-e2e"
    assert info.publisher == "thetestingacademy"
    assert info.score == 92
    assert info.skill_md.startswith("---")
    assert info.mcp_servers == ("playwright-mcp",)


def test_info_returns_no_mcp_servers_when_absent() -> None:
    fake_stdout = json.dumps(
        {
            "name": "axe-accessibility",
            "publisher": "thetestingacademy",
            "score": 88,
            "description": "Axe",
            "skill_md": "no mcp here",
        }
    )
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(fake_stdout)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        info = qaskills.info("axe-accessibility")

    assert info.mcp_servers == ()


def test_info_returns_no_mcp_servers_when_value_is_null() -> None:
    fake_stdout = json.dumps(
        {
            "name": "axe-accessibility",
            "publisher": "thetestingacademy",
            "score": 88,
            "description": "Axe",
            "skill_md": "no mcp here",
            "mcp_servers": None,
        }
    )
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(fake_stdout)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        info = qaskills.info("axe-accessibility")

    assert info.mcp_servers == ()


def test_info_raises_node_not_found_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        with pytest.raises(qaskills.NodeNotFoundError):
            qaskills.info("anything")


def test_info_raises_cli_error_on_nonzero_exit_with_name_in_message() -> None:
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("", returncode=2, stderr="boom")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.info("playwright-e2e")
    assert "playwright-e2e" in str(exc_info.value)
    assert "boom" in str(exc_info.value)


def test_info_raises_cli_error_on_non_json_stdout() -> None:
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("not json")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError):
            qaskills.info("anything")
