# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Approach-C resolver contract for the repo-map import-edge layer (#354).

A language's import resolution splits into a declarative half and an
imperative half (the "Approach C" split, lifted 1:1 from Understand-Anything):

- :class:`LanguageConfig` — pure data describing the language to the
  orchestrator: its id, the file extensions it owns, and its barrel filenames
  (``__init__.py`` / ``index.ts``). Frozen so a registered config can't be
  mutated out from under the registry.
- :class:`Resolver` — the imperative protocol. ``extract`` pulls raw imports
  off a parsed source file (tree-sitter); ``resolve`` turns one raw import into
  the repo-relative file path(s) it points at, given the set of files that
  exist. The two are separate so each language is an independently-testable
  unit and the orchestrator stays language-agnostic.

The registry maps a language id (the same string the scanner stamps on each
:class:`~sumo_qa.repo_map_models.RepoMapNode`) to its resolver. The foundation
slice registers only ``python``; follow-on slices register their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LanguageConfig:
    """Declarative description of a language for the import-edge layer.

    ``id`` matches the language string the scanner stamps on each node
    (``python``, ``typescript``, …); ``extensions`` are the suffixes (with the
    leading dot) the language owns; ``barrels`` are package-index filenames
    (``__init__.py``, ``index.ts``) that let a directory import stand in for a
    file. Frozen: a registered config is shared, not owned, so it must not be
    mutated.
    """

    id: str
    extensions: tuple[str, ...]
    barrels: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawImport:
    """One import as written, before path resolution.

    ``module`` is the raw dotted path / string literal exactly as it appears in
    source. ``level`` is the relative-import dot count (``0`` = absolute,
    ``1`` = ``from . import x``, ``2`` = ``from .. import x``). ``names`` are
    the imported specifiers, used for submodule probing (``from pkg import
    sub`` may resolve to ``pkg/sub.py``). ``function_local`` is true when the
    import is nested inside a function body — a lazy/deferred import that the
    orchestrator tags ``medium`` confidence rather than ``high``.
    """

    module: str
    level: int
    names: tuple[str, ...]
    function_local: bool


@runtime_checkable
class Resolver(Protocol):
    """The imperative half of a language's import resolution (Approach C).

    A resolver owns a :class:`LanguageConfig` and two operations:

    - ``extract`` parses raw source bytes and returns the imports it found, as
      :class:`RawImport` records. tree-sitter lives behind this method; callers
      never touch the raw binding.
    - ``resolve`` maps one raw import to the repo-relative file path(s) it
      references, given ``file_set`` (every repo-relative path that exists).
      Returns ``[]`` when nothing resolves inside the repo (external package,
      wildcard, unresolved relative) — the orchestrator emits an edge only when
      a returned path matches an existing node, so an empty list is the normal
      "external / not-ours" outcome, never an error.
    """

    config: LanguageConfig

    def extract(self, src: bytes) -> list[RawImport]: ...

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]: ...


# language id -> resolver instance. Module-level so registration via
# `register()` (called at resolver-module import time) accumulates here and
# `get_resolver()` reads it. The orchestrator imports the concrete resolver
# modules, which self-register on import.
_REGISTRY: dict[str, Resolver] = {}


def register(resolver: Resolver) -> None:
    """Register ``resolver`` under its ``config.id``.

    Idempotent-by-overwrite: re-registering the same language id replaces the
    prior resolver (a resolver module imported twice must not raise). The id is
    taken from the resolver's own config so registration can't disagree with
    the language string the orchestrator dispatches on.
    """
    _REGISTRY[resolver.config.id] = resolver


def get_resolver(language_id: str) -> Resolver | None:
    """Return the resolver registered for ``language_id``, or ``None``.

    ``None`` means "no resolver for this language" — the orchestrator skips
    those nodes silently (an unsupported language is not an error; the
    foundation registers only ``python``).
    """
    return _REGISTRY.get(language_id)


def registered_languages() -> tuple[str, ...]:
    """Language ids with a registered resolver, sorted for determinism."""
    return tuple(sorted(_REGISTRY))
