# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the no-em-dashes prose gate.

Pins the checker's behaviour (em/en-dash detected in prose, fenced code
exempt, exit codes) and asserts the tracked documentation set is actually
clean so a regression fails here as well as at the gate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _repo_root() -> Path:
    """Walk up to the ``.git`` ancestor.

    Anchors on ``.git`` (a dir in a normal clone, a file in a worktree),
    NOT pyproject.toml: mutmut copies tests AND pyproject.toml into
    ``mutants/`` but not README/docs, so a pyproject anchor would resolve
    into that copy and then fail to read the real docs. ``.git`` is never
    copied, so this always finds the real repo root under both plain pytest
    and the mutation gate.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


REPO = _repo_root()


def _load_checker():
    path = REPO / "scripts" / "check_no_em_dashes.py"
    spec = importlib.util.spec_from_file_location("check_no_em_dashes", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_em_dash_in_prose_is_detected():
    hits = checker.prose_hits("The verdict is in — and it is final.\n")
    assert len(hits) == 1
    assert hits[0][0] == 1
    assert hits[0][1] == checker.EM_DASH


def test_en_dash_in_prose_is_detected():
    hits = checker.prose_hits("Names 3–7 risks per change.\n")
    assert len(hits) == 1
    assert hits[0][1] == checker.EN_DASH


def test_em_dash_inside_fenced_block_is_exempt():
    text = "Prose is clean here.\n\n```bash\n# regenerate — then commit\nrun --now\n```\n\nStill clean.\n"
    assert checker.prose_hits(text) == []


def test_tilde_fence_is_also_exempt():
    text = "~~~text\nsample output — with a dash\n~~~\n"
    assert checker.prose_hits(text) == []


def test_dash_in_a_table_row_is_prose_and_flagged():
    # Markdown tables are not fenced, so their cells are prose.
    text = "| col |\n|---|\n| value — note |\n"
    hits = checker.prose_hits(text)
    assert len(hits) == 1
    assert hits[0][0] == 3


def test_clean_prose_has_no_hits():
    assert checker.prose_hits("A colon: a clause; a parenthetical (aside). Done.\n") == []


def test_main_returns_1_on_a_file_with_a_prose_dash(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("This sentence — has a dash.\n", encoding="utf-8")
    assert checker.main([str(f)]) == 1


def test_main_returns_0_on_a_clean_file(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("This sentence has no dash.\n", encoding="utf-8")
    assert checker.main([str(f)]) == 0


def test_main_skips_a_missing_file(tmp_path):
    assert checker.main([str(tmp_path / "nope.md")]) == 0


@pytest.mark.parametrize(
    "rel",
    [
        "README.md",
        "DEMO.md",
        "AGENTS.md",
        *(str(p.relative_to(_repo_root())) for p in sorted((_repo_root() / "docs").glob("*.md"))),
    ],
)
def test_tracked_docs_have_no_em_dashes_in_prose(rel):
    path = REPO / rel
    hits = checker.prose_hits(path.read_text(encoding="utf-8"))
    assert hits == [], f"{rel} has em/en-dashes in prose: {hits[:5]}"
