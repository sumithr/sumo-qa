# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The eval judge sees every catalogue the candidate was given (issue #683).

A promptfoo `rubricPrompt` only receives the vars it renders. A config that
hands the candidate a catalogue (`file://` under `knowledge/` or `standards/`)
but leaves it out of the rubric makes the judge grade citations from memory:
with the catalogue stripped from its rubric, the judge passed a candidate
citing `metamorphic testing` (a real technique the catalogue does not carry)
and said it could only check the citation was "plausibly present". With the
catalogue in view it failed that answer as training-data drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

EVAL_DIR = Path(__file__).parent / "evals" / "promptfoo"
_CATALOGUE_VALUE = re.compile(r"^file://(\.\./)+(knowledge|standards)/")


def _eval_configs() -> list[Path]:
    return sorted(
        path
        for path in EVAL_DIR.glob("skill-*.yaml")
        if not path.name.endswith((".gen.yaml", ".generated-tests.yaml"))
    )


def _renders(template: str, var: str) -> bool:
    return re.search(r"\{\{\s*" + re.escape(var) + r"\s*\}\}", template) is not None


def _catalogue_vars_shown_to_candidate(config: dict) -> list[str]:
    default_vars = (config.get("defaultTest") or {}).get("vars") or {}
    prompts = json.dumps(config.get("prompts"))
    return [
        var
        for var, value in default_vars.items()
        if isinstance(value, str) and _CATALOGUE_VALUE.match(value) and _renders(prompts, var)
    ]


def _rubric_prompts(node) -> list[str]:
    """Every rubricPrompt in the config, wherever promptfoo would read one."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "rubricPrompt" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_rubric_prompts(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_rubric_prompts(item))
    return found


CATALOGUE_CONFIGS = [
    path
    for path in _eval_configs()
    if _catalogue_vars_shown_to_candidate(yaml.safe_load(path.read_text(encoding="utf-8")))
]


def test_the_catalogue_configs_are_found():
    # Vacuity guard: a glob or var-shape drift must not turn the check below into zero cases.
    assert len(CATALOGUE_CONFIGS) >= 20


@pytest.mark.parametrize("path", CATALOGUE_CONFIGS, ids=lambda path: path.name)
def test_every_rubric_prompt_renders_the_catalogues_the_candidate_saw(path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalogues = _catalogue_vars_shown_to_candidate(config)
    rubrics = _rubric_prompts(config)
    assert rubrics, f"{path.name} gives the candidate {catalogues} but has no rubricPrompt"
    for rubric in rubrics:
        missing = [var for var in catalogues if not _renders(rubric, var)]
        assert not missing, f"{path.name}: the judge's rubricPrompt does not render {missing}"
