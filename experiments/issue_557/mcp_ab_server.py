# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run the production sumo-qa MCP surface with one issue #557 skill variant.

The baseline is byte-for-byte production behavior. The candidate changes only
the callable behind ``sumo_qa_reviewing_before_merge``; every tool name,
description, schema, server instruction, and non-review result remains the same.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .run_candidate import candidate_prompt

REVIEW_SKILL_DIRECTORY = "sumo-qa-reviewing-before-merge"


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
