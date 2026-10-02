# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Suite-wide test isolation."""

from __future__ import annotations

import os

from sumo_qa.tool_registry import PROFILE_ENV


def pytest_configure(config):
    """``build_mcp_server()`` and the installer read the tool profile from the
    environment, so a caller's exported value would silently change what every
    test builds. Clearing it here runs before collection-time imports and every
    fixture scope; tests that need a profile set it explicitly."""
    os.environ.pop(PROFILE_ENV, None)
