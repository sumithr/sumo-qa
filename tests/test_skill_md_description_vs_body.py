# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract: a SKILL.md frontmatter ``description`` must not claim to load a
catalogue the body never loads.

The ``description`` is the MCP tool's discovery surface — what every host LLM
sees when picking which tool to call. An over-claiming description anchors the
LLM into expecting catalogues that never get loaded and makes the skill's
contract look more permissive than it is (the #188 ``sumo-qa-deciding-approach``
drift: the description claimed ``classifications, approaches, rules, standards``
while the body only loaded classifications + approaches).

The check is mechanical and host-agnostic: keyword-match the catalogue names
in the description against the ``sumo_qa_load_<catalogue>`` CALLS in the body.
Matching the prefixed call form is load-bearing — bodies also mention other
skills' bare ``load_<catalogue>`` in prose (e.g. the deciding-approach
"Catalogue responsibilities" section names reviewing-before-merge's
``load_rules`` + ``load_standards``); counting those prose mentions as loads
would hide the very drift this test exists to catch.
"""

import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILL_PATHS = sorted(SKILLS_DIR.glob("*/SKILL.md"))

# The canonical catalogue names a description can name and a body can load.
CATALOGUES = (
    "classifications",
    "approaches",
    "principles",
    "techniques",
    "standards",
    "rules",
)

# Frontmatter is the block between the first two `---` fences (same pattern as
# test_skill_conformance.py); the body is everything after it.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# A real load is the prefixed call form naming an EXACT catalogue token, so a
# different tool like `sumo_qa_load_rules_v2` does not count as a `rules` load.
_LOAD_RE = re.compile(r"sumo_qa_load_(" + "|".join(CATALOGUES) + r")\b")


def _split_frontmatter(skill_md_text: str) -> tuple[str, str]:
    """Return ``(frontmatter_text, body_text)``. With no frontmatter, the whole
    text is treated as body."""
    match = _FRONTMATTER_RE.match(skill_md_text)
    if not match:
        return "", skill_md_text
    return match.group(1), skill_md_text[match.end() :]


def _described_catalogues(skill_md_text: str) -> set[str]:
    """Catalogue names the frontmatter ``description`` scalar mentions
    (whole-word, case-insensitive). Parsed as YAML so a multi-line description
    is read in full, not just its first line."""
    frontmatter, _ = _split_frontmatter(skill_md_text)
    data = yaml.safe_load(frontmatter) if frontmatter else None
    description = data.get("description", "") if isinstance(data, dict) else ""
    return {cat for cat in CATALOGUES if re.search(rf"\b{cat}\b", description, re.IGNORECASE)}


def _loaded_catalogues(skill_md_text: str) -> set[str]:
    """Catalogues the BODY loads, via the prefixed ``sumo_qa_load_<cat>`` call
    form. Scoped to the body (so a description that merely names the load tool
    cannot self-satisfy the contract) and matched as an exact catalogue token
    (not bare ``load_<cat>`` prose mentions of other skills' loads)."""
    _, body = _split_frontmatter(skill_md_text)
    return set(_LOAD_RE.findall(body))


def _description_body_drift(skill_md_text: str) -> set[str]:
    """Catalogues the description claims but the body never loads."""
    return _described_catalogues(skill_md_text) - _loaded_catalogues(skill_md_text)


def test_known_drift_is_detected():
    """A pre-#188-style description that over-claims `rules` + `standards`
    while the body only loads classifications + approaches (and merely mentions
    other skills' `load_rules`/`load_standards` in prose) must be flagged.

    Discriminator: a naive ``"load_rules" in body`` checker returns set() here
    (it sees the prose mentions) and fails this assertion; the correct
    prefixed-call checker returns {"rules", "standards"}.
    """
    pre_188 = (
        "---\n"
        "name: sumo-qa-deciding-approach\n"
        "description: Loads classifications, approaches, rules, and standards, "
        "then routes to the matching sub-skill.\n"
        "---\n\n"
        "Call `sumo_qa_load_classifications()` and `sumo_qa_load_approaches()`.\n\n"
        "## Catalogue responsibilities\n"
        "- `sumo-qa-reviewing-before-merge` -> `load_classifications` + "
        "`load_standards` + `load_rules`.\n"
    )
    assert _description_body_drift(pre_188) == {"rules", "standards"}


def test_load_call_in_frontmatter_does_not_count_as_a_body_load():
    """A `sumo_qa_load_rules()` token in the DESCRIPTION must not satisfy the
    contract — loads are counted from the body only, not the frontmatter."""
    text = (
        "---\n"
        "name: x\n"
        "description: Loads rules. (Mentions sumo_qa_load_rules() in the desc.)\n"
        "---\n\n"
        "The body loads nothing.\n"
    )
    assert _description_body_drift(text) == {"rules"}


def test_partial_load_token_is_not_counted():
    """`sumo_qa_load_rules_v2()` is a different tool and must not count as a
    `rules` load."""
    text = "---\nname: x\ndescription: Loads rules.\n---\n\nCalls `sumo_qa_load_rules_v2()`.\n"
    assert _description_body_drift(text) == {"rules"}


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_shipped_skill_description_matches_body_loads(skill_path: Path):
    """Every shipped skill's description must not over-claim a catalogue its
    body never loads."""
    drift = _description_body_drift(skill_path.read_text())
    assert not drift, (
        f"{skill_path.parent.name}/SKILL.md description names catalogue(s) "
        f"{sorted(drift)} that the body never loads "
        f"(no sumo_qa_load_<catalogue> call)"
    )
