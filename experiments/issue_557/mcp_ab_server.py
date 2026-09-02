# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run the production sumo-qa MCP surface with one issue #557 skill variant.

The baseline is byte-for-byte production behavior. The candidate replaces the
review skill's body on every surface that can serve a skill body: the
``sumo_qa_reviewing_before_merge`` tool, ``sumo_qa_load_skill_context`` and
``sumo_qa_list_skill_manifests``, the ``sumoqa://skills/...`` resources, and
``sumo_qa_execute_external_skill`` when it resolves a host-installed copy of the
review skill.
Every tool name, description, schema, server instruction, and non-review result
remains the same, so no MCP path can hand the candidate the full review skill.

The record override is process-wide state, because the manifest loader resolves
its records at request time, not at server build time. One process serves one
variant; ``build_variant_server`` switches the active variant for in-process
tests.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .run_candidate import candidate_prompt

REVIEW_SKILL_DIRECTORY = "sumo-qa-reviewing-before-merge"

# The compact body currently served for the review skill, or None for baseline.
_ACTIVE_COMPACT: str | None = None
_ORIGINAL_SKILL_RECORDS: Callable[[], dict[str, dict[str, Any]]] | None = None
_ORIGINAL_EXECUTE_EXTERNAL: Callable[..., dict[str, str]] | None = None


# Whitespace, a BOM, or HTML comments that may precede a copied SKILL.md's
# frontmatter without changing what the model reads.
_LEADING_NOISE_RE = re.compile(r"\A(?:\s|\ufeff|<!--.*?-->)*", re.DOTALL)


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n", re.DOTALL)


def _without_frontmatter(text: str) -> str:
    """The skill body a model reads: leading noise and the YAML frontmatter removed."""
    return _FRONTMATTER_RE.sub("", _LEADING_NOISE_RE.sub("", text), count=1)


