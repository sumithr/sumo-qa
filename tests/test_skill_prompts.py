# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for src/sumo_qa/skill_prompts.py.

Every skills/*/SKILL.md must register as an MCP TOOL at server startup
(not a prompt). Single delivery channel across hosts — Claude Code,
IntelliJ AI Assistant, and VS Code + Copilot all surface MCP tools in
their slash menu identically. Registering as prompts would only surface
in Claude Code, creating asymmetric behavior. See
src/sumo_qa/skill_prompts.py module docstring for the full rationale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sumo_qa.server import build_mcp_server

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "skills"

_EXPECTED_SKILL_TOOL_NAMES = {
    "using_sumo_qa",
    "sumo_qa_deciding_approach",
    "sumo_qa_preparing_for_work",
    "sumo_qa_creating_test_plan",
    "sumo_qa_implementing_with_tdd",
    "sumo_qa_reviewing_before_merge",
    "sumo_qa_strengthening_tests",
    "sumo_qa_finding_test_data",
    "sumo_qa_answering_testing_question",
    "sumo_qa_strategising",
}


def test_every_skill_registers_as_an_mcp_tool() -> None:
    """Every skills/*/SKILL.md must surface as an MCP tool at startup."""
    server = build_mcp_server()
    tool_names = set(server._tool_manager._tools.keys())

    missing = _EXPECTED_SKILL_TOOL_NAMES - tool_names
    assert not missing, f"Missing skill tools: {missing}"


def test_no_skill_registered_as_a_prompt() -> None:
    """Skills must register as tools only, never as prompts. Dual
    registration would create duplicate slash-menu entries in Claude
    Code (the host that surfaces both) — the confusion this design
    explicitly avoids."""
    server = build_mcp_server()
    prompt_names = set(server._prompt_manager._prompts.keys())

    leaked = _EXPECTED_SKILL_TOOL_NAMES & prompt_names
    assert not leaked, f"Skills leaked into MCP prompts: {leaked}"


def test_skill_tool_body_matches_skill_md_content(monkeypatch) -> None:
    """Calling each skill tool returns the full SKILL.md content, read fresh
    from disk on each invocation (single source of truth), UNLESS the body
    exceeds the per-response token cap (#393), in which case the tool returns a
    compact progressive-loading pointer instead of the over-cap body the host
    would refuse. Pinned with the default profile: the body must be EQUAL to
    the SKILL.md text (byte-for-byte), not merely contain it, so an overlay
    wrongly prepended on the default path fails through the real
    registration path."""
    from sumo_qa.skill_prompts import DEFAULT_SKILL_RESPONSE_TOKEN_CAP, _approx_tokens

    monkeypatch.delenv("SUMO_QA_OUTPUT_PROFILE", raising=False)
    server = build_mcp_server()

    async def collect() -> dict[str, str]:
        bodies: dict[str, str] = {}
        for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
            result = await server.call_tool(tool_name, {})
            # The server drops outputSchema, so call_tool returns a bare
            # content list (unstructured text). Older FastMCP returned a
            # (content_list, structured_content) tuple — handle both. Extract
            # the text from the first text content block.
            content_list = result[0] if isinstance(result, tuple) else result
            text = ""
            for content in content_list:
                block_text = getattr(content, "text", None)
                if block_text:
                    text = block_text
                    break
            bodies[tool_name] = text
        return bodies

    bodies = asyncio.run(collect())

    for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
        skill_dir_name = tool_name.replace("_", "-")
        # `sumo-qa-strategising` is the only multi-hyphen name; `_` -> `-`
        # round-trips correctly because none of the directory names contain
        # underscores.
        skill_path = _SKILLS_DIR / skill_dir_name / "SKILL.md"
        assert skill_path.is_file(), f"missing skill file: {skill_path}"
        expected_text = skill_path.read_text(encoding="utf-8")
        if _approx_tokens(expected_text) > DEFAULT_SKILL_RESPONSE_TOKEN_CAP:
            # Over-cap: a compact pointer to the progressive-loading route, NOT
            # the oversized body the host refuses to inline.
            pointer = bodies[tool_name]
            assert expected_text not in pointer, (
                f"tool {tool_name!r} returned the over-cap body inline"
            )
            assert "sumo_qa_load_skill_context" in pointer, (
                f"tool {tool_name!r} pointer does not name the progressive-loading route"
            )
        else:
            assert bodies[tool_name] == expected_text, (
                f"tool {tool_name!r} body is not byte-for-byte the SKILL.md "
                f"content under the default profile"
            )


# ---------------------------------------------------------------------------
# Branch coverage for skill_prompts.py
# ---------------------------------------------------------------------------


def test_parse_frontmatter_returns_empty_when_no_frontmatter() -> None:
    """_parse_frontmatter() returns {} when the text has no --- block (line 61)."""
    from sumo_qa.skill_prompts import _parse_frontmatter

    result = _parse_frontmatter("# Skill\n\nJust markdown, no frontmatter.\n")
    assert result == {}


def test_parse_frontmatter_returns_empty_on_yaml_error() -> None:
    """_parse_frontmatter() returns {} when the YAML inside --- is malformed (lines 64-65)."""
    from sumo_qa.skill_prompts import _parse_frontmatter

    # Valid frontmatter delimiters but invalid YAML content.
    text = "---\nkey: [unclosed\n---\n# Body"
    result = _parse_frontmatter(text)
    assert result == {}


def test_register_skills_as_prompts_noop_when_skills_dir_missing(tmp_path) -> None:
    """register_skills_as_prompts() returns immediately when the skills dir
    doesn't exist — the inner loop is never entered (line 82)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    mcp = MagicMock()
    nonexistent = tmp_path / "no_such_dir"
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=nonexistent):
        register_skills_as_prompts(mcp)

    mcp.tool.assert_not_called()


