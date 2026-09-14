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


def _tests(config: dict, base_dir: Path) -> list[dict]:
    """Inline `tests:` entries plus any `file://` include that exists on disk.

    The `*.generated-tests.yaml` includes are gitignored and stripped to `user_prompt`
    by extract_tests.py, so an absent include cannot carry a catalogue var.
    """
    entries = config.get("tests") or []
    if isinstance(entries, str):
        entries = [entries]
    found = []
    for entry in entries:
        if isinstance(entry, str) and entry.startswith("file://"):
            include = base_dir / entry.removeprefix("file://")
            if include.is_file():
                found.extend(
                    _tests({"tests": yaml.safe_load(include.read_text(encoding="utf-8"))}, base_dir)
                )
        elif isinstance(entry, dict):
            found.append(entry)
    return found


def _catalogue_vars_shown_to_candidate(config: dict, base_dir: Path = EVAL_DIR) -> list[str]:
    var_sets = [(config.get("defaultTest") or {}).get("vars") or {}]
    var_sets += [test.get("vars") or {} for test in _tests(config, base_dir)]
    prompts = json.dumps(config.get("prompts"))
    shown = []
    for var_set in var_sets:
        for var, value in var_set.items():
            if (
                var not in shown
                and isinstance(value, str)
                and _CATALOGUE_VALUE.match(value)
                and _renders(prompts, var)
            ):
                shown.append(var)
    return shown


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
    # Vacuity guard: a glob or var-shape drift must not silently drop configs from the check below.
    assert len(CATALOGUE_CONFIGS) >= 32


def test_a_catalogue_defined_only_on_a_test_counts_as_shown_to_the_candidate():
    config = {
        "defaultTest": {"vars": {"skill_content": "file://../../../skills/x/SKILL.md"}},
        "prompts": [{"label": "only", "raw": "--- LOADED RULES ---\n{{loaded_rules}}"}],
        "tests": [{"vars": {"loaded_rules": "file://../../../standards/change_rules.yaml"}}],
    }
    assert _catalogue_vars_shown_to_candidate(config) == ["loaded_rules"]


@pytest.mark.parametrize("path", CATALOGUE_CONFIGS, ids=lambda path: path.name)
def test_every_rubric_prompt_renders_the_catalogues_the_candidate_saw(path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalogues = _catalogue_vars_shown_to_candidate(config)
    rubrics = _rubric_prompts(config)
    assert rubrics, f"{path.name} gives the candidate {catalogues} but has no rubricPrompt"
    for rubric in rubrics:
        missing = [var for var in catalogues if not _renders(rubric, var)]
        assert not missing, f"{path.name}: the judge's rubricPrompt does not render {missing}"


_CATALOGUE_BLOCK = re.compile(
    r"--- (?:LOADED [A-Z ]+\((?P<given>catalogue the candidate was given)\)|REFERENCE [A-Z ]+\([^)]*\)) ---"
    r"\s*\{\{\s*(?P<var>\w+)\s*\}\}"
)


@pytest.mark.parametrize("path", CATALOGUE_CONFIGS, ids=lambda path: path.name)
def test_the_catalogue_block_label_matches_the_legs_that_render_it(path):
    # A rubricPrompt is shared by every prompt leg. Telling the judge "the candidate was given"
    # a catalogue that some leg never renders (an A/B no-skill leg) grades that leg against
    # context it never had.
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    legs = [json.dumps(prompt) for prompt in config.get("prompts") or []]
    for rubric in _rubric_prompts(config):
        for block in _CATALOGUE_BLOCK.finditer(rubric):
            rendering = [leg for leg in legs if _renders(leg, block["var"])]
            if block["given"]:
                assert len(rendering) == len(legs), (
                    f"{path.name}: {block['var']} is labelled as given to the candidate but "
                    f"{len(legs) - len(rendering)} of {len(legs)} prompt legs do not render it"
                )
            else:
                assert rendering and len(rendering) < len(legs), (
                    f"{path.name}: {block['var']} has a leg-scoped label but "
                    f"{len(rendering)} of {len(legs)} prompt legs render it"
                )


def test_a_catalogue_defined_in_an_included_tests_file_counts_as_shown_to_the_candidate(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        yaml.safe_dump(
            [{"vars": {"loaded_techniques": "file://../../../knowledge/techniques.md"}}]
        ),
        encoding="utf-8",
    )
    config = {
        "prompts": ["{{loaded_techniques}}"],
        "tests": ["file://cases.yaml", "file://absent.generated-tests.yaml"],
    }
    assert _catalogue_vars_shown_to_candidate(config, base_dir=tmp_path) == ["loaded_techniques"]
