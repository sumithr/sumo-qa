# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Knowledge-provider tools.

Each `sumo_qa_load_*` function reads a markdown catalogue from
`knowledge/<name>.md` and returns it verbatim. No inference, no filtering
beyond optional metadata-based subset selection on `load_standards` and
`load_rules`. The host LLM picks from the returned catalogue.

Path resolution mirrors the existing pattern in `server.py` for
`QA_TEST_DATA_PATH`: env var override, then bundled `_data/knowledge/`
in installed wheels, then `knowledge/` at repo root in dev.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT_KNOWLEDGE = Path(__file__).parent.parent.parent / "knowledge"
_BUNDLED_KNOWLEDGE = Path(__file__).parent / "_data" / "knowledge"
_RULE_CLASSIFICATION_ALIASES = {
    "frontend_change": ("ui_only_change",),
    "config_change": ("configuration_change",),
    "data_migration": ("data_mapping_change",),
    "performance_change": ("caching_change",),
    "infrastructure_change": ("configuration_change",),
}


def _classification_filter_terms(classification: str | None) -> set[str] | None:
    """Normalize an optional classification filter.

    Hosts sometimes pass multi-classification intent as a comma-separated string
    because MCP exposes the argument as a scalar. Treat comma, semicolon, and
    whitespace separated values as a set while preserving `None` as no filter.
    """
    if classification is None:
        return None
    return {
        # pragma: no mutate — XX-quoted strip variant is equivalent (no realistic
        # classification name contains a literal 'X' distinct from the trimmed
        # quote chars). The strip→None variant is covered by
        # test_classification_filter_strips_backticks_and_quotes.
        part.strip("`'\"")  # pragma: no mutate
        for part in re.split(r"[\s,;]+", str(classification))
        # pragma: no mutate — same rationale as the result-expression strip above;
        # filter behaviour is verified by the same strengthening test.
        if part.strip("`'\"")  # pragma: no mutate
    }


def _metadata_terms(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return _classification_filter_terms(value) or set()
    if isinstance(value, (list, tuple, set)):
        return {
            # pragma: no mutate — XX-quoted strip variant is equivalent (see
            # rationale in _classification_filter_terms). Strip→None covered by
            # test_metadata_terms_strips_backticks_in_list_inputs.
            part.strip("`'\"")  # pragma: no mutate
            for item in value
            # pragma: no mutate — regex XX-wrapped variant matches only inputs
            # containing literal "XX...XX"; equivalent for realistic metadata.
            for part in re.split(r"[\s,;]+", str(item))  # pragma: no mutate
            # pragma: no mutate — same rationale as the result-expression strip
            # above; covered by the same metadata strengthening test.
            if part.strip("`'\"")  # pragma: no mutate
        }
    return {str(value)}


def _knowledge_dir() -> Path:
    """Return the directory holding knowledge catalogues.

    Resolution order: QA_KNOWLEDGE_PATH env var > bundled _data > repo root.
    """
    override = os.environ.get("QA_KNOWLEDGE_PATH")
    if override:
        return Path(override)
    if _BUNDLED_KNOWLEDGE.is_dir():
        return _BUNDLED_KNOWLEDGE
    return _REPO_ROOT_KNOWLEDGE


def _read(name: str) -> str:
    path = _knowledge_dir() / name
    return path.read_text(encoding="utf-8")


def sumo_qa_load_classifications() -> str:
    """Return the catalogue of 10 canonical change classifications as text."""
    return _read("classifications.md")


def sumo_qa_load_approaches() -> str:
    """Return the catalogue of 8 canonical QA approaches as text."""
    return _read("approaches.md")


def sumo_qa_load_principles() -> str:
    """Return ISTQB Foundation + Advanced + ISO 25010 grounding as text."""
    return _read("principles.md")


def sumo_qa_load_techniques() -> str:
    """Return the test design technique catalogue as text."""
    return _read("techniques.md")


def _standards_dir() -> Path:
    """Return the standards directory, honouring QA_STANDARDS_PATH override."""
    override = os.environ.get("QA_STANDARDS_PATH")
    if override:
        # pragma: no mutate — "packs" → "PACKS" mutation is Mac-survivor-only:
        # killed on case-sensitive FS (Linux CI) by
        # test_standards_dir_env_var_with_packs_subdirectory, indistinguishable
        # on case-insensitive APFS. Pragma keeps the pre-push hook usable on Mac.
        return (
            Path(override) / "packs" if (Path(override) / "packs").is_dir() else Path(override)
        )  # pragma: no mutate
    bundled = Path(__file__).parent / "_data" / "standards" / "packs"
    if bundled.is_dir():
        return bundled
    # pragma: no mutate — "standards"/"packs" → "STANDARDS"/"PACKS" mutations
    # are Mac-survivor-only (same rationale as the override branch above);
    # killed on Linux CI by the fallback-path tests.
    return Path(__file__).parent.parent.parent / "standards" / "packs"  # pragma: no mutate


def sumo_qa_load_standards(classification: str | None = None) -> str:
    """Return the team's loaded standards as text. Optional metadata filter
    by classification — packs whose frontmatter declares any requested
    classification. Multiple classifications may be comma/space separated.
    No keyword inference; the filter is pure file-metadata selection."""
    root = _standards_dir()
    packs: list[str] = []
    pack_paths = sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml")))
    requested = _classification_filter_terms(classification)
    for path in pack_paths:
        text = path.read_text(encoding="utf-8")
        if requested is not None:
            try:
                doc = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                continue
            applies = _metadata_terms(
                doc.get("applies_to_classifications") or doc.get("classifications")
            )
            if not applies or requested.isdisjoint(applies):
                continue
        packs.append(f"# {path.name}\n\n{text}")
    return "\n\n---\n\n".join(packs)


def _rules_path() -> Path:
    override = os.environ.get("QA_RULES_PATH")
    if override:
        return Path(override)
    bundled = Path(__file__).parent / "_data" / "standards" / "rules" / "change_rules.yaml"
    if bundled.is_file():
        return bundled
    candidates = [
        Path(__file__).parent.parent.parent / "standards" / "rules" / "change_rules.yaml",
        Path(__file__).parent.parent.parent / "rules" / "change_rules.yaml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def sumo_qa_load_rules(classification: str | None = None) -> str:
    """Return the team's loaded change rules as text. Optional metadata filter
    by classification — the rules file is a dict keyed by classification, so
    filtering returns matching entries. Multiple classifications may be
    comma/space separated."""
    path = _rules_path()
    text = path.read_text(encoding="utf-8")
    requested = _classification_filter_terms(classification)
    if requested is None:
        return text
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return text
    if not isinstance(doc, dict):
        return text
    entries = {name: entry for name, entry in doc.items() if str(name) in requested}
    for term in sorted(requested):
        if term in entries:
            continue
        for alias in _RULE_CLASSIFICATION_ALIASES.get(term, ()):
            if alias in doc:
                entries[term] = doc[alias]
                break
    if not entries:
        # pragma: no mutate — equivalent: empty dict renders identically under any sort_keys value
        # (covers load_rules mutants that swap False↔None↔True or drop the kwarg)
        return yaml.safe_dump({}, sort_keys=False)  # pragma: no mutate
    # pragma: no mutate — equivalent: PyYAML treats sort_keys=None identically to False
    # (preserves insertion order); covers load_rules mutant that swaps False→None
    return yaml.safe_dump(entries, sort_keys=False)  # pragma: no mutate