def test_register_skills_skips_non_directory_entries(tmp_path) -> None:
    """register_skills_as_prompts() skips files inside the skills dir (line 85)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    # Create a file (not a directory) inside the fake skills dir.
    (tmp_path / "not_a_skill.txt").write_text("hello", encoding="utf-8")

    mcp = MagicMock()
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    mcp.tool.assert_not_called()


def test_register_skills_skips_directories_without_skill_md(tmp_path) -> None:
    """register_skills_as_prompts() skips skill dirs that have no SKILL.md (line 88)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    # A directory with no SKILL.md.
    (tmp_path / "my-skill").mkdir()

    mcp = MagicMock()
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    mcp.tool.assert_not_called()


def test_register_skills_uses_description_from_frontmatter(tmp_path) -> None:
    """register_skills_as_prompts() reads description from frontmatter (line 92-96)
    and collapses multi-line folded YAML descriptions."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: A multi-line\n  description here\n---\n# Body",
        encoding="utf-8",
    )

    mcp = MagicMock()
    mcp.tool.return_value = lambda fn: fn  # decorator passthrough
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    # tool() should have been called once for the one skill directory.
    assert mcp.tool.called


def test_register_skills_falls_back_to_skill_name_when_no_description(tmp_path) -> None:
    """When frontmatter has no description, the name is used as fallback (line 92)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nid: x\n---\n# Body", encoding="utf-8")

    mcp = MagicMock()
    mcp.tool.return_value = lambda fn: fn
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    assert mcp.tool.called


def test_skills_dir_returns_bundled_when_exists() -> None:
    """_skills_dir() returns the bundled path when it exists (line 52)."""
    from pathlib import Path
    from unittest.mock import patch

    from sumo_qa.skill_prompts import _BUNDLED_SKILLS, _skills_dir

    with patch.object(Path, "is_dir", return_value=True):
        result = _skills_dir()

    assert result == _BUNDLED_SKILLS


def test_skill_tool_description_matches_frontmatter() -> None:
    """Each skill tool's MCP description should come from the SKILL.md
    frontmatter `description`, so hosts that show tool menus surface the
    canonical sentence the skill author wrote."""
    import yaml

    server = build_mcp_server()
    tools = server._tool_manager._tools

    for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
        skill_dir_name = tool_name.replace("_", "-")
        skill_path = _SKILLS_DIR / skill_dir_name / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        # Cheap frontmatter parse mirroring the implementation; if this
        # diverges from the implementation, the test failure points at the
        # discrepancy, which is what we want.
        assert text.startswith("---"), f"{skill_path} missing frontmatter"
        _, fm, _ = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
        expected_description = meta.get("description")
        assert expected_description, f"{skill_path} frontmatter missing `description`"
        # The implementation collapses folded YAML descriptions to a single
        # line, so compare against the same transformation.
        expected_collapsed = " ".join(expected_description.split())

        tool = tools[tool_name]
        assert tool.description == expected_collapsed, (
            f"tool {tool_name!r} description mismatch: "
            f"expected={expected_collapsed!r} got={tool.description!r}"
        )


