# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the marketplace.json adapter (issue #382).

`.claude-plugin/marketplace.json` is the catalog Claude Code reads after
`/plugin marketplace add sumithr/sumo-qa`. Like every other plugin folder
it is GENERATED from the canonical `[tool.sumo-qa.plugin]` overlay in
pyproject.toml — never hand-written — and covered by the drift + schema
gates.

Two layers, mirroring the existing template/schema split:

  * canonical-value propagation + SHAPE — here (this file), against the
    pure `marketplace.render()` template function.
  * JSON-Schema validity — in test_plugin_packaging_schema_validation.py,
    against the vendored claude-code-marketplace.json schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin_packaging.canonical import CanonicalPlugin, HookSpec, McpSpec
from plugin_packaging.templates import marketplace

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plugin() -> CanonicalPlugin:
    return CanonicalPlugin(
        name="sumo-qa",
        version="9.9.9",
        description="d",
        license="Apache-2.0",
        author={"name": "T", "email": "t@t.test"},
        homepage="https://h.test",
        repository="https://r.test",
        display_name="Sumo QA",
        keywords=("qa", "tdd"),
        mcp=McpSpec(server_name="sumo-qa", command="sumo-qa"),
        hooks=(
            HookSpec(
                event="SessionStart",
                script="session-start",
                trigger="startup|clear|compact",
            ),
        ),
        short_description="Short marketplace copy.",
        long_description="Long marketplace copy.",
        category="testing",
    )


def test_marketplace_top_level_shape(plugin):
    """The catalog declares name + owner + a single plugins entry — the
    three required top-level fields of the Claude Code marketplace schema."""
    out = marketplace.render(plugin)
    assert out["name"] == "sumo-qa"
    assert out["owner"] == {"name": "T", "email": "t@t.test"}
    assert isinstance(out["plugins"], list)
    assert len(out["plugins"]) == 1


def test_marketplace_plugin_entry_required_fields(plugin):
    """The single plugin entry carries the two schema-required fields
    (name + source). The repo IS the plugin, so source points at the
    marketplace root (the repo root, which holds .claude-plugin/)."""
    entry = marketplace.render(plugin)["plugins"][0]
    assert entry["name"] == "sumo-qa"
    # Relative-path source form: marketplace-root-relative, must start "./".
    assert entry["source"] == "./"


def test_marketplace_plugin_entry_propagates_canonical_copy(plugin):
    """Listing metadata propagates from the canonical overlay only — no
    value is hand-typed in the template. The short marketplace copy (issue
    #84) becomes the listing description; keywords/category/version/author
    /license/homepage/repository all flow from canonical."""
    entry = marketplace.render(plugin)["plugins"][0]
    assert entry["description"] == "Short marketplace copy."
    assert entry["version"] == "9.9.9"
    assert entry["author"] == {"name": "T", "email": "t@t.test"}
    assert entry["license"] == "Apache-2.0"
    assert entry["homepage"] == "https://h.test"
    assert entry["repository"] == "https://r.test"
    assert entry["category"] == "testing"
    assert entry["keywords"] == ["qa", "tdd"]


def test_marketplace_falls_back_to_project_description_when_no_short_copy():
    """When no marketplace short copy is set, the listing description falls
    back to the [project] description rather than emitting an empty string —
    the listing always shows SOMETHING describing the plugin."""
    bare = CanonicalPlugin(
        name="sumo-qa",
        version="0.0.1",
        description="project-level description",
        license="Apache-2.0",
        author={"name": "T"},
        homepage="https://h.test",
        repository="https://r.test",
        display_name="Sumo QA",
        keywords=(),
        mcp=McpSpec(server_name="sumo-qa", command="sumo-qa"),
        hooks=(),
    )
    entry = marketplace.render(bare)["plugins"][0]
    assert entry["description"] == "project-level description"


def test_marketplace_is_a_generated_output() -> None:
    """The committed marketplace.json must be present on a clean checkout
    (it is generated + committed like every other plugin folder)."""
    assert (REPO_ROOT / ".claude-plugin" / "marketplace.json").is_file()


def test_committed_marketplace_matches_template() -> None:
    """The committed file equals what the template renders from the live
    canonical source — i.e. it was produced by the generator, not edited."""
    from plugin_packaging.canonical import load

    plugin = load(REPO_ROOT / "pyproject.toml")
    rendered = marketplace.render(plugin)
    on_disk = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert on_disk == rendered
