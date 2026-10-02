# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/no-routing-leak.js``
(issue #248).

The assert fails a deciding-approach reply that leaks internal routing state.
It mirrors ``find_routing_leaks`` in ``sumo_qa.conformance``; these tests run
the real file under node (the promptfoo runtime) over the shared leak fixture
and require the same family verdicts as the Python validator, so the eval and
the conformance check cannot drift apart.

Technique: *equivalence partitioning* over the five leak families, each with a
clean near-miss class of ordinary prose.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from sumo_qa.conformance import find_routing_leaks

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"
ASSERT_PATH = PROMPTFOO_DIR / "asserts" / "no-routing-leak.js"
ASSERT_REF = "file://asserts/no-routing-leak.js"
LEAK_FIXTURE = REPO_ROOT / "tests" / "scenarios" / "conformance" / "leak_transcripts.yaml"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)"
)

_ENTRIES = yaml.safe_load(LEAK_FIXTURE.read_text(encoding="utf-8"))["transcripts"]
_EXTRA = [
    "",
    "Your approach: add a boundary test first.",
    '{"classification": "public", "approach": "canary"}',
    "Approach: regression-first thinking does not fit, nothing is broken yet.",
    "> Approach: `verify-existing`",
    "Handing off to sumo_qa_strategising.",
    "- [PENDING] ask one question",
    "- [PENDING] Pick the approach",
    "4. Build the routing payload",
    "I'm routing traffic through the new load balancer first.",
    "I'll route this to the next step.",
    '{"classification":"x","approach":"y","rationale":"a { b","next_action":{"skill":"none"}}',
    '{"classification":"public","approach":"canary","next_action":{"deploy":"staging"}}',
    '{"classification":"x","approach":"y","rationale":"say \\"{\\" here","next_action":{"skill":"none"}}',
    '{"classification":"x","approach":"y","next_action":{"skill"\n:"review"}}',
    "Routing to **`sumo-qa-reviewing-before-merge`**.",
    "Approach: verify-existing\r\nStart with the suite.",
    "Approach:\u00a0verify-existing",
    "Routing to [sumo-qa-reviewing-before-merge](skills/review/SKILL.md).",
    "Load catalogues [DONE]\nRemovability check [DONE]",
    "\ufeff1. Load catalogues\n2. Pick the approach",
    "Routing\u0085to sumo-qa-reviewing-before-merge.",
    "\u0661. Load catalogues\n\u0662. Pick the approach",
    '{"classification":"p","approach":"c","next_action":{"description":"skill: beginner","deploy":"s"}}',
    '{"classification":"p","approach":"c","next_action":{"deploy":"s"},"description":"skill: beginner"}',
    "I\u2019m routing you to the pre-merge review.",
    "Approach: no-tests-recommended \u2014 no runtime change.",
    "1. [DONE] Run the pricing regression suite.\n2. [PENDING] Verify staging.",
    "[DONE] Load catalogues",
    "\u5206\u985eapproach: verify-existing",
    "Approach: verify-existing\u2028More text",
    '{"classification":"x","approach":"y","rationale":"a\\\nb","next_action":{"skill":"none"}}',
    "{\u5206\u985eclassification:x,approach:y,next_action:{skill:z}}",
    "{classification:x,approach:y,next_action:{\u5206\u985eskill:z}}",
    "Routing you to sumo-qa-strategising.",
    "Approach: verify-existing since the suite covers it.",
    "**Approach restated:** Regression-first for the payments change.",
    "Approach re-stated: REGRESSION-FIRST",
    "- Chosen approach: `tdd-scaffold`, starting with the boundary.",
    "Selected approach: verify-existing since the suite covers it.",
    "Classification identified: Infrastructure_Change for the load balancer.",
    "Approach chosen with the team: regression-first thinking does not fit yet.",
    "Chosen approach: pin the regression-first cases before refactoring.",
    "Approach restated: regression-firstish spikes are not a catalogue entry.",
    "Approach restated: n/a/b",
    "> **Chosen approach:** _regression-first_ for the payments change.",
    "Approach restated: _regression-first_",
    "Chosen approach: regression-first_ish spikes are not a catalogue entry.",
    "Chosen approach: _regression-first__x",
    "Chosen approach: regression-first__ish spikes are not a catalogue entry.",
    "Chosen approach: regression-first_-ish spikes are not a catalogue entry.",
    "Chosen approach: __regression-first__ for the payments change.",
    "Chosen approach: verify-existing" + " " * 2_000 + "x",
    "I'm routing this QA intent to the review.",
    "Classification: docs_change so no tests.",
    "Handing this over to sumo-qa-strategising.",
    "Let me route this to sumo-qa-implementing-with-tdd.",
    "Hand the fixture to the pricing team, then rerun the suite.",
    "Route the coverage output to sumo_qa_record_coverage.",
    "Here is a hands-on intro to sumo-qa.",
    "Data classification: n/a here",
    "### Approach:\nregression-first work is not needed.",
    "Handoff to sumo-qa-strategising.",
    "I'll hand you over to the review skill.",
    "Approach: \u201ctdd-scaffold\u201d",
    "* **Approach:** tdd-scaffold",
    "Classification: docs_change, Approach: no-tests-recommended",
    "Routing this to the sumo-qa-reviewing-before-merge skill.",
    "I'm routing this traffic through the new load balancer first.",
    "The survivors are routed to sumo_qa_record_mutation for the report.",
    "Approach: n/a" + " " * 2_000 + "x",
    "Approach: \u2018tdd-scaffold\u2019",
    "Classification: n/a. Approach is up to you once the typo is fixed.",
    "I'm handing this to you with two failing tests.",
    "Routing this to sumo_qa_record_coverage now.",
    "Routed to sumo-qa-reviewing-before-merge.",
    "2024. Approach: tdd-scaffold",
    "I'll route this to sumo-qa-reviewing-before-merge.",
    "Routing it to sumo-qa-strategising.",
    "**Classification:** docs_change **Approach:** no-tests-recommended" + " " * 2_000 + "x",
    "{classification: docs_change, approach: no-tests-recommended, rationale: "
    "\u2018the user\u2019s change is docs only\u2019, next_action: {skill: none}}",
    "{classification: docs_change, approach: no-tests-recommended, rationale: "
    "'the user's change is docs only', next_action: {skill: none}}",
    "{\u2018classification\u2019: \u2018docs_change\u2019, \u2018approach\u2019: "
    "\u2018no-tests-recommended\u2019, \u2018next_action\u2019: {\u2018skill\u2019: \u2018none\u2019}}",
    "Routing to \u2018sumo-qa-strategising\u2019.",
    "1. [DONE] Read the user\u2018s intent",
    "{note: 'don't', classification: x, approach: y, next_action: {skill: z}}",
    "Classification: docs_change" + "*" * 3_000 + "x",
    "**Classification:** docs_change**Approach:** no-tests-recommended",
    '{"classification":"p","approach":"c","next_action":{"deploy":"s"},'
    '"see next_action:{skill:x}":1}',
    "{classification:x,approach:y," + "next_action:{a:" * 300 + "1" + "}" * 301,
    "{classification:x,approach:y,next_action:{a:{b:1}},z:{skill:q}}",
    "{classification:x,approach:y,next_action:{a:{skill:q}}}",
    '{"classification":"public","approach":"canary",'
    '"next_action":{"description":"a \u201cskill: beginner\u201d example"}}',
    '{"classification":"docs_change","approach":"no-tests-recommended",'
    '"rationale":"use \u201c{\u201d literally","next_action":{"skill":"none"}}',
    "[PEND\u0130NG] Load catalogues",
    "Wrap it in a `{` brace.\n"
    '{"classification":"x","approach":"y","rationale":"r","next_action":{"skill":"none"}}',
    "{ { {classification:x,approach:y,next_action:{skill:z}} x",
    "{" * 3_000 + "{classification:x,approach:y,next_action:{skill:z}}",
    "Routing to \u201csumo-qa-strategising\u201d.",
    "Routing you to the \u201dsumo-qa-strategising\u201d skill",
    "{\u201cclassification\u201d:x,\u201capproach\u201d:y,\u201cnext_action\u201d:{\u201cskill\u201d:z}}",
    "{classification:public,approach:canary,next_action:{description:\u201cskill: beginner\u201d}}",
    "{classification: docs_change, approach: n/a, rationale: \u201ca { b\u201d, "
    "next_action: {skill: none}}",
    "{a: \u201c" + "x" * 3_000,
    "Classification: docs_change; Approach: no-tests-recommended." + " " * 2_000 + "x",
]


