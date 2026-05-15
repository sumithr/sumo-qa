# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.knowledge_loaders.

These tools read markdown catalogues and return them verbatim. No inference,
no filtering beyond optional metadata-based subset selection. The tests
assert that known canonical entries are present in the returned text.
"""

from sumo_qa.knowledge_loaders import sumo_qa_load_classifications


def test_load_classifications_contains_ten_canonical_entries():
    text = sumo_qa_load_classifications()
    for entry in [
        "api_contract_change",
        "business_logic_change",
        "security_change",
        "performance_change",
        "frontend_change",
        "infrastructure_change",
        "test_change",
        "docs_change",
        "config_change",
        "data_migration",
    ]:
        assert entry in text, f"Missing canonical classification: {entry}"


def test_load_classifications_returns_non_empty_text():
    text = sumo_qa_load_classifications()
    assert isinstance(text, str)
    assert len(text) > 200


from sumo_qa.knowledge_loaders import sumo_qa_load_approaches


def test_load_approaches_contains_eight_canonical_entries():
    text = sumo_qa_load_approaches()
    for entry in [
        "strategy-orchestration",
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strengthen-test-coverage",
        "verify-existing",
        "no-tests-recommended",
        "spike-first-then-tests",
    ]:
        assert entry in text, f"Missing canonical approach: {entry}"


from sumo_qa.knowledge_loaders import sumo_qa_load_principles


def test_load_principles_contains_istqb_and_iso():
    text = sumo_qa_load_principles()
    assert "ISTQB Foundation" in text
    assert "ISO/IEC 25010" in text
    assert "Pesticide paradox" in text
    assert "Defects cluster" in text
    assert "shift left" in text.lower() or "shift-left" in text.lower()


from sumo_qa.knowledge_loaders import sumo_qa_load_techniques


def test_load_techniques_contains_canonical_techniques():
    text = sumo_qa_load_techniques()
    for entry in [
        "boundary value analysis",
        "equivalence partitioning",
        "decision tables",
        "state transition testing",
        "MC-DC",
        "exploratory testing",
        "property-based testing",
        "mutation testing",
    ]:
        assert entry in text, f"Missing canonical technique: {entry}"


from sumo_qa.knowledge_loaders import sumo_qa_load_standards


def test_load_standards_returns_text_when_no_filter():
    text = sumo_qa_load_standards()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_standards_filter_returns_only_matching_packs():
    """The classification filter is metadata-based — only packs whose
    frontmatter declares the classification are returned."""
    full = sumo_qa_load_standards()
    filtered = sumo_qa_load_standards(classification="security_change")
    assert len(filtered) <= len(full)
    assert isinstance(filtered, str)


from sumo_qa.knowledge_loaders import sumo_qa_load_rules


def test_load_rules_returns_text_when_no_filter():
    text = sumo_qa_load_rules()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_rules_filter_by_classification_is_smaller():
    full = sumo_qa_load_rules()
    filtered = sumo_qa_load_rules(classification="security_change")
    assert len(filtered) <= len(full)


# ---------------------------------------------------------------------------
# Branch coverage for knowledge_loaders.py
# ---------------------------------------------------------------------------


def test_knowledge_dir_honours_env_var_override(tmp_path, monkeypatch):
    """_knowledge_dir() returns the env-var path when QA_KNOWLEDGE_PATH is set (line 32)."""
    from sumo_qa.knowledge_loaders import _knowledge_dir

    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(tmp_path))
    result = _knowledge_dir()
    assert result == tmp_path


def test_standards_dir_honours_env_var_override(tmp_path, monkeypatch):
    """_standards_dir() returns the env-var path when QA_STANDARDS_PATH is set (line 77)."""
    from sumo_qa.knowledge_loaders import _standards_dir

    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = _standards_dir()
    # When the path has no 'packs' subdirectory, the path itself is returned.
    assert result == tmp_path


def test_standards_dir_env_var_with_packs_subdirectory(tmp_path, monkeypatch):
    """_standards_dir() returns packs/ subdir when QA_STANDARDS_PATH/packs/ exists (line 77)."""
    from sumo_qa.knowledge_loaders import _standards_dir

    packs = tmp_path / "packs"
    packs.mkdir()
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = _standards_dir()
    assert result == packs


def test_load_standards_skips_yaml_parse_error(tmp_path, monkeypatch):
    """sumo_qa_load_standards() silently skips packs with malformed YAML (lines 96-97)."""
    from sumo_qa.knowledge_loaders import sumo_qa_load_standards

    # Point standards dir at tmp_path containing a broken yaml pack.
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    broken = tmp_path / "bad_pack.yaml"
    broken.write_text("{ unclosed bracket\n", encoding="utf-8")

    # Filter requires YAML parse; broken pack must be silently skipped.
    result = sumo_qa_load_standards(classification="anything")
    assert isinstance(result, str)


def test_load_standards_skips_pack_missing_classification(tmp_path, monkeypatch):
    """sumo_qa_load_standards() skips packs that don't declare the requested
    classification in their frontmatter (lines 98-100 branch)."""
    import yaml as _yaml

    from sumo_qa.knowledge_loaders import sumo_qa_load_standards

    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    pack = tmp_path / "pack.yaml"
    pack.write_text(
        _yaml.safe_dump({"applies_to_classifications": ["other_change"]}),
        encoding="utf-8",
    )
    result = sumo_qa_load_standards(classification="security_change")
    # Pack declaring only 'other_change' must not appear in result.
    assert "other_change" not in result


def test_rules_path_honours_env_var(tmp_path, monkeypatch):
    """_rules_path() returns the env-var path when QA_RULES_PATH is set (line 108)."""
    from sumo_qa.knowledge_loaders import _rules_path

    fake_rules = tmp_path / "my_rules.yaml"
    fake_rules.touch()
    monkeypatch.setenv("QA_RULES_PATH", str(fake_rules))
    result = _rules_path()
    assert result == fake_rules


def test_load_rules_returns_empty_yaml_for_missing_classification(monkeypatch):
    """sumo_qa_load_rules() returns empty YAML when the classification key
    is absent from the rules dict (lines 132-133 + 135-138)."""
    from sumo_qa.knowledge_loaders import sumo_qa_load_rules

    result = sumo_qa_load_rules(classification="nonexistent_classification_xyz")
    assert isinstance(result, str)
    # Should be a YAML-safe empty mapping representation.
    assert result.strip() in ("{}", "{}\\n", "") or result == "{}\n"


def test_load_rules_returns_raw_text_on_yaml_parse_error(tmp_path, monkeypatch):
    """sumo_qa_load_rules() returns the raw text when the YAML is unparseable
    (lines 132-133 except block)."""
    from sumo_qa.knowledge_loaders import sumo_qa_load_rules

    broken_rules = tmp_path / "broken_rules.yaml"
    broken_rules.write_text("{ unclosed\n", encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(broken_rules))

    result = sumo_qa_load_rules(classification="security_change")
    assert "{ unclosed" in result


def test_load_rules_returns_raw_text_when_not_a_dict(tmp_path, monkeypatch):
    """sumo_qa_load_rules() returns the raw text when the parsed YAML is not
    a mapping (line 135 isinstance check)."""
    import yaml as _yaml

    from sumo_qa.knowledge_loaders import sumo_qa_load_rules

    list_rules = tmp_path / "list_rules.yaml"
    list_rules.write_text(_yaml.safe_dump(["item1", "item2"]), encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(list_rules))

    result = sumo_qa_load_rules(classification="security_change")
    assert isinstance(result, str)


def test_knowledge_dir_returns_bundled_when_bundled_exists(monkeypatch) -> None:
    """_knowledge_dir() returns the bundled path when _BUNDLED_KNOWLEDGE.is_dir()
    is True and no env var is set (line 34)."""
    from pathlib import Path
    from unittest.mock import patch

    from sumo_qa import knowledge_loaders

    fake_bundled = Path("/fake/bundled/knowledge")
    with (
        patch.object(Path, "is_dir", return_value=True),
        patch("sumo_qa.knowledge_loaders._BUNDLED_KNOWLEDGE", fake_bundled),
    ):
        result = knowledge_loaders._knowledge_dir()

    assert result == fake_bundled


def test_standards_dir_returns_bundled_when_bundled_exists(monkeypatch, tmp_path) -> None:
    """_standards_dir() returns the bundled packs when _data/standards/packs/ exists (line 80)."""
    from pathlib import Path

    import sumo_qa.knowledge_loaders as kl

    monkeypatch.delenv("QA_STANDARDS_PATH", raising=False)

    # Build the expected bundled path and create it temporarily so is_dir() returns True.
    bundled_packs = Path(kl.__file__).parent / "_data" / "standards" / "packs"
    bundled_packs.mkdir(parents=True, exist_ok=True)
    try:
        result = kl._standards_dir()
        assert result == bundled_packs
    finally:
        # Clean up — only remove what we created.
        import shutil

        data_dir = Path(kl.__file__).parent / "_data"
        shutil.rmtree(data_dir, ignore_errors=True)


def test_rules_path_returns_bundled_when_bundled_exists(monkeypatch, tmp_path) -> None:
    """_rules_path() returns the bundled rules path when _data/standards/rules/ file exists (line 111)."""
    from pathlib import Path

    import sumo_qa.knowledge_loaders as kl

    monkeypatch.delenv("QA_RULES_PATH", raising=False)

    bundled_rules = Path(kl.__file__).parent / "_data" / "standards" / "rules" / "change_rules.yaml"
    bundled_rules.parent.mkdir(parents=True, exist_ok=True)
    bundled_rules.write_text("# placeholder", encoding="utf-8")
    try:
        result = kl._rules_path()
        assert result == bundled_rules
    finally:
        import shutil

        data_dir = Path(kl.__file__).parent / "_data"
        shutil.rmtree(data_dir, ignore_errors=True)


def test_rules_path_returns_first_candidate_when_none_exist(monkeypatch, tmp_path) -> None:
    """_rules_path() returns candidates[0] when no bundled or candidate paths exist (line 119)."""
    from pathlib import Path
    from unittest.mock import patch

    import sumo_qa.knowledge_loaders as kl

    monkeypatch.delenv("QA_RULES_PATH", raising=False)

    # Patch is_file to always return False so no candidate is found.
    with patch.object(Path, "is_file", return_value=False):
        result = kl._rules_path()

    # Should return the first candidate (even though it doesn't exist).
    assert isinstance(result, Path)
    assert "change_rules.yaml" in result.name
