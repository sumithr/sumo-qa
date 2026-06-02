# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the additive MCP resources/resource-templates over the skill index.

Issue #289 (epic #137, Lever 3). The resources expose the SAME content the
``skill_manifest`` loader already serves, as FastMCP resources/templates:

  * ``sumoqa://skills``                              (static index)
  * ``sumoqa://skills/{skill_name}/manifest``        (template)
  * ``sumoqa://skills/{skill_name}/sections/{section_id}``  (template)
  * ``sumoqa://skills/{skill_name}/modules/{module_id}``    (template)
  * ``sumoqa://skills/{skill_name}/full``            (template)

Discipline (equivalence partitioning over the four read modes + the index;
decision-table over URI param combinations; path-traversal negative case):

  * Registration — the templates + static resource are advertised.
  * Content equivalence — each resource body is byte-for-byte the loader's
    JSON for the same skill/section/module/full (single source of truth).
  * Additive — registering resources adds NO tools and does not rename the
    existing tool path.
  * Error surfacing — unknown skill/section/module and path-traversal attempts
    come back as the loader's error envelope as resource CONTENT, not as a
    crash (the loader never raises).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sumo_qa import skill_manifest as sm
from sumo_qa.server import build_mcp_server


@pytest.fixture(scope="module")
def mcp():
    return build_mcp_server()


@pytest.fixture
def module_mcp(monkeypatch, tmp_path):
    """A server whose skill index is a tmp skills dir with a REAL module file.

    No bundled skill ships a ``modules/`` dir, so the module resource template
    (``sumoqa://skills/{skill}/modules/{module}``) would otherwise never get
    exercised at the resource layer. This mirrors the monkeypatch pattern from
    ``tests/test_skill_manifest.py`` (``sm._skills_dir`` → a ``tmp_path`` skill
    holding ``modules/<x>.md``): records are read fresh on each loader call, so
    a server built under the patch reads the fake skill end-to-end.

    Yields ``(server, skill_name, module_id)``.
    """
    skill_name = "sumo-qa-fake"
    module_id = "alpha"
    skill_dir = tmp_path / skill_name
    (skill_dir / "modules").mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n# T\n", encoding="utf-8"
    )
    skill_dir.joinpath("modules", f"{module_id}.md").write_text(
        "alpha module body", encoding="utf-8"
    )
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    server = build_mcp_server()
    return server, skill_name, module_id


def _read(mcp, uri: str) -> str:
    """Read one resource URI through FastMCP and return its text content."""
    contents = list(asyncio.run(mcp.read_resource(uri)))
    assert len(contents) == 1, f"expected one content block for {uri}, got {contents!r}"
    return contents[0].content


def _a_skill_with_sections() -> str:
    # The compact default carries no sections[]; ask for the full index here.
    skills = sm.list_skill_manifests(detail="full_index")["skills"]
    for s in skills:
        if s["sections"]:
            return s["skill_name"]
    raise AssertionError("no skill has sections")


# --------------------------------------------------------------------------
# Registration — templates + static index advertised
# --------------------------------------------------------------------------


def test_resource_templates_are_registered(mcp):
    templates = {t.uriTemplate for t in asyncio.run(mcp.list_resource_templates())}
    assert "sumoqa://skills/{skill_name}/manifest" in templates
    assert "sumoqa://skills/{skill_name}/sections/{section_id}" in templates
    assert "sumoqa://skills/{skill_name}/modules/{module_id}" in templates
    assert "sumoqa://skills/{skill_name}/full" in templates


def test_static_index_resource_is_registered(mcp):
    uris = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
    assert "sumoqa://skills" in uris


def test_static_index_matches_list_skill_manifests(mcp):
    body = _read(mcp, "sumoqa://skills")
    assert json.loads(body) == sm.list_skill_manifests()


def test_static_index_mirrors_the_compact_default(mcp):
    # #306: sumoqa://skills mirrors the compact default — metadata only, no
    # sections[]/modules[] — not the full index.
    payload = json.loads(_read(mcp, "sumoqa://skills"))
    assert payload == sm.list_skill_manifests(detail="compact")
    assert payload["skills"], "expected at least one bundled skill"
    for entry in payload["skills"]:
        assert "sections" not in entry
        assert "modules" not in entry