def _node(outputs: list[str], expr: str) -> list:
    script = (
        "const check = require(process.argv[1]);"
        "const outputs = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        f"process.stdout.write(JSON.stringify(outputs.map((o) => {expr})));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(ASSERT_PATH)],
        input=json.dumps(outputs),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def test_js_assert_matches_python_validator_family_for_family() -> None:
    outputs = [e["output_text"] for e in _ENTRIES] + _EXTRA
    js = _node(outputs, "check.findRoutingLeaks(o)")
    py = [list(find_routing_leaks(o)) for o in outputs]
    assert js == py


def test_js_assert_verdicts_follow_the_fixture_labels() -> None:
    grades = _node([e["output_text"] for e in _ENTRIES], "check(o)")
    for entry, grade in zip(_ENTRIES, grades, strict=True):
        assert grade["pass"] is (not entry["leaks"]), (entry["id"], grade)
        if entry["leaks"]:
            assert entry["family"] in grade["reason"], (entry["id"], grade)


def test_js_blank_string_values_does_not_backtrack_exponentially() -> None:
    """Same CodeQL py/redos shape as the Python matcher: an unterminated
    string of escapes must not backtrack exponentially."""
    span = '{"a' + "\\a" * 28
    start = time.perf_counter()
    assert _node([span], "check.blankStringValues(o)") == [span]
    assert time.perf_counter() - start < 2


