# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the deterministic skill-manifest index + partial loader.

Covers: markdown section indexing + stable section ids; duplicate headings;
missing/malformed frontmatter; empty sections; unknown skill_name/section/
mode; module indexing + path-traversal rejection; manifest/section/module/
full loader behaviour; and mode='full' byte-equivalence to the existing
zero-argument skill tool body.
"""

from __future__ import annotations

import hashlib

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


# --------------------------------------------------------------------------
# CommonMark fence-parsing parity with knowledge_loaders._iter_entry_headings
# (#297). Technique: boundary value analysis — defects cluster at the fence
# rule boundaries (run length, indent, close-line content). Each case is
# derived from the CommonMark rule for that specific input, not recalled.
# --------------------------------------------------------------------------


def test_longer_backtick_fence_is_not_closed_by_a_shorter_inner_run():
    # CommonMark: a closing fence must be a run of the SAME char with length
    # >= the opener. A 4-backtick opener wraps a 3-backtick run as CONTENT, so
    # the block stays open until the matching 4-backtick close. Any '#' line
    # between the inner 3-backtick run and the 4-backtick close is INSIDE the
    # block and must NOT be indexed. The buggy len-blind tracker closes on the
    # inner ``` and indexes '## leaked' as a real section.
    text = (
        "## Outer\n\n"
        "````\n"  # 4-backtick opener
        "```\n"  # inner 3-backtick run — content, NOT a close
        "## leaked\n"  # still inside the block
        "````\n\n"  # 4-backtick close (length >= opener)
        "## After\n"
    )
    sections = sm._index_sections(text)
    assert _ids(sections) == ["outer", "after"]


def test_info_string_on_closing_fence_does_not_close_the_block():
    # CommonMark: a closing fence may carry ONLY whitespace after the run; a
    # trailing info string (```bash) makes it content, not a valid close. So the
    # block opened by ``` stays open across the ```bash line and the '## leaked'
    # heading inside it, until the bare ``` close. The buggy tracker treats the
    # ```bash line as a close and indexes '## leaked'.
    text = (
        "## Outer\n\n"
        "```\n"  # opener
        "```bash\n"  # info string after the run — content, NOT a close
        "## leaked\n"  # still inside the block
        "```\n\n"  # bare close
        "## After\n"
    )
    sections = sm._index_sections(text)
    assert _ids(sections) == ["outer", "after"]


def test_info_string_on_opening_fence_is_allowed():
    # An OPENING fence may carry an info string (language tag). The '#' lines
    # inside the ```python block must be suppressed; the block closes on the
    # bare ```.
    text = (
        "## Examples\n\n"
        "```python\n"
        "# not a heading\n"
        "## also not a heading\n"
        "```\n\n"
        "## After\n"
    )
    sections = sm._index_sections(text)
    assert _ids(sections) == ["examples", "after"]


def test_indented_four_space_backtick_run_is_not_a_fence():
    # CommonMark: a line indented >= 4 spaces is an indented code block, NOT a
    # fence opener. So the 4-space-indented ``` does NOT open a fenced block,
    # and the '## Real' heading that follows is a normal heading. The buggy
    # tracker (\\s* allows any indent) opens a fence on the indented run and
    # swallows '## Real'.
    text = "## Outer\n\n    ```\n## Real\n"
    sections = sm._index_sections(text)
    assert _ids(sections) == ["outer", "real"]


def test_unclosed_fence_at_eof_suppresses_trailing_headings():
    # An opener with no matching close runs to EOF: every '#' line after it is
    # inside the (unterminated) block and must NOT be indexed.
    text = "## Outer\n\n```\n## inside unterminated block\nstill inside\n"
    sections = sm._index_sections(text)
    assert _ids(sections) == ["outer"]


def test_tilde_fence_is_not_closed_by_a_backtick_run():
    # CommonMark: a fence closes only on a run of the SAME char as the opener.
    # A ~~~ block is not closed by a ``` line; the '## leaked' between them stays
    # inside the block until the matching ~~~ close.
    text = (
        "## Outer\n\n"
        "~~~\n"  # tilde opener
        "```\n"  # backtick run — different char, NOT a close
        "## leaked\n"  # still inside the tilde block
        "~~~\n\n"  # tilde close
        "## After\n"
    )
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
# Manifest tool — compact default (detail="compact") vs full_index opt-in (#306)
# --------------------------------------------------------------------------

_COMPACT_KEYS = {
    "skill_name",
    "tool_name",
    "description",
    "content_hash",
    "estimated_tokens_full",
}


def test_list_skill_manifests_covers_every_bundled_skill():
    result = sm.list_skill_manifests()
    manifest_names = {m["skill_name"] for m in result["skills"]}
    skills_dir = skill_prompts._skills_dir()
    on_disk = {p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}
    assert manifest_names == on_disk
    assert on_disk, "expected at least one bundled skill"


def test_compact_is_the_default_and_omits_section_and_module_arrays():
    # #306: the no-arg call is the compact routing projection — metadata only,
    # NO sections[]/modules[] keys, so a host can route across all skills cheaply.
    result = sm.list_skill_manifests()
    assert result["skills"], "expected at least one bundled skill"
    for entry in result["skills"]:
        assert set(entry) == _COMPACT_KEYS
        assert "sections" not in entry
        assert "modules" not in entry


def test_detail_compact_equals_default():
    # #306 AC: detail="compact" is equivalent to the default.
    assert sm.list_skill_manifests(detail="compact") == sm.list_skill_manifests()


def test_compact_entries_carry_the_routing_metadata():
    sample = sm.list_skill_manifests()["skills"][0]
    assert sample["tool_name"] == sample["skill_name"].replace("-", "_")
    assert len(sample["content_hash"]) == 64  # sha256 hex
    assert isinstance(sample["estimated_tokens_full"], int)


def test_full_index_restores_sections_and_modules():
    # #306 AC: detail="full_index" returns the previous full-index schema with
    # public sections[]/modules[] arrays.
    result = sm.list_skill_manifests(detail="full_index")
    assert result["skills"], "expected at least one bundled skill"
    for entry in result["skills"]:
        assert set(entry) == _COMPACT_KEYS | {"sections", "modules"}


def test_full_index_sections_do_not_leak_body_text():
    result = sm.list_skill_manifests(detail="full_index")
    for skill in result["skills"]:
        for section in skill["sections"]:
            assert "_text" not in section
            assert set(section) == {"id", "heading", "level", "estimated_tokens", "required"}
        for module in skill["modules"]:
            assert "_text" not in module


def test_full_index_preserves_required_iron_law_and_red_flags():
    # Partial loading must preserve Iron Law / Red Flags availability.
    result = sm.list_skill_manifests(detail="full_index")
    for skill in result["skills"]:
        assert any(s["required"] for s in skill["sections"])


def test_invalid_detail_returns_error_envelope_not_raise():
    # #306 AC: invalid detail returns a JSON error envelope, never raises —
    # the host-friendly style the loader already uses. Exact-match validation:
    # a value that merely CONTAINS "compact" ("compact_index") is still invalid
    # (the equivalence-partitioning substring-confusion failure mode).
    out = sm.list_skill_manifests(detail="compact_index")
    assert "error" in out
    assert "skills" not in out
    assert out["available_detail"] == ["compact", "full_index"]


def test_invalid_detail_empty_string_returns_envelope():
    out = sm.list_skill_manifests(detail="")
    assert "error" in out and "available_detail" in out


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
    result = sm.list_skill_manifests(detail="full_index")
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


# --------------------------------------------------------------------------
# Lever 6 (#290): per-slice content_hash + estimated_tokens + change-detection
# --------------------------------------------------------------------------
#
# Technique: decision tables — the response shape is a conjunction of
# (mode, known_hash supplied?, known_hash matches the slice?). Each row below
# pins one combination to its exact output, so a partial/heuristic impl that
# satisfies one row but not the others is caught.


def _expected_hash(text: str) -> str:
    # Derive from the SAME slice text the loader returns, not a recalled
    # constant — sha256 of the returned content, hex-digested.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _heaviest_skill_with_real_section():
    """A real bundled skill name plus the id of its first non-frontmatter
    section (every bundled skill has at least one heading after frontmatter)."""
    name = _a_skill_name()
    manifest = sm.load_skill_context(name, "manifest")
    section_id = manifest["sections"][1]["id"]
    return name, section_id


def test_full_mode_returns_content_hash_and_estimated_tokens():
    name = _a_skill_name()
    out = sm.load_skill_context(name, "full")
    # Hash is sha256 of EXACTLY the returned content slice (derived, not recalled).
    assert out["content_hash"] == _expected_hash(out["content"])
    assert len(out["content_hash"]) == 64
    # estimated_tokens is len/4 (ceil) of the returned slice — the project estimator.
    assert out["estimated_tokens"] == (len(out["content"]) + 3) // 4


def test_section_mode_returns_content_hash_and_estimated_tokens():
    name, section_id = _heaviest_skill_with_real_section()
    out = sm.load_skill_context(name, "section", section=section_id)
    assert out["content_hash"] == _expected_hash(out["content"])
    assert out["estimated_tokens"] == (len(out["content"]) + 3) // 4


def test_module_mode_returns_content_hash_and_estimated_tokens(monkeypatch, tmp_path):
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", "alpha.md").write_text("alpha body", encoding="utf-8")
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    out = sm.load_skill_context("sumo-qa-fake", "module", module="alpha")
    assert out["content"] == "alpha body"
    assert out["content_hash"] == _expected_hash("alpha body")
    assert out["estimated_tokens"] == (len("alpha body") + 3) // 4


def test_slice_hash_is_stable_across_repeated_loads():
    # Repeated partial loads of the same slice return the identical hash — the
    # property a caller relies on to skip re-sending unchanged text.
    name, section_id = _heaviest_skill_with_real_section()
    first = sm.load_skill_context(name, "section", section=section_id)
    second = sm.load_skill_context(name, "section", section=section_id)
    assert first["content_hash"] == second["content_hash"]
    assert first["content"] == second["content"]


def test_change_detection_unchanged_omits_body_and_flags_not_changed():
    # known_hash matches the current slice → changed=False and the body is
    # omitted (the token saving). No hidden cache: the answer is derived purely
    # from re-hashing the live slice and comparing to the caller-supplied hash.
    name, section_id = _heaviest_skill_with_real_section()
    current = sm.load_skill_context(name, "section", section=section_id)
    again = sm.load_skill_context(
        name, "section", section=section_id, known_hash=current["content_hash"]
    )
    assert again["changed"] is False
    assert again["content_hash"] == current["content_hash"]
    assert "content" not in again


def test_change_detection_changed_returns_body_and_flags_changed():
    # known_hash does NOT match → changed=True and the full slice text is returned.
    name, section_id = _heaviest_skill_with_real_section()
    current = sm.load_skill_context(name, "section", section=section_id)
    out = sm.load_skill_context(
        name, "section", section=section_id, known_hash="sha256-that-will-never-match"
    )
    assert out["changed"] is True
    assert out["content"] == current["content"]
    assert out["content_hash"] == current["content_hash"]


def test_change_detection_works_for_full_mode():
    name = _a_skill_name()
    current = sm.load_skill_context(name, "full")
    unchanged = sm.load_skill_context(name, "full", known_hash=current["content_hash"])
    assert unchanged["changed"] is False
    assert "content" not in unchanged
    changed = sm.load_skill_context(name, "full", known_hash="nope")
    assert changed["changed"] is True
    assert changed["content"] == current["content"]


def test_no_known_hash_default_returns_body_and_no_changed_flag():
    # The no-cache default: omitting known_hash returns the body unchanged
    # (backward-compatible) and does NOT add a `changed` flag.
    name, section_id = _heaviest_skill_with_real_section()
    out = sm.load_skill_context(name, "section", section=section_id)
    assert "content" in out
    assert "changed" not in out


def test_manifest_mode_is_unaffected_by_known_hash():
    # known_hash is a partial-load affordance; manifest mode keeps its shape.
    name = _a_skill_name()
    out = sm.load_skill_context(name, "manifest", known_hash="anything")
    assert out["mode"] == "manifest"
    assert "sections" in out
