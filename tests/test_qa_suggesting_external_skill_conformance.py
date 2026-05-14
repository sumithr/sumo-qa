# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Conformance tests specific to sumo-qa-suggesting-external-skill/SKILL.md.

These supplement the suite-wide parametrised checks in test_skill_conformance.py
with assertions about the external-skill-suggestion contract:
- find-skills / skills.sh discovery flow
- install gate (explicit [y/N] confirmation)
- no-sudo guarantee
- no companion MCP shims
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


def test_skill_has_output_economy_section() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "## Output economy (mandatory)" in text


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


def test_skill_targets_skills_sh_registry() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "skills.sh" in text


def test_skill_documents_find_skills_install_command_verbatim() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "github.com/vercel-labs/skills" in text
    assert "--skill find-skills" in text


def test_skill_gates_find_skills_install_on_user_confirmation() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Must have a [y/N] gate (allow variations like [y / N])
    import re

    has_yn_gate = bool(re.search(r"\[y\s*/?\s*N\]", text, re.IGNORECASE))
    assert has_yn_gate, "SKILL.md must contain a [y/N] (or [y / N]) confirmation gate"
    # Must instruct to stop on 'n'
    assert "stop" in text.lower()


def test_skill_explicitly_rejects_companion_python_shims() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Red Flags section must address the companion-MCP-shim anti-pattern
    # Look for "MCP" alongside "shim" or "wrap" or "Python" or "companion"
    lower = text.lower()
    has_mcp = "mcp" in lower
    has_anti_shim = any(kw in lower for kw in ("shim", "wrap", "python", "companion"))
    assert has_mcp and has_anti_shim, (
        "SKILL.md Red Flags must address the companion-MCP-shim / wrapper anti-pattern "
        "(look for 'MCP' + one of 'shim', 'wrap', 'Python', 'companion')"
    )
