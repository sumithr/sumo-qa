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
    r"--- (?:LOADED [A-Z ]+\((?P<given>catalogue the candidate was given)\)"
    r"|REFERENCE [A-Z ]+\((?P<reference>[^)]*)\)) ---"
    r"\s*\{\{\s*(?P<var>\w+)\s*\}\}"
)
# The two leg-scoped wordings in use. Each names the legs that load the catalogue and the legs
# that were not given it, then the fixed caveat. The whole label must be one of these wordings:
# any other text, trailing or inside a leg list, is unparsed and fails rather than going unchecked.
_LEG = r"[A-Z][0-9]*(?: [a-z]+(?:-[a-z]+)*)?"  # a leg id with an optional one-word description
_LEGS = rf"{_LEG}(?:(?:, | and ){_LEG})*"
_REFERENCE_CAVEAT = r", so do not penalise a response for not quoting it"
_REFERENCE_LABELS = (
    re.compile(
        rf"the catalogue the (?P<loaders>{_LEGS}) legs? loads?; "
        rf"the (?P<others>{_LEGS}) legs? (?:was|were) not given it{_REFERENCE_CAVEAT}"
    ),
    re.compile(
        rf"the catalogue only the (?P<loaders>{_LEG}) leg loads; "
        rf"the (?P<others>{_LEGS}) legs? (?:was|were) not given it{_REFERENCE_CAVEAT}"
    ),
)
_LEG_ID = re.compile(r"\b[A-Z][0-9]*\b")


def _leg_id(prompt) -> str | None:
    """The A0 / A1 / B id a prompt leg's label starts with."""
    label = prompt.get("label") if isinstance(prompt, dict) else None
    match = re.match(r"([A-Z][0-9]*)\b", label) if isinstance(label, str) else None
    return match.group(1) if match else None


def _claimed_legs(reference: str) -> tuple[set[str], set[str]] | None:
    """(legs the label says load the catalogue, legs it says were not given it), or None."""
    for form in _REFERENCE_LABELS:
        match = form.fullmatch(reference)
        if match:
            # The leg-list grammar starts every list with a leg id, so neither set is empty.
            return set(_LEG_ID.findall(match["loaders"])), set(_LEG_ID.findall(match["others"]))
    return None


def _catalogue_label_errors(config: dict, name: str) -> list[str]:
    errors = []
    prompts = config.get("prompts") or []
    legs = [json.dumps(prompt) for prompt in prompts]
    for rubric in _rubric_prompts(config):
        for block in _CATALOGUE_BLOCK.finditer(rubric):
            var = block["var"]
            rendering = [leg for leg in legs if _renders(leg, var)]
            if block["given"]:
                if len(rendering) != len(legs):
                    errors.append(
                        f"{name}: {var} is labelled as given to the candidate but "
                        f"{len(legs) - len(rendering)} of {len(legs)} prompt legs do not render it"
                    )
                continue
            claimed = _claimed_legs(block["reference"])
            if claimed is None:
                errors.append(f"{name}: unparsed REFERENCE label for {var}: ({block['reference']})")
                continue
            ids = [_leg_id(prompt) for prompt in prompts]
            if None in ids:
                errors.append(
                    f"{name}: {var} has a leg-scoped label but a prompt leg has no leg id label"
                )
                continue
            both = claimed[0] & claimed[1]
            if both:
                errors.append(
                    f"{name}: {var} label names {sorted(both)} as both loading the catalogue "
                    "and not given it"
                )
                continue
            # Checked before any set comparison: as sets, a repeated id would let a leg that does
            # not render the catalogue hide behind a same-id leg that does.
            repeated = sorted({leg_id for leg_id in ids if ids.count(leg_id) > 1})
            if repeated:
                errors.append(
                    f"{name}: {var} has a leg-scoped label but prompt leg ids repeat: {repeated}"
                )
                continue
            loaders = {leg_id for leg_id, leg in zip(ids, legs, strict=True) if _renders(leg, var)}
            not_given = set(ids) - loaders
            if claimed != (loaders, not_given):
                errors.append(
                    f"{name}: {var} label claims loaders {sorted(claimed[0])} and not given "
                    f"{sorted(claimed[1])}, but the legs rendering it are {sorted(loaders)} "
                    f"and the rest are {sorted(not_given)}"
                )
    return errors


