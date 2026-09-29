# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/mirror-gate.js``
(issue #493).

The gate grades the mirrored dependency constraint corpus: the final verdict
must be NOT SAFE TO MERGE on a stale-mirror seed and SAFE TO MERGE otherwise; a
stale-mirror seed must name the stale path and require the isolated
environment's own run as a command still to be run; no seed may name a
non-mirror path in a drift row, ledger row, risk line or surface-verifier line
under any label but COVERED / DISCHARGED. It runs under node, the
promptfoo runtime, so these tests execute the real file both configs load.

Techniques: *equivalence partitioning* over the verifier mention classes
(required run / install / negated run / absent) and the row shapes (drift row,
ledger row, risk line, verifier line, markdown table, prose), plus *error guessing* over letter case
and the table layouts a candidate emits.
"""

from __future__ import annotations

import json
import re
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
    assert "CHANGELOG.md named in a" in result["reason"]


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
    assert "named in a" in result["reason"]


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


# --- Negation judged relative to the command ----------------------------------


def test_blocker_accepts_a_command_framed_after_a_negated_verdict():
    line = "NOT SAFE TO MERGE until pre-commit run pytest --all-files passes."
    assert _one(f"{STALE_ROW}\n{line}", BLOCKER_VARS)["pass"] is True


@pytest.mark.parametrize(
    "verifier_line",
    [
        "pre-commit run pytest was not executed this turn.",
        "`pre-commit run` evidence: none supplied.",
    ],
    ids=["negated-after", "negated-after-colon"],
)
def test_blocker_rejects_a_mention_negated_after_the_command(verifier_line):
    result = _one(_blocker(verifier_line), BLOCKER_VARS)
    assert result["pass"] is False
    assert "verifier" in result["reason"]


# --- Final verdict, not a substring --------------------------------------------


def test_blocker_with_a_final_safe_verdict_fails():
    output = (
        f"{STALE_ROW}\n{AFFIRMATIVE_VERIFIER}\n"
        "It would be NOT SAFE TO MERGE if the hook were stale. Verdict: SAFE TO MERGE"
    )
    result = _one(output, BLOCKER_VARS)
    assert result["pass"] is False
    assert "final verdict is SAFE TO MERGE" in result["reason"]


def test_non_blocker_with_a_final_not_safe_verdict_fails():
    result = _one(
        "Inventory drift anchor: NONE supplied | Coverage: N/A\nNOT SAFE TO MERGE", CONTROL_VARS
    )
    assert result["pass"] is False
    assert "expected SAFE TO MERGE" in result["reason"]


def test_missing_verdict_fails():
    result = _one("Inventory drift anchor: NONE supplied | Coverage: N/A", CONTROL_VARS)
    assert result["pass"] is False
    assert "final verdict is missing" in result["reason"]


# --- Any finding on a non-mirror path fails, whatever its label ----------------


@pytest.mark.parametrize(
    "row",
    [
        "Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Diff updated it: NO | Coverage: N/A",
        "Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Diff updated it: NO | Coverage: UNPROVEN",
        "Risk: stale history | Anchor: CHANGELOG.md:212 | Fresh matching tests: tests/test_x.py::t | Coverage: UNPROVEN",
        "Risk 3: stale history at CHANGELOG.md:212",
    ],
    ids=["drift-na", "drift-unproven", "ledger-unproven", "risk-line"],
)
def test_any_finding_naming_a_non_mirror_path_fails(row):
    result = _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n" + row, BLOCKER_VARS)
    assert result["pass"] is False
    assert "CHANGELOG.md named in a" in result["reason"]


DECLARED_MIRROR_VARS = {
    "stale_mirror_path": ".pre-commit-config.yaml",
    "not_stale_paths": [".github/workflows/nightly.yml", "uv.lock"],
}


def test_verifier_line_on_an_undeclared_ci_pin_fails():
    line = (
        "Surface verifier: .github/workflows/nightly.yml:31 (pip install job) | Ran: NO | "
        "Status: UNVERIFIED (surface verifier), SAFE-blocker"
    )
    result = _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n" + line, DECLARED_MIRROR_VARS)
    assert result["pass"] is False
    assert "nightly.yml named in a verifier finding" in result["reason"]


def test_discharged_verifier_and_covered_row_on_an_updated_path_pass():
    output = (
        "Risk 1: hook environment resolves the new floor (.pre-commit-config.yaml:34)\n"
        "Risk: hook env | Anchor: .pre-commit-config.yaml:34 | Fresh matching tests: pre-commit run | Coverage: COVERED\n"
        "Surface verifier: pre-commit run pytest --all-files (.pre-commit-config.yaml) | Ran: YES | Status: DISCHARGED\n"
        "SAFE TO MERGE"
    )
    assert (
        _one(output, CONTROL_VARS | {"not_stale_paths": [".pre-commit-config.yaml"]})["pass"]
        is True
    )


# --- Only the pinned row shapes are rows ---------------------------------------


def test_relationship_anchor_prose_is_not_a_row():
    prose = "Relationship anchor: CHANGELOG.md:212 is history, never an UNCOVERED row."
    assert _one(_blocker(AFFIRMATIVE_VERIFIER) + "\n" + prose, BLOCKER_VARS)["pass"] is True


def test_none_drift_anchor_without_fields_passes_on_a_non_blocker():
    output = "Inventory drift anchor: NONE supplied (history is not uncovered)\nSAFE TO MERGE"
    assert _one(output, CONTROL_VARS)["pass"] is True


# --- A0/A1 differ only by the #493 change --------------------------------------

AB_CONFIG = PROMPTFOO_DIR / "skill-reviewing-before-merge-mirrored-constraints.ab.yaml"


def _fixture_modules(ref: str) -> list[str]:
    assert ref.startswith("file://"), ref
    text = (PROMPTFOO_DIR / ref.removeprefix("file://")).read_text(encoding="utf-8")
    return re.findall(r"^--- MODULE ([a-z0-9-]+) ---$", text, flags=re.MULTILINE)


def test_each_ab_seed_loads_the_same_modules_on_both_arms():
    raw = yaml.safe_load(AB_CONFIG.read_text(encoding="utf-8"))
    defaults = raw["defaultTest"]["vars"]
    assert raw["tests"], "the .ab.yaml has no seeds"
    for seed in raw["tests"]:
        seed_vars = {**defaults, **seed.get("vars", {})}
        a1 = [m for m in seed_vars["review_modules"] if m != "mirrored-constraints"]
        assert "mirrored-constraints" in seed_vars["review_modules"], seed["description"]
        assert _fixture_modules(seed_vars["skill_content_old"]) == a1, (
            f"{seed['description']}: A0 fixture modules differ from A1's minus mirrored-constraints"
        )
