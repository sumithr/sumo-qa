# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Conformance tests specific to sumo-qa-suggesting-external-skill/SKILL.md.

These supplement the suite-wide parametrised checks in test_skill_conformance.py
with assertions about the external-skill-suggestion contract:
- sumo-qa MCP-owned external skill lifecycle
- install gate (explicit [y/N] confirmation)
- no direct host-shell npx bypass
"""

from pathlib import Path

SKILL_PATH = (
    Path(__file__).parent.parent / "skills" / "sumo-qa-suggesting-external-skill" / "SKILL.md"
)


def test_skill_file_exists() -> None:
    assert SKILL_PATH.exists(), f"SKILL.md not found at {SKILL_PATH}"


def test_skill_has_output_discipline_section() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "## Output discipline (mandatory)" in text


def test_skill_has_output_economy_discipline() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    lower = text.lower()
    # The token-reduction pass (issue #89) folded the duplicated Output economy
    # block into the global discipline inherited from using-sumo-qa. The
    # discipline must still be carried — but a bare "output economy" substring is
    # too weak (any incidental mention would pass). Require EITHER a dedicated
    # section OR an explicit using-sumo-qa inheritance statement that names it,
    # so a reword that effectively drops the policy still fails this guard.
    has_section = "## output economy" in lower
    has_inheritance = (
        "inherits the global discipline from `using-sumo-qa`" in lower and "output economy" in lower
    )
    assert has_section or has_inheritance, (
        "sumo-qa-suggesting-external-skill must carry the output-economy discipline "
        "as its own `## Output economy` section or via an explicit "
        "`Inherits the global discipline from `using-sumo-qa`` statement that names "
        "output economy — not merely an incidental mention."
    )


def test_skill_has_when_to_use_section() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "## When to Use" in text


def test_skill_requires_explicit_confirmation_before_install() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Must require explicit user confirmation before installing
    assert "confirmation" in text.lower() or "confirm" in text.lower()


def test_skill_warns_against_silent_sudo() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "sudo" in text.lower()
    # Must not promise to elevate
    assert "never" in text.lower()


def test_skill_iron_law_mentions_install_gate() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    iron_law_section = text.split("## The Iron Law", 1)[1].split("##", 1)[0]
    assert "install" in iron_law_section.lower()


def test_skill_references_external_skill_mcp_tools() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "sumo_qa_search_external_skills" in text
    assert "sumo_qa_install_external_skill" in text
    assert "sumo_qa_execute_external_skill" in text


def test_skill_does_not_document_host_shell_install_command() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "npx --yes skills add" not in text
    assert "--skill find-skills" not in text


def test_skill_gates_external_skill_install_on_user_confirmation() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Must have a [y/N] gate (allow variations like [y / N])
    import re

    has_yn_gate = bool(re.search(r"\[y\s*/?\s*N\]", text, re.IGNORECASE))
    assert has_yn_gate, "SKILL.md must contain a [y/N] (or [y / N]) confirmation gate"
    # Must instruct to stop on 'n'
    assert "stop" in text.lower()
    assert "confirmed=true" in text


def test_skill_explicitly_rejects_direct_host_shell_npx() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    lower = text.lower()
    assert "host shell" in lower
    assert "npx skills" in lower
    assert "mcp server owns" in lower


def test_skill_documents_conversion_entry() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Generalized beyond QA tooling: the ingestion conversion entry is documented,
    # keyed on the structured entry_kind signal.
    assert "conversion" in text.lower()
    assert "entry_kind" in text


def test_skill_documents_capped_fallback_to_next_candidate() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    lower = text.lower()
    # On install/execute isError, advance to the next candidate, capped at 3.
    assert "next candidate" in lower
    assert "3 attempts" in lower


def test_skill_conversion_terminal_forbids_hand_transcription() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "transcribe" in text.lower()


def test_skill_does_not_pin_ingest_tool_token() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Ingest stays a standalone, description-discoverable tool; the skill must NOT
    # name its tool token, keeping test_skill_tool_crossref's whitelist comment honest.
    assert "sumo_qa_ingest_knowledge_pack" not in text
