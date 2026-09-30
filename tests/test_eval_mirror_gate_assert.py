# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/mirror-gate.js``
(issue #493).

The gate is structural. It reads only the two pinned row shapes the review
module emits, `Inventory drift anchor: ... | Coverage: ...` and
`Surface verifier: ... | Status: ...`: a stale-mirror seed must name the stale
path in an UNCOVERED drift row and an UNVERIFIED verifier line, and no seed may
name a non-mirror path in either shape, whatever its label. Markdown tables,
`Risk N:` lines and free text never pass or fail it; the verdict and the
clearing command's wording are the llm-rubric's to judge. It runs under node,
the promptfoo runtime, so these tests execute the real file both configs load.

Techniques: *equivalence partitioning* over the row shapes (pinned drift row,
pinned verifier line, markdown table, risk line, prose) and labels, plus
*error guessing* over markdown emphasis and letter case.
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
NON_BLOCKER_VARS = {"not_stale_paths": ["CHANGELOG.md", ".devcontainer/Dockerfile", "uv.lock"]}

STALE_ROW = (
    "Inventory drift anchor: .pre-commit-config.yaml:34 (>=1.10.0 → >=1.12.5) | "
    "Required update: this file | Diff updated it: NO | Coverage: UNCOVERED"
)
STALE_VERIFIER = (
    "Surface verifier: pre-commit run pytest --all-files (.pre-commit-config.yaml hook env rebuilt) "
    "| Ran: NO | Status: UNVERIFIED (surface verifier), SAFE-blocker"
)
BLOCKER = f"{STALE_ROW}\n{STALE_VERIFIER}"


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


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: p.name)
def test_both_configs_load_the_shared_gate(config):
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    refs = [a.get("value") for a in raw["defaultTest"]["assert"] if a.get("type") == "javascript"]
    assert ASSERT_REF in refs, f"{config.name} does not load {ASSERT_REF}"
    assert all(ref.startswith("file://") for ref in refs), (
        f"{config.name} carries an inline javascript gate; use {ASSERT_REF}"
    )


# --- Blocker seeds: the stale path in both pinned shapes ------------------------


def test_blocker_with_an_uncovered_row_and_an_unverified_line_passes():
    assert _one(BLOCKER, BLOCKER_VARS)["pass"] is True


def test_blocker_rows_in_markdown_emphasis_and_list_markers_pass():
    output = f"- **{STALE_ROW}**\n1. `{STALE_VERIFIER}`"
    assert _one(output, BLOCKER_VARS)["pass"] is True


def test_blocker_labels_match_case_insensitively():
    output = BLOCKER.replace("UNCOVERED", "Uncovered").replace("UNVERIFIED", "unverified")
    assert _one(output, BLOCKER_VARS)["pass"] is True


