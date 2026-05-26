# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.ingest — runtime ingestion of native QA knowledge packs."""

from pathlib import Path

import pytest

from sumo_qa import ingest


def test_ingest_principles_writes_to_project_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_text("# Custom principles\n\nBody.\n", encoding="utf-8")
    report = ingest.ingest_pack(str(src), scope="project")
    assert report["status"] == "ingested"
    dest = tmp_path / ".sumo-qa" / "knowledge" / "principles.md"
    assert dest.read_text(encoding="utf-8") == "# Custom principles\n\nBody.\n"
    assert report["files"][0]["type"] == "principles"


def test_ingest_empty_knowledge_file_is_actionable_error_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_text("   \n", encoding="utf-8")
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "principles.md" in str(exc.value) and "empty" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_ingest_malformed_rules_is_actionable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "change_rules.yaml"
    src.write_text("not: [a, valid, rules, schema\n", encoding="utf-8")  # broken YAML
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "change_rules.yaml" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_ingest_standards_pack_preserves_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "team_pack.yaml"
    src.write_text("applies_to_classifications: [ui_only_change]\nrules: []\n", encoding="utf-8")
    report = ingest.ingest_pack(str(src), scope="project")
    assert (tmp_path / ".sumo-qa" / "standards" / "packs" / "team_pack.yaml").is_file()
    assert report["files"][0]["type"] == "standards"


def test_ingest_malformed_standards_pack_is_actionable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "bad_pack.yaml"
    src.write_text("- just\n- a\n- list\n", encoding="utf-8")  # top-level not a mapping
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "bad_pack.yaml" in str(exc.value) and "mapping" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_unsupported_source_routes_to_converter_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "deck.pdf"
    src.write_bytes(b"%PDF-1.4 ...")
    report = ingest.ingest_pack(str(src), scope="project")
    assert report["status"] == "unsupported_source"
    # Routing is structured, not prose-inferred, and names the flow (not find-skills).
    assert report["next_skill"] == "sumo-qa-suggesting-external-skill"
    assert report["entry_kind"] == "conversion"
    assert "sumo-qa-suggesting-external-skill" in report["guidance"]
    assert "pdf" in report["guidance"].lower()
    assert not (tmp_path / ".sumo-qa").exists()


def test_missing_local_source_is_not_found_error(tmp_path, monkeypatch):
    # A genuine missing local path is a not-found error — NOT an entry_kind=conversion
    # route (don't send the agent hunting for a converter for a file that isn't there).
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ingest.IngestValidationError, match="not found"):
        ingest.ingest_pack(str(tmp_path / "nope.md"), scope="project")
    assert not (tmp_path / ".sumo-qa").exists()


def test_remote_url_source_routes_to_conversion(tmp_path, monkeypatch):
    # A URL isn't a local file but IS a conversion candidate; the converter owns
    # the fetch, so it routes through the shared external-skill flow.
    monkeypatch.chdir(tmp_path)
    report = ingest.ingest_pack("https://example.com/standards", scope="project")
    assert report["status"] == "unsupported_source"
    assert report["entry_kind"] == "conversion"
    assert report["next_skill"] == "sumo-qa-suggesting-external-skill"
    assert "remote source" in report["guidance"]


def test_content_type_override_ingests_noncanonical_markdown_as_principles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "converted.md"
    src.write_text("# From PDF\n\nContent.\n", encoding="utf-8")
    report = ingest.ingest_pack(str(src), scope="project", content_type="principles")
    assert (tmp_path / ".sumo-qa" / "knowledge" / "principles.md").is_file()
    assert report["files"][0]["type"] == "principles"


def test_content_type_override_rules_ingests_noncanonical_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "myrules.yaml"
    src.write_text("{}\n", encoding="utf-8")  # empty dict — 0 rules, valid schema
    report = ingest.ingest_pack(str(src), scope="project", content_type="rules")
    assert report["files"][0]["type"] == "rules"
    assert (tmp_path / ".sumo-qa" / "standards" / "rules" / "change_rules.yaml").is_file()