def _normalised(text: str) -> str:
    """Collapse whitespace differences that do not change what the model reads."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _content_lines(text: str) -> set[str]:
    """The substantive lines of a skill body: frontmatter, blanks and short lines dropped."""
    return {
        line.strip() for line in _without_frontmatter(text).splitlines() if len(line.strip()) >= 24
    }


def shares_skill_body(candidate: str, reference: str, *, threshold: float = 0.8) -> bool:
    """Whether ``candidate`` carries ``reference``'s body: at least ``threshold`` of the
    reference's substantive lines appear verbatim in the candidate.

    An identity check by hash or equality misses a copy that was renamed,
    stripped of its frontmatter, edited, or is an older revision; line overlap
    recognises all of those while an unrelated skill shares almost no lines.
    """
    reference_lines = _content_lines(reference)
    if not reference_lines:
        return False
    candidate_lines = _content_lines(candidate)
    return len(reference_lines & candidate_lines) / len(reference_lines) >= threshold


def _install_external_skill_override() -> None:
    """Serve the active variant when a host-installed review skill is executed."""
    global _ORIGINAL_EXECUTE_EXTERNAL
    from sumo_qa import external_skills, server

    if _ORIGINAL_EXECUTE_EXTERNAL is not None:
        return
    original = external_skills.execute_external_skill
    _ORIGINAL_EXECUTE_EXTERNAL = original

    def is_review_skill(payload: dict[str, str]) -> bool:
        # Case-insensitive filesystems resolve any spelling of the directory,
        # and a host copy may be renamed, edited, or an older revision, so
        # match the directory name, the frontmatter name, and a
        # whitespace-normalised body, not only an exact hash.
        directory = Path(payload["path"]).parent.name.lower().replace("_", "-")
        if directory == REVIEW_SKILL_DIRECTORY:
            return True
        from sumo_qa import skill_manifest
        from sumo_qa.skill_prompts import _parse_frontmatter

        body = _LEADING_NOISE_RE.sub("", payload["skill_body"])
        declared = _parse_frontmatter(body).get("name")
        if isinstance(declared, str) and (
            declared.strip().lower().replace("_", "-") == REVIEW_SKILL_DIRECTORY
        ):
            return True
        production = (_ORIGINAL_SKILL_RECORDS or skill_manifest._skill_records)()
        record = production.get(REVIEW_SKILL_DIRECTORY)
        if record is None:
            return False
        # A copy whose directory and name: line were both changed, and whose
        # body was edited, is still the review skill if it carries its lines.
        return shares_skill_body(body, record["_full"])

    def execute_external_skill(
        skill: str,
        intent: str = "",
        scope: str = "auto",
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> dict[str, str]:
        payload = original(skill, intent, scope, cwd, home)
        compact = _ACTIVE_COMPACT
        if compact is not None and is_review_skill(payload):
            payload = {**payload, "skill_body": compact}
        return payload

    external_skills.execute_external_skill = execute_external_skill
    for module in (server,):
        for name, value in list(vars(module).items()):
            if value is original:
                setattr(module, name, execute_external_skill)


def _install_records_override() -> None:
    """Route the manifest loader (tools and resources) through the active variant."""
    global _ORIGINAL_SKILL_RECORDS
    from sumo_qa import skill_manifest

    if _ORIGINAL_SKILL_RECORDS is not None:
        return
    original = skill_manifest._skill_records
    _ORIGINAL_SKILL_RECORDS = original

    def skill_records() -> dict[str, dict[str, Any]]:
        records = original()
        compact = _ACTIVE_COMPACT
        record = records.get(REVIEW_SKILL_DIRECTORY)
        if compact is not None and record is not None:
            records[REVIEW_SKILL_DIRECTORY] = {
                **record,
                "content_hash": skill_manifest._content_hash(compact),
                "estimated_tokens_full": skill_manifest._approx_tokens(compact),
                "sections": skill_manifest._index_sections(compact),
                "modules": [],
                "_full": compact,
            }
        return records

    skill_manifest._skill_records = skill_records


def set_active_variant(variant: str) -> None:
    """Select which review-skill body the manifest loader serves in this process."""
    global _ACTIVE_COMPACT
    _install_records_override()
    _install_external_skill_override()
    _ACTIVE_COMPACT = candidate_prompt("repaired-compact") if variant == "candidate" else None


def clear_variant_override() -> None:
    """Remove the process-wide override entirely, restoring production records.

    In-process tests call this after each A/B test so no later test in the same
    pytest process sees the candidate's review skill body.
    """
    global _ACTIVE_COMPACT, _ORIGINAL_SKILL_RECORDS, _ORIGINAL_EXECUTE_EXTERNAL
    from sumo_qa import external_skills, server, skill_manifest

    if _ORIGINAL_SKILL_RECORDS is not None:
        skill_manifest._skill_records = _ORIGINAL_SKILL_RECORDS
        _ORIGINAL_SKILL_RECORDS = None
    if _ORIGINAL_EXECUTE_EXTERNAL is not None:
        patched = external_skills.execute_external_skill
        external_skills.execute_external_skill = _ORIGINAL_EXECUTE_EXTERNAL
        for name, value in list(vars(server).items()):
            if value is patched:
                setattr(server, name, _ORIGINAL_EXECUTE_EXTERNAL)
        _ORIGINAL_EXECUTE_EXTERNAL = None
    _ACTIVE_COMPACT = None


@contextmanager
def candidate_skill_override() -> Iterator[None]:
    """Replace only the review-skill result before the server registers tools."""
    from sumo_qa import skill_prompts

    original = skill_prompts._make_skill_callable
    compact = candidate_prompt("repaired-compact")

    def make_skill_callable(path: Path, token_cap: int | None = None) -> Callable[[], str]:
        if path.parent.name == REVIEW_SKILL_DIRECTORY:
            return lambda: compact
        return original(path, token_cap)

    skill_prompts._make_skill_callable = make_skill_callable
    try:
        yield
    finally:
        skill_prompts._make_skill_callable = original


def build_variant_server(variant: str):
    if variant not in {"baseline", "candidate"}:
        raise ValueError(f"unknown MCP A/B variant: {variant}")

    from sumo_qa.server import build_mcp_server

    set_active_variant(variant)
    if variant == "baseline":
        return build_mcp_server()
    with candidate_skill_override():
        return build_mcp_server()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("baseline", "candidate"), required=True)
    args = parser.parse_args()
    build_variant_server(args.variant).run()


if __name__ == "__main__":
    main()