# ---------------------------------------------------------------------------
# Output-profile overlay (issue #215)
#
# SUMO_QA_OUTPUT_PROFILE=concise|default|strict tunes how much ceremony wraps a
# served skill body WITHOUT editing any SKILL.md (a shared serve-time overlay,
# not a per-skill rewrite). `default` must serve the body byte-for-byte
# (backwards compatible); `concise`/`strict` prepend a small, bounded overlay
# that reshapes output but can never downgrade a mandatory gate.
# ---------------------------------------------------------------------------


def test_default_profile_serves_body_byte_for_byte(tmp_path, monkeypatch) -> None:
    """With the profile unset (or `default`), the served body is the SKILL.md
    content byte-for-byte — no overlay, no drift from current behavior."""
    from sumo_qa.skill_prompts import _make_skill_callable

    monkeypatch.delenv("SUMO_QA_OUTPUT_PROFILE", raising=False)
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n\nsome content\n"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md")
    assert fn() == body


def test_default_profile_explicit_value_is_byte_for_byte(tmp_path) -> None:
    """An explicit `default` override behaves identically to unset."""
    from sumo_qa.skill_prompts import _make_skill_callable

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", profile="default")
    assert fn() == body


def test_concise_profile_prepends_overlay_before_body(tmp_path) -> None:
    """`concise` prepends the concise overlay, then the untouched body."""
    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, _make_skill_callable

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", profile="concise")
    out = fn()
    assert out.startswith(_CONCISE_OVERLAY)
    assert out.endswith(body)
    assert "concise" in _CONCISE_OVERLAY.lower()


def test_strict_profile_prepends_overlay_before_body(tmp_path) -> None:
    """`strict` prepends the strict overlay, then the untouched body."""
    from sumo_qa.skill_prompts import _STRICT_OVERLAY, _make_skill_callable

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", profile="strict")
    out = fn()
    assert out.startswith(_STRICT_OVERLAY)
    assert out.endswith(body)
    assert "strict" in _STRICT_OVERLAY.lower()


def test_env_var_selects_profile_at_call_time(tmp_path, monkeypatch) -> None:
    """The env var (not just the explicit param) selects the profile, resolved
    fresh on each call so a host config change takes effect without a rebind."""
    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, _make_skill_callable

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md")  # no explicit override
    monkeypatch.setenv("SUMO_QA_OUTPUT_PROFILE", "concise")
    assert fn().startswith(_CONCISE_OVERLAY)
    monkeypatch.delenv("SUMO_QA_OUTPUT_PROFILE", raising=False)
    assert fn() == body


def test_invalid_profile_falls_back_to_default(tmp_path, monkeypatch) -> None:
    """An unrecognised profile value falls back predictably to `default`
    (byte-for-byte body) rather than raising — a typo can never break serving
    or silently drop a gate."""
    from sumo_qa.skill_prompts import _make_skill_callable

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    monkeypatch.setenv("SUMO_QA_OUTPUT_PROFILE", "verbose-plz")
    fn = _make_skill_callable(skill_dir / "SKILL.md")
    assert fn() == body


def test_resolve_output_profile_normalises_case_and_whitespace(monkeypatch) -> None:
    """Resolution is case/whitespace-insensitive so `  Concise ` == `concise`."""
    from sumo_qa.skill_prompts import _resolve_output_profile

    monkeypatch.delenv("SUMO_QA_OUTPUT_PROFILE", raising=False)
    assert _resolve_output_profile("  Concise ") == "concise"
    assert _resolve_output_profile("STRICT") == "strict"
    assert _resolve_output_profile() == "default"


def test_resolve_output_profile_invalid_explicit_override(monkeypatch) -> None:
    """An invalid EXPLICIT override also falls back to default (same predictable
    rule as the env path)."""
    from sumo_qa.skill_prompts import _resolve_output_profile

    monkeypatch.delenv("SUMO_QA_OUTPUT_PROFILE", raising=False)
    assert _resolve_output_profile("nonsense") == "default"


def test_concise_and_strict_overlays_preserve_mandatory_gates(tmp_path) -> None:
    """Every non-default overlay must restate the never-optional floor so a
    high-risk workflow keeps its gates in concise mode: Iron Law / HARD-GATE,
    evidence for claims, and confirmation before writes or installs. This is the
    safety invariant behind the issue's non-goal 'No profile may allow skipping
    required tests, evidence, confirmations, or safety gates.'"""
    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, _LEAN_OVERLAY, _STRICT_OVERLAY

    for overlay in (_CONCISE_OVERLAY, _LEAN_OVERLAY, _STRICT_OVERLAY):
        low = overlay.lower()
        assert "iron law" in low
        assert "hard-gate" in low
        assert "evidence" in low
        assert "confirm" in low
        assert "install" in low


