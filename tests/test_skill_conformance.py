# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Skill conformance — every skills/*/SKILL.md must follow the upstream
superpowers structure.

In Phase 1, only frontmatter checks are active. Phase 2 unskips the
structure checks (Iron Law, Checklist, Process Flow, Red Flags, Examples)
once the stub skills get their full content."""

import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILL_PATHS = sorted(SKILLS_DIR.glob("*/SKILL.md"))
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter(path: Path) -> dict:
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    return yaml.safe_load(match.group(1)) if match else {}


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_frontmatter_with_name_and_description(skill_path):
    fm = _frontmatter(skill_path)
    assert "name" in fm, f"Missing 'name' frontmatter in {skill_path}"
    assert "description" in fm, f"Missing 'description' frontmatter in {skill_path}"


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_name_matches_directory_name(skill_path):
    fm = _frontmatter(skill_path)
    assert fm.get("name") == skill_path.parent.name, (
        f"Frontmatter name '{fm.get('name')}' must match directory '{skill_path.parent.name}'"
    )


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_descriptions_are_non_empty(skill_path):
    fm = _frontmatter(skill_path)
    desc = fm.get("description") or ""
    assert len(desc.strip()) >= 30, f"Description too short in {skill_path}: {desc[:80]}"


def test_skill_descriptions_are_unique():
    descriptions = [_frontmatter(p).get("description") for p in SKILL_PATHS]
    assert len(set(descriptions)) == len(descriptions), (
        "Duplicate skill descriptions detected — auto-trigger will be ambiguous"
    )


# Structure checks — un-skipped in Phase 2.
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_iron_law_section(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## The Iron Law" in text or "## Iron Law" in text


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_checklist_section_with_at_least_four_items(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## Checklist" in text
    checklist_section = text.split("## Checklist", 1)[1].split("##", 1)[0]
    items = re.findall(r"^\s*\d+\.", checklist_section, flags=re.MULTILINE)
    assert len(items) >= 4


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_process_flow_section(skill_path):
    """Every skill declares a Process Flow section.

    Originally required an inline graphviz ``dot`` block. The token-reduction
    pass replaced verbose dot diagrams with a one-line pointer to the
    Checklist (the dot block was duplicating what the numbered checklist
    already encoded). Skills MAY still inline a dot block — we just don't
    require it.
    """
    text = skill_path.read_text(encoding="utf-8")
    assert "## Process Flow" in text


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_red_flags_section(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## Red Flags" in text


# Host-neutrality — skill bodies must not name host-specific tools (issue #82).
# Skills are consumed by Claude Code, Cursor, Codex, JetBrains AI Assistant,
# Junie, VS Code Copilot and any other MCP-capable host. Hard-coding one
# host's tool name in the prose silently breaks the contract for everyone
# else. The capability-shaped vocabulary lives in
# `using-sumo-qa` → Shared vocabulary.
HOST_SPECIFIC_BODY_DENYLIST = (
    "TodoWrite",
    "AskUserQuestion",
    "Agent tool",
    "host already shows tool calls",
)


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("phrase", HOST_SPECIFIC_BODY_DENYLIST)
def test_skill_body_has_no_bare_host_specific_phrase(skill_path, phrase):
    text = skill_path.read_text(encoding="utf-8")
    assert phrase not in text, (
        f"{skill_path.relative_to(SKILLS_DIR.parent)} contains host-specific phrase "
        f"{phrase!r}. Skill prose must declare capability obligations, not name one "
        f"host's tool. See using-sumo-qa → Shared vocabulary for the capability terms."
    )


# Frontmatter description guard — descriptions trigger auto-routing across
# every host, so a Claude Code-only tool name in a description routes
# nowhere on JetBrains or Copilot.
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("phrase", HOST_SPECIFIC_BODY_DENYLIST[:3])  # 4th phrase isn't a tool name
def test_skill_description_has_no_host_specific_tool_name(skill_path, phrase):
    fm = _frontmatter(skill_path)
    description = fm.get("description") or ""
    assert phrase not in description, (
        f"{skill_path.relative_to(SKILLS_DIR.parent)} description references "
        f"{phrase!r}. Descriptions must use host-neutral wording — see "
        f"using-sumo-qa → Shared vocabulary."
    )


# Provider / model-name drift guard (issue #161). The reasoning-effort guidance
# is deliberately host-neutral and capability-shaped: it must NOT name a
# provider, a model family, or a host-specific reasoning-control setting,
# because any such list rots and creates documentation debt the moment a vendor
# renames a model or ships a new tier. This denylist is the deterministic guard
# — if a future edit reaches for a concrete vendor/model/control name in skill
# prose, the offending token lands here and the test fails. The skills express a
# preference for *stronger available reasoning*, never a maintained matrix.
#
# Matched case-insensitively against skill prose with fenced code blocks stripped
# (a fenced shell/JSON example may legitimately show a model id; normative prose
# may not). Two layers:
#
#  1. PROVIDER_MODEL_DRIFT_DENYLIST — literal multi-word / unambiguous tokens,
#     word-boundary matched. Kept focused on strings that would only appear if
#     someone enumerated vendors/models/controls — not generic English. Bare
#     English-homograph verbs ("cohere", "grok") are deliberately NOT here: they
#     are covered by the narrower vendor-context regexes below so the guard
#     cannot fail on ordinary prose (#161 FIX 3).
#
#  2. PROVIDER_MODEL_DRIFT_PATTERNS — compiled regexes for family classes the
#     literal list cannot express safely: the gpt-N family *including* suffixes
#     (gpt-4o, gpt-4o-mini, gpt-5.1, …), the o-series reasoning models
#     (o1/o3/o4 + -mini/-pro) without false-positiving on a standalone "o", the
#     bare capability-tier model names (haiku/sonnet/opus — now safe to flag
#     because Model Selection is host-neutral after #161 FIX 1), and the
#     English-homograph vendors only in a vendor context (#161 FIX 3).
PROVIDER_MODEL_DRIFT_DENYLIST = (
    # providers / vendors
    "openai",
    "anthropic",
    "google deepmind",
    "deepmind",
    "mistral",
    "xai",
    "meta ai",
    # model families
    "claude opus",
    "claude sonnet",
    "claude haiku",
    "gemini",
    "llama",
    # host-specific reasoning-control setting names
    "extended thinking",
    "thinking budget",
    "reasoning_effort",
    "reasoning effort control",
    "max reasoning tokens",
)

# Compiled family-class patterns. Each is case-insensitive and intended to run
# against prose with fenced code blocks already stripped.
PROVIDER_MODEL_DRIFT_PATTERNS = (
    # gpt-N family incl. point and suffixed ids: gpt-3, gpt-4, gpt-4o,
    # gpt-4o-mini, gpt-5, gpt-5.1, gpt-4-turbo, …
    re.compile(r"(?<![\w-])gpt-\d[\w.]*(?:-\w+)*", re.IGNORECASE),
    # o-series reasoning models: o1, o3, o3-mini, o4-mini, o1-pro — the digit is
    # mandatory so a standalone letter "o" never matches.
    re.compile(r"(?<![\w-])o[134](?:-(?:mini|pro))?(?![\w-])", re.IGNORECASE),
    # bare capability-tier model names (safe to flag after #161 FIX 1).
    re.compile(r"(?<![\w-])(?:haiku|sonnet|opus)(?![\w-])", re.IGNORECASE),
    # Claude model family: bare ("use Claude for the final review") OR a
    # hyphenated model id ("claude-3-opus", "claude-3-5-sonnet") — the [\w-]
    # boundary used elsewhere lets a hyphenated id slip past, so match the
    # optional "-suffix" run explicitly. Spares the host PRODUCTS "Claude Code"
    # / "Claude Desktop" and a "~/.claude/" path / "claude_desktop_config"
    # filename (those are host config, not a model-as-reasoning choice; a host
    # phrase in a body is the separate HOST_SPECIFIC_BODY_DENYLIST's job).
    # #161 codex follow-up, PR #270.
    re.compile(
        r"(?<![\w/.-])claude(?:-[\w.]+)*(?![\w-])(?!\s+(?:code|desktop)\b)",
        re.IGNORECASE,
    ),
    # English-homograph vendors, only in a vendor context (#161 FIX 3): require
    # an adjacent vendor/model cue word so ordinary prose using the verbs
    # "cohere" / "grok" cannot trip the guard.
    re.compile(
        r"(?<![\w-])(?:cohere|grok)(?![\w-])"
        r"(?=[^.\n]*\b(?:model|models|provider|vendor|api|llm|ai)\b)"
        r"|"
        r"\b(?:model|models|provider|vendor|api|llm|ai)\b[^.\n]*"
        r"(?<![\w-])(?:cohere|grok)(?![\w-])",
        re.IGNORECASE,
    ),
)

_FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _provider_model_drift_hit(prose: str):
    """Return the first denied provider/model/control token found in prose, or
    None. Shared by the per-skill guard and the focused guard test so both use
    one matcher (#161). `prose` should already have fenced code blocks stripped."""
    for token in PROVIDER_MODEL_DRIFT_DENYLIST:
        pattern = re.compile(rf"(?<![\w-]){re.escape(token)}(?![\w-])", re.IGNORECASE)
        m = pattern.search(prose)
        if m:
            return m.group(0)
    for pattern in PROVIDER_MODEL_DRIFT_PATTERNS:
        m = pattern.search(prose)
        if m:
            return m.group(0)
    return None


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_body_has_no_provider_or_model_name(skill_path):
    """Reasoning-effort guidance must stay host-neutral — no maintained list of
    providers, models, or host-specific reasoning-control setting names (#161).
    Fenced code blocks are exempt (they may carry a concrete example); normative
    prose may not enumerate vendors/models/controls."""
    text = skill_path.read_text(encoding="utf-8")
    prose = _FENCED_BLOCK_RE.sub("", text)
    hit = _provider_model_drift_hit(prose)
    assert hit is None, (
        f"{skill_path.relative_to(SKILLS_DIR.parent)} names {hit!r} in prose. "
        f"sumo-qa expresses a preference for the strongest AVAILABLE reasoning, "
        f"never a maintained provider/model/control list (issue #161). Use the "
        f"host-neutral, capability-based wording — see using-sumo-qa → "
        f"Reasoning effort."
    )


def test_provider_model_drift_matcher_flags_and_spares():
    """Focused positive/negative guard for the #161 drift matcher itself."""
    # Positive: suffixed model id in prose must be caught.
    assert _provider_model_drift_hit("use gpt-4o-mini for cheap subagents")
    # Positive: bare capability-tier model name must be caught.
    assert _provider_model_drift_hit("switch to opus for the final review")
    # Positive: bare model-family reference must be caught (#161 codex follow-up).
    assert _provider_model_drift_hit("use Claude for the final review")
    # Positive: a hyphenated Claude model id must be caught (#161 codex P1).
    assert _provider_model_drift_hit("route to claude-3-opus for hard reviews")
    assert _provider_model_drift_hit("prefer claude-3-5-sonnet here")
    # Negative: the host PRODUCTS "Claude Code" / "Claude Desktop" and a
    # ~/.claude path / claude_desktop_config filename are host config, not a
    # model-as-reasoning choice — the provider/model guard must spare them.
    assert _provider_model_drift_hit("install the skill for Claude Code") is None
    assert _provider_model_drift_hit("see Claude Desktop's mcp config") is None
    assert _provider_model_drift_hit("symlinks land in ~/.claude/skills/") is None
    assert _provider_model_drift_hit("writes claude_desktop_config.json") is None
    # Positive: o-series reasoning model.
    assert _provider_model_drift_hit("route hard calls to o3-mini")
    # Negative: host-neutral capability prose must pass.
    assert _provider_model_drift_hit("use the strongest available reasoning") is None
    # Negative: a standalone letter "o" must not false-positive.
    assert _provider_model_drift_hit("plan o through the rollout") is None
    # Negative: English-homograph verbs in ordinary prose must pass.
    assert _provider_model_drift_hit("the findings cohere into one risk") is None
    assert _provider_model_drift_hit("grok the diff before reviewing") is None
    # Negative: a fenced code block legitimately containing a model id is exempt
    # (the per-skill guard strips fences before matching).
    fenced = "```\nmodel: gpt-4o-mini\n```"
    assert _provider_model_drift_hit(_FENCED_BLOCK_RE.sub("", fenced)) is None


# The same deny-list applies to the three skill-contract docs. Generic scenario
# labels in tests/scenarios/ are intentionally out of scope; deny-lists target
# normative contract surfaces, not eval labels.
SKILL_CONTRACT_DOCS = (
    SKILLS_DIR.parent / "docs" / "ARCHITECTURE.md",
    SKILLS_DIR.parent / "docs" / "SKILLS.md",
    SKILLS_DIR.parent / "docs" / "TOOLS.md",
)


@pytest.mark.parametrize("doc_path", SKILL_CONTRACT_DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize("phrase", HOST_SPECIFIC_BODY_DENYLIST[:3])
def test_skill_contract_doc_has_no_bare_host_specific_phrase(doc_path, phrase):
    # mutmut's CWD points at mutants/ and only `also_copy` paths are mirrored
    # there. The docs/ tree is not in also_copy (no production-code mutation
    # would invalidate this doc-level check), so silently skip when the file
    # isn't reachable — the same assertion still runs in the normal `pytest`
    # invocation, in CI, and in the pre-commit gate.
    if not doc_path.is_file():
        pytest.skip(f"{doc_path} not present in this test root (mutmut CWD?)")
    text = doc_path.read_text(encoding="utf-8")
    # Allow occurrences inside fenced code blocks (used to show host-specific
    # examples) but flag bare prose mentions of the contract wording.
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    assert phrase not in stripped, (
        f"{doc_path.name} mentions {phrase!r} in normative prose. Use the "
        f"host-neutral capability term instead (see using-sumo-qa → Shared vocabulary)."
    )
