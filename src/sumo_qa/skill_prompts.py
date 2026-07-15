# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Register every skills/*/SKILL.md as an MCP tool.

Single delivery channel for skills across every supported host. MCP tools
are surfaced in the slash menu by Claude Code, IntelliJ AI Assistant, and
VS Code + Copilot — so registering each SKILL.md as a tool means
`/sumo_qa_deciding_approach`, `/sumo_qa_creating_test_plan`, etc. appear identically
in every host. Calling the tool returns the SKILL.md body, which the host
LLM follows. When the body would exceed the host's per-response token cap, a
compact pointer to the progressive-loading slices (see #393 and
``skill_manifest``) is returned instead, so the load never fails opaquely.

Why not also register as MCP prompts? MCP prompts are surfaced by Claude
Code but not by IntelliJ. Registering as both creates duplicate entries
in Claude Code's slash menu — same name, two routes — which is the
confusion the user pushed back on. One channel keeps the experience
identical.

Why not also symlink into ~/.claude/skills/ for Claude Code's native
skill loader? The native loader has richer features (auto-loads checklist
into TodoWrite, treats Iron Law as system-prompt-grade discipline) but
those features don't exist in IntelliJ or Copilot. Symlinking creates
asymmetric behavior the user shouldn't have to think about. install.py
no longer creates the symlink.

The SKILL.md file is read fresh on each invocation so editing it propagates
without restart.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from sumo_qa.debug_capture import maybe_capture

_REPO_ROOT_SKILLS = Path(__file__).resolve().parent.parent.parent / "skills"
_BUNDLED_SKILLS = Path(__file__).resolve().parent / "_data" / "skills"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# --- Per-response token cap (#393) ---------------------------------------
# The host refuses to inline a tool response above its per-response token
# limit and saves it to a file instead, so the canonical load fails opaquely
# ("result ... exceeds maximum allowed tokens"). The largest skill,
# sumo-qa-reviewing-before-merge, was first to cross that wall: ~66,492 chars
# (~16,623 est. tokens by the len/4 estimator) at filing, ~17.8k now. Dense
# skill markdown tokenises HEAVIER than len/4, so the real cap is crossed
# before the estimate reaches the host's nominal limit; the default sits
# conservatively below the observed reject point and well above every other
# skill (next largest ~4.7k est. tokens), leaving growth headroom. It is a
# safety net, not the host's exact constant (which varies by host/tokeniser):
# override per-host via SUMO_QA_SKILL_RESPONSE_TOKEN_CAP, or inject in tests.
DEFAULT_SKILL_RESPONSE_TOKEN_CAP = 12000
_RESPONSE_TOKEN_CAP_ENV = "SUMO_QA_SKILL_RESPONSE_TOKEN_CAP"

# --- Output-profile overlay (#215) ---------------------------------------
# SUMO_QA_OUTPUT_PROFILE tunes how much ceremony wraps a served skill body so
# small, low-risk changes don't feel like a full QA audit while risky work
# still gets strict handling. It is a serve-time overlay on the SINGLE skill-
# serving path (this module), NOT a per-skill rewrite: the canonical SKILL.md
# files stay readable and host-neutral, and `default` serves them byte-for-byte
# (backwards compatible). Only the skill body is touched — the sumo_qa_load_*
# catalogue payloads are untouched, so strict mode cannot bloat them.
DEFAULT_OUTPUT_PROFILE = "default"
_OUTPUT_PROFILE_ENV = "SUMO_QA_OUTPUT_PROFILE"
_VALID_OUTPUT_PROFILES = ("concise", "default", "lean", "strict")

