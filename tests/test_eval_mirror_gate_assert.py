# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for ``tests/evals/promptfoo/asserts/mirror-gate.js``
(issue #493).

The gate is structural. It reads only the two pinned row shapes the review
module emits, `Inventory drift anchor: ... | Coverage: ...` and
`Surface verifier: ... | Status: ...`: a stale-mirror seed must name the stale
path in an UNCOVERED drift row and an UNVERIFIED verifier line, and no seed may
name a non-mirror path in a drift row, whatever its label, or in any verifier
line except one that reads `Ran: YES` and `Status: DISCHARGED` (a run already
done is never a sync demand). Markdown tables,
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


@pytest.mark.parametrize(
    ("drift_label", "verifier_label"),
    [("2a. ", "8. "), ("Item 2a: ", "Item 8: "), ("- 2a) ", "- 8) "), ("**2a.** ", "**8.** ")],
    ids=["dotted", "item-colon", "list-paren", "bold"],
)
def test_rows_labelled_with_their_verdict_format_item_pass(drift_label, verifier_label):
    output = f"{drift_label}{STALE_ROW}\n{verifier_label}{STALE_VERIFIER}"
    assert _one(output, BLOCKER_VARS)["pass"] is True
    row = "2a. Inventory drift anchor: CHANGELOG.md:212 (1.10.0 → 1.12.5) | Coverage: UNCOVERED"
    assert _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)["pass"] is False


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
    ],
    ids=[
        "drift-uncovered",
        "drift-na",
        "drift-covered-markdown",
        "verifier-unverified",
    ],
)
def test_a_drift_row_or_an_undischarged_line_naming_a_non_mirror_path_fails(row):
    result = _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "CHANGELOG.md named in a" in result["reason"]


COMPAT_VARS = {"not_stale_paths": [".github/workflows/compat.yml", "pyproject.toml:31", "uv.lock"]}
COMPAT_HEAD = "Surface verifier: CI job compat-pytest7 (.github/workflows/compat.yml)"


@pytest.mark.parametrize(
    "row",
    [
        f"{COMPAT_HEAD} | Ran: YES | Status: DISCHARGED",
        "Surface verifier: uv sync --locked && uv run pytest -q (uv.lock) | Ran: YES | Status: DISCHARGED",
        "Surface verifier: compat job (.github/workflows/compat.yml installs the pyproject.toml:31 "
        "plugin extra) | Ran: YES | Status: DISCHARGED",
    ],
    ids=["independent-env", "locked-sync", "mixed-head"],
)
def test_a_line_citing_a_run_already_done_passes(row):
    """A `Ran: YES`, DISCHARGED verifier line cites evidence, never a sync
    demand, whatever non-mirror paths its head names."""
    assert _one(row, COMPAT_VARS)["pass"] is True
    assert _one(f"{BLOCKER}\n{row}", {**BLOCKER_VARS, **COMPAT_VARS})["pass"] is True


@pytest.mark.parametrize(
    "tail",
    [
        "| Ran: NO | Status: DISCHARGED",
        "| Ran: YES | Status: UNVERIFIED (surface verifier), SAFE-blocker",
        "| Ran: NO | Status: PENDING",
        "| Ran: NO | Status: SAFE-blocker, UNVERIFIED",
        "| Ran: NO | Status: N/A",
        "| Ran: NO",
    ],
    ids=["discharged-not-ran", "ran-unverified", "pending", "blocker-first", "na", "no-status"],
)
def test_any_other_verifier_line_naming_a_non_mirror_path_fails(tail):
    result = _one(f"{COMPAT_HEAD} {tail}", COMPAT_VARS)
    assert result["pass"] is False
    assert ".github/workflows/compat.yml named in a verifier row" in result["reason"]


def test_a_non_mirror_environment_in_a_drift_row_fails():
    row = "Inventory drift anchor: .github/workflows/compat.yml:3 (a → b) | Coverage: COVERED"
    assert _one(row, COMPAT_VARS)["pass"] is False


def test_a_not_stale_paths_string_fails_loudly():
    result = _one(BLOCKER, {**BLOCKER_VARS, "not_stale_paths": "uv.lock"})
    assert result["pass"] is False
    assert "not_stale_paths must be a list" in result["reason"]


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


