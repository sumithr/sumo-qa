# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the analysis language-adapter registry (issue #212)."""

from __future__ import annotations

from sumo_qa.analysis.registry import (
    LanguageAdapter,
    adapter_for_language,
    adapter_for_path,
    supported_languages,
)


def test_python_language_resolves_to_an_adapter():
    adapter = adapter_for_language("python")
    assert adapter is not None
    assert adapter.language == "python"


def test_unsupported_language_returns_none():
    assert adapter_for_language("kotlin") is None


def test_path_resolves_by_extension():
    assert adapter_for_path("src/pkg/mod.py") is not None
    assert adapter_for_path("src/pkg/stub.pyi") is not None


def test_path_extension_match_is_case_insensitive():
    assert adapter_for_path("SRC/MOD.PY") is not None


def test_unsupported_extension_and_extensionless_return_none():
    assert adapter_for_path("notes.md") is None
    assert adapter_for_path("Makefile") is None


def test_supported_languages_is_sorted():
    assert supported_languages() == ("python",)


def test_registered_adapter_satisfies_the_protocol():
    adapter = adapter_for_language("python")
    assert isinstance(adapter, LanguageAdapter)