# The non-negotiable floor. Whatever the profile, these obligations are never
# skipped or shortened away — this is the safety guarantee behind the issue's
# non-goal "No profile may allow skipping required tests, evidence,
# confirmations, or safety gates." Every non-default overlay restates it so a
# high-risk workflow keeps its gates even in concise mode.
_NEVER_OPTIONAL = (
    "Whatever the profile, these are never skipped or shortened away: the "
    "skill's Iron Law and any HARD-GATE; evidence for every claim (show the "
    "command and its output, never assert a pass without proof); explicit user "
    "confirmation before writing files, running mutating commands, or "
    "installing anything; and every mandatory test or safety gate the skill "
    "names. A profile tunes how much prose wraps the work, never whether these "
    "hold."
)

_CONCISE_OVERLAY = (
    "> Output profile: concise. Give the shortest useful answer for this "
    "change: one focused risk/test summary, findings over framing, no formal "
    "section headers or evidence tables unless the skill marks them mandatory. "
    "Drop preamble, restating, and closing pleasantries. "
    # The #528 measured finding: real session cost is dominated by tool traffic
    # and turn count, not answer prose, so concise must budget the PROCESS too.
    "Spend tools leanly: load only what this skill's gates require, skip "
    "supplementary loads and sweeps, never re-load what is already in "
    "context. " + _NEVER_OPTIONAL + "\n\n---\n\n"
)

_LEAN_OVERLAY = (
    "> Output profile: lean. This response is the skill's progressive-loading "
    "route, not its body: load the manifest, then ONLY the sections this "
    "skill's gates require; skip supplementary loads and sweeps, never re-load "
    "what is already in context. Give the shortest useful answer: findings "
    "over framing, drop preamble and closing pleasantries. " + _NEVER_OPTIONAL + "\n\n---\n\n"
)

_STRICT_OVERLAY = (
    "> Output profile: strict. Use the skill's full ceremony: state each gate "
    "explicitly, present evidence as a table, map every named risk to the test "
    "that covers it, and close with an explicit residual-risk section. Prefer "
    "completeness over brevity while staying grounded — never pad with generic "
    "advice. " + _NEVER_OPTIONAL + "\n\n---\n\n"
)

_PROFILE_OVERLAYS = {
    "concise": _CONCISE_OVERLAY,
    "lean": _LEAN_OVERLAY,
    "strict": _STRICT_OVERLAY,
    # `default` intentionally maps to no overlay (byte-for-byte body).
    "default": "",
}


def _approx_tokens(text: str) -> int:
    """Approximate token count: length / 4, rounded up. Mirrors the estimator
    in skill_manifest and tests/test_token_weight_regression.py so weights are
    comparable across the codebase."""
    return (len(text) + 3) // 4


def _response_token_cap(override: int | None = None) -> int:
    """Resolve the per-response token cap: explicit override > env var >
    documented default. A non-integer or non-positive env value is ignored
    (falls back to the default) so a misconfigured host cannot silently
    disable the guard."""
    if override is not None:
        return override
    raw = os.environ.get(_RESPONSE_TOKEN_CAP_ENV)
    if raw is not None:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return DEFAULT_SKILL_RESPONSE_TOKEN_CAP


def _resolve_output_profile(override: str | None = None) -> str:
    """Resolve the active output profile: explicit override > env var >
    documented default. Resolution is case/whitespace-insensitive. An
    unrecognised value (typo, unknown profile) falls back predictably to
    `default` — mirroring `_response_token_cap`'s bad-env handling — so a
    misconfigured host can never break serving or silently drop a gate."""
    raw = override if override is not None else os.environ.get(_OUTPUT_PROFILE_ENV)
    if raw is None:
        return DEFAULT_OUTPUT_PROFILE
    normalized = raw.strip().lower()
    if normalized in _VALID_OUTPUT_PROFILES:
        return normalized
    return DEFAULT_OUTPUT_PROFILE


def _profile_overlay(profile: str) -> str:
    """Return the serve-time overlay for `profile` (prepended to the served
    output, or dropped when the composed payload would exceed the token cap).

    `default` returns "" (the body is served byte-for-byte). `concise` and
    `strict` return a small, bounded directive block prepended to the body;
    `lean` returns one prepended to the progressive-loading pointer. Every
    non-empty overlay restates the never-optional gate floor."""
    return _PROFILE_OVERLAYS.get(profile, "")