# --- Paths match as whole tokens in the pinned first field ---------------------


def test_a_backup_file_does_not_satisfy_the_required_stale_anchor():
    output = (
        "Inventory drift anchor: .pre-commit-config.yaml.bak:34 (>=1.10.0 → >=1.12.5) | "
        "Diff updated it: NO | Coverage: UNCOVERED\n"
        "Surface verifier: pre-commit run pytest --all-files (.pre-commit-config.yaml.bak) "
        "| Ran: NO | Status: UNVERIFIED (surface verifier), SAFE-blocker"
    )
    result = _one(output, BLOCKER_VARS)
    assert result["pass"] is False
    assert "has no UNCOVERED `Inventory drift anchor:` row" in result["reason"]
    assert "has no UNVERIFIED `Surface verifier:` line" in result["reason"]


def test_a_backup_of_a_non_mirror_path_does_not_trip_it():
    row = (
        "Inventory drift anchor: uv.lock.backup:3 (1.10.0 → 1.12.5) | "
        "Diff updated it: NO | Coverage: UNCOVERED"
    )
    assert _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)["pass"] is True


def test_a_path_line_anchor_names_the_path():
    assert _one(BLOCKER, BLOCKER_VARS)["pass"] is True
    row = "Inventory drift anchor: uv.lock:3 (1.10.0 → 1.12.5) | Coverage: UNCOVERED"
    result = _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "uv.lock named in a drift row" in result["reason"]


def test_a_backticked_path_names_the_path():
    backticked = (
        "Inventory drift anchor: `.pre-commit-config.yaml` line 34 (>=1.10.0 → >=1.12.5) | "
        "Coverage: UNCOVERED\n"
        "Surface verifier: `pre-commit run --all-files` on `.pre-commit-config.yaml` | Ran: NO | "
        "Status: UNVERIFIED (surface verifier), SAFE-blocker"
    )
    assert _one(backticked, BLOCKER_VARS)["pass"] is True
    row = "Surface verifier: `uv lock --check` against `uv.lock` | Ran: NO | Status: UNVERIFIED"
    result = _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "uv.lock named in a verifier row" in result["reason"]


@pytest.mark.parametrize("junk", [".bak", "junk", "/x"])
def test_a_line_suffix_with_trailing_junk_does_not_satisfy_the_stale_anchor(junk):
    output = BLOCKER.replace(".pre-commit-config.yaml:34", f".pre-commit-config.yaml:34{junk}")
    output = output.replace(
        "(.pre-commit-config.yaml hook", f"(.pre-commit-config.yaml:9{junk} hook"
    )
    result = _one(output, BLOCKER_VARS)
    assert result["pass"] is False
    assert "has no UNCOVERED `Inventory drift anchor:` row" in result["reason"]
    assert "has no UNVERIFIED `Surface verifier:` line" in result["reason"]


@pytest.mark.parametrize(
    "anchor",
    [
        ".pre-commit-config.yaml:34–36",
        ".pre-commit-config.yaml:34:5",
        ".pre-commit-config.yaml#L34",
        ".pre-commit-config.yaml:34.",
    ],
    ids=["en-dash-range", "column", "github-anchor", "sentence-end"],
)
def test_a_location_suffix_names_the_path(anchor):
    output = BLOCKER.replace(".pre-commit-config.yaml:34 ", f"{anchor} ")
    assert anchor in output
    assert _one(output, BLOCKER_VARS)["pass"] is True


@pytest.mark.parametrize(
    "anchor",
    [
        ".pre-commit-config.yaml:34-36",
        ".pre-commit-config.yaml#L34-L36",
        ".pre-commit-config.yaml:",
    ],
    ids=["hyphen-range", "github-anchor-range", "sentence-colon"],
)
def test_a_location_suffix_names_the_path_in_a_verifier_head(anchor):
    output = BLOCKER.replace("(.pre-commit-config.yaml hook", f"({anchor} hook")
    assert anchor in output
    assert _one(output, BLOCKER_VARS)["pass"] is True