@pytest.mark.parametrize("path", CATALOGUE_CONFIGS, ids=lambda path: path.name)
def test_the_catalogue_block_label_matches_the_legs_that_render_it(path):
    # A rubricPrompt is shared by every prompt leg. Telling the judge "the candidate was given"
    # a catalogue that some leg never renders (an A/B no-skill leg) grades that leg against
    # context it never had.
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert not _catalogue_label_errors(config, path.name)


def _ab_config(label: str, loaders: set[str]) -> dict:
    legs = {"A0": "no skill, no catalogues", "A1": "catalogues only", "B": "full skill"}
    return {
        "prompts": [
            {"label": f"{leg} - {desc}", "raw": "{{principles}}" if leg in loaders else "bare"}
            for leg, desc in legs.items()
        ],
        "defaultTest": {
            "options": {
                "rubricPrompt": f"--- REFERENCE PRINCIPLES ({label}) ---\n{{{{principles}}}}"
            }
        },
    }


_A1_AND_B_LABEL = (
    "the catalogue the A1 and B legs load; the A0 no-skill leg was not given it, "
    "so do not penalise a response for not quoting it"
)
_ONLY_A1_LABEL = (
    "the catalogue only the A1 catalogues-only leg loads; the A0 no-skill and B full-skill "
    "legs were not given it, so do not penalise a response for not quoting it"
)


def test_a_reference_label_naming_a_leg_that_does_not_render_the_catalogue_fails():
    errors = _catalogue_label_errors(_ab_config(_A1_AND_B_LABEL, {"A1"}), "synthetic.yaml")
    assert errors and "synthetic.yaml" in errors[0]


@pytest.mark.parametrize(
    ("label", "loaders"),
    [(_A1_AND_B_LABEL, {"A1", "B"}), (_ONLY_A1_LABEL, {"A1"})],
    ids=["a1-and-b-load", "only-a1-loads"],
)
def test_a_reference_label_naming_exactly_the_rendering_legs_passes(label, loaders):
    assert _catalogue_label_errors(_ab_config(label, loaders), "synthetic.yaml") == []


def test_only_a1_label_fails_when_b_also_renders_the_catalogue():
    assert _catalogue_label_errors(_ab_config(_ONLY_A1_LABEL, {"A1", "B"}), "synthetic.yaml")


def test_a_reference_label_in_an_unknown_wording_fails_naming_the_config_and_label():
    errors = _catalogue_label_errors(_ab_config("some legs load this", {"A1"}), "synthetic.yaml")
    assert errors == [
        "synthetic.yaml: unparsed REFERENCE label for principles: (some legs load this)"
    ]


_CAVEAT = ", so do not penalise a response for not quoting it"


@pytest.mark.parametrize(
    "label",
    [
        "the catalogue the A1 and B legs load; the A0 leg was not given it; A1 was also not given it",
        "the catalogue the A1 and B legs load; the A0 leg was not given it; A1 was also not given it"
        + _CAVEAT,
        "the catalogue the A1 and B legs load; the A0 leg was not given it; every leg was not given it"
        + _CAVEAT,
        _A1_AND_B_LABEL + "; the B leg was not given it either",
    ],
    ids=[
        "trailing-prose",
        "prose-before-caveat",
        "prose-absorbed-into-leg-list",
        "prose-after-caveat",
    ],
)
def test_a_reference_label_with_contradictory_prose_fails_as_unparsed(label):
    errors = _catalogue_label_errors(_ab_config(label, {"A1", "B"}), "synthetic.yaml")
    assert errors == [f"synthetic.yaml: unparsed REFERENCE label for principles: ({label})"]


def test_a_reference_label_naming_a_leg_as_both_loading_and_not_given_fails():
    label = "the catalogue the A1 and B legs load; the A0 and A1 legs were not given it" + _CAVEAT
    errors = _catalogue_label_errors(_ab_config(label, {"A1", "B"}), "synthetic.yaml")
    assert errors == [
        "synthetic.yaml: principles label names ['A1'] as both loading the catalogue and not given it"
    ]


def test_a_duplicate_leg_id_fails_before_the_label_is_compared():
    # As sets, {A0, A1, A1, B} collapses to {A0, A1, B}: the A1 leg that never renders the
    # catalogue would hide behind the A1 leg that does, and the label would pass.
    config = _ab_config(_A1_AND_B_LABEL, {"A1", "B"})
    config["prompts"].insert(2, {"label": "A1 - catalogues only, again", "raw": "bare"})
    errors = _catalogue_label_errors(config, "synthetic.yaml")
    assert errors == [
        "synthetic.yaml: principles has a leg-scoped label but prompt leg ids repeat: ['A1']"
    ]


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
