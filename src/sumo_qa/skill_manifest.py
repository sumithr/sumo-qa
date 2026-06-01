# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic, read-only index over the bundled SKILL.md files.

This module builds a *manifest* for every skill — compact metadata plus a
section index (one entry per markdown heading) and a module index (one entry
per ``skills/<skill>/modules/*.md`` file) — and serves a partial loader so a
host can fetch just the routing summary, a single section, or a single module
instead of the whole SKILL.md body.

Why a sibling module rather than extending ``skill_prompts``: the existing
``skill_prompts`` module owns the *registration* of each SKILL.md as a
zero-argument MCP tool that returns the full body. Those tools MUST keep
returning the body byte-for-byte (the ``mode="full"`` contract here is
verified against them). This module only *reads*; it reuses
``skill_prompts``' skill discovery (``_skills_dir``) and frontmatter parsing
(``_parse_frontmatter``) so enumeration logic is not duplicated.

No LLM extraction, no network, no caching, no embeddings — pure markdown
structure + sha256 content hashing. Token estimates are approximate
(``len/4``), matching ``tests/test_token_weight_regression.py``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sumo_qa.skill_prompts import _parse_frontmatter, _skills_dir

# Heading line: 1-6 leading '#', a space, then the heading text. Matched only
# on lines OUTSIDE fenced code blocks (see _iter_headings).
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
# A fence opener/closer: ``` or ~~~ (3+), optionally indented, optional info string.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
# Sections whose heading text contains any of these terms (case-insensitively)
# are flagged required=True. `frontmatter` is the synthetic frontmatter section.
_REQUIRED_TERMS = ("frontmatter", "iron law", "hard-gate", "checklist", "flow", "red flags")
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")

_FRONTMATTER_SECTION_ID = "frontmatter"


def _approx_tokens(text: str) -> int:
    """Approximate token count: length / 4, rounded up. Mirrors the estimator
    in tests/test_token_weight_regression.py so weights are comparable."""
    return (len(text) + 3) // 4


def _content_hash(text: str) -> str:
    """sha256 of the full SKILL.md body, hex-digested. Deterministic id for
    cache/version comparisons by a host."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slugify(heading: str) -> str:
    """Lowercase, strip non-alphanumerics to single hyphens, trim hyphens.

    Deterministic and stable: the same heading text always yields the same
    base slug. Empty result (heading was all punctuation) falls back to
    ``section``."""
    slug = _NON_SLUG_RE.sub("-", heading.lower()).strip("-")
    return slug or "section"


def _is_required(heading_text: str) -> bool:
    """True when the heading names one of the required structural sections.

    Match is case-insensitive substring so canonical variants count:
    ``Red Flags — STOP and rework`` matches ``red flags``; ``Process Flow``
    matches ``flow``; ``The Iron Law`` matches ``iron law``."""
    lowered = heading_text.lower()
    return any(term in lowered for term in _REQUIRED_TERMS)


def _frontmatter_block(text: str) -> str:
    """Return the raw frontmatter block (including the --- fences) or ''."""
    match = _FRONTMATTER_RE.match(text)
    return match.group(0) if match else ""


def _iter_headings(body: str) -> list[tuple[int, int, str]]:
    """Yield (line_index, level, heading_text) for every ATX heading in *body*
    that is NOT inside a fenced code block.

    Tracks ``` / ~~~ fences so a ``# comment`` inside a python/js example block
    is never mistaken for a section heading."""
    headings: list[tuple[int, int, str]] = []
    fence: str | None = None
    for idx, line in enumerate(body.splitlines()):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]  # ` or ~
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            headings.append((idx, level, text))
    return headings


def _dedupe(slug: str, seen: dict[str, int]) -> str:
    """Return a unique id for *slug*, appending ``-2``, ``-3`` … on collision.

    Deterministic: the first occurrence keeps the bare slug, the second gets
    ``-2``, etc. (``red-flags`` then ``red-flags-2``)."""
    count = seen.get(slug, 0) + 1
    seen[slug] = count
    return slug if count == 1 else f"{slug}-{count}"


def _index_sections(text: str) -> list[dict[str, Any]]:
    """Build the section index for one SKILL.md body.

    The first synthetic section is ``frontmatter`` (the YAML block, required).
    Then one section per ATX heading; each section's text runs from its
    heading line up to (but excluding) the next heading at any level. Section
    ids are stable slugs with deterministic ``-N`` suffixes on duplicates.
    """
    sections: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    fm_block = _frontmatter_block(text)
    if fm_block:
        sections.append(
            {
                "id": _dedupe(_FRONTMATTER_SECTION_ID, seen),
                "heading": "frontmatter",
                "level": 0,
                "estimated_tokens": _approx_tokens(fm_block),
                "required": True,
                # Internal: byte range used by the loader; not part of the
                # public manifest schema (stripped before serialising).
                "_text": fm_block,
            }
        )

    lines = text.splitlines(keepends=True)
    headings = _iter_headings(text)
    for pos, (line_idx, level, heading_text) in enumerate(headings):
        end_idx = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        section_text = "".join(lines[line_idx:end_idx])
        sections.append(
            {
                "id": _dedupe(_slugify(heading_text), seen),
                "heading": heading_text,
                "level": level,
                "estimated_tokens": _approx_tokens(section_text),
                "required": _is_required(heading_text),
                "_text": section_text,
            }
        )
    return sections


def _modules_dir(skill_dir: Path) -> Path:
    return skill_dir / "modules"


def _index_modules(skill_dir: Path) -> list[dict[str, Any]]:
    """Build the module index from ``skills/<skill>/modules/*.md`` filenames.

    Empty list when no ``modules/`` dir exists (the common case today). Module
    ids are slugs of the filename stem; ``path`` is repo-relative."""
    modules_dir = _modules_dir(skill_dir)
    if not modules_dir.is_dir():
        return []
    seen: dict[str, int] = {}
    modules: list[dict[str, Any]] = []
    for path in sorted(modules_dir.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        modules.append(
            {
                "id": _dedupe(_slugify(path.stem), seen),
                "path": f"skills/{skill_dir.name}/modules/{path.name}",
                "estimated_tokens": _approx_tokens(body),
                "_text": body,
            }
        )
    return modules


def _public_section(section: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in section.items() if not k.startswith("_")}


def _public_module(module: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in module.items() if not k.startswith("_")}


def _skill_records() -> dict[str, dict[str, Any]]:
    """Read every bundled SKILL.md and build its full (internal) record.

    Reuses ``skill_prompts._skills_dir`` for discovery — no duplicate
    enumeration. Records are read fresh on each call so editing a SKILL.md
    propagates without restart (same contract as the skill tools)."""
    records: dict[str, dict[str, Any]] = {}
    skills_dir = _skills_dir()
    if not skills_dir.is_dir():
        return records
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        text = skill_path.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(text)
        description = frontmatter.get("description") or f"Skill: {skill_dir.name}"
        if isinstance(description, str):
            description = " ".join(description.split())
        records[skill_dir.name] = {
            "skill_name": skill_dir.name,
            "tool_name": skill_dir.name.replace("-", "_"),
            "description": description,
            "content_hash": _content_hash(text),
            "estimated_tokens_full": _approx_tokens(text),
            "sections": _index_sections(text),
            "modules": _index_modules(skill_dir),
            "_full": text,
        }
    return records


def list_skill_manifests() -> dict[str, Any]:
    """Compact metadata for every bundled skill.

    Returns ``{"skills": [manifest, …]}`` where each manifest carries
    skill_name, tool_name, description, content_hash, estimated_tokens_full,
    and the section/module indexes (public fields only — no section/module
    body text)."""
    skills = []
    for record in _skill_records().values():
        skills.append(
            {
                "skill_name": record["skill_name"],
                "tool_name": record["tool_name"],
                "description": record["description"],
                "content_hash": record["content_hash"],
                "estimated_tokens_full": record["estimated_tokens_full"],
                "sections": [_public_section(s) for s in record["sections"]],
                "modules": [_public_module(m) for m in record["modules"]],
            }
        )
    return {"skills": skills}


def _has_traversal(value: str) -> bool:
    """True when *value* looks like a path-traversal / absolute-path attempt.

    Section and module ids are flat slugs; any path separator, ``..`` segment,
    or absolute marker is illegitimate and rejected before any lookup."""
    if not value:
        return False
    return (
        "/" in value
        or "\\" in value
        or ".." in value
        or value.startswith("~")
        or Path(value).is_absolute()
    )


def _slice_envelope(base: dict[str, Any], text: str, known_hash: str | None) -> dict[str, Any]:
    """Attach the per-slice digest fields and apply optional change-detection.

    Every partial load (section/module/full) returns ``content_hash`` (sha256
    of exactly the returned slice) and ``estimated_tokens`` (``len/4`` of that
    slice) so a caller can cheaply tell whether a re-fetched slice has changed.

    Change-detection (the Lever 6 affordance) is purely derived — there is no
    hidden cache. When the caller passes ``known_hash``:
      * it matches the live slice  → ``changed=False`` and the body is omitted
        (the token saving — the caller already holds identical text);
      * it differs (or is stale)   → ``changed=True`` and the body is returned.
    When ``known_hash`` is omitted the body is always returned and no
    ``changed`` flag is added (backward-compatible no-cache default)."""
    content_hash = _content_hash(text)
    envelope = dict(base)
    envelope["content_hash"] = content_hash
    envelope["estimated_tokens"] = _approx_tokens(text)
    if known_hash is None:
        envelope["content"] = text
        return envelope
    if known_hash == content_hash:
        envelope["changed"] = False
        return envelope
    envelope["changed"] = True
    envelope["content"] = text
    return envelope


def _error(message: str, available: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an actionable error envelope (does NOT raise).

    Shape mirrors the catalogue loaders' plain-text discipline but as a small
    structured payload the host LLM can read: ``{"error": msg, **available}``.
    ``available`` lists the valid choices for the failed argument."""
    payload: dict[str, Any] = {"error": message}
    if available:
        payload.update(available)
    return payload


def load_skill_context(
    skill_name: str | None = None,
    mode: str | None = None,
    section: str | None = None,
    module: str | None = None,
    known_hash: str | None = None,
) -> dict[str, Any]:
    """Load a slice of one skill's context.

    ``mode``:
      * ``"manifest"`` — routing summary + section list + module list.
      * ``"section"``  — one section's text (requires ``section``).
      * ``"module"``   — one module's text (requires ``module``).
      * ``"full"``     — the entire SKILL.md body, byte-for-byte identical to
        the existing zero-argument skill tool for this skill.

    The partial-load modes (``section``/``module``/``full``) each return a
    ``content_hash`` (sha256 of exactly the returned slice) and
    ``estimated_tokens``. Pass ``known_hash`` to ask "has this slice changed
    since hash X?": a match returns ``changed=False`` with the body omitted (the
    token saving), a mismatch returns ``changed=True`` with the body. This is
    derived per-call — there is no hidden cache (``manifest`` mode ignores
    ``known_hash``).

    Never raises: every invalid input returns an error envelope that lists the
    valid choices. ``skill_name`` and ``mode`` are accepted as optional (default
    ``None``) so that a host omitting a required argument gets the documented
    error envelope rather than a schema-level rejection before this runs.
    Path-traversal in ``section``/``module`` is rejected."""
    records = _skill_records()
    valid_modes = ["manifest", "section", "module", "full"]

    if skill_name is None:
        return _error(
            "skill_name is required.",
            {"available_skills": sorted(records)},
        )
    if skill_name not in records:
        return _error(
            f"Unknown skill_name {skill_name!r}.",
            {"available_skills": sorted(records)},
        )
    record = records[skill_name]

    if mode is None:
        return _error(
            "mode is required.",
            {"available_modes": valid_modes},
        )
    if mode not in valid_modes:
        return _error(
            f"Unknown mode {mode!r}.",
            {"available_modes": valid_modes},
        )

    if mode == "full":
        return _slice_envelope(
            {"skill_name": skill_name, "mode": "full"}, record["_full"], known_hash
        )

    if mode == "manifest":
        return {
            "skill_name": skill_name,
            "mode": "manifest",
            "description": record["description"],
            "content_hash": record["content_hash"],
            "estimated_tokens_full": record["estimated_tokens_full"],
            "sections": [_public_section(s) for s in record["sections"]],
            "modules": [_public_module(m) for m in record["modules"]],
        }

    if mode == "section":
        sections = record["sections"]
        available = [s["id"] for s in sections]
        if section is None:
            return _error(
                "mode='section' requires a section id.",
                {"available_sections": available},
            )
        if _has_traversal(section):
            return _error(
                f"Illegal section id {section!r} (path traversal rejected).",
                {"available_sections": available},
            )
        match = next((s for s in sections if s["id"] == section), None)
        if match is None:
            return _error(
                f"Unknown section {section!r} for skill {skill_name!r}.",
                {"available_sections": available},
            )
        return _slice_envelope(
            {
                "skill_name": skill_name,
                "mode": "section",
                "section": match["id"],
                "heading": match["heading"],
            },
            match["_text"],
            known_hash,
        )

    # mode == "module"
    modules = record["modules"]
    available = [m["id"] for m in modules]
    if not modules:
        return _error(
            f"Skill {skill_name!r} has no modules.",
            {"available_modules": available},
        )
    if module is None:
        return _error(
            "mode='module' requires a module id.",
            {"available_modules": available},
        )
    if _has_traversal(module):
        return _error(
            f"Illegal module id {module!r} (path traversal rejected).",
            {"available_modules": available},
        )
    match = next((m for m in modules if m["id"] == module), None)
    if match is None:
        return _error(
            f"Unknown module {module!r} for skill {skill_name!r}.",
            {"available_modules": available},
        )
    return _slice_envelope(
        {
            "skill_name": skill_name,
            "mode": "module",
            "module": match["id"],
            "path": match["path"],
        },
        match["_text"],
        known_hash,
    )