def _skills_dir() -> Path:
    """Return the directory holding SKILL.md files.

    Resolution order:
    1. The bundled `_data/skills/` shipped inside the wheel (production
       installs via uv/pipx land here).
    2. The repo's top-level `skills/` (development / source checkout).

    Returning a path that doesn't exist is fine — the iteration code below
    no-ops cleanly when there are no skill dirs."""
    if _BUNDLED_SKILLS.is_dir():
        return _BUNDLED_SKILLS
    return _REPO_ROOT_SKILLS


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from a markdown file. Returns {} when absent or
    malformed; we never want a bad frontmatter to break server startup."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return parsed or {}


def register_skills_as_prompts(
    mcp: Any, token_cap: int | None = None, profile: str | None = None
) -> None:
    """Register every SKILL.md under skills/ as an MCP tool.

    Name kept as the historic `register_skills_as_prompts` for backwards
    compatibility with existing `server.py` call sites. The implementation
    is now tool-only (see module docstring for why).

    Name: directory name with `-` -> `_`. Description: from frontmatter.
    Body: full file content (including frontmatter), read fresh on each call
    so editing the SKILL.md propagates without restart, and reshaped by the
    active output profile (#215, resolved from SUMO_QA_OUTPUT_PROFILE). An
    over-cap body is served as a progressive-loading pointer instead (#393);
    `token_cap` overrides the resolved cap and `profile` overrides the resolved
    profile — both are used by tests.
    """
    skills_dir = _skills_dir()
    if not skills_dir.is_dir():
        return
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        text = skill_path.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(text)
        name = skill_dir.name.replace("-", "_")
        description = frontmatter.get("description") or f"Skill: {skill_dir.name}"
        # Collapse multi-line YAML folded descriptions to a single line so MCP
        # hosts that render descriptions inline don't show stray newlines.
        if isinstance(description, str):
            description = " ".join(description.split())
        _bind_tool(mcp, name, description, skill_path, token_cap=token_cap, profile=profile)


def _oversize_pointer_text(skill_name: str, tokens: int, cap: int) -> str:
    """Compact, actionable pointer returned in place of an over-cap skill body.

    Names the progressive-loading route so the host can fetch the discipline a
    slice at a time without tripping the per-response token cap (#393). The
    pointer is a small constant; it never itself exceeds a realistic cap."""
    return (
        f"# {skill_name} is too large to return in one response\n\n"
        f"This skill's full body is ~{tokens} estimated tokens, above the "
        f"~{cap}-token per-response cap, so returning it inline would exceed "
        f"the host's maximum allowed tokens. Load it progressively with the "
        f"`sumo_qa_load_skill_context` tool instead:\n\n"
        f'1. `sumo_qa_load_skill_context(skill_name="{skill_name}", mode="manifest")`: '
        f"the section and module index (ids, headings, token weights).\n"
        f'2. `sumo_qa_load_skill_context(skill_name="{skill_name}", mode="section", section="<id>")`: '
        f"one section's text.\n"
        f'3. `sumo_qa_load_skill_context(skill_name="{skill_name}", mode="module", module="<id>")`: '
        f"one module's text (when the skill ships modules).\n\n"
        f'Start with `mode="manifest"` to choose the sections you need.'
    )


def _lean_pointer_text(skill_name: str, tokens: int) -> str:
    """The lean profile's serve payload (#528): the progressive-loading route,
    worded truthfully for ANY body size (unlike the #393 over-cap pointer, this
    never claims the body exceeded a cap - lean serves the route by design, so
    the host loads only the sections its gates need instead of the full body)."""
    return (
        f"# {skill_name}: progressive loading (lean profile)\n\n"
        f"The lean output profile serves this route instead of the skill's "
        f"~{tokens}-token full body, so load only what you need with the "
        f"`sumo_qa_load_skill_context` tool:\n\n"
        f'1. `sumo_qa_load_skill_context(skill_name="{skill_name}", mode="manifest")`: '
        f"the section and module index (ids, headings, token weights).\n"
        f'2. `sumo_qa_load_skill_context(skill_name="{skill_name}", mode="section", section="<id>")`: '
        f"one section's text.\n"
        f'3. `sumo_qa_load_skill_context(skill_name="{skill_name}", mode="module", module="<id>")`: '
        f"one module's text (when the skill ships modules).\n\n"
        f'Start with `mode="manifest"`, and load the Iron Law / checklist '
        f"sections before acting."
    )


