# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/mirror-gate.js``
(issue #493).

The gate grades the mirrored dependency constraint corpus: a stale-mirror seed
must name the stale path, deliver NOT SAFE TO MERGE and require the isolated
environment's own run as an affirmative command; no seed may anchor a
non-mirror path in an UNCOVERED ledger or drift row. It runs under node, the
promptfoo runtime, so these tests execute the real file both configs load.

Techniques: *equivalence partitioning* over the verifier mention classes
(affirmative run / install / negated run / absent) and the row shapes (inline
anchor field, markdown table, prose), plus *error guessing* over letter case
and the table layouts a candidate emits.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"
ASSERT_PATH = PROMPTFOO_DIR / "asserts" / "mirror-gate.js"
ASSERT_REF = "file://asserts/mirror-gate.js"
CONFIGS = [
    PROMPTFOO_DIR / "skill-reviewing-before-merge-mirrored-constraints.yaml",
    PROMPTFOO_DIR / "skill-reviewing-before-merge-mirrored-constraints.ab.yaml",
]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)"
)

BLOCKER_VARS = {
    "stale_mirror_path": ".pre-commit-config.yaml",
    "not_stale_paths": ["CHANGELOG.md", "uv.lock"],
}
CONTROL_VARS = {"not_stale_paths": ["CHANGELOG.md", ".github/workflows/test.yml", "uv.lock"]}

STALE_ROW = (
    "Inventory drift anchor: .pre-commit-config.yaml:34 (>=1.10.0 → >=1.12.5) | "
    "Required update: this file | Diff updated it: NO | Coverage: UNCOVERED"
)
AFFIRMATIVE_VERIFIER = (
    "Surface verifier: pre-commit run pytest --hook-stage pre-push --all-files "
    "(hook environment rebuilt) | Ran: NO | Status: UNVERIFIED (surface verifier), SAFE-blocker"
)


def _grade(cases: list[tuple[str, dict]]) -> list[dict]:
    script = (
        "const check = require(process.argv[1]);"
        "const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(cases.map(([o, v]) => check(o, { vars: v }))));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(ASSERT_PATH)],
        input=json.dumps(cases),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _one(output: str, variables: dict) -> dict:
    return _grade([(output, variables)])[0]


def _blocker(verifier_line: str) -> str:
    return f"{STALE_ROW}\n{verifier_line}\nNOT SAFE TO MERGE"


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: p.name)
def test_both_configs_load_the_shared_gate(config):
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    refs = [a.get("value") for a in raw["defaultTest"]["assert"] if a.get("type") == "javascript"]
    assert ASSERT_REF in refs, f"{config.name} does not load {ASSERT_REF}"
    assert all(ref.startswith("file://") for ref in refs), (
        f"{config.name} carries an inline javascript gate; use {ASSERT_REF}"
    )


def test_blocker_with_an_affirmative_hook_run_passes():
    assert _one(_blocker(AFFIRMATIVE_VERIFIER), BLOCKER_VARS)["pass"] is True


@pytest.mark.parametrize(
    "verifier_line",
    [
        "Clears when the hook environment is rebuilt with pre-commit install --hook-type pre-push.",
        "No `pre-commit run` evidence was supplied for the hook environment.",
        "The green suite is not a pre-commit run of the hook.",
        "| .pre-commit-config.yaml hook env | Ran: NO pre-commit run evidence |",
        "The hook environment needs its own run.",
    ],
    ids=["install-only", "negated-no", "negated-not", "negated-table-cell", "absent"],
)
def test_blocker_without_an_affirmative_hook_run_fails(verifier_line):
    result = _one(_blocker(verifier_line), BLOCKER_VARS)
    assert result["pass"] is False
    assert "verifier" in result["reason"]


def test_blocker_accepts_a_run_after_a_negated_clause():
    line = "The uv suite does not exercise the hook; clear it with `pre-commit run pytest --all-files`."
    assert _one(_blocker(line), BLOCKER_VARS)["pass"] is True


