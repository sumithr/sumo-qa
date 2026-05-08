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