def _make_skill_callable(path: Path, token_cap: int | None = None, profile: str | None = None):
    """Factory returning a zero-argument function that reads `path` at call time.

    The factory closes over `path` so each generated function returns its OWN
    skill content. Using a factory (instead of a default-argument closure)
    keeps the function's signature parameter-free, which FastMCP's tool
    introspection requires.

    The active output profile (#215) is resolved FRESH on each call (env var >
    documented default), so a host config change takes effect without a rebind —
    the same freshness philosophy as reading the SKILL.md each call. For
    `concise`/`strict` a small overlay is prepended to the body; `lean` serves the
    skill's progressive-loading route (a pointer) in place of the body; `default`
    leaves the body byte-for-byte unchanged. `profile` is an explicit override used by
    tests (falls through to the env var when None).

    When the composed body would exceed the per-response token cap (#393), the
    function returns a compact pointer to the progressive-loading route instead
    of the oversized body (which the host refuses and saves to a file); the
    profile overlay is preserved on the pointer so the host still knows the
    active profile, but ONLY when overlay + pointer itself fits the cap. With a
    cap small enough that the overlaid pointer would overflow it, the overlay is
    dropped: the pointer is the degraded-mode payload and must never recreate
    the over-cap response it exists to prevent. Under-cap `default` skills
    return the body byte-for-byte, unchanged. `token_cap` overrides the
    resolved cap (env var > default) and is used by tests.
    """
    cap = _response_token_cap(token_cap)

    def _skill_body() -> str:
        active = _resolve_output_profile(profile)
        overlay = _profile_overlay(active)
        text = path.read_text(encoding="utf-8")
        if active == "lean":
            # #528: lean serves the progressive route instead of the body -
            # served bytes are re-read every turn, so this is the cost lever.
            pointer = _lean_pointer_text(path.parent.name, _approx_tokens(text))
            if _approx_tokens(overlay + pointer) <= cap:
                return overlay + pointer
            return pointer
        body = overlay + text if overlay else text
        tokens = _approx_tokens(body)
        if tokens > cap:
            pointer = _oversize_pointer_text(path.parent.name, tokens, cap)
            if overlay and _approx_tokens(overlay + pointer) <= cap:
                return overlay + pointer
            return pointer
        return body

    return _skill_body


def _bind_tool(
    mcp: Any,
    name: str,
    description: str,
    path: Path,
    token_cap: int | None = None,
    profile: str | None = None,
) -> None:
    """Bind one SKILL.md as an MCP tool named `name`. The tool returns the
    SKILL.md body (reshaped by the active output profile, #215), which the host
    LLM follows, or a progressive-loading pointer when the body would exceed the
    per-response token cap (#393).

    The call is recorded through `maybe_capture` so a `SUMO_QA_DEBUG_DIR`
    capture contains the skill-tool (routing) calls the #214 conformance
    fixtures check — without it a real capture could never satisfy an
    `expected_entry_skill` contract. The captured output is a compact summary,
    not the served body (which can be ~12k tokens)."""
    body_fn = _make_skill_callable(path, token_cap=token_cap, profile=profile)

    def fn() -> str:
        text = body_fn()
        maybe_capture(
            tool=name,
            args={},
            output={"skill_tool": name, "served_chars": len(text)},
        )
        return text

    fn.__name__ = name
    mcp.tool(name=name, description=description)(fn)
