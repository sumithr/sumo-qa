# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""User-writable locations for ingested QA knowledge packs.

Two scopes mirror the bundled ``_data/`` layout so the knowledge loaders can
resolve them with identical sub-paths:

- ``global`` — applies to every repo. ``$XDG_DATA_HOME/sumo-qa`` if set, else
  ``%LOCALAPPDATA%\\sumo-qa`` on Windows, else ``~/.local/share/sumo-qa``.
- ``project`` — current working tree only: ``<cwd>/.sumo-qa``.

Hand-rolled (no platformdirs dependency) to match the explicit-path convention
already used by the installer.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

SCOPES = ("project", "global")


def _windows_global_root(env: Mapping[str, str] | None = None) -> Path:
    """Windows user-data dir: ``%LOCALAPPDATA%\\sumo-qa`` else ``~/AppData/Local/sumo-qa``."""
    local = (os.environ if env is None else env).get("LOCALAPPDATA")
    if local:
        return Path(local) / "sumo-qa"
    return Path.home() / "AppData" / "Local" / "sumo-qa"


def _posix_global_root(env: Mapping[str, str] | None = None) -> Path:
    """POSIX user-data dir: ``~/.local/share/sumo-qa``, ``~`` taken from a
    passed ``env``'s ``HOME`` when it sets one."""
    home = None if env is None else env.get("HOME")
    return (Path(home) if home else Path.home()) / ".local" / "share" / "sumo-qa"


def _global_root(env: Mapping[str, str] | None = None) -> Path:
    # XDG override wins on any platform; otherwise dispatch to the platform
    # default. The two dispatch arms are platform-conditional (only one runs on
    # a given OS), so they're pragma-excluded; the helpers they call are tested
    # directly on every platform to keep real coverage. ``env`` (default: this
    # process's) is the environment of the process whose root is wanted.
    xdg = (os.environ if env is None else env).get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "sumo-qa"
    if os.name == "nt":  # pragma: no cover -- platform-conditional (Windows only)
        return _windows_global_root(env)
    return _posix_global_root(env)  # pragma: no cover -- platform-conditional (POSIX only)


def user_pack_root(scope: str) -> Path:
    """Return the root directory for an ingested pack at ``scope``."""
    if scope == "global":
        return _global_root()
    if scope == "project":
        return Path.cwd() / ".sumo-qa"
    raise ValueError(f"unknown scope {scope!r}; expected one of {SCOPES}")


def knowledge_dir(scope: str) -> Path:
    """Return the knowledge-markdown directory for ``scope``."""
    return user_pack_root(scope) / "knowledge"


def standards_packs_dir(scope: str) -> Path:
    """Return the standards-packs directory for ``scope``."""
    return user_pack_root(scope) / "standards" / "packs"


def rules_path(scope: str) -> Path:
    """Return the change-rules file path for ``scope``."""
    return user_pack_root(scope) / "standards" / "rules" / "change_rules.yaml"


def export_dir(scope: str) -> Path:
    """Return the test-case export directory for ``scope``.

    Lives in its OWN ``exports/`` subdir under the #92 user-pack root (the same
    ``project``/``global`` location custom packs use) — parallel to ``feedback/``,
    never colliding with the bundled knowledge/standards/rules tiers. This is the
    sole allowed root for ``sumo_qa_export_test_cases``'s explicit file-write
    carve-out: a host-supplied ``output_path`` is confined here.
    """
    return user_pack_root(scope) / "exports"


def feedback_memory_path(scope: str) -> Path:
    """Return the review-feedback-memory file path for ``scope``.

    Lives in its OWN ``feedback/`` subdir under the #92 user-pack root (the same
    ``project``/``global`` location custom packs use) — never a second hidden
    tree. It is deliberately NOT one of the bundled knowledge/standards/rules
    tiers, so it can never shadow a canonical catalogue: feedback memory is
    advisory context the planning/review skills cite *separately*, never an
    override of classifications or change-rules.
    """
    return user_pack_root(scope) / "feedback" / "review_feedback.yaml"


def mcp_profile_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the saved MCP tool profile file a process with ``env`` (default:
    this one's) reads. Global only: a host launches the server from any cwd, so
    a per-project file would differ by launch path."""
    return _global_root(env) / "mcp-profile"
