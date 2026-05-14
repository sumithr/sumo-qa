# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
import json
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from sumo_qa import node_install, qaskills
from sumo_qa.debug_capture import maybe_capture
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches as _load_approaches,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_classifications as _load_classifications,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_principles as _load_principles,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_rules as _load_rules,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_specialty_tools as _load_specialty_tools,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_standards as _load_standards,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_techniques as _load_techniques,
)
from sumo_qa.skill_prompts import register_skills_as_prompts
from sumo_qa.tools import QAShiftLeftService

# Reusable actionable hints for isError envelopes. Hosts surface these to the
# user when a tool fails, so they should describe a concrete next step rather
# than restate the error.
_HINT_LOCAL_FILES_MISSING = (
    "If the working tree or knowledge/test_data/ is missing files, confirm the repo is checked out."
)
_HINT_TEST_DATA_WRITE = (
    "If the write fails, confirm `knowledge/test_data/` is writable and the entry's "
    "`domain` field matches an existing folder."
)
_HINT_NODE_MISSING = (
    "Install Node ≥ 18 to use this feature. "
    "Download from https://nodejs.org or run `brew install node` on macOS."
)
_HINT_QASKILLS_CLI = (
    "Run `npx @qaskills/cli search` manually to debug."
)
_HINT_INVALID_SCOPE = (
    "Pass scope='global' or scope='project'."
)
_HINT_REGISTRY_JSON = (
    "Check the registry.json file for valid JSON syntax and fix any errors."
)

# Path to the external skills trust registry shipped with sumo-qa.
_REGISTRY_PATH = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "sumo-qa-suggesting-external-skill"
    / "registry.json"
)


def _error_envelope(exc: BaseException, actionable_hint: str) -> dict[str, Any]:
    """Wrap an exception in the MCP `isError` envelope.

    The host surfaces `error.actionable_hint` to the user when the protocol
    error pattern is suppressed in favour of structured tool output.
    """
    return {
        "isError": True,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc).strip() or "(no message)",
            "actionable_hint": actionable_hint,
        },
    }


def build_service() -> QAShiftLeftService:
    standards_path = Path(os.environ.get("QA_STANDARDS_PATH", "standards/packs"))
    rules_path = Path(os.environ.get("QA_RULES_PATH", "standards/rules/change_rules.yaml"))
    test_data_path = Path(os.environ.get("QA_TEST_DATA_PATH", "knowledge/test_data"))
    return QAShiftLeftService.from_standards_path(standards_path, rules_path, test_data_path)


