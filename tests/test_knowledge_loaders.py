# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.knowledge_loaders.

These tools read markdown catalogues and return them verbatim. No inference,
no filtering beyond optional metadata-based subset selection. The tests
assert that known canonical entries are present in the returned text.
"""

import pytest

from sumo_qa import knowledge_loaders
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


def test_load_standards_filter_returns_core_pack_for_canonical_classification():
    text = sumo_qa_load_standards(classification="business_logic_change")

    assert "QA Shift-Left Core Standards" in text
    assert "ISTQB-Aligned Senior QA Standards" not in text


def test_load_standards_filter_accepts_multiple_classifications(tmp_path, monkeypatch):
    import yaml as _yaml

    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "api.yaml").write_text(
        _yaml.safe_dump(
            {"applies_to_classifications": ["api_contract_change"], "name": "api_pack"}
        ),
        encoding="utf-8",
    )
    (packs_dir / "business.yaml").write_text(
        _yaml.safe_dump(
            {"applies_to_classifications": ["business_logic_change"], "name": "business_pack"}
        ),
        encoding="utf-8",
    )
    (packs_dir / "security.yaml").write_text(
        _yaml.safe_dump({"applies_to_classifications": ["security_change"], "name": "sec_pack"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))

    result = sumo_qa_load_standards(classification="api_contract_change, business_logic_change")

    assert "api_pack" in result
    assert "business_pack" in result
    assert "sec_pack" not in result


def test_metadata_terms_accepts_scalar_string_and_other_values():
    from sumo_qa.knowledge_loaders import _metadata_terms

    assert _metadata_terms("api_contract_change, security_change") == {
        "api_contract_change",
        "security_change",
    }
    assert _metadata_terms(123) == {"123"}


from sumo_qa.knowledge_loaders import sumo_qa_load_rules


def test_load_rules_returns_text_when_no_filter():
    text = sumo_qa_load_rules()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_rules_filter_by_classification_is_smaller():
    full = sumo_qa_load_rules()
    filtered = sumo_qa_load_rules(classification="security_change")
    assert len(filtered) <= len(full)


def test_load_rules_filter_accepts_multiple_classifications(tmp_path, monkeypatch):
    import yaml as _yaml

    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        _yaml.safe_dump(
            {
                "api_contract_change": {"must_consider": ["contract"]},
                "business_logic_change": {"must_consider": ["decision"]},
                "security_change": {"must_consider": ["auth"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))

    result = sumo_qa_load_rules(classification="api_contract_change business_logic_change")

    assert "api_contract_change" in result
    assert "business_logic_change" in result
    assert "security_change" not in result


@pytest.mark.parametrize(
    ("classification", "legacy_key", "expected_text"),
    [
        ("frontend_change", "ui_only_change", "display correctness"),
        ("config_change", "configuration_change", "environment override behavior"),
        ("data_migration", "data_mapping_change", "source-to-target parity"),
        ("performance_change", "caching_change", "stale data"),
        ("infrastructure_change", "configuration_change", "deployment rollback"),
    ],
)
def test_load_rules_filter_maps_canonical_classification_to_legacy_rule_key(
    classification, legacy_key, expected_text
):
    result = sumo_qa_load_rules(classification=classification)

    assert f"{classification}:" in result
    assert f"{legacy_key}:" not in result
    assert expected_text in result


def test_same_surface_different_contexts_get_identical_probes():
    """Issue #98 AC: two different change contexts sharing one underlying risk
    surface must receive the SAME concrete guidance, not tech-tailored variants.

    `config_change` (application config) and `infrastructure_change` (deploy /
    IaC) both resolve to the CI/config/deploy surface, so the WHOLE probe set
    must be identical for both — not merely sharing a few markers. Asserting the
    full `must_consider` list (rather than substring presence) proves the
    surface→probe mapping is keyed on the risk pattern, not the technology, and
    cannot be satisfied by a partial overlap.
    """
    import yaml as _yaml

    app_config = _yaml.safe_load(sumo_qa_load_rules(classification="config_change"))
    infra = _yaml.safe_load(sumo_qa_load_rules(classification="infrastructure_change"))

    app_probes = app_config["config_change"]["must_consider"]
    infra_probes = infra["infrastructure_change"]["must_consider"]

    # Identical guidance, and it actually carries the enriched concrete probes.
    assert app_probes == infra_probes
    assert (
        "A missing or empty value falls back to a safe default rather than crashing on startup"
        in app_probes
    )


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
        # Clean up — only remove the standards/ subtree we created. The parent
        # _data/ directory may contain other bundled artefacts (e.g.
        # plugin_metadata.json from plugin_packaging) that this test did not
        # create and must not delete.
        import shutil

        standards_dir = Path(kl.__file__).parent / "_data" / "standards"
        shutil.rmtree(standards_dir, ignore_errors=True)


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
        # Clean up — only remove the standards/ subtree we created. The parent
        # _data/ directory may contain other bundled artefacts that this test
        # did not create and must not delete.
        import shutil

        standards_dir = Path(kl.__file__).parent / "_data" / "standards"
        shutil.rmtree(standards_dir, ignore_errors=True)


def test_rules_path_returns_first_candidate_when_none_exist(monkeypatch, tmp_path) -> None:
    """_rules_path() returns candidates[0] when no bundled or candidate paths exist (line 119)."""
    from pathlib import Path
    from unittest.mock import patch

    import sumo_qa.knowledge_loaders as kl

    monkeypatch.delenv("QA_RULES_PATH", raising=False)

    # Patch is_file to always return False so no candidate is found.
    with patch.object(Path, "is_file", return_value=False):
        result = kl._rules_path()

    # Should return the FIRST candidate (which has 'standards' in its parts);
    # asserting 'standards' guards against `return candidates[0]` → `candidates[1]`,
    # since candidates[1] is `<repo>/rules/change_rules.yaml` (no 'standards').
    assert isinstance(result, Path)
    assert "change_rules.yaml" in result.name
    assert "standards" in result.parts, (
        f"Fallback must return candidates[0] (with 'standards' in path); got {result.parts}"
    )


# ---------------------------------------------------------------------------
# Phase 4.3 — strengthening tests against 5/19 mutation survivors
# ---------------------------------------------------------------------------


def test_classification_filter_strips_backticks_and_quotes():
    """Backtick/quote-wrapped classification names must be normalised AND
    pure-backtick inputs must be filtered out.

    Kills the strip→None mutations on lines 11 + 13 of
    _classification_filter_terms: with strip(None) the default whitespace-only
    strip leaves the wrapping chars in place, so 'auth' would appear as
    '\\`auth\\`' in the result and a pure-backtick token would pass the filter.
    """
    from sumo_qa.knowledge_loaders import _classification_filter_terms

    # Result-expression strip: wrapping chars must be removed from the output.
    assert _classification_filter_terms("`api_contract_change`") == {"api_contract_change"}
    assert _classification_filter_terms("'security_change'") == {"security_change"}
    assert _classification_filter_terms('"data_migration"') == {"data_migration"}

    # If-filter strip: a token consisting only of wrapping chars must drop out,
    # not pass through as a backtick/quote-only entry. The result set must
    # contain only the real classification name, not a stray empty-after-strip
    # placeholder.
    assert _classification_filter_terms("```, security_change") == {"security_change"}
    assert _classification_filter_terms("'''") == set()
    assert _classification_filter_terms('"""') == set()


