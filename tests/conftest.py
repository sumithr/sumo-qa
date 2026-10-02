# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Suite-wide test isolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sumo_qa.tool_registry import PROFILE_ENV


def pytest_configure(config):
    """``build_mcp_server()`` and the installer read the tool profile from the
    environment, so a caller's exported value would silently change what every
    test builds. Clearing it here runs before collection-time imports and every
    fixture scope; tests that need a profile set it explicitly."""
    os.environ.pop(PROFILE_ENV, None)


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
