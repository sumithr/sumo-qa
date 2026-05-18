# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.validate_content — risk-anchored, not coverage-anchored.

Each test pins ONE named risk's contract, picked from the validator's
five load-bearing risks (see commit message / docs/CONTENT-FORMATS.md):

  R1: strict-schema violation MUST exit 1 (`change_rules.yaml`, TDM YAML)
  R2: permissive content MUST stay a warning, never an error
  R3: missing / empty required knowledge file MUST exit 1
  R4: exit-code mapping (no-error→0, any-error→1, no-repo→2) holds
  R5: repo-root resolver walks up cwd; explicit arg wins

Technique applied throughout: `decision tables` from
knowledge/techniques.md. The validator's contract is a (input-class →
output-classification → exit-code) table; each test pins one row's cell.

Sabotage handshake done at test-authoring time for the most load-bearing
rows (R1 schema-violation, R2 unfiltered-pack-warning, R4 exit-code
mapping): each test was confirmed to go red when the corresponding
production branch was temporarily inverted, then restored. The remaining
tests follow the same decision-table shape — assertions reference
observable contract (exit code, FAIL/WARN section, message substring),
not implementation detail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa import validate_content as vc

# ---------------------------------------------------------------------------
# Canonical fixtures
# ---------------------------------------------------------------------------

_VALID_RULES = """\
api_contract_change:
  must_consider: [backward compatibility]
  suggested_test_types: [contract]
"""

_VALID_PACK_FILTERED = """\
pack: team_v1
applies_to_classifications: [api_contract_change]
checks: []
"""

_VALID_TDM = """\
entries:
  - id: orders-001
    environment: integration
    domain: orders
    owner: orders-platform
    source: qa-curated
"""


def _scaffold_clean_repo(root: Path) -> None:
    """Build a fully valid repo at `root`. Individual tests then mutate ONE
    input class to pin one decision-table row, keeping all other cells clean."""
    (root / "knowledge").mkdir()
    for name in vc.REQUIRED_KNOWLEDGE_FILES:
        (root / "knowledge" / name).write_text(f"# {name}\n\ncontent\n", encoding="utf-8")
    (root / "knowledge" / "repo_walk.md").write_text("# repo walk\n", encoding="utf-8")
    (root / "standards" / "packs").mkdir(parents=True)
    (root / "standards" / "packs" / "team_v1.yml").write_text(
        _VALID_PACK_FILTERED, encoding="utf-8"
    )
    (root / "standards" / "rules").mkdir(parents=True)
    (root / "standards" / "rules" / "change_rules.yaml").write_text(_VALID_RULES, encoding="utf-8")
    (root / "knowledge" / "test_data" / "orders").mkdir(parents=True)
    (root / "knowledge" / "test_data" / "orders" / "happy.yaml").write_text(
        _VALID_TDM, encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# R1 — strict-schema violation MUST exit 1
# ---------------------------------------------------------------------------
# Decision-table row: (change_rules.yaml present, schema invalid) →
# (FAIL section present, exit 1). The pre-commit hook gates on the
# exit code; if `_check_change_rules` ever degraded the schema branch
# from `r.err` to `r.warn`, a broken `change_rules.yaml` would land on
# main and the MCP server would refuse to start at host startup.


def test_change_rules_schema_violation_exits_one_with_FAIL_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "rules" / "change_rules.yaml").write_text(
        "api_contract_change:\n  suggested_test_types: [banana]\n",
        encoding="utf-8",
    )

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "FAIL:" in out
    assert "banana" in out  # operator can grep the offending token


def test_change_rules_invalid_yaml_exits_one_with_FAIL_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "rules" / "change_rules.yaml").write_text(
        "{this: is not parseable\n", encoding="utf-8"
    )

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "FAIL:" in out


def test_tdm_schema_violation_exits_one_with_offending_field_in_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "knowledge" / "test_data" / "orders" / "happy.yaml").write_text(
        "entries:\n  - id: bad\n    environment: int\n    domain: o\n"
        "    owner: x\n    source: s\n    unknown_field: nope\n",
        encoding="utf-8",
    )

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "FAIL:" in out
    assert "unknown_field" in out


# ---------------------------------------------------------------------------
# R2 — permissive content MUST stay a warning, never an error
# ---------------------------------------------------------------------------
# Decision-table rows: (standards pack: no applies_to_classifications) and
# (standards pack: non-mapping body) MUST exit 0. The upstream pack
# `qa_shift_left_v1.yml` is itself a deliberate global pack — if these
# rows ever flipped to errors, every clone of sumo-qa would fail its own
# pre-commit hook on day one.