def test_metadata_terms_strips_backticks_in_list_inputs():
    """List/tuple/set values containing backtick/quote-wrapped strings must be
    normalised AND pure-quote tokens must be filtered out.

    Kills the strip→None mutations on lines 7 + 10 of _metadata_terms.
    """
    from sumo_qa.knowledge_loaders import _metadata_terms

    # Result-expression strip on the list branch.
    assert _metadata_terms(["`auth_change`", '"config_change"']) == {
        "auth_change",
        "config_change",
    }
    assert _metadata_terms(("'data_migration'",)) == {"data_migration"}

    # If-filter strip — pure-quote items must not survive into the output set.
    assert _metadata_terms(["```", "security_change"]) == {"security_change"}
    assert _metadata_terms(["```", "'''", '"""']) == set()


def test_load_rules_resolves_aliases_for_multiple_terms_in_one_call(tmp_path, monkeypatch):
    """When several terms are requested and the first is a direct hit while a
    later one needs alias resolution, both must end up in the response.

    Kills the continue→break mutation on line 19 of sumo_qa_load_rules:
    with `break`, the alias-resolution loop would short-circuit on the first
    direct-hit term and the alias-only term would be dropped from the output.
    """
    import yaml as _yaml

    from sumo_qa.knowledge_loaders import sumo_qa_load_rules

    # Build a rules doc where:
    #   - "api_contract_change" is a direct hit (no alias needed)
    #   - "frontend_change" is NOT in the doc; its alias "ui_only_change" IS
    # Alphabetical iteration order (sorted in the source) processes
    # api_contract_change first, then frontend_change. With `continue`, the
    # loop continues to frontend_change's alias resolution. With `break`,
    # the loop exits and frontend_change never resolves.
    rules_doc = {
        "api_contract_change": {"checks": ["contract_v1"]},
        "ui_only_change": {"checks": ["snapshot_diff"]},  # alias for frontend_change
    }
    rules_file = tmp_path / "change_rules.yaml"
    rules_file.write_text(_yaml.safe_dump(rules_doc), encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))

    result_text = sumo_qa_load_rules(classification="api_contract_change, frontend_change")
    result = _yaml.safe_load(result_text)

    # Both terms must be in the result; frontend_change resolves via alias.
    assert set(result.keys()) == {"api_contract_change", "frontend_change"}, (
        f"Expected both terms in result; got {set(result.keys())}. "
        "If only 'api_contract_change' is present, the loop short-circuited "
        "(continue→break mutation)."
    )
    assert result["frontend_change"] == {"checks": ["snapshot_diff"]}


