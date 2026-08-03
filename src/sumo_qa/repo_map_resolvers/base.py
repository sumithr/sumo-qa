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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from sumo_qa.repo_map_models import RepoMapWarning

# A Windows drive prefix — a letter then a colon — WITH OR WITHOUT a following
# separator (`C:`, `C:/`, `C:\`, `C:util` all match). The colon alone marks the
# drive; a trailing slash is not required (that separator-required gap let a bare
# `baseUrl: "C:"` slip through as a repo-relative directory, #563).
_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")


def is_out_of_repo_specifier(value: str) -> bool:
    r"""True when ``value`` is a filesystem-absolute path naming a location OUTSIDE
    the repo tree, so a resolver must emit no edge for it.

    Absolute means any of: a leading ``/`` (POSIX / root-relative), a leading
    ``\`` (UNC / Windows root), or a Windows drive ``C:`` — with OR without a
    following separator. A naive repo-relative join would silently strip the
    leading separator (``/src`` -> ``src``) or fold the drive into a segment
    (``C:/x`` / ``C:`` -> a ``C:`` path component), re-anchoring an out-of-repo
    value into a phantom in-repo path — a false dependency, the worst repo-map
    failure. This is the SINGLE shared choke point for the "absolute value =>
    no edge" rule, applied at every resolver entry point: the TypeScript import
    specifier + ``baseUrl`` / ``paths`` targets, the PHP PSR-4 base dirs, and the
    C# ``<ProjectReference>`` include paths (#563).

    A repo-ESCAPING value that climbs out and lands back INSIDE the repo (a
    sibling package / project via ``../shared``) is NOT out-of-repo — it names a
    legitimate in-repo target — so escape handling stays with each resolver's own
    path join, which drops only the values that climb ABOVE the repo root.
    """
    return value.startswith(("/", "\\")) or _DRIVE_ABSOLUTE_RE.match(value) is not None


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


# Cap per-file source read (bounded, deterministic). Preparation and the
# orchestrator share one bound so a pathological file can't blow memory and so
# a prepared read and the orchestrator's later consume see identical bytes.
MAX_SOURCE_READ_BYTES = 2_000_000


class ScanContext:
    """Per-scan repository context handed to resolver preparation (#484).

    One instance exists per scan invocation and dies with it, so anything a
    resolver derives through the context is scoped to that single scan:
    sequential and concurrent scans can never share config or indexes through
    this object. Three operations:

    - ``read`` — bounded (:data:`MAX_SOURCE_READ_BYTES`), memoized read of one
      repo-relative file. Preparation reads through here so each file hits
      disk at most once per scan; ``None`` (unreadable) is memoized too.
    - ``consume`` — the orchestrator's read. It drains the preparation cache
      (returning the cached bytes and evicting the entry — the orchestrator
      visits each node exactly once) and falls back to a direct bounded read
      WITHOUT caching, so peak memory stays at what preparation actually
      needed rather than the whole repository.
    - ``warn_config`` — records one deterministic ``other``
      :class:`~sumo_qa.repo_map_models.RepoMapWarning` per unusable config
      file (deduplicated on ``(message, path)``), never aborting the scan.
      A missing warning sink (``warnings=None``) makes it a no-op.
    """

    def __init__(
        self,
        root: Path,
        files: frozenset[str],
        warnings: list[RepoMapWarning] | None = None,
    ) -> None:
        self.root = root
        self.files = files
        self._warnings = warnings
        self._cache: dict[str, bytes | None] = {}
        self._warned: set[tuple[str, str]] = set()

    def read(self, rel_path: str) -> bytes | None:
        """Bounded, memoized read of one repo-relative file; ``None`` if unreadable."""
        if rel_path in self._cache:
            return self._cache[rel_path]
        data = self._read_from_disk(rel_path)
        self._cache[rel_path] = data
        return data

    def consume(self, rel_path: str) -> bytes | None:
        """One-shot read: serve-and-evict the prepared bytes, else read directly."""
        if rel_path in self._cache:
            return self._cache.pop(rel_path)
        return self._read_from_disk(rel_path)

    def warn_config(self, message: str, path: str) -> None:
        """Append one deduplicated ``other`` warning for an unusable config file."""
        if self._warnings is None:
            return
        key = (message, path)
        if key in self._warned:
            return
        self._warned.add(key)
        self._warnings.append(RepoMapWarning(kind="other", message=message, path=path))

    def _read_from_disk(self, rel_path: str) -> bytes | None:
        """Bounded raw read; ``None`` on any OS-level failure (never raises)."""
        try:
            with (self.root / rel_path).open("rb") as fh:
                return fh.read(MAX_SOURCE_READ_BYTES)
        except OSError:
            return None


@runtime_checkable
class PreparableResolver(Protocol):
    """A resolver that can derive scan-local repository context (#484).

    ``prepare`` receives the per-scan :class:`ScanContext` and returns the
    resolver instance to use FOR THAT SCAN ONLY — typically a fresh instance
    carrying derived config/indexes. The registered module-level singleton
    must never be mutated with repository data; returning a new object is what
    keeps sequential and concurrent scans isolated. Resolvers without
    ``prepare`` keep the plain path-only contract and are used as registered.
    """

    config: LanguageConfig

    def extract(self, src: bytes) -> list[RawImport]: ...

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]: ...

    def prepare(self, context: ScanContext) -> Resolver: ...


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