@pytest.mark.parametrize(
    "drift_row",
    [
        "",
        STALE_ROW.replace("UNCOVERED", "COVERED"),
        "Inventory drift anchor: .pre-commit-config.yaml:34 (>=1.10.0 → >=1.12.5) is UNCOVERED",
        STALE_ROW.replace(".pre-commit-config.yaml", "tox.ini"),
        "| Inventory drift anchor | Coverage |\n|---|---|\n| .pre-commit-config.yaml:34 | UNCOVERED |",
    ],
    ids=["absent", "covered", "no-fields", "other-path", "table-only"],
)
def test_blocker_without_a_pinned_uncovered_drift_row_fails(drift_row):
    result = _one(f"{drift_row}\n{STALE_VERIFIER}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "no UNCOVERED `Inventory drift anchor:` row" in result["reason"]


@pytest.mark.parametrize(
    "verifier_line",
    [
        "",
        STALE_VERIFIER.replace("UNVERIFIED (surface verifier), SAFE-blocker", "DISCHARGED"),
        "Surface verifier: pre-commit run pytest --all-files (hook env rebuilt) | Ran: NO | Status: UNVERIFIED",
        "Surface verifier: pre-commit run pytest on .pre-commit-config.yaml is UNVERIFIED",
        "Run `pre-commit run pytest --all-files` for .pre-commit-config.yaml: UNVERIFIED.",
    ],
    ids=["absent", "discharged", "path-missing", "no-fields", "prose"],
)
def test_blocker_without_a_pinned_unverified_verifier_line_fails(verifier_line):
    result = _one(f"{STALE_ROW}\n{verifier_line}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "no UNVERIFIED `Surface verifier:` line" in result["reason"]


# --- Every seed: no non-mirror path in a pinned shape ---------------------------


@pytest.mark.parametrize(
    "row",
    [
        "Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Diff updated it: NO | Coverage: UNCOVERED",
        "Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Diff updated it: NO | Coverage: N/A",
        "**Inventory drift anchor: `CHANGELOG.md:212` (1.10.0 → 1.12.5) | Coverage: COVERED**",
        "Surface verifier: git log CHANGELOG.md | Ran: NO | Status: UNVERIFIED (surface verifier), SAFE-blocker",
        "Surface verifier: review CHANGELOG.md | Ran: YES | Status: DISCHARGED",
    ],
    ids=[
        "drift-uncovered",
        "drift-na",
        "drift-covered-markdown",
        "verifier-unverified",
        "verifier-discharged",
    ],
)
def test_a_pinned_row_naming_a_non_mirror_path_fails_whatever_its_label(row):
    result = _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "CHANGELOG.md named in a" in result["reason"]


def test_a_non_blocker_pinned_row_naming_a_non_mirror_path_fails():
    row = (
        "Surface verifier: docker build -f .devcontainer/Dockerfile . | Ran: NO | "
        "Status: UNVERIFIED (surface verifier), SAFE-blocker"
    )
    result = _one(row, NON_BLOCKER_VARS)
    assert result["pass"] is False
    assert ".devcontainer/Dockerfile named in a verifier row" in result["reason"]


RELATIONSHIP_TABLE = (
    "| Occurrence | Constraint | Relationship | Finding |\n|---|---|---|---|\n"
    "| .devcontainer/Dockerfile:14 | ruff>=0.6.0 | undeclared, shares versions | none |\n"
    "| uv.lock:1502 | 0.6.9 | generated resolution | UNCOVERED? no |\n"
    "| CHANGELOG.md:212 | 1.10.0 | history | none |"
)
PROSE = (
    "Risk 1: none at .devcontainer/Dockerfile:14, it is compatible.\n"
    ".devcontainer/Dockerfile:14 `ruff>=0.6.0`: undeclared range, shares versions with >=0.5.0, "
    "compatible, no finding; no drift anchor, UNCOVERED or UNVERIFIED label applies.\n"
    "CHANGELOG.md:212 is history. uv.lock resolves inside the new range."
)


@pytest.mark.parametrize(
    "free_text", [RELATIONSHIP_TABLE, PROSE], ids=["relationship-table", "prose"]
)
def test_a_relationship_table_and_prose_naming_non_mirror_paths_pass(free_text):
    assert _one(free_text, NON_BLOCKER_VARS)["pass"] is True
    assert _one(f"{BLOCKER}\n\n{free_text}", BLOCKER_VARS)["pass"] is True


def test_verdict_and_command_wording_are_not_judged():
    """The verdict phrase and the clearing command are the rubric's: the gate
    passes a blocker whose free text says SAFE and never names a run, and a
    non-blocker whose free text says NOT SAFE."""
    assert _one(f"{BLOCKER}\nVerdict: SAFE TO MERGE", BLOCKER_VARS)["pass"] is True
    assert _one("Verdict: NOT SAFE TO MERGE", NON_BLOCKER_VARS)["pass"] is True


def test_a_non_blocker_with_no_pinned_rows_passes():
    assert _one("", NON_BLOCKER_VARS)["pass"] is True


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
