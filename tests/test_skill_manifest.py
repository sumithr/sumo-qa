# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the deterministic skill-manifest index + partial loader.

Covers: markdown section indexing + stable section ids; duplicate headings;
missing/malformed frontmatter; empty sections; unknown skill_name/section/
mode; module indexing + path-traversal rejection; manifest/section/module/
full loader behaviour; and mode='full' byte-equivalence to the existing
zero-argument skill tool body.
"""

from __future__ import annotations

import pytest

from sumo_qa import skill_manifest as sm
from sumo_qa import skill_prompts

# --------------------------------------------------------------------------
# Pure helpers — section indexing, slugs, dedup, required flag (unit level)
# --------------------------------------------------------------------------


def _ids(sections):
    return [s["id"] for s in sections]


def test_frontmatter_is_first_section_and_required():
    text = "---\nname: x\ndescription: y\n---\n\n# Title\n\nbody\n"
    sections = sm._index_sections(text)
    assert sections[0]["id"] == "frontmatter"
    assert sections[0]["heading"] == "frontmatter"
    assert sections[0]["required"] is True
    assert sections[0]["level"] == 0


def test_section_ids_are_stable_slugs_from_headings():
    text = "# Deciding the QA approach\n\n## The Iron Law\n\n## When to Use\n"
    sections = sm._index_sections(text)
    assert _ids(sections) == ["deciding-the-qa-approach", "the-iron-law", "when-to-use"]


def test_duplicate_headings_get_deterministic_suffixes():
    text = "## Red Flags\n\nfoo\n\n## Red Flags\n\nbar\n\n## Red Flags\n\nbaz\n"
    sections = sm._index_sections(text)
    assert _ids(sections) == ["red-flags", "red-flags-2", "red-flags-3"]


def test_missing_frontmatter_yields_no_frontmatter_section():
    text = "# Title\n\nbody\n"
    sections = sm._index_sections(text)
    assert all(s["id"] != "frontmatter" for s in sections)
    assert _ids(sections) == ["title"]


def test_malformed_frontmatter_does_not_crash_manifest():
    # Unterminated frontmatter fence: _FRONTMATTER_RE won't match, so there is
    # simply no frontmatter section — the indexer must not raise.
    text = "---\nname: x\n: : :\n# Heading\n\nbody\n"
    sections = sm._index_sections(text)
    assert isinstance(sections, list)
    # The '# Heading' is still indexed as a section.
    assert any(s["heading"] == "Heading" for s in sections)


def test_empty_section_has_only_its_heading_text():
    text = "## Alpha\n## Beta\n\nbody\n"
    sections = sm._index_sections(text)
    alpha = next(s for s in sections if s["id"] == "alpha")
    # Empty section: text is just the heading line, tiny token estimate.
    assert alpha["estimated_tokens"] >= 1
    assert "Alpha" in alpha["_text"]
    assert "Beta" not in alpha["_text"]


def test_headings_inside_fenced_code_blocks_are_ignored():
    text = (
        "## Examples\n\n"
        "```python\n"
        "# this is a comment, not a heading\n"
        "## also not a heading\n"
        "```\n\n"
        "## Real Section\n"
    )
    sections = sm._index_sections(text)
    assert _ids(sections) == ["examples", "real-section"]


def test_tilde_fences_also_suppress_headings():
    text = "## Outer\n\n~~~\n# not a heading\n~~~\n\n## After\n"
    sections = sm._index_sections(text)
    assert _ids(sections) == ["outer", "after"]


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("The Iron Law", True),
        ("Iron Law", True),
        ("Checklist", True),
        ("Process Flow", True),  # contains 'flow'
        ("Red Flags — STOP and rework", True),  # contains 'red flags'
        ("When to Use", False),
        ("Examples", False),
        ("Routing table", False),
    ],
)
def test_required_flag_matches_named_structural_sections(heading, expected):
    assert sm._is_required(heading) is expected


def test_all_headings_exposed_even_when_names_differ():
    # A skill using non-canonical heading names still exposes every heading.
    text = "# X\n\n## Foo\n\n## Bar\n\n## Baz\n"
    sections = sm._index_sections(text)
    assert _ids(sections) == ["x", "foo", "bar", "baz"]
    assert all(s["required"] is False for s in sections if s["id"] != "frontmatter")


def test_slugify_falls_back_to_section_for_punctuation_only_heading():
    assert sm._slugify("***") == "section"


# --------------------------------------------------------------------------
# Module indexing + path-traversal rejection
# --------------------------------------------------------------------------


def test_index_modules_empty_when_no_modules_dir(tmp_path):
    skill_dir = tmp_path / "sumo-qa-x"
    skill_dir.mkdir()
    assert sm._index_modules(skill_dir) == []


def test_index_modules_slugs_filenames(tmp_path):
    skill_dir = tmp_path / "sumo-qa-x"
    (skill_dir / "modules").mkdir(parents=True)
    (skill_dir / "modules" / "verdict-format.md").write_text("body one", encoding="utf-8")
    (skill_dir / "modules" / "risk_ledger.md").write_text("body two", encoding="utf-8")
    modules = sm._index_modules(skill_dir)
    ids = {m["id"] for m in modules}
    assert ids == {"verdict-format", "risk-ledger"}
    by_id = {m["id"]: m for m in modules}
    assert by_id["verdict-format"]["path"] == "skills/sumo-qa-x/modules/verdict-format.md"
    assert by_id["verdict-format"]["_text"] == "body one"


@pytest.mark.parametrize(
    "candidate",
    ["../etc/passwd", "a/b", "a\\b", "..", "~/secret", "/abs/path"],
)
def test_has_traversal_rejects_path_like_ids(candidate):
    assert sm._has_traversal(candidate) is True


@pytest.mark.parametrize("candidate", ["red-flags", "iron-law", "verdict-format", ""])
def test_has_traversal_allows_flat_slugs(candidate):
    assert sm._has_traversal(candidate) is False


# --------------------------------------------------------------------------
# Manifest tool
# --------------------------------------------------------------------------


def test_list_skill_manifests_covers_every_bundled_skill():
    result = sm.list_skill_manifests()
    manifest_names = {m["skill_name"] for m in result["skills"]}
    skills_dir = skill_prompts._skills_dir()
    on_disk = {p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}
    assert manifest_names == on_disk
    assert on_disk, "expected at least one bundled skill"


def test_manifest_entries_carry_required_metadata_fields():
    result = sm.list_skill_manifests()
    sample = result["skills"][0]
    assert set(sample) == {
        "skill_name",
        "tool_name",
        "description",
        "content_hash",
        "estimated_tokens_full",
        "sections",
        "modules",
    }
    assert sample["tool_name"] == sample["skill_name"].replace("-", "_")
    assert len(sample["content_hash"]) == 64  # sha256 hex


def test_manifest_sections_do_not_leak_body_text():
    result = sm.list_skill_manifests()
    for skill in result["skills"]:
        for section in skill["sections"]:
            assert "_text" not in section
            assert set(section) == {"id", "heading", "level", "estimated_tokens", "required"}


def test_every_bundled_skill_exposes_a_required_iron_law_and_red_flags():
    # Partial loading must preserve Iron Law / Red Flags availability.
    result = sm.list_skill_manifests()
    for skill in result["skills"]:
        assert any(s["required"] for s in skill["sections"])


# --------------------------------------------------------------------------
# Loader: mode dispatch + error envelopes
# --------------------------------------------------------------------------


def _a_skill_name() -> str:
    return sorted(sm._skill_records())[0]


def test_load_unknown_skill_returns_envelope_with_valid_names():
    out = sm.load_skill_context("nope", "manifest")
    assert "error" in out
    assert "available_skills" in out
    assert _a_skill_name() in out["available_skills"]


def test_load_unknown_mode_returns_envelope_with_valid_modes():
    out = sm.load_skill_context(_a_skill_name(), "bogus")
    assert "error" in out
    assert out["available_modes"] == ["manifest", "section", "module", "full"]


def test_load_missing_skill_name_returns_required_envelope():
    # A host omitting skill_name must get the documented JSON envelope, not a
    # schema-level rejection — skill_name defaults to None and is handled here.
    out = sm.load_skill_context(mode="manifest")
    assert "error" in out
    assert "required" in out["error"].lower()
    assert _a_skill_name() in out["available_skills"]


def test_load_missing_mode_returns_required_envelope():
    out = sm.load_skill_context(_a_skill_name())
    assert "error" in out
    assert "required" in out["error"].lower()
    assert out["available_modes"] == ["manifest", "section", "module", "full"]


def test_load_manifest_mode_returns_sections_and_modules():
    name = _a_skill_name()
    out = sm.load_skill_context(name, "manifest")
    assert out["skill_name"] == name
    assert out["mode"] == "manifest"
    assert isinstance(out["sections"], list)
    assert "modules" in out


def test_load_section_without_section_lists_available():
    name = _a_skill_name()
    out = sm.load_skill_context(name, "section")
    assert "error" in out
    assert "available_sections" in out
    assert "frontmatter" in out["available_sections"]


def test_load_unknown_section_lists_available():
    name = _a_skill_name()
    out = sm.load_skill_context(name, "section", section="does-not-exist")
    assert "error" in out
    assert "available_sections" in out


def test_load_section_returns_that_section_text():
    name = _a_skill_name()
    manifest = sm.load_skill_context(name, "manifest")
    section_id = manifest["sections"][1]["id"]  # first real heading after frontmatter
    out = sm.load_skill_context(name, "section", section=section_id)
    assert out["mode"] == "section"
    assert out["section"] == section_id
    assert out["content"]


def test_load_section_rejects_path_traversal():
    name = _a_skill_name()
    out = sm.load_skill_context(name, "section", section="../../etc/passwd")
    assert "error" in out
    assert "traversal" in out["error"].lower()


def test_load_module_with_no_modules_returns_no_modules_envelope():
    name = _a_skill_name()  # bundled skills have no modules/ dir yet
    out = sm.load_skill_context(name, "module", module="anything")
    assert "error" in out
    assert "no modules" in out["error"].lower()
    assert out["available_modules"] == []


def test_load_module_missing_arg_returns_envelope(monkeypatch, tmp_path):
    # Force a skill record that *has* modules so the "requires a module id"
    # branch (distinct from "no modules") is exercised.
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", "alpha.md").write_text("alpha body", encoding="utf-8")
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    out = sm.load_skill_context("sumo-qa-fake", "module")
    assert "error" in out
    assert out["available_modules"] == ["alpha"]


def test_load_module_returns_module_text(monkeypatch, tmp_path):
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", "alpha.md").write_text("alpha body", encoding="utf-8")
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    out = sm.load_skill_context("sumo-qa-fake", "module", module="alpha")
    assert out["mode"] == "module"
    assert out["module"] == "alpha"
    assert out["content"] == "alpha body"
    assert out["path"] == "skills/sumo-qa-fake/modules/alpha.md"


def test_load_module_rejects_path_traversal(monkeypatch, tmp_path):
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", "alpha.md").write_text("alpha body", encoding="utf-8")
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    out = sm.load_skill_context("sumo-qa-fake", "module", module="../secret")
    assert "error" in out
    assert "traversal" in out["error"].lower()


# --------------------------------------------------------------------------
# mode='full' byte-equivalence to the existing zero-argument skill tool
# --------------------------------------------------------------------------


def test_load_unknown_module_id_lists_available(monkeypatch, tmp_path):
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", "alpha.md").write_text("alpha body", encoding="utf-8")
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    out = sm.load_skill_context("sumo-qa-fake", "module", module="missing")
    assert "error" in out
    assert "unknown module" in out["error"].lower()
    assert out["available_modules"] == ["alpha"]


def test_manifest_lists_modules_when_present(monkeypatch, tmp_path):
    # Drives _public_module + the modules[] manifest field with a real module.
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", "alpha.md").write_text("alpha body", encoding="utf-8")
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    result = sm.list_skill_manifests()
    modules = result["skills"][0]["modules"]
    assert modules and set(modules[0]) == {"id", "path", "estimated_tokens"}
    assert "_text" not in modules[0]


# --------------------------------------------------------------------------
# _skill_records discovery guards
# --------------------------------------------------------------------------


def test_skill_records_empty_when_skills_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path / "nope")
    assert sm._skill_records() == {}


def test_skill_records_skips_non_dir_and_dir_without_skill_md(monkeypatch, tmp_path):
    (tmp_path / "loose-file.txt").write_text("x", encoding="utf-8")  # non-dir entry
    (tmp_path / "sumo-qa-empty").mkdir()  # dir without SKILL.md
    real = tmp_path / "sumo-qa-real"
    real.mkdir()
    real.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-real\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    records = sm._skill_records()
    assert set(records) == {"sumo-qa-real"}


def test_full_mode_is_byte_for_byte_equal_to_skill_tool_body():
    skills_dir = skill_prompts._skills_dir()
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        # What the existing zero-arg skill tool would return:
        expected = skill_prompts._make_skill_callable(skill_path)()
        out = sm.load_skill_context(skill_dir.name, "full")
        assert out["mode"] == "full"
        assert out["content"] == expected, f"full-mode drift for {skill_dir.name}"