def build_mcp_server(service: QAShiftLeftService | None = None) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("The MCP SDK is not installed. Run `pip install -e .`.") from exc

    qa_service = service or build_service()
    mcp = FastMCP(
        "sumo-qa",
        instructions=(
            "sumo-qa — senior-QA-shaped MCP server + skills library. "
            "Created by Sumith Ramsookbhai (https://github.com/sumithr). "
            "Licensed under Apache-2.0; please preserve the NOTICE file when redistributing."
        ),
        website_url="https://github.com/sumithr/sumo-qa",
    )

    # Standard annotation patterns. The QA test-data reasoning tools are read-only
    # and idempotent. Only `sumo_qa_register_known_good_test_data` writes to disk,
    # and even then the operation is additive (never deletes), so
    # destructiveHint stays false.
    _read_only_local = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    _writer_local = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_explain_test_data_requirements(
        question: str,
        environment: str = "",
        domain: str = "",
    ) -> dict:
        """Explain what test data shape and characteristics are needed for a scenario.

        Returns: required entity characteristics, resource-state conditions,
        scenario preconditions, downstream dependencies, edge cases, and
        explicit "what NOT to use" guidance. Domain-neutral by design — works
        for any domain (auth, billing, retail, infrastructure, ML, etc.).
        Optional `environment` (e.g. "integration") and `domain` are folded
        into the analysis.

        Common natural-language phrasings that map to this tool:
        "what data do I need to test X", "what test data should I look for to
        cover X", "what records / accounts / fixtures do I need for X",
        "what's the minimum data setup for X", "what edge-case data should I
        test".
        """
        try:
            output = qa_service.qa_explain_test_data_requirements(question, environment, domain)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_LOCAL_FILES_MISSING)
        captured = maybe_capture(
            tool="sumo_qa_explain_test_data_requirements",
            args={
                "question": question,
                "environment": environment,
                "domain": domain,
            },
            output=output,
        )
        return captured

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_find_test_data(
        environment: str = "",
        domain: str = "",
        scenario_tags: Annotated[
            list | None,
            Field(
                default=None,
                description="Scenario tags to match against catalogue entries.",
                examples=[["boundary_input", "degraded_dependency"]],
            ),
        ] = None,
        known_valid_for: Annotated[
            list | None,
            Field(
                default=None,
                description="Use-case labels the entry has been validated for.",
                examples=[["boundary input validation"]],
            ),
        ] = None,
        product_id: str = "",
        sku: str = "",
        limit: int = 5,
        offset: int = 0,
    ) -> dict:
        """Search the local known-good test data catalogue for entries that match a scenario.

        Returns: ranked matches with confidence, freshness, and suitability
        reasons. Reads the local YAML catalogue under `knowledge/test_data/`
        only; no external lookups. Optional `scenario_tags` and `known_valid_for`
        narrow the search.

        Pagination: pass `offset` to skip the first N matches, and read
        `total_count`, `has_more`, and `next_offset` on the response to walk
        pages. When `has_more` is false, `next_offset` is null.

        Common natural-language phrasings that map to this tool:
        "find me test data for X", "do we have a known-good record for X",
        "give me an account / fixture / record that does X", "is there a
        fixture for X", "what test data is available for X".
        """
        try:
            output = qa_service.qa_find_test_data(
                environment,
                domain,
                scenario_tags,
                known_valid_for,
                product_id,
                sku,
                limit,
                offset,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_LOCAL_FILES_MISSING)
        captured = maybe_capture(
            tool="sumo_qa_find_test_data",
            args={
                "environment": environment,
                "domain": domain,
                "scenario_tags": scenario_tags,
                "known_valid_for": known_valid_for,
                "product_id": product_id,
                "sku": sku,
                "limit": limit,
                "offset": offset,
            },
            output=output,
        )
        return captured

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_validate_test_data(
        entry_id: str | None = None,
        entry: dict | None = None,
    ) -> dict:
        """Validate a test data entry without provisioning or mutating downstream systems.

        Returns: validation result with confidence level, freshness status, and
        an explained reason. Accepts either `entry_id` (looked up in the
        catalogue) or `entry` (a full record dict).

        Common natural-language phrasings that map to this tool:
        "is this test data still valid", "validate this record", "is entry X
        still good", "check if X is fresh".
        """
        try:
            output = qa_service.qa_validate_test_data(entry_id, entry)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_LOCAL_FILES_MISSING)
        captured = maybe_capture(
            tool="sumo_qa_validate_test_data",
            args={
                "entry_id": entry_id,
                "entry": entry,
            },
            output=output,
        )
        return captured

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_register_known_good_test_data(
        entry: dict,
    ) -> dict:
        """Add or update a known-good test data entry in the local YAML catalogue.

        Detects duplicates by environment + domain + product/SKU + scenario
        overlap. Writes to `knowledge/test_data/<domain>/known_good.yaml`.

        Common natural-language phrasings that map to this tool:
        "save this as known-good test data", "register this fixture so the team
        can reuse it", "promote this record to known-good", "update the
        validated timestamp on entry X", "add this record to the catalogue".
        """
        try:
            output = qa_service.qa_register_known_good_test_data(entry)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_TEST_DATA_WRITE)
        captured = maybe_capture(
            tool="sumo_qa_register_known_good_test_data",
            args={
                "entry": entry,
            },
            output=output,
        )
        return captured

    def _register_knowledge_loaders(mcp):
        """Register the 7 knowledge-provider tools.

        Each tool is a thin wrapper around a markdown read. The host LLM picks
        from the returned catalogue; this server does no inference."""

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_classifications() -> str:
            """Return the 10 canonical change classifications as plain text. The
            host LLM picks which apply to a given change."""
            return _load_classifications()

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_approaches() -> str:
            """Return the 8 canonical QA approaches as plain text. The host LLM
            picks which approach fits a given piece of work."""
            return _load_approaches()

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_principles() -> str:
            """Return ISTQB Foundation + Advanced + ISO 25010 grounding as plain
            text. The host LLM cites principles when shaping recommendations."""
            return _load_principles()

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_techniques() -> str:
            """Return the test design technique catalogue (black-box, white-box,
            experience-based, static, property-based, mutation) as plain text.
            The host LLM picks one technique per named risk."""
            return _load_techniques()

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_specialty_tools() -> str:
            """Return the specialty + tool fit category primer as plain text.
            This is a CATEGORY-FIT primer (when does mutation testing apply,
            when does DAST apply, etc.), NOT a brand whitelist. The host LLM
            recommends the best-fit tool from its training-data knowledge of
            the ecosystem anchored to the user's stack; this file confirms the
            category fits the risk. Brand names in the file are illustrative."""
            return _load_specialty_tools()

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_standards(classification: str | None = None) -> str:
            """Return the team's loaded standards packs as plain text. Optional
            classification filter is metadata-based (packs whose frontmatter
            declares the classification); no keyword inference."""
            return _load_standards(classification=classification)

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_rules(classification: str | None = None) -> str:
            """Return the team's loaded change rules as plain text. Optional
            classification filter is metadata-based; no keyword inference."""
            return _load_rules(classification=classification)

    def _register_qaskills_tools(mcp):
        """Register the 8 qaskills / Node-install MCP tools.

        Consent for any qaskills install is per-action — the skill asks
        the user `[y/N]` before invoking `sumo_qa_install_external_skill`
        or `sumo_qa_install_node`. No runtime feature flag.
        """

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_search_external_skills(
            query: Annotated[str, Field(description="Free-text search query, e.g. 'playwright e2e'.")],
        ) -> dict[str, Any]:
            """Search qaskills.sh and return the CLI's human-readable output.

            The host LLM reads the text and decides which skill (if any)
            matches the user's intent. No fields are parsed out — the
            output is intentionally raw so Claude can use it directly.
            """
            try:
                return {"output": qaskills.search(query)}
            except qaskills.NodeNotFoundError as exc:
                return _error_envelope(exc, _HINT_NODE_MISSING)
            except qaskills.QaskillsError as exc:
                return _error_envelope(exc, _HINT_QASKILLS_CLI)

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_get_external_skill_info(
            name: Annotated[str, Field(description="Exact skill slug, e.g. 'playwright-e2e'.")],
        ) -> dict[str, Any]:
            """Return the CLI's `info` output for a named skill, as text.

            Metadata only (version, publisher, score, license, languages,
            frameworks, web URL). The CLI does not expose the SKILL.md
            body — read it via your Read tool after install.
            """
            try:
                return {"output": qaskills.info(name)}
            except qaskills.NodeNotFoundError as exc:
                return _error_envelope(exc, _HINT_NODE_MISSING)
            except qaskills.QaskillsError as exc:
                return _error_envelope(exc, _HINT_QASKILLS_CLI)

        @mcp.tool(annotations=_writer_local)
        def sumo_qa_install_external_skill(
            name: Annotated[str, Field(description="Exact skill slug to install.")],
            scope: Annotated[str, Field(description="Install scope: 'global' or 'project'.")],
        ) -> dict[str, Any]:
            """Install a qaskill via the qaskills CLI.

            CALLER MUST HAVE EXPLICIT USER CONSENT before invoking this
            tool — the suggesting skill asks the user `[y/N]` first. The
            qaskills CLI lands the skill at `~/.claude/commands/<name>/`;
            sumo-qa relocates it to `~/.claude/skills/<name>/` (or the
            project's `.claude/skills/` when scope='project') so Claude
            Code's skill loader discovers it.
            """
            try:
                result = qaskills.add(name, scope=scope)  # type: ignore[arg-type]
            except ValueError as exc:
                return _error_envelope(exc, _HINT_INVALID_SCOPE)
            except qaskills.NodeNotFoundError as exc:
                return _error_envelope(exc, _HINT_NODE_MISSING)
            except qaskills.QaskillsError as exc:
                return _error_envelope(exc, _HINT_QASKILLS_CLI)
            return {
                "name": result.name,
                "scope": result.scope,
                "installed_at": str(result.installed_at),
                "skill_md_path": str(result.installed_at / "SKILL.md"),
                "cli_output": result.cli_output,
            }

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_check_external_skill_installed(
            name: Annotated[str, Field(description="Exact skill slug to check.")],
        ) -> dict[str, Any]:
            """Check whether a qaskill is installed locally (global or project).

            Returns {"installed": True, "scope": ..., "skill_md_path": ...}
            when found, or {"installed": False} when not present. Pure
            filesystem check — does not require Node.
            """
            location = qaskills.is_installed_locally(name)
            if location is None:
                return {"installed": False}
            return {
                "installed": True,
                "scope": location.scope,
                "skill_md_path": str(location.path),
            }

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_external_skills_registry() -> dict[str, Any]:
            """Return the trust registry (trusted/blocked publishers) as a dict.

            The host LLM uses these lists to decide which qaskills.sh
            publishers are auto-eligible vs. require explicit confirmation.
            """
            if not _REGISTRY_PATH.is_file():
                return {"trusted_publishers": [], "blocked_publishers": []}
            try:
                raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return _error_envelope(exc, _HINT_REGISTRY_JSON)
            return {
                "trusted_publishers": list(raw.get("trusted_publishers", ())),
                "blocked_publishers": list(raw.get("blocked_publishers", ())),
            }

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_check_node_available() -> dict[str, Any]:
            """Check whether Node (npx) is available on PATH.

            Returns {"available": bool}.
            """
            return {"available": qaskills.is_available()}

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_detect_node_installer() -> dict[str, Any]:
            """Detect the best Node package manager on the current OS.

            Returns {"installer": name, "command": [...], "needs_sudo": bool} when
            a supported package manager is found, or
            {"installer": None, "reason": "..."} when none is detected.
            """
            installer = node_install.detect_installer()
            if installer is None:
                return {"installer": None, "reason": "no supported package manager detected"}
            return {
                "installer": installer.name,
                "command": list(installer.command),
                "needs_sudo": installer.needs_sudo,
            }

        @mcp.tool(annotations=_writer_local)
        def sumo_qa_install_node() -> dict[str, Any]:
            """Install Node using the detected OS package manager.

            CALLER MUST HAVE EXPLICIT USER CONSENT before invoking this
            tool — the suggesting skill asks the user `[y/N]` first.
            Uses brew on macOS, winget on Windows, apt-get/dnf on Linux.
            Never calls sudo — returns the manual command when elevation
            is needed.
            """
            installer = node_install.detect_installer()
            if installer is None:
                return {"installed": False, "reason": "no installer detected"}
            result = node_install.install(installer)
            return {
                "installed": result.installed,
                "reason": result.reason,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

    _register_knowledge_loaders(mcp)
    _register_qaskills_tools(mcp)
    register_skills_as_prompts(mcp)
    return mcp


def main() -> None:
    build_mcp_server().run()