@pytest.mark.parametrize(
    "head",
    [
        ".pre-commit-config.yaml.bak.",
        ".pre-commit-config.yaml:34.bak",
        ".pre-commit-config.yaml..",
        ".pre-commit-config.yaml#L34.bak",
    ],
)
def test_a_sentence_end_never_admits_another_file(head):
    output = BLOCKER.replace(".pre-commit-config.yaml:34 ", f"{head} ").replace(
        "(.pre-commit-config.yaml hook", f"({head} hook"
    )
    assert _one(output, BLOCKER_VARS)["pass"] is False


@pytest.mark.parametrize(
    ("named", "expected"),
    [
        ("pyproject.toml#L31", False),
        ("pyproject.toml#L31–L33", False),
        ("pyproject.toml:31–33.", False),
        ("pyproject.toml:31:4", False),
        ("pyproject.toml#L310", True),
        ("pyproject.toml:310", True),
    ],
)
def test_a_configured_path_line_matches_its_own_location_forms(named, expected):
    row = f"Inventory drift anchor: {named} (>=7 → >=8) | Coverage: UNCOVERED"
    assert _one(row, {"not_stale_paths": ["pyproject.toml:31"]})["pass"] is expected


def _seeds():
    for config in CONFIGS:
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        for test in data["tests"]:
            yield pytest.param(test["vars"], id=f"{config.stem}:{test['description'][:40]}")


def _correct_rows(variables: dict) -> str:
    rows = []
    stale = variables.get("stale_mirror_path")
    if stale:
        rows.append(
            f"Inventory drift anchor: {stale}:9 (>=1 → >=2) | Diff updated it: NO | Coverage: UNCOVERED"
        )
        rows.append(
            f"Surface verifier: pre-commit run --all-files ({stale}) | Ran: NO | Status: UNVERIFIED (surface verifier), SAFE-blocker"
        )
    for path in variables.get("not_stale_paths", []):
        rows.append(f"Surface verifier: its own run ({path}) | Ran: YES | Status: DISCHARGED")
    return "\n".join(rows)


@pytest.mark.parametrize("variables", list(_seeds()))
def test_each_real_seed_passes_its_correct_rows(variables):
    assert _one(_correct_rows(variables), variables)["pass"] is True


@pytest.mark.parametrize("variables", list(_seeds()))
def test_each_real_seed_fails_a_drift_row_for_every_non_mirror_path(variables):
    for path in variables.get("not_stale_paths", []):
        row = f"Inventory drift anchor: {path} (a → b) | Coverage: UNCOVERED"
        result = _one(f"{_correct_rows(variables)}\n{row}", variables)
        assert result["pass"] is False, path


def test_a_numeric_filename_suffix_is_another_file():
    output = BLOCKER.replace(".pre-commit-config.yaml:34", ".pre-commit-config.yaml-2026").replace(
        ".pre-commit-config.yaml hook", ".pre-commit-config.yaml-2026 hook"
    )
    result = _one(output, BLOCKER_VARS)
    assert result["pass"] is False
    assert "has no UNCOVERED `Inventory drift anchor:` row" in result["reason"]
    assert "has no UNVERIFIED `Surface verifier:` line" in result["reason"]
    row = "Inventory drift anchor: uv.lock-2026 (1.10.0 → 1.12.5) | Coverage: UNCOVERED"
    assert _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)["pass"] is True


def test_a_line_range_names_a_configured_path_with_a_line():
    row = "Inventory drift anchor: pyproject.toml:31-33 (>=1.10 → >=1.12.5) | Coverage: UNCOVERED"
    variables = {**BLOCKER_VARS, "not_stale_paths": ["pyproject.toml:31"]}
    result = _one(f"{BLOCKER}\n{row}", variables)
    assert result["pass"] is False
    assert "pyproject.toml:31 named in a drift row" in result["reason"]
    other = row.replace("pyproject.toml:31-33", "pyproject.toml:310")
    assert _one(f"{BLOCKER}\n{other}", variables)["pass"] is True


def test_a_dot_slash_prefix_names_the_path():
    row = "Inventory drift anchor: ./uv.lock:3 (1.10.0 → 1.12.5) | Coverage: UNCOVERED"
    result = _one(f"{BLOCKER}\n{row}", BLOCKER_VARS)
    assert result["pass"] is False
    assert "uv.lock named in a drift row" in result["reason"]


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
