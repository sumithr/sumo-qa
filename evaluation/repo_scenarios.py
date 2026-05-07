"""Repo scenarios for the sumo-qa iteration loop.

Each scenario stresses a slice of the rubric. The suite spans the full
specificity spectrum (very-specific -> very-generic) so the iteration
loop catches both the "AI reads exact diff" case and the "AI reasons
about strategy" case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SPECIFICITY_VALUES: tuple[str, ...] = (
    "very-specific",
    "specific",
    "moderate",
    "generic",
    "very-generic",
)


@dataclass(frozen=True)
class RepoScenario:
    id: str
    description: str
    tool: str
    args: dict[str, Any]
    specificity: str
    rubric_focus: list[str] = field(default_factory=list)
    repo_files_to_load: list[str] = field(default_factory=list)


# The initial scenario list is filled in Task 2.
SCENARIOS: list[RepoScenario] = []