@pytest.mark.parametrize(
    "config_name",
    [
        "skill-closing-qa-gaps.yaml",
        "skill-implementing-with-tdd.yaml",
        "skill-triaging-test-failures.yaml",
        "skill-security-testing.yaml",
    ],
)
def test_downstream_skill_evals_wire_the_assert(config_name) -> None:
    """#735: the skills deciding-approach routes to must not leak labels either.
    Only the label family is checked: a downstream hand-off may name a skill."""
    config = yaml.safe_load((PROMPTFOO_DIR / config_name).read_text(encoding="utf-8"))
    wired = [a for a in config["defaultTest"]["assert"] if a.get("value") == ASSERT_REF]
    assert [a.get("config") for a in wired] == [{"families": ["taxonomy_label"]}]


def test_js_assert_families_config_limits_the_check() -> None:
    expr = "check(o, {config: {families: ['taxonomy_label']}}).pass"
    handoff = "Routing to sumo-qa-reviewing-before-merge."
    label = "Approach: regression-first"
    assert _node([handoff, label], expr) == [True, False]
    # No config checks every family.
    assert _node([handoff], "check(o).pass") == [False]


def test_deciding_approach_user_facing_eval_wires_the_assert() -> None:
    config = yaml.safe_load(
        (PROMPTFOO_DIR / "skill-deciding-approach-user-facing.yaml").read_text(encoding="utf-8")
    )
    refs = [a.get("value") for a in config["defaultTest"]["assert"] if a["type"] == "javascript"]
    assert ASSERT_REF in refs
    # The entry router is graded too: both hops load, entry router first.
    assert config["defaultTest"]["vars"]["entry_skill_content"].endswith(
        "skills/using-sumo-qa/SKILL.md"
    )
    prompt = config["prompts"][0]
    assert prompt.index("{{entry_skill_content}}") < prompt.index("{{skill_content}}")