def test_concise_overlay_carries_a_tool_budget_contract(tmp_path) -> None:
    """The measured #528 defect: real session cost is dominated by tool traffic
    and turn count, which answer-shape prose alone cannot reduce, so the concise
    overlay must also budget the PROCESS: load only what the skill's gates
    require, skip supplementary loads, and never re-load content already in
    context. Asserted on the served output through the real registration path so
    the contract ships with the overlay, not just as a constant."""
    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, _make_skill_callable

    low = _CONCISE_OVERLAY.lower()
    assert "load only what this skill's gates require" in low
    assert "skip supplementary" in low
    assert "re-load" in low

    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\ndescription: d\n---\n# Body\n", encoding="utf-8")
    fn = _make_skill_callable(skill_dir / "SKILL.md", profile="concise")
    assert "skip supplementary" in fn().lower()


def test_lean_profile_serves_the_progressive_pointer_not_the_body(tmp_path) -> None:
    """The #528 cost fix: under `lean` the skill tool serves the overlay plus the
    progressive-loading pointer INSTEAD of the full body, so the host loads only
    the sections its gates need. Session cost is dominated by served bytes
    re-read every turn; this is the serve-boundary lever with measured headroom.
    Loader and resources stay canonical, so change-detection is unaffected."""
    from sumo_qa.skill_prompts import _LEAN_OVERLAY, _approx_tokens, _make_skill_callable

    skill_dir = tmp_path / "some-skill"
    skill_dir.mkdir()
    marker = "UNIQUE-BODY-MARKER-a7f3"
    body = "---\ndescription: d\n---\n# Body\n" + (marker + " word ") * 400
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", profile="lean")
    out = fn()
    assert out.startswith(_LEAN_OVERLAY)
    assert "sumo_qa_load_skill_context" in out
    assert marker not in out
    assert _approx_tokens(out) <= 450


def test_lean_profile_is_env_selectable(tmp_path, monkeypatch) -> None:
    """`lean` is a first-class profile value: selecting it via the env var at
    call time switches serving to the pointer, and it never claims the body is
    over the cap (the pointer wording must stay truthful for small bodies)."""
    from sumo_qa.skill_prompts import _make_skill_callable

    skill_dir = tmp_path / "small-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\ndescription: d\n---\n# Tiny\n", encoding="utf-8")
    monkeypatch.setenv("SUMO_QA_OUTPUT_PROFILE", "lean")
    out = _make_skill_callable(skill_dir / "SKILL.md")()
    assert "sumo_qa_load_skill_context" in out
    assert "too large" not in out.lower()
    assert "above the" not in out.lower()


def test_lean_over_cap_serves_the_minimal_pointer_never_the_body(tmp_path) -> None:
    """The honest #393 invariant for lean is "never serve the over-cap BODY", NOT
    "the served pointer always fits the cap". The progressive-loading pointer has a
    floor size and cannot shrink below it, so under a cap below that floor the pointer
    legitimately exceeds the cap - but it is still the minimal payload and still far
    under the over-cap body the host would refuse. Two regimes, both must hold: the
    body is never served, and what IS served is exactly the minimal pointer.

    Regression: the previous version asserted served <= cap at cap=200, above the
    ~195-token pointer floor, so it silently passed a claim (pointer always <= cap)
    that is false for a sub-floor cap - masking the real, weaker-but-honest contract."""
    from sumo_qa.skill_prompts import (
        _LEAN_OVERLAY,
        _approx_tokens,
        _lean_pointer_text,
        _make_skill_callable,
    )

    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    marker = "OVERCAP_BODY_MARKER_z9"
    body = "---\ndescription: d\n---\n# Body\n" + (marker + " x ") * 2000
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    bare_pointer = _lean_pointer_text(skill_dir.name, _approx_tokens(body))
    floor = _approx_tokens(bare_pointer)

    # Regime 1: cap between the bare pointer and overlay + pointer -> overlay
    # dropped, the in-cap bare pointer served (never the body).
    out1 = _make_skill_callable(skill_dir / "SKILL.md", token_cap=floor + 5, profile="lean")()
    assert marker not in out1  # the over-cap body is never served
    assert out1 == bare_pointer  # exactly the minimal pointer
    assert not out1.startswith(_LEAN_OVERLAY)  # overlay dropped to fit
    assert _approx_tokens(out1) <= floor + 5  # fits the cap in this regime

    # Regime 2: cap BELOW the bare-pointer floor -> the body is STILL never served;
    # the minimal pointer is served even though it exceeds this sub-floor cap,
    # because it is the smallest payload available.
    out2 = _make_skill_callable(skill_dir / "SKILL.md", token_cap=floor - 20, profile="lean")()
    assert marker not in out2  # the over-cap body is STILL never served
    assert out2 == bare_pointer  # the minimal pointer, not a larger payload
    assert _approx_tokens(out2) > floor - 20  # honestly above the sub-floor cap