# --- Ingested-pack precedence tiers (issue #92) ---------------------------------
# Precedence with no env var: project pack > global pack > bundled > repo root.
# Knowledge markdown resolves per file; standards/rules resolve first-tier-exists.


def test_read_prefers_project_pack_per_file(tmp_path, monkeypatch):
    monkeypatch.delenv("QA_KNOWLEDGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / ".sumo-qa" / "knowledge"
    proj.mkdir(parents=True)
    (proj / "principles.md").write_text("CUSTOM PRINCIPLES", encoding="utf-8")
    # principles overridden; techniques falls through to bundled/repo (non-empty).
    assert knowledge_loaders.sumo_qa_load_principles() == "CUSTOM PRINCIPLES"
    assert "CUSTOM PRINCIPLES" not in knowledge_loaders.sumo_qa_load_techniques()


def test_read_project_beats_global(tmp_path, monkeypatch):
    monkeypatch.delenv("QA_KNOWLEDGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    g = tmp_path / "xdg" / "sumo-qa" / "knowledge"
    g.mkdir(parents=True)
    (g / "principles.md").write_text("GLOBAL", encoding="utf-8")
    p = tmp_path / ".sumo-qa" / "knowledge"
    p.mkdir(parents=True)
    (p / "principles.md").write_text("PROJECT", encoding="utf-8")
    assert knowledge_loaders.sumo_qa_load_principles() == "PROJECT"


def test_read_uses_global_when_no_project_pack(tmp_path, monkeypatch):
    monkeypatch.delenv("QA_KNOWLEDGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    g = tmp_path / "xdg" / "sumo-qa" / "knowledge"
    g.mkdir(parents=True)
    (g / "principles.md").write_text("GLOBAL ONLY", encoding="utf-8")
    assert knowledge_loaders.sumo_qa_load_principles() == "GLOBAL ONLY"


def test_env_var_still_wins_over_project_pack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / "principles.md").write_text("ENV", encoding="utf-8")
    proj = tmp_path / ".sumo-qa" / "knowledge"
    proj.mkdir(parents=True)
    (proj / "principles.md").write_text("PROJECT", encoding="utf-8")
    monkeypatch.setenv("QA_KNOWLEDGE_PATH", str(env_dir))
    assert knowledge_loaders.sumo_qa_load_principles() == "ENV"


def test_standards_dir_prefers_project_pack(tmp_path, monkeypatch):
    monkeypatch.delenv("QA_STANDARDS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    packs = tmp_path / ".sumo-qa" / "standards" / "packs"
    packs.mkdir(parents=True)
    (packs / "team.yaml").write_text("name: team\n", encoding="utf-8")
    assert knowledge_loaders._standards_dir() == packs


def test_standards_dir_ignores_empty_project_packs_dir(tmp_path, monkeypatch):
    # An empty .sumo-qa/standards/packs must NOT shadow the bundled packs.
    monkeypatch.delenv("QA_STANDARDS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sumo-qa" / "standards" / "packs").mkdir(parents=True)
    assert knowledge_loaders._standards_dir() != tmp_path / ".sumo-qa" / "standards" / "packs"


def test_rules_path_prefers_project_pack(tmp_path, monkeypatch):
    monkeypatch.delenv("QA_RULES_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    rules = tmp_path / ".sumo-qa" / "standards" / "rules"
    rules.mkdir(parents=True)
    f = rules / "change_rules.yaml"
    f.write_text("{}\n", encoding="utf-8")
    assert knowledge_loaders._rules_path() == f


# ---------------------------------------------------------------------------
# Issue #99 — docs_change and test_change rule entries (+ #176 fold-in)
#
# `classifications.md` lists docs_change and test_change as canonical
# classifications, but `change_rules.yaml` previously carried no concrete
# rule entries for them. These tests pin the entry shape:
#   - direct-hit filtering returns docs/test-specific guidance,
#   - multi-classification filtering returns docs/test entries WITH the
#     existing aliased entries for config/infrastructure (the AC),
#   - the docs entry carries the inventory-drift probe (#176 fold-in):
#     a diff that changes a documented count / inventory / public-surface
#     name / schema field must trigger a repo-wide search for stale
#     occurrences of the old value.
# ---------------------------------------------------------------------------


def test_load_rules_returns_docs_focused_entry_for_docs_change():
    """`sumo_qa_load_rules('docs_change')` returns a docs-specific entry."""
    result = sumo_qa_load_rules(classification="docs_change")

    assert "docs_change:" in result
    text = result.lower()
    assert "broken links" in text or "stale commands" in text
    assert "ui_only_change" not in result  # not an accidental alias hit


def test_load_rules_returns_test_focused_entry_for_test_change():
    """`sumo_qa_load_rules('test_change')` returns a test-specific entry."""
    result = sumo_qa_load_rules(classification="test_change")

    assert "test_change:" in result
    text = result.lower()
    assert "tautological" in text or "fails on the intended" in text


def test_docs_change_carries_inventory_drift_probe():
    """#176 fold-in: when a diff changes a documented count, inventory,
    public-surface name, or schema field, the docs_change entry must instruct
    a repo-wide search for stale occurrences of the old value — not just the
    obvious doc."""
    result = sumo_qa_load_rules(classification="docs_change")

    text = result.lower()
    assert "stale occurrences" in text or "repo-wide" in text, (
        "docs_change must carry the inventory-drift probe text"
    )
    # The probe must name what's being searched for, not just say 'search the repo'.
    assert any(
        marker in text for marker in ("documented count", "inventory", "public-surface", "schema")
    ), "docs_change drift probe must enumerate count / inventory / public surface / schema"


def test_load_rules_multi_filter_docs_plus_aliased_config(tmp_path, monkeypatch):
    """Multi-classification filter: docs_change (direct hit) alongside
    config_change (resolved via the existing alias to configuration_change).
    Uses an in-test rules doc so the assertion is independent of unrelated
    drift in the real file."""
    import yaml as _yaml

    rules_doc = {
        "docs_change": {"must_consider": ["accuracy"]},
        "test_change": {"must_consider": ["tautology"]},
        "configuration_change": {"must_consider": ["env override"]},
    }
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(_yaml.safe_dump(rules_doc, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))

    result = _yaml.safe_load(sumo_qa_load_rules(classification="docs_change, config_change"))

    assert set(result.keys()) == {"docs_change", "config_change"}
    assert result["config_change"] == {"must_consider": ["env override"]}


def test_load_rules_multi_filter_test_plus_aliased_infrastructure(tmp_path, monkeypatch):
    """Multi-classification filter: test_change (direct hit) alongside
    infrastructure_change (resolved via the existing alias to
    configuration_change)."""
    import yaml as _yaml

    rules_doc = {
        "test_change": {"must_consider": ["tautology"]},
        "configuration_change": {"must_consider": ["deploy rollback"]},
    }
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(_yaml.safe_dump(rules_doc, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))

    result = _yaml.safe_load(
        sumo_qa_load_rules(classification="test_change, infrastructure_change")
    )

    assert set(result.keys()) == {"test_change", "infrastructure_change"}
    assert result["infrastructure_change"] == {"must_consider": ["deploy rollback"]}


def test_load_rules_multi_filter_all_four_in_one_call(tmp_path, monkeypatch):
    """Codex review follow-up: a real review may classify a change as carrying
    several concerns at once. The earlier mixed tests only paired one new
    direct-hit (docs/test) with one alias (config/infrastructure); a regression
    that silently drops an entry inside the dedup/alias loop would pass them
    all. Exercise the FULL four-classification call in one go so the result
    must contain all four entries non-empty and correctly keyed."""
    import yaml as _yaml

    rules_doc = {
        "docs_change": {"must_consider": ["doc accuracy"]},
        "test_change": {"must_consider": ["tautology"]},
        "configuration_change": {"must_consider": ["env override"]},
    }
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(_yaml.safe_dump(rules_doc, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))

    result = _yaml.safe_load(
        sumo_qa_load_rules(
            classification="docs_change, test_change, config_change, infrastructure_change"
        )
    )

    assert set(result.keys()) == {
        "docs_change",
        "test_change",
        "config_change",
        "infrastructure_change",
    }
    # Direct hits keep their own payloads; aliases (config/infrastructure) both
    # resolve through configuration_change, so they share its payload — the
    # alias mechanism must reach the same source for both.
    assert result["docs_change"] == {"must_consider": ["doc accuracy"]}
    assert result["test_change"] == {"must_consider": ["tautology"]}
    assert result["config_change"] == {"must_consider": ["env override"]}
    assert result["infrastructure_change"] == {"must_consider": ["env override"]}
