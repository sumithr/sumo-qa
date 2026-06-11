"""Isolated scratch mirror: candidate SKILL.md writes can never touch the real repo."""

import hashlib
import shutil
import subprocess
from pathlib import Path

POC = Path(__file__).resolve().parent
REPO = POC.parents[1]  # .sumo-qa/gepa-poc -> repo root
SCRATCH = POC / "scratch"
TARGET = "sumo-qa-reviewing-before-merge"
SKILL_REL = Path("skills") / TARGET / "SKILL.md"
EVAL_REL = Path("tests/evals/promptfoo")


def build_scratch() -> Path:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / SKILL_REL).parent.mkdir(parents=True)
    shutil.copy2(REPO / SKILL_REL, SCRATCH / SKILL_REL)
    shutil.copytree(
        REPO / EVAL_REL,
        SCRATCH / EVAL_REL,
        ignore=shutil.ignore_patterns(
            "bakeoff", "validate-local-judge", "*.cache.json", "output*.json"
        ),
    )
    # The eval configs also resolve file://../../../{knowledge,standards}/… vars
    # (grep-verified across skill-reviewing-before-merge*.yaml). Missing dirs fail
    # every row with ENOENT (measured: 27/27 instant errors).
    for extra in ("knowledge", "standards"):
        shutil.copytree(REPO / extra, SCRATCH / extra)
    (SCRATCH / "node_modules").symlink_to(REPO / "node_modules")
    return SCRATCH


def write_candidate(text: str) -> None:
    (SCRATCH / SKILL_REL).write_text(text, encoding="utf-8")


def seed_text() -> str:
    return (REPO / SKILL_REL).read_text(encoding="utf-8")


def primary_sha() -> str:
    return hashlib.sha256((REPO / SKILL_REL).read_bytes()).hexdigest()


def repo_porcelain() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