def test_unfiltered_standards_pack_exits_zero_with_warning_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "packs" / "global_v1.yml").write_text(
        "pack: global_v1\nchecks: []\n", encoding="utf-8"
    )

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "WARN:" in out
    assert "global_v1.yml" in out and "applies_to_classifications" in out
    assert "FAIL:" not in out


def test_standards_pack_non_mapping_body_exits_zero_with_warning_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "packs" / "list_pack.yml").write_text("- a\n- b\n", encoding="utf-8")

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "list_pack.yml" in out and "not a mapping" in out
    assert "FAIL:" not in out


def test_standards_pack_empty_document_exits_zero_with_warning_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "packs" / "empty_pack.yml").write_text("", encoding="utf-8")

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "empty_pack.yml: empty document" in out
    assert "FAIL:" not in out


def test_standards_pack_invalid_yaml_DOES_exit_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Counter-row in the same decision table: a pack that doesn't parse at
    # all is a different cell — the operator can't read it, the loader
    # can't read it under classification filtering, so it's a hard error.
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "packs" / "broken.yml").write_text(
        "{this: is broken\n", encoding="utf-8"
    )

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "broken.yml" in out and "not valid YAML" in out


def test_packs_with_legacy_classifications_key_does_not_warn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The loader accepts both `applies_to_classifications` (current) and
    # `classifications` (legacy). The warning must trigger on neither
    # being present — not on the current name being absent.
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "packs" / "legacy_v1.yml").write_text(
        "pack: legacy\nclassifications: [security_change]\nchecks: []\n",
        encoding="utf-8",
    )

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "legacy_v1.yml" not in out.split("WARN:")[-1] if "WARN:" in out else True


# ---------------------------------------------------------------------------
# R3 — missing / empty required knowledge file MUST exit 1
# ---------------------------------------------------------------------------
# Decision-table rows: (required file present, non-empty) → OK; everything
# else → FAIL. Skill output relies on these four catalogues being non-empty;
# an empty `techniques.md` silently degrades every skill that picks from it.


def test_missing_required_knowledge_file_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "knowledge" / "techniques.md").unlink()

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "techniques.md" in out and "missing" in out


def test_empty_required_knowledge_file_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "knowledge" / "principles.md").write_text("", encoding="utf-8")

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "principles.md" in out and "empty" in out


def test_missing_optional_knowledge_file_is_warning_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "knowledge" / "repo_walk.md").unlink()

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "repo_walk.md" in out and "WARN:" in out


def test_missing_knowledge_directory_entirely_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Resolver requires `knowledge/` to even consider the directory a
    # repo root, so this case is only reachable if you pass an explicit
    # path to a directory whose knowledge/ has been deleted between
    # invocations. Still a real failure mode and must exit 1.
    _scaffold_clean_repo(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "knowledge")
    # Re-create just the test_data root so _check_test_data sees no test_data
    # without short-circuiting — but knowledge_catalogues must still error.
    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "knowledge" in out and "directory missing" in out


# ---------------------------------------------------------------------------
# R4 — exit-code mapping
# ---------------------------------------------------------------------------
# Decision table for the validator's return contract:
#   (errors=0, warnings=0) → 0
#   (errors=0, warnings≥1) → 0
#   (errors≥1, anything)   → 1
#   no repo root resolved  → 2
# Pre-commit's gate depends on this mapping. A flipped cell either silently
# passes broken content or blocks every commit.


def test_fully_clean_repo_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _scaffold_clean_repo(tmp_path)
    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "FAIL:" not in out
    # Clean repo: the four required files OK, one filtered pack OK,
    # rules OK, test_data OK = exit 0 with at most pack/optional warnings.


def test_warnings_only_repo_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _scaffold_clean_repo(tmp_path)
    # Trigger only warnings: unfiltered pack + remove optional knowledge.
    (tmp_path / "standards" / "packs" / "global_v1.yml").write_text(
        "pack: g\nchecks: []\n", encoding="utf-8"
    )
    (tmp_path / "knowledge" / "repo_walk.md").unlink()

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "WARN:" in out
    assert "FAIL:" not in out


def test_no_repo_root_resolvable_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # tmp_path has neither knowledge/ nor standards/, and isn't inside a
    # repo that does. Walk-up resolver returns None; main returns 2.
    monkeypatch.chdir(tmp_path)
    rc = vc.main([])
    assert rc == 2