def test_overlays_stay_within_a_bounded_token_budget() -> None:
    """Concise must reduce output and strict must not bloat payloads, so the
    overlay itself is a small bounded constant — pin a ceiling so it cannot grow
    into a payload of its own."""
    from sumo_qa.skill_prompts import (
        _CONCISE_OVERLAY,
        _LEAN_OVERLAY,
        _STRICT_OVERLAY,
        _approx_tokens,
    )

    for overlay in (_CONCISE_OVERLAY, _LEAN_OVERLAY, _STRICT_OVERLAY):
        assert _approx_tokens(overlay) <= 250, (
            f"profile overlay is ~{_approx_tokens(overlay)} tokens (>250); "
            f"keep it a compact directive, not a second payload"
        )


def test_over_cap_skill_under_profile_returns_overlaid_pointer(tmp_path) -> None:
    """When the composed (overlay + body) exceeds the per-response token cap, the
    tool still degrades to the progressive-loading pointer (#393) rather than
    the over-cap body — and the profile overlay is preserved on the pointer so
    the host still knows the active profile, because overlay + pointer fits
    this cap (~358 tokens composed vs a 400 cap)."""
    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, _approx_tokens, _make_skill_callable

    skill_dir = tmp_path / "big-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n" + ("x " * 5000)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", token_cap=400, profile="concise")
    out = fn()
    assert out.startswith(_CONCISE_OVERLAY)
    assert "sumo_qa_load_skill_context" in out
    assert body not in out
    assert _approx_tokens(out) <= 400


def test_overlaid_pointer_never_exceeds_cap(tmp_path) -> None:
    """With a cap the bare pointer fits under but overlay + pointer does NOT
    (cap 200: pointer ~183 tokens, overlay ~176, composed ~358), the overlay is
    dropped rather than recreating the over-cap response the pointer exists to
    prevent (#393). A broken implementation that always prepends the overlay
    returns ~358 tokens against a 200 cap; the correct one returns the in-cap
    pointer alone."""
    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, _approx_tokens, _make_skill_callable

    skill_dir = tmp_path / "big-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n" + ("x " * 5000)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", token_cap=200, profile="concise")
    out = fn()
    assert _approx_tokens(out) <= 200
    assert "sumo_qa_load_skill_context" in out
    assert not out.startswith(_CONCISE_OVERLAY)


def test_over_cap_skill_default_profile_pointer_unchanged(tmp_path) -> None:
    """Default profile over-cap path is byte-for-byte the existing pointer — no
    overlay leaks into the default degraded response."""
    from sumo_qa.skill_prompts import (
        _approx_tokens,
        _make_skill_callable,
        _oversize_pointer_text,
    )

    skill_dir = tmp_path / "big-skill"
    skill_dir.mkdir()
    body = "---\ndescription: d\n---\n# Body\n" + ("x " * 5000)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    fn = _make_skill_callable(skill_dir / "SKILL.md", token_cap=100)
    expected = _oversize_pointer_text("big-skill", _approx_tokens(body), 100)
    assert fn() == expected


def test_register_threads_profile_through_to_tool(tmp_path, monkeypatch) -> None:
    """register_skills_as_prompts binds the serving callable; with the env
    profile set, each bound tool serves the overlaid body."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import _CONCISE_OVERLAY, register_skills_as_prompts

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\ndescription: d\n---\n# Body\n", encoding="utf-8")

    captured = {}

    def fake_tool(name, description):
        def decorator(fn):
            captured["fn"] = fn
            return fn

        return decorator

    mcp = MagicMock()
    mcp.tool.side_effect = fake_tool
    monkeypatch.setenv("SUMO_QA_OUTPUT_PROFILE", "concise")
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    assert captured["fn"]().startswith(_CONCISE_OVERLAY)
