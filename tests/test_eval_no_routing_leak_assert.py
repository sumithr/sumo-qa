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
    "4. Build the routing payload",
    "I'm routing traffic through the new load balancer first.",
    "I'll route this to the next step.",
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


def test_deciding_approach_user_facing_eval_wires_the_assert() -> None:
    config = yaml.safe_load(
        (PROMPTFOO_DIR / "skill-deciding-approach-user-facing.yaml").read_text(encoding="utf-8")
    )
    refs = [a.get("value") for a in config["defaultTest"]["assert"] if a["type"] == "javascript"]
    assert ASSERT_REF in refs