# ---------------------------------------------------------------------------
# R5 — repo-root resolver
# ---------------------------------------------------------------------------
# Decision-table rows for resolver inputs:
#   (arg=None, cwd inside repo)    → walk-up to repo root
#   (arg=None, cwd outside repo)   → None + error printed
#   (arg=path,  path is directory) → that path
#   (arg=path,  path not directory) → None + error printed


def test_resolver_walks_up_from_nested_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scaffold_clean_repo(tmp_path)
    nested = tmp_path / "standards" / "packs"  # already exists, real subdir
    monkeypatch.chdir(nested)

    assert vc._resolve_repo_root(None) == tmp_path.resolve()


def test_resolver_returns_none_when_walk_up_finds_no_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    resolved = vc._resolve_repo_root(None)
    err = capsys.readouterr().err

    assert resolved is None
    assert "no knowledge/ + standards/" in err


def test_resolver_explicit_arg_wins_over_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cwd is OUTSIDE any repo (no knowledge/ nor standards/), but the
    # explicit arg points to a valid one. The arg must win — otherwise
    # `sumo-qa-validate /path/to/clone` wouldn't work from $HOME.
    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold_clean_repo(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    assert vc._resolve_repo_root(str(repo)) == repo.resolve()


def test_resolver_explicit_arg_must_point_to_existing_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist"
    assert vc._resolve_repo_root(str(missing)) is None
    assert "not a directory" in capsys.readouterr().err


def test_main_with_no_argv_uses_sys_argv_and_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The console script entry calls main() with no argv; main() must
    # then read sys.argv[1:] and walk cwd up. If that fallback breaks,
    # `sumo-qa-validate` would only work with an explicit path arg.
    _scaffold_clean_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sumo-qa-validate"])

    rc = vc.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "ok" in out


# ---------------------------------------------------------------------------
# Adjacent contracts surfaced by the risks above
# ---------------------------------------------------------------------------
# These tests pin behaviour that the five risks depend on but that no
# single risk fully exercises on its own.


def test_zero_change_rules_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A `change_rules.yaml` that parses to an empty dict is permissive
    # content per R2 (not malformed), and must NOT exit 1.
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "rules" / "change_rules.yaml").write_text("", encoding="utf-8")

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "zero rules" in out


def test_zero_test_data_entries_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Fresh-install default: empty test-data catalogue. Per R2 this
    # is permissive content — exit 0 with a warning so operators know
    # `sumo_qa_find_test_data` will return nothing.
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "knowledge" / "test_data" / "orders" / "happy.yaml").unlink()

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "0 test-data entries" in out


def test_packs_directory_absent_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Edge: a repo that has knowledge/ + standards/ but no standards/packs/.
    # Resolver still considers it a repo (knowledge/ + standards/ both
    # present); the missing packs/ is per R2 permissive content.
    _scaffold_clean_repo(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "standards" / "packs")

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "packs: directory missing" in out


def test_empty_packs_directory_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "packs" / "team_v1.yml").unlink()

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "no *.yml" in out


def test_test_data_directory_absent_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "knowledge" / "test_data")

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "test_data: not present" in out


def test_change_rules_file_absent_warns_but_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _scaffold_clean_repo(tmp_path)
    (tmp_path / "standards" / "rules" / "change_rules.yaml").unlink()

    rc = vc.main([str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "change_rules.yaml: not present" in out


# ---------------------------------------------------------------------------
# Render contract — surfaced for operator readability
# ---------------------------------------------------------------------------
# The three-section render is the operator-facing contract. Empty sections
# must be omitted (otherwise pre-commit output is noisy with FAIL: nothing
# headers on clean runs); summary line must always tally all three buckets.


def test_render_includes_all_three_sections_when_each_has_entries() -> None:
    report = vc._Report()
    report.ok("a")
    report.warn("b")
    report.err("c")

    rendered = vc._render(report)

    assert "OK:\n  - a" in rendered
    assert "WARN:\n  - b" in rendered
    assert "FAIL:\n  - c" in rendered
    assert "1 ok, 1 warning(s), 1 error(s)" in rendered


def test_render_omits_empty_sections_for_clean_pre_commit_output() -> None:
    report = vc._Report()
    report.ok("only pass")

    rendered = vc._render(report)

    assert "OK:" in rendered
    assert "WARN:" not in rendered
    assert "FAIL:" not in rendered
    assert "1 ok, 0 warning(s), 0 error(s)" in rendered
