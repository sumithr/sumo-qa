# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests that installer.py uses PluginMetadata instead of hardcoded literals.

Regression test for issue #81: every host-specific install-time config
file (claude_desktop_config.json, .vscode/mcp.json) must source the
server-name and command values from the canonical snapshot, not from
inline string literals.

The existing test_installer_claude_desktop.py / test_installer_vscode.py
suites cover end-to-end behaviour. These tests are tight assertions on
the refactor's plumbing.
"""

from __future__ import annotations

import pathlib

from sumo_qa import installer, plugin_metadata


def test_installer_module_exposes_metadata() -> None:
    """The installer module reads metadata at import time and exposes it."""
    assert hasattr(installer, "PLUGIN_METADATA")
    assert isinstance(installer.PLUGIN_METADATA, plugin_metadata.PluginMetadata)
    assert installer.PLUGIN_METADATA.mcp_server_name == "sumo-qa"


def test_no_hardcoded_mcpservers_index_literal() -> None:
    """No code path indexes config['mcpServers'] with a literal 'sumo-qa'."""
    src = pathlib.Path(installer.__file__).read_text(encoding="utf-8")
    forbidden = 'config["mcpServers"]["sumo-qa"]'
    assert forbidden not in src, (
        "installer.py still indexes mcpServers with a hardcoded server name "
        "literal — should use PLUGIN_METADATA.mcp_server_name."
    )


def test_no_hardcoded_claude_mcp_argv_literal() -> None:
    """The `claude mcp add/remove ... sumo-qa ...` argv list should source
    the server name from PLUGIN_METADATA, not from a literal string."""
    src = pathlib.Path(installer.__file__).read_text(encoding="utf-8")
    # The previous idiom interleaved the literal 'sumo-qa' inside the argv
    # list for `claude mcp remove`. After refactor, that exact line should
    # use PLUGIN_METADATA.mcp_server_name. We grep for the prior shape.
    forbidden = '"sumo-qa", "-s", "user"'
    assert forbidden not in src, (
        "installer.py still passes literal 'sumo-qa' as `claude mcp` argv "
        "— should use PLUGIN_METADATA.mcp_server_name."
    )
