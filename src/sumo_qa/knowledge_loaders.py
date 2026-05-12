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
from pathlib import Path

import yaml

_REPO_ROOT_KNOWLEDGE = Path(__file__).parent.parent.parent / "knowledge"
_BUNDLED_KNOWLEDGE = Path(__file__).parent / "_data" / "knowledge"


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


def sumo_qa_load_specialty_tools() -> str:
    """Return the specialty + tool fit category primer as text.

    Category-fit primer (does mutation testing apply? does DAST apply?),
    NOT a brand whitelist. Tool brand picks come from the host LLM's
    training-data knowledge of the ecosystem, anchored to the user's stack.
    """
    return _read("specialty_tools.md")


def _standards_dir() -> Path:
    """Return the standards directory, honouring QA_STANDARDS_PATH override."""
    override = os.environ.get("QA_STANDARDS_PATH")
    if override:
        return Path(override) / "packs" if (Path(override) / "packs").is_dir() else Path(override)
    bundled = Path(__file__).parent / "_data" / "standards" / "packs"
    if bundled.is_dir():
        return bundled
    return Path(__file__).parent.parent.parent / "standards" / "packs"


def sumo_qa_load_standards(classification: str | None = None) -> str:
    """Return the team's loaded standards as text. Optional metadata filter
    by classification — packs whose frontmatter declares this classification.
    No keyword inference; the filter is pure file-metadata selection."""
    root = _standards_dir()
    packs: list[str] = []
    pack_paths = sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml")))
    for path in pack_paths:
        text = path.read_text(encoding="utf-8")
        if classification is not None:
            try:
                doc = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                continue
            applies = doc.get("applies_to_classifications") or doc.get("classifications") or []
            if classification not in applies:
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
    filtering returns just that classification's entry."""
    path = _rules_path()
    text = path.read_text(encoding="utf-8")
    if classification is None:
        return text
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return text
    if not isinstance(doc, dict):
        return text
    entry = doc.get(classification)
    if entry is None:
        return yaml.safe_dump({}, sort_keys=False)
    return yaml.safe_dump({classification: entry}, sort_keys=False)