def test_blocker_missing_path_or_verdict_fails():
    no_path = _one(f"{AFFIRMATIVE_VERIFIER}\nNOT SAFE TO MERGE", BLOCKER_VARS)
    assert no_path["pass"] is False and "not named" in no_path["reason"]
    no_verdict = _one(f"{STALE_ROW}\n{AFFIRMATIVE_VERIFIER}\nSAFE TO MERGE", BLOCKER_VARS)
    assert no_verdict["pass"] is False and "NOT SAFE" in no_verdict["reason"]


@pytest.mark.parametrize(
    "row",
    [
        "Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Diff updated it: NO | Coverage: UNCOVERED",
        "Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Diff updated it: NO | Coverage: uncovered",
        "**Risk: stale history | Anchor: `CHANGELOG.md:212` | Fresh matching tests: NONE | Coverage: Uncovered**",
    ],
    ids=["inline-upper", "inline-lower", "inline-markdown-mixed-case"],
)
def test_inline_row_anchoring_a_non_mirror_path_fails(row):
    result = _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n" + row, BLOCKER_VARS)
    assert result["pass"] is False
    assert "CHANGELOG.md anchored as UNCOVERED" in result["reason"]


@pytest.mark.parametrize(
    "table",
    [
        "| Risk | Anchor | Fresh matching tests | Coverage |\n|---|---|---|---|\n"
        "| Stale history | CHANGELOG.md:212 | NONE | UNCOVERED |",
        "| Inventory drift anchor | Old → new | Diff updated it | Coverage |\n|---|---|---|---|\n"
        "| `uv.lock:1441` | 1.11.2 → 1.12.5 | NO | **uncovered** |",
    ],
    ids=["ledger-table", "drift-table-lowercase"],
)
def test_table_row_anchoring_a_non_mirror_path_fails(table):
    result = _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n\n" + table, BLOCKER_VARS)
    assert result["pass"] is False
    assert "anchored as UNCOVERED" in result["reason"]


def test_prose_mention_beside_uncovered_is_not_a_row():
    prose = "CHANGELOG.md:212 is history, so nothing there is UNCOVERED."
    assert _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n" + prose, BLOCKER_VARS)["pass"] is True


def test_covered_table_row_for_a_non_mirror_path_passes():
    table = (
        "| Risk | Anchor | Fresh matching tests | Coverage |\n|---|---|---|---|\n"
        "| Parser binding | uv.lock:1441 | tests/repo_map/test_parser.py::test_parses | COVERED |"
    )
    assert _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n\n" + table, BLOCKER_VARS)["pass"] is True


@pytest.mark.parametrize(
    "drift",
    [
        "Inventory drift anchor: src/app.py:3 (a → b) | Coverage: UNCOVERED",
        "| Inventory drift anchor | Coverage |\n|---|---|\n| src/app.py:3 | Uncovered |",
    ],
    ids=["inline", "table"],
)
def test_seed_without_a_stale_mirror_rejects_any_uncovered_drift_anchor(drift):
    result = _one(f"{drift}\nSAFE TO MERGE", CONTROL_VARS)
    assert result["pass"] is False
    assert "inventory drift anchor" in result["reason"]


def test_control_with_relationship_lines_passes():
    output = (
        ".pre-commit-config.yaml:34 `<2,>=1.12.5`: compatible range, no finding.\n"
        "Inventory drift anchor: NONE supplied | Coverage: N/A\n"
        "SAFE TO MERGE"
    )
    assert _one(output, CONTROL_VARS)["pass"] is True


def test_custom_verifier_command_is_honoured():
    variables = {**BLOCKER_VARS, "stale_mirror_verifier": "docker build"}
    passing = _blocker("Surface verifier: docker build -f Dockerfile . | Ran: NO")
    failing = _blocker(AFFIRMATIVE_VERIFIER)
    results = _grade([(passing, variables), (failing, variables)])
    assert [r["pass"] for r in results] == [True, False]
