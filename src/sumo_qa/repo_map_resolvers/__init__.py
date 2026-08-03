# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Per-language import resolvers for the repo-map import-edge layer (#354).

Importing this package self-registers every shipped resolver into the registry
in :mod:`sumo_qa.repo_map_resolvers.base`, so the orchestrator only has to
import the package and then dispatch by language id via ``get_resolver``. The
foundation slice ships the Python reference resolver; follow-on epic slices add
``typescript``, ``go``, … modules here, each self-registering on import.

The resolver modules import the tree-sitter adapter, which owns the optional-
dependency guard, so importing this package is always safe — it does not force
tree-sitter to be installed (the parser is only invoked under
``TREESITTER_AVAILABLE``).
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers import cpp as _cpp  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import csharp as _csharp  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import go as _go  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import java as _java  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import php as _php  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import python as _python  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import ruby as _ruby  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import rust as _rust  # noqa: F401 -- import for side effect
from sumo_qa.repo_map_resolvers import (
    typescript as _typescript,  # noqa: F401 -- import for side effect
)
from sumo_qa.repo_map_resolvers.base import (
    LanguageConfig,
    PreparableResolver,
    RawImport,
    Resolver,
    ScanContext,
    get_resolver,
    register,
    registered_languages,
)

__all__ = [
    "LanguageConfig",
    "PreparableResolver",
    "RawImport",
    "Resolver",
    "ScanContext",
    "get_resolver",
    "register",
    "registered_languages",
]