# --------------------------------------------------------------------------
# Content equivalence — each mode byte-for-byte equals the loader output
# --------------------------------------------------------------------------


def test_manifest_resource_matches_loader(mcp):
    skill = _a_skill_with_sections()
    body = _read(mcp, f"sumoqa://skills/{skill}/manifest")
    assert json.loads(body) == sm.load_skill_context(skill, "manifest")


def test_full_resource_matches_loader(mcp):
    skill = _a_skill_with_sections()
    body = _read(mcp, f"sumoqa://skills/{skill}/full")
    assert json.loads(body) == sm.load_skill_context(skill, "full")


def test_section_resource_matches_loader(mcp):
    skill = _a_skill_with_sections()
    section_id = sm.load_skill_context(skill, "manifest")["sections"][0]["id"]
    body = _read(mcp, f"sumoqa://skills/{skill}/sections/{section_id}")
    assert json.loads(body) == sm.load_skill_context(skill, "section", section=section_id)


def test_module_resource_matches_loader(module_mcp):
    server, skill, module_id = module_mcp
    # Sanity: the fake skill really exposes the module via the manifest.
    assert sm.load_skill_context(skill, "manifest")["modules"][0]["id"] == module_id
    body = _read(server, f"sumoqa://skills/{skill}/modules/{module_id}")
    assert json.loads(body) == sm.load_skill_context(skill, "module", module=module_id)


# --------------------------------------------------------------------------
# Additive — no new tools, existing tool path unchanged
# --------------------------------------------------------------------------


def test_resources_add_no_tools(mcp):
    tool_names = {t.name for t in asyncio.run(mcp.list_tools())}
    # The model-callable loader tools from #285 remain; no per-resource tool.
    assert "sumo_qa_load_skill_context" in tool_names
    assert "sumo_qa_list_skill_manifests" in tool_names
    assert not any(name.startswith("sumoqa_resource") for name in tool_names)


# --------------------------------------------------------------------------
# Error surfacing — loader error envelope returned as content, not a crash
# --------------------------------------------------------------------------


def test_unknown_skill_returns_error_envelope(mcp):
    body = _read(mcp, "sumoqa://skills/does-not-exist/manifest")
    payload = json.loads(body)
    assert "error" in payload
    assert "available_skills" in payload


def test_unknown_section_returns_error_envelope(mcp):
    skill = _a_skill_with_sections()
    body = _read(mcp, f"sumoqa://skills/{skill}/sections/no-such-section")
    payload = json.loads(body)
    assert "error" in payload
    assert "available_sections" in payload


def test_module_resource_on_skill_without_modules_returns_error_envelope(mcp):
    # Exercises the module template even before any bundled skill ships
    # modules: a real skill name + a module id on a skill that has none must
    # return the loader's "no modules" error envelope as content.
    skill = _a_skill_with_sections()
    assert not sm.load_skill_context(skill, "manifest")["modules"], (
        f"{skill} unexpectedly has modules; pick a module-less skill"
    )
    body = _read(mcp, f"sumoqa://skills/{skill}/modules/anything")
    payload = json.loads(body)
    assert "error" in payload
    assert "available_modules" in payload


def test_module_path_traversal_is_rejected(module_mcp):
    server, skill, _module_id = module_mcp
    # The fake skill HAS modules, so the "no modules" guard does not short
    # circuit — the traversal value reaches the per-module lookup and trips
    # the loader's traversal guard. FastMCP passes the param through verbatim
    # (no URL-decoding), so the `..` segment survives to the loader.
    body = _read(server, f"sumoqa://skills/{skill}/modules/..%2fsecrets")
    payload = json.loads(body)
    assert "error" in payload
    assert "traversal" in payload["error"].lower()


def test_section_path_traversal_is_rejected(mcp):
    skill = _a_skill_with_sections()
    # FastMCP passes template params through verbatim (no URL-decoding), so a
    # literal `/` would not match the single-segment template at all. A value
    # carrying a `..` segment DOES match and reaches the loader, whose
    # traversal guard must reject it (".." in value). `%2f` stays literal.
    body = _read(mcp, f"sumoqa://skills/{skill}/sections/..%2fsecrets")
    payload = json.loads(body)
    assert "error" in payload
    assert "traversal" in payload["error"].lower()