def test_content_type_override_standards_renames_markdown_to_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "converted.md"
    src.write_text("key: value\n", encoding="utf-8")
    report = ingest.ingest_pack(str(src), scope="project", content_type="standards")
    assert report["files"][0]["type"] == "standards"
    assert (tmp_path / ".sumo-qa" / "standards" / "packs" / "converted.yaml").is_file()


def test_ingest_standards_pack_broken_yaml_is_actionable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "broken.yaml"
    src.write_text("key: [unclosed\n", encoding="utf-8")  # invalid YAML syntax
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "broken.yaml" in str(exc.value) and "not valid YAML" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_unknown_content_type_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "x.md"
    src.write_text("body\n", encoding="utf-8")
    with pytest.raises(ingest.IngestValidationError, match="unknown content_type"):
        ingest.ingest_pack(str(src), scope="project", content_type="bogus")


def test_unknown_scope_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_text("body\n", encoding="utf-8")
    with pytest.raises(ingest.IngestValidationError, match="unknown scope"):
        ingest.ingest_pack(str(src), scope="nope")


def test_directory_source_ingests_native_skips_rest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    d.mkdir()
    (d / "principles.md").write_text("P\n", encoding="utf-8")
    (d / "notes.txt").write_text("ignore me\n", encoding="utf-8")
    report = ingest.ingest_pack(str(d), scope="project")
    types = {f["type"] for f in report["files"]}
    assert types == {"principles"}
    assert "notes.txt" in report["skipped"]
    assert (tmp_path / ".sumo-qa" / "knowledge" / "principles.md").is_file()


def test_directory_with_no_native_files_reports_nothing_ingested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    d.mkdir()
    (d / "notes.txt").write_text("nothing useful\n", encoding="utf-8")
    report = ingest.ingest_pack(str(d), scope="project")
    assert report["status"] == "nothing_ingested"
    assert "notes.txt" in report["skipped"]


def test_global_scope_writes_to_xdg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    src = tmp_path / "techniques.md"
    src.write_text("# T\n\nbody\n", encoding="utf-8")
    report = ingest.ingest_pack(str(src), scope="global")
    assert report["scope"] == "global"
    assert (tmp_path / "xdg" / "sumo-qa" / "knowledge" / "techniques.md").is_file()


def test_cli_main_ingests_and_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "approaches.md"
    src.write_text("# A\n\nbody\n", encoding="utf-8")
    rc = ingest.main([str(src), "--scope", "project"])
    assert rc == 0
    assert (tmp_path / ".sumo-qa" / "knowledge" / "approaches.md").is_file()
    assert "ingested" in capsys.readouterr().out


def test_cli_main_validation_error_returns_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_text("  \n", encoding="utf-8")
    rc = ingest.main([str(src)])
    assert rc == 1
    assert "sumo-qa-ingest" in capsys.readouterr().err


def test_cli_main_unsupported_returns_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "deck.pdf"
    src.write_bytes(b"%PDF")
    rc = ingest.main([str(src)])
    assert rc == 1
    assert "sumo-qa-suggesting-external-skill" in capsys.readouterr().err


def test_cli_main_nothing_ingested_returns_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    d.mkdir()
    (d / "notes.txt").write_text("x\n", encoding="utf-8")
    rc = ingest.main([str(d)])
    assert rc == 1
    assert "nothing ingested" in capsys.readouterr().err


# --- Codex-review hardening (PR #164) -------------------------------------------


