# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Suite-wide test isolation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from sumo_qa.tool_registry import PROFILE_ENV


def pytest_configure(config):
    """``build_mcp_server()`` and the installer read the tool profile from the
    environment, then from the saved profile file under the global data dir, so
    a caller's exported value or saved file would silently change what every
    test builds. Clearing the env var and pointing ``XDG_DATA_HOME`` at an empty
    temp dir here runs before collection-time imports and every fixture scope;
    tests that need a profile set it explicitly."""
    os.environ.pop(PROFILE_ENV, None)
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="sumo-qa-test-data-")


@pytest.fixture(autouse=True)
def _empty_saved_profile(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:
    """A fresh global data dir per test, so a profile one test saves never
    reaches another."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path_factory.mktemp("xdg-data")))


@pytest.fixture
def _empty_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp HOME with no Claude Code registry, so nothing reads the real
    ``~/.claude.json`` (``Path.home()``, ``HOME``/``USERPROFILE`` for
    subprocesses, and no ``CLAUDE_CONFIG_DIR``)."""
    home = tmp_path / "isolated-home"  # tests use tmp_path and tmp_path/"home" themselves
    home.mkdir()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


@pytest.fixture(autouse=True)
def _isolate_doctor_and_installer_home(request: pytest.FixtureRequest) -> None:
    """The doctor and installer read Claude Code's registry and host configs
    from HOME, so their test modules always run in ``_empty_claude_home``."""
    if request.module.__name__.rpartition(".")[2].startswith(("test_doctor", "test_installer")):
        request.getfixturevalue("_empty_claude_home")
