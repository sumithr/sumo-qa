# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Additive MCP resources / resource-templates over the skill index.

Issue #289 (epic #137, Lever 3). Hosts that support MCP resources can
subscribe to or select skill context as resources, without replacing the
model-callable tool path from #285.

Single source of truth: every resource body is exactly the JSON the
``skill_manifest`` loader already serves through the
``sumo_qa_load_skill_context`` / ``sumo_qa_list_skill_manifests`` tools. The
resource handlers add no new logic — they serialise the loader output. This
keeps tool and resource paths byte-for-byte equivalent.

URI scheme (one static resource + four templates):

  * ``sumoqa://skills``                                  — list_skill_manifests()
  * ``sumoqa://skills/{skill_name}/manifest``            — mode="manifest"
  * ``sumoqa://skills/{skill_name}/sections/{section_id}`` — mode="section"
  * ``sumoqa://skills/{skill_name}/modules/{module_id}``   — mode="module"
  * ``sumoqa://skills/{skill_name}/full``                — mode="full"

The loader never raises: unknown skill/section/module and path-traversal
attempts come back as the loader's structured error envelope, which is
serialised as the resource content (so a host sees an actionable error, not a
transport-level failure). A ``..`` path component, null byte, or absolute
path in a template param is rejected earlier by the SDK's ``ResourceSecurity``
policy (checked on the decoded value, so ``..%2f`` is caught too) and
surfaces as a JSON-RPC ``-32602`` "Unknown resource" error; the loader's own
traversal guard remains as defence-in-depth behind it.

Additive guarantee: these are ``@mcp.resource`` registrations, not tools, so
``tools/list`` is unchanged — no per-section / per-module tool is created.
"""

from __future__ import annotations

import json
from typing import Any

from sumo_qa.skill_manifest import list_skill_manifests, load_skill_context


def _dumps(payload: Any) -> str:
    """Serialise a loader payload as the resource body.

    Matches the tool path's serialisation (``ensure_ascii=False, indent=2``)
    so a resource read is byte-for-byte identical to the corresponding tool
    call's JSON."""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def register_skill_resources(mcp: Any) -> None:
    """Register the skill index static resource + the four resource-templates.

    Mirrors ``skill_prompts.register_skills_as_prompts``: takes the MCPServer
    server and attaches resources via its decorator API. Idempotent per
    server instance (each ``build_mcp_server`` builds a fresh ``mcp``)."""

    @mcp.resource(
        "sumoqa://skills",
        name="sumo-qa skill index",
        description=(
            "Compact, deterministic metadata for every bundled sumo-qa skill "
            "(same payload as the default sumo_qa_list_skill_manifests tool — "
            "detail='compact'): skill_name, tool_name, description, "
            "content_hash, estimated_tokens_full. NO sections[]/modules[] "
            "arrays — fetch one skill's section/module index via "
            "sumo_qa_load_skill_context(skill_name, mode='manifest'). "
            "Routing/index aid, not the skill bodies."
        ),
        mime_type="application/json",
    )
    def skills_index() -> str:
        return _dumps(list_skill_manifests())

    @mcp.resource(
        "sumoqa://skills/{skill_name}/manifest",
        name="sumo-qa skill manifest",
        description=(
            "Routing summary + section list + module list for one skill "
            "(mode='manifest' of sumo_qa_load_skill_context). Not the body."
        ),
        mime_type="application/json",
    )
    def skill_manifest_resource(skill_name: str) -> str:
        return _dumps(load_skill_context(skill_name, "manifest"))

    @mcp.resource(
        "sumoqa://skills/{skill_name}/sections/{section_id}",
        name="sumo-qa skill section",
        description=(
            "One named section's text from a skill's SKILL.md "
            "(mode='section'). section_id is a stable heading slug from the "
            "manifest."
        ),
        mime_type="application/json",
    )
    def skill_section_resource(skill_name: str, section_id: str) -> str:
        return _dumps(load_skill_context(skill_name, "section", section=section_id))

    @mcp.resource(
        "sumoqa://skills/{skill_name}/modules/{module_id}",
        name="sumo-qa skill module",
        description=(
            "One named lazy module's text from a skill "
            "(mode='module'). module_id is a stable filename slug from the "
            "manifest."
        ),
        mime_type="application/json",
    )
    def skill_module_resource(skill_name: str, module_id: str) -> str:
        return _dumps(load_skill_context(skill_name, "module", module=module_id))

    @mcp.resource(
        "sumoqa://skills/{skill_name}/full",
        name="sumo-qa skill full body",
        description=(
            "The entire SKILL.md body for one skill (mode='full'), "
            "byte-for-byte identical to the existing zero-argument skill tool. "
            "A body over the host's per-response token cap is returned as an "
            "oversize pointer to the progressive-loading slices instead (#393)."
        ),
        mime_type="application/json",
    )
    def skill_full_resource(skill_name: str) -> str:
        return _dumps(load_skill_context(skill_name, "full"))
