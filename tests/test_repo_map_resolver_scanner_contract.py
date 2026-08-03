# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Drift guard between resolver extension metadata and scanner dispatch (#483).

The import-edge layer carries two copies of per-language extension metadata:
each registered resolver's ``LanguageConfig.extensions`` (what the resolver
declares it owns or probes) and the scanner's ``_LANGUAGE_BY_EXT`` /
``_PROGRAMMING_LANGS`` (what ``scan_repo`` classifies and stamps, which is what
actually dispatches a node to a resolver). PR #468 proved the two can drift
silently: the C/C++ resolver merged registered-but-unreachable because the
scanner owned none of its extensions, so ``scan_repo`` emitted zero C/C++ nodes
(#483). This suite is the contract that stops that drift: every extension a
registered resolver declares must be scanner-owned (classified as a source or
test node and stamped with a language that dispatches to a registered
resolver), with the deliberate cross-language cases collected in ONE documented
exception mapping (:data:`AMBIGUOUS_EXTENSION_OWNER`).

The reverse direction is deliberately NOT contracted: the scanner's language
inventory must keep classifying source languages that have no registered
resolver (kotlin, shell, ...), so the inventory is never derived from the
registry. :func:`test_scanner_classifies_languages_without_resolvers` pins
that counter-requirement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_scanner import _LANGUAGE_BY_EXT, _PROGRAMMING_LANGS, _classify

# The one small documented exception mapping (#483): extensions whose scanner
# owner is deliberately NOT the id of every resolver that declares them. Each
# entry maps the extension to the language the scanner stamps on it.
#
# - ``.h``: a bare header is ambiguous between C and C++. The scanner stamps
#   the documented default ``cpp`` (a classification heuristic, not a claim
#   that every header is C++); both the ``c`` and ``cpp`` resolver configs
#   declare it because the shared include extractor serves both language ids,
#   while a ``.c`` translation unit remains stamped ``c``.
# - ``.js`` / ``.jsx`` / ``.mjs`` / ``.cjs``: scanner-owned by ``javascript``;
#   the ``typescript`` resolver also declares them because TS import
#   resolution probes JS targets (one shared probe-extension list).
# - ``.ts`` / ``.tsx`` / ``.d.ts``: scanner-owned by ``typescript``; the
#   ``javascript`` resolver also declares them for the same shared-probe
#   reason. ``.d.ts`` is a compound suffix the scanner sees as ``.ts``
#   (``Path.suffix`` keeps only the last dot segment).
AMBIGUOUS_EXTENSION_OWNER: dict[str, str] = {
    ".h": "cpp",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".d.ts": "typescript",
}


def _scanner_language(ext: str) -> str | None:
    """The language the scanner stamps on a file with suffix ``ext``.

    Mirrors the scanner's own lookup: ``Path.suffix`` keeps only the last dot
    segment, so a compound resolver extension like ``.d.ts`` reaches the
    scanner as ``.ts``."""
    lang = _LANGUAGE_BY_EXT.get(ext)
    if lang is None and ext.count(".") > 1:
        lang = _LANGUAGE_BY_EXT.get("." + ext.rsplit(".", 1)[-1])
    return lang


def _resolver_declared_pairs() -> list[tuple[str, str]]:
    """Every (language id, declared extension) pair in the LIVE registry."""
    pairs: list[tuple[str, str]] = []
    for lang in registered_languages():
        resolver = get_resolver(lang)
        assert resolver is not None  # registered_languages() only lists registered ids
        for ext in resolver.config.extensions:
            pairs.append((lang, ext))
    return pairs


_PAIRS = _resolver_declared_pairs()
_PAIR_IDS = [f"{lang}:{ext}" for lang, ext in _PAIRS]


@pytest.mark.parametrize(("lang", "ext"), _PAIRS, ids=_PAIR_IDS)
def test_resolver_extension_has_scanner_ownership(lang: str, ext: str):
    # Adding a resolver extension without scanner ownership must fail the
    # suite: an unowned extension classifies to no node, so the resolver is
    # registered but unreachable at scan time (the #483 failure mode).
    assert _scanner_language(ext) is not None, (
        f"resolver {lang!r} declares {ext!r} but the scanner does not own it: "
        f"add it to repo_map_scanner._LANGUAGE_BY_EXT (and _PROGRAMMING_LANGS "
        f"for its language) or the resolver never activates through scan_repo"
    )


@pytest.mark.parametrize(("lang", "ext"), _PAIRS, ids=_PAIR_IDS)
def test_resolver_extension_scanner_language_matches_resolver_id(lang: str, ext: str):
    # The scanner language must match the declaring resolver's id, unless the
    # extension is one of the documented ambiguous cases above.
    owner = _scanner_language(ext)
    assert owner == lang or owner == AMBIGUOUS_EXTENSION_OWNER.get(ext), (
        f"scanner stamps {ext!r} as {owner!r} but resolver {lang!r} declares it; "
        f"either fix the mapping or document the ambiguity in "
        f"AMBIGUOUS_EXTENSION_OWNER"
    )


@pytest.mark.parametrize(("lang", "ext"), _PAIRS, ids=_PAIR_IDS)
def test_resolver_extension_classifies_as_source_and_test(lang: str, ext: str):
    # A declared extension must produce nodes: a plain path classifies as a
    # source file and a tests/ path as a test file (both node types reach the
    # import-edge layer's file_set).
    assert _classify(Path(f"app/widget{ext}")) == "source_file"
    assert _classify(Path(f"tests/widget{ext}")) == "test_file"


@pytest.mark.parametrize(("lang", "ext"), _PAIRS, ids=_PAIR_IDS)
def test_resolver_extension_language_is_dispatchable(lang: str, ext: str):
    # The stamped language must itself dispatch: it is a programming language
    # to the classifier AND has a registered resolver, so a node with this
    # extension reaches resolver.extract at scan time.
    owner = _scanner_language(ext)
    assert owner in _PROGRAMMING_LANGS
    assert get_resolver(owner) is not None


@pytest.mark.parametrize(("ext", "owner"), sorted(AMBIGUOUS_EXTENSION_OWNER.items()))
def test_exception_mapping_is_live_and_minimal(ext: str, owner: str):
    # Every exception entry must be real (the owner is what the scanner
    # actually stamps) and still needed (some registered resolver with a
    # DIFFERENT id declares the extension). A stale entry must be pruned so
    # the exception list stays the small documented set #483 requires.
    assert _scanner_language(ext) == owner
    declaring = {lang for lang, declared in _PAIRS if declared == ext}
    assert declaring - {owner}, (
        f"AMBIGUOUS_EXTENSION_OWNER[{ext!r}] is stale: no registered resolver "
        f"other than {owner!r} declares it"
    )


def test_scanner_classifies_languages_without_resolvers():
    # Counter-requirement (#483): the scanner's source-language inventory must
    # NOT be derived from the resolver registry. Languages with no registered
    # resolver still classify as source files, so the repo map keeps working
    # when an optional resolver is absent.
    for lang, ext in (("kotlin", ".kt"), ("shell", ".sh")):
        assert get_resolver(lang) is None  # genuinely resolver-less today
        assert _LANGUAGE_BY_EXT[ext] == lang
        assert lang in _PROGRAMMING_LANGS
        assert _classify(Path(f"app/thing{ext}")) == "source_file"
