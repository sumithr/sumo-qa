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
from pathlib import Path

SCOPES = ("project", "global")


def _windows_global_root() -> Path:
    """Windows user-data dir: ``%LOCALAPPDATA%\\sumo-qa`` else ``~/AppData/Local/sumo-qa``."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "sumo-qa"
    return Path.home() / "AppData" / "Local" / "sumo-qa"


def _posix_global_root() -> Path:
    """POSIX user-data dir: ``~/.local/share/sumo-qa``."""
    return Path.home() / ".local" / "share" / "sumo-qa"


def _global_root() -> Path:
    # XDG override wins on any platform; otherwise dispatch to the platform
    # default. The two dispatch arms are platform-conditional (only one runs on
    # a given OS), so they're pragma-excluded; the helpers they call are tested
    # directly on every platform to keep real coverage.
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "sumo-qa"
    if os.name == "nt":  # pragma: no cover -- platform-conditional (Windows only)
        return _windows_global_root()
    return _posix_global_root()  # pragma: no cover -- platform-conditional (POSIX only)


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
