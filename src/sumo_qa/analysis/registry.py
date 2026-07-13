# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Language-adapter registry for the analysis layer (issue #212).

Dispatches a file's language (or extension) to the adapter that extracts its
symbols. The foundation ships only the Python adapter; an UNSUPPORTED language
returns ``None`` so the caller emits an ``unsupported_language`` fallback rather
than failing (issue #212 AC: unsupported languages degrade cleanly). Mirrors the
#353 resolver-registry split, kept separate so a new language is one
registration, not a change at every call site.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable

from sumo_qa.analysis.contracts import Symbol
from sumo_qa.analysis.python_adapter import PythonSymbolAdapter


@runtime_checkable
class LanguageAdapter(Protocol):
    """The structural contract a language adapter satisfies.

    ``language`` is the id the repo-map scanner stamps on a node; ``extensions``
    are the suffixes (with the leading dot) the language owns. ``extract_symbols``
    returns the file's symbols (raising :class:`SyntaxError` on unparseable
    source); ``symbols_touching_lines`` maps changed line numbers onto them.
    """

    language: str
    extensions: tuple[str, ...]

    def extract_symbols(self, src: bytes) -> list[Symbol]: ...

    def symbols_touching_lines(
        self, symbols: list[Symbol], changed_lines: Iterable[int]
    ) -> list[Symbol]: ...


# The shipped adapters. A single tuple is the source of truth; the by-language
# and by-extension lookups are derived from it so the two can never disagree.
_ADAPTERS: tuple[LanguageAdapter, ...] = (PythonSymbolAdapter(),)
_BY_LANGUAGE: dict[str, LanguageAdapter] = {a.language: a for a in _ADAPTERS}
_BY_EXTENSION: dict[str, LanguageAdapter] = {ext: a for a in _ADAPTERS for ext in a.extensions}


def adapter_for_language(language: str) -> LanguageAdapter | None:
    """The adapter registered for ``language``, or ``None`` if unsupported."""
    return _BY_LANGUAGE.get(language)


def adapter_for_path(path: str) -> LanguageAdapter | None:
    """The adapter for ``path`` by file extension, or ``None`` if unsupported.

    ``path`` is a repo-relative POSIX path; the suffix is matched
    case-insensitively (``.PY`` resolves the same as ``.py``)."""
    ext = PurePosixPath(path).suffix.lower()
    return _BY_EXTENSION.get(ext)


def supported_languages() -> tuple[str, ...]:
    """Registered language ids, sorted for deterministic reporting."""
    return tuple(sorted(_BY_LANGUAGE))