def test_ingest_nonmapping_rules_is_actionable_error(tmp_path, monkeypatch):
    # A list/scalar change_rules.yaml would make StandardsRulesEngine.from_file
    # raise AttributeError (.items() on a list); ingest must surface a clear error.
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "change_rules.yaml"
    src.write_text("- a\n- b\n", encoding="utf-8")  # top-level list, not a mapping
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "change_rules.yaml" in str(exc.value) and "mapping" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_directory_ingest_skips_symlinks(tmp_path, monkeypatch):
    # Symlinked entries in a pack dir must be skipped, never followed out of the
    # source tree. Simulate is_symlink via monkeypatch so the branch is covered
    # on every OS (real symlinks need privileges on Windows CI).
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    d.mkdir()
    (d / "principles.md").write_text("P\n", encoding="utf-8")
    (d / "techniques.md").write_text("T\n", encoding="utf-8")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self.name == "techniques.md" or real_is_symlink(self),
    )
    report = ingest.ingest_pack(str(d), scope="project")
    assert {f["type"] for f in report["files"]} == {"principles"}
    assert "techniques.md" in report["skipped"]
    assert not (tmp_path / ".sumo-qa" / "knowledge" / "techniques.md").exists()


def test_write_atomic_cleans_up_temp_on_replace_failure(tmp_path, monkeypatch):
    dest = tmp_path / "knowledge" / "principles.md"

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(ingest.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        ingest._write_atomic(dest, "body\n")
    # No leftover temp file in the destination directory.
    assert list(dest.parent.glob(".*tmp*")) == []


def test_multifile_write_rolls_back_on_oserror(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    d.mkdir()
    (d / "principles.md").write_text("P\n", encoding="utf-8")
    (d / "techniques.md").write_text("T\n", encoding="utf-8")

    real_write = ingest._write_atomic
    calls: list[Path] = []

    def flaky(dest, text):
        calls.append(dest)
        if len(calls) == 1:
            real_write(dest, text)  # first file lands
        else:
            raise OSError("disk full")  # second fails

    monkeypatch.setattr(ingest, "_write_atomic", flaky)
    with pytest.raises(OSError, match="disk full"):
        ingest.ingest_pack(str(d), scope="project")
    # The first-written file is rolled back so the pack isn't left partial.
    assert not (tmp_path / ".sumo-qa" / "knowledge" / "principles.md").exists()


def test_ingest_rules_invalid_rule_body_is_actionable_error(tmp_path, monkeypatch):
    # Valid YAML mapping, but a rule body that fails StandardsRulesEngine's
    # schema -> from_file raises ValueError, surfaced as an actionable error.
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "change_rules.yaml"
    src.write_text("api_contract_change: not-a-rule-mapping\n", encoding="utf-8")
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "change_rules.yaml" in str(exc.value) and "Invalid change rule" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_ingest_non_utf8_file_is_actionable_error(tmp_path, monkeypatch):
    # A mislabeled non-UTF-8 principles.md must fail with a clean ingest error
    # (CLI main() only catches IngestValidationError), not a raw UnicodeDecodeError.
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(src), scope="project")
    assert "principles.md" in str(exc.value) and "UTF-8" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()


def test_cli_main_non_utf8_returns_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_bytes(b"\xff\xfe\x80")
    rc = ingest.main([str(src)])
    assert rc == 1
    assert "sumo-qa-ingest" in capsys.readouterr().err


def test_multifile_rollback_restores_preexisting_file(tmp_path, monkeypatch):
    # P1 (PR #164 review): if a later write fails, an already-overwritten
    # pre-existing file must be RESTORED to its prior content, not deleted.
    monkeypatch.chdir(tmp_path)
    proj_k = tmp_path / ".sumo-qa" / "knowledge"
    proj_k.mkdir(parents=True)
    (proj_k / "principles.md").write_text("ORIGINAL\n", encoding="utf-8")
    d = tmp_path / "pack"
    d.mkdir()
    (d / "principles.md").write_text("NEW\n", encoding="utf-8")
    (d / "techniques.md").write_text("T\n", encoding="utf-8")

    real_write = ingest._write_atomic

    def flaky(dest, text):
        if dest.name == "techniques.md":
            raise OSError("disk full")
        real_write(dest, text)

    monkeypatch.setattr(ingest, "_write_atomic", flaky)
    with pytest.raises(OSError, match="disk full"):
        ingest.ingest_pack(str(d), scope="project")
    # Prior content restored — not left as NEW, not deleted.
    assert (proj_k / "principles.md").read_text(encoding="utf-8") == "ORIGINAL\n"
    assert not (proj_k / ".principles.md.sumo-bak").exists()


def test_reingest_overwrites_and_leaves_no_backup(tmp_path, monkeypatch):
    # Successful re-ingest over an existing file writes the new content and
    # cleans up the backup of the overwritten file.
    monkeypatch.chdir(tmp_path)
    proj_k = tmp_path / ".sumo-qa" / "knowledge"
    proj_k.mkdir(parents=True)
    (proj_k / "principles.md").write_text("OLD\n", encoding="utf-8")
    src = tmp_path / "principles.md"
    src.write_text("REPLACED\n", encoding="utf-8")
    report = ingest.ingest_pack(str(src), scope="project")
    assert report["status"] == "ingested"
    assert (proj_k / "principles.md").read_text(encoding="utf-8") == "REPLACED\n"
    assert not (proj_k / ".principles.md.sumo-bak").exists()


def test_directory_ingest_repo_shaped_tree(tmp_path, monkeypatch):
    # An exported repo-shaped pack (knowledge/, standards/packs/, standards/rules/)
    # must ingest without flattening — the canonical layout this feature mirrors.
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "team-pack"
    (d / "knowledge").mkdir(parents=True)
    (d / "standards" / "packs").mkdir(parents=True)
    (d / "standards" / "rules").mkdir(parents=True)
    (d / "knowledge" / "principles.md").write_text("# Team P\n", encoding="utf-8")
    (d / "standards" / "packs" / "team.yaml").write_text(
        "applies_to_classifications: [security_change]\n", encoding="utf-8"
    )
    (d / "standards" / "rules" / "change_rules.yaml").write_text("{}\n", encoding="utf-8")
    report = ingest.ingest_pack(str(d), scope="project")
    assert report["status"] == "ingested"
    assert {f["type"] for f in report["files"]} == {"principles", "standards", "rules"}
    root = tmp_path / ".sumo-qa"
    assert (root / "knowledge" / "principles.md").is_file()
    assert (root / "standards" / "packs" / "team.yaml").is_file()
    assert (root / "standards" / "rules" / "change_rules.yaml").is_file()


def test_directory_ingest_skips_symlinked_subdir(tmp_path, monkeypatch):
    # A symlinked canonical subdir must not be followed out of the pack tree.
    # Simulate via monkeypatch so the branch is covered on every OS.
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    (d / "knowledge").mkdir(parents=True)
    (d / "knowledge" / "principles.md").write_text("P\n", encoding="utf-8")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda self: self.name == "knowledge" or real_is_symlink(self)
    )
    report = ingest.ingest_pack(str(d), scope="project")
    assert "knowledge" in report["skipped"]
    assert not (tmp_path / ".sumo-qa" / "knowledge" / "principles.md").exists()


def test_conflicting_destinations_rejected_before_write(tmp_path, monkeypatch):
    # P1 (PR #164 review): a flat principles.md AND a repo-shaped
    # knowledge/principles.md map to one destination — reject up front so the
    # transactional backup chain can't be corrupted, and write nothing.
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pack"
    (d / "knowledge").mkdir(parents=True)
    (d / "principles.md").write_text("FLAT\n", encoding="utf-8")
    (d / "knowledge" / "principles.md").write_text("NESTED\n", encoding="utf-8")
    with pytest.raises(ingest.IngestValidationError) as exc:
        ingest.ingest_pack(str(d), scope="project")
    assert "conflicting sources" in str(exc.value) and "principles.md" in str(exc.value)
    assert not (tmp_path / ".sumo-qa").exists()
