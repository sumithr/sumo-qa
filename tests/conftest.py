# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Suite-wide test isolation."""

from __future__ import annotations

import pytest

from sumo_qa.tool_registry import PROFILE_ENV


@pytest.fixture(autouse=True)
def _no_ambient_mcp_profile(monkeypatch):
    """``build_mcp_server()`` reads the tool profile from the environment, so a
    caller's exported value would silently change what every test builds."""
    monkeypatch.delenv(PROFILE_ENV, raising=False)
