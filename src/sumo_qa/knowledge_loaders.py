# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Knowledge-provider tools.

Each `sumo_qa_load_*` function reads a markdown catalogue from
`knowledge/<name>.md` and returns it verbatim. No inference, no filtering
beyond optional metadata-based subset selection on `load_standards` and
`load_rules`. The host LLM picks from the returned catalogue.

Path resolution mirrors the existing pattern in `server.py` for
`QA_TEST_DATA_PATH`: env var override, then bundled `_data/knowledge/`
in installed wheels, then `knowledge/` at repo root in dev.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from sumo_qa import paths

_REPO_ROOT_KNOWLEDGE = Path(__file__).parent.parent.parent / "knowledge"
_BUNDLED_KNOWLEDGE = Path(__file__).parent / "_data" / "knowledge"
_RULE_CLASSIFICATION_ALIASES = {
    "frontend_change": ("ui_only_change",),
    "config_change": ("configuration_change",),
    "data_migration": ("data_mapping_change",),
    "performance_change": ("caching_change",),
    "infrastructure_change": ("configuration_change",),
}


def _classification_filter_terms(classification: str | None) -> set[str] | None:
    """Normalize an optional classification filter.

    Hosts sometimes pass multi-classification intent as a comma-separated string
    because MCP exposes the argument as a scalar. Treat comma, semicolon, and
    whitespace separated values as a set while preserving `None` as no filter.
    """
    if classification is None:
        return None
    return {
        # pragma: no mutate — XX-quoted strip variant is equivalent (no realistic
        # classification name contains a literal 'X' distinct from the trimmed
        # quote chars). The strip→None variant is covered by
        # test_classification_filter_strips_backticks_and_quotes.
        part.strip("`'\"")  # pragma: no mutate
        for part in re.split(r"[\s,;]+", str(classification))
        # pragma: no mutate — same rationale as the result-expression strip above;
        # filter behaviour is verified by the same strengthening test.
        if part.strip("`'\"")  # pragma: no mutate
    }


def _metadata_terms(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return _classification_filter_terms(value) or set()
    if isinstance(value, (list, tuple, set)):
        return {
            # pragma: no mutate — XX-quoted strip variant is equivalent (see
            # rationale in _classification_filter_terms). Strip→None covered by
            # test_metadata_terms_strips_backticks_in_list_inputs.
            part.strip("`'\"")  # pragma: no mutate
            for item in value
            # pragma: no mutate — regex XX-wrapped variant matches only inputs
            # containing literal "XX...XX"; equivalent for realistic metadata.
            for part in re.split(r"[\s,;]+", str(item))  # pragma: no mutate
            # pragma: no mutate — same rationale as the result-expression strip
            # above; covered by the same metadata strengthening test.
            if part.strip("`'\"")  # pragma: no mutate
        }
    return {str(value)}


def _knowledge_dir() -> Path:
    """Return the directory holding knowledge catalogues.

    Resolution order: QA_KNOWLEDGE_PATH env var > bundled _data > repo root.
    """
    override = os.environ.get("QA_KNOWLEDGE_PATH")
    if override:
        return Path(override)
    if _BUNDLED_KNOWLEDGE.is_dir():
        return _BUNDLED_KNOWLEDGE
    return _REPO_ROOT_KNOWLEDGE


def _has_packs(directory: Path) -> bool:
    """True when *directory* exists and holds at least one YAML pack.

    An empty ingested-pack dir must not shadow the bundled packs, so emptiness
    is treated as "tier absent" rather than "tier present but empty".
    """
    return directory.is_dir() and bool(
        list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
    )


def _read(name: str) -> str:
    # Explicit QA_KNOWLEDGE_PATH stays authoritative (top precedence tier).
    # Otherwise resolve per file: project pack > global pack > bundled > repo.
    if not os.environ.get("QA_KNOWLEDGE_PATH"):
        for scope in ("project", "global"):
            candidate = paths.knowledge_dir(scope) / name
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
    path = _knowledge_dir() / name
    return path.read_text(encoding="utf-8")


def sumo_qa_load_classifications() -> str:
    """Return the catalogue of canonical change classifications as text."""
    return _read("classifications.md")


def sumo_qa_load_approaches() -> str:
    """Return the catalogue of canonical QA approaches as text."""
    return _read("approaches.md")


def sumo_qa_load_principles() -> str:
    """Return ISTQB Foundation + Advanced + ISO 25010 grounding as text."""
    return _read("principles.md")


def sumo_qa_load_techniques() -> str:
    """Return the test design technique catalogue as text."""
    return _read("techniques.md")


# ---------------------------------------------------------------------------
# Per-entry / compact catalogue access (issue #287, epic #137 Lever 4).
#
# The four prose catalogues above (classifications, approaches, principles,
# techniques) are markdown with one ATX heading per entry. This block indexes
# those headings deterministically — no LLM, no network — so a host can fetch a
# single entry (full verbatim, canonical) or a compact summary (lead line,
# explicitly NON-canonical) instead of the whole catalogue. The zero-argument
# full loaders above are unchanged.
# ---------------------------------------------------------------------------

# catalogue id -> markdown filename. Only the prose catalogues with per-entry
# headings are addressable here; standards/rules are pack-shaped, not entries.
_CATALOGUE_FILES = {
    "classifications": "classifications.md",
    "approaches": "approaches.md",
    "principles": "principles.md",
    "techniques": "techniques.md",
}
_CATALOGUE_FORMATS = ("full", "compact")

# Heading line: 1-6 leading '#', a space, then heading text. Matched only on
# lines OUTSIDE fenced code blocks (mirrors skill_manifest._iter_headings).
_ENTRY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
# CommonMark fenced code blocks: an opening fence is a run of >=3 backticks or
# >=3 tildes, indented by AT MOST 3 spaces (>=4 spaces is an indented code
# block, not a fence). Capture the whole run so we can compare lengths: a
# closing fence must use the same char with length >= the opener's, so an outer
# 4-backtick fence is NOT closed by an inner 3-backtick run. Capture the
# remainder after the run too: a CLOSING fence may carry only whitespace after
# it, whereas an OPENING fence may carry an info string (e.g. ```python).
_ENTRY_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# The first heading in each file is the catalogue's own title (e.g. "# Test
# design techniques"); it is not an entry. Entry headings start at level 2.
_ENTRY_MIN_LEVEL = 2
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _entry_slugify(heading: str) -> str:
    """Lowercase heading -> stable hyphen slug. ``api_contract_change`` keeps
    its shape (underscores collapse to hyphens? no — see below); prose headings
    like ``equivalence partitioning`` become ``equivalence-partitioning``.

    Classification/approach ids already use underscores/hyphens as their
    canonical spelling, so we preserve alnum runs and join with a single
    hyphen — but underscores are alphanumeric-adjacent identifiers and must be
    kept verbatim so ``api_contract_change`` round-trips."""
    lowered = heading.lower()
    # Keep underscores (canonical classification spelling) and alphanumerics;
    # everything else collapses to a single hyphen.
    slug = re.sub(r"[^a-z0-9_]+", "-", lowered).strip("-")
    return slug or "entry"


def _iter_entry_headings(body: str) -> list[tuple[int, int, str]]:
    """Yield (line_index, level, heading_text) for every ATX heading outside a
    fenced code block. Same fence tracking as skill_manifest."""
    headings: list[tuple[int, int, str]] = []
    # Open fence as (char, length), or None when outside a code block. CommonMark
    # closes a fence only on a same-char run at least as long as the opener.
    fence: tuple[str, int] | None = None
    for idx, line in enumerate(body.splitlines()):
        fence_match = _ENTRY_FENCE_RE.match(line)
        if fence_match:
            run = fence_match.group(1)
            remainder = fence_match.group(2)
            marker, length = run[0], len(run)
            if fence is None:
                # Opening fence: an info string after the run is allowed.
                fence = (marker, length)
            elif marker == fence[0] and length >= fence[1] and not remainder.strip():
                # Closing fence: CommonMark requires whitespace-only after the
                # run. A trailing info string (e.g. ```bash) means this is
                # content inside the block, not a valid close.
                fence = None
            continue
        if fence is not None:
            continue
        heading_match = _ENTRY_HEADING_RE.match(line)
        if heading_match:
            headings.append((idx, len(heading_match.group(1)), heading_match.group(2).strip()))
    return headings


def _dedupe_entry(slug: str, seen: dict[str, int]) -> str:
    count = seen.get(slug, 0) + 1
    seen[slug] = count
    return slug if count == 1 else f"{slug}-{count}"


def _first_prose_line(entry_text: str) -> str:
    """First non-empty, non-heading line of an entry body — the deterministic
    compact summary. Verbatim from the catalogue but truncated, hence the
    summary is marked non-canonical (it is not the full entry)."""
    for line in entry_text.splitlines()[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _is_grouper(headings: list[tuple[int, int, str]], pos: int, lines: list[str]) -> bool:
    """True when the heading at *pos* is a category grouper, not a leaf entry.

    A grouper is a heading immediately followed by a *deeper* heading with no
    prose body in between (e.g. ``## Mutation`` directly above
    ``### mutation testing`` in techniques.md). Such headings have empty
    summaries and hollow bodies, so indexing them would produce a citable-but-
    empty entry; the real content lives under the leaf headings. Flat
    catalogues (classifications/approaches/principles), whose level-2 headings
    carry their own prose and are never followed by a deeper heading, are
    unaffected."""
    line_idx, level, _ = headings[pos]
    if pos + 1 >= len(headings):
        return False
    next_idx, next_level, _ = headings[pos + 1]
    if next_level <= level:
        return False
    # Deeper heading follows — grouper only if nothing but blank lines sits
    # between this heading line and that next heading line.
    between = lines[line_idx + 1 : next_idx]
    return all(not line.strip() for line in between)


def _index_catalogue_entries(text: str) -> list[dict[str, Any]]:
    """Build the entry index for one catalogue body.

    One entry per ATX heading at level >= 2 (the level-1 line is the catalogue
    title, not an entry). Category groupers — a heading immediately followed by
    a deeper heading with no prose between — are skipped so only leaf headings
    are addressable. Each entry's text runs from its heading line to the next
    heading at any level. Entry ids are stable slugs of the heading;
    duplicates get deterministic ``-2``/``-3`` suffixes."""
    entries: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    lines = text.splitlines(keepends=True)
    headings = _iter_entry_headings(text)
    for pos, (line_idx, level, heading_text) in enumerate(headings):
        if level < _ENTRY_MIN_LEVEL:
            continue
        if _is_grouper(headings, pos, lines):
            continue
        end_idx = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        entry_text = "".join(lines[line_idx:end_idx])
        entries.append(
            {
                "id": _dedupe_entry(_entry_slugify(heading_text), seen),
                "heading": heading_text,
                "level": level,
                "text": entry_text,
                "summary": _first_prose_line(entry_text),
            }
        )
    return entries


def list_catalogue_entries(catalogue: str) -> list[dict[str, Any]]:
    """Return the entry index (id, heading, level, text, summary) for one of the
    four prose catalogues. Raises ``KeyError`` for an unknown catalogue id —
    callers that want an error envelope use ``load_catalogue_entry`` /
    ``load_catalogue`` instead."""
    if catalogue not in _CATALOGUE_FILES:
        raise KeyError(catalogue)
    return _index_catalogue_entries(_read(_CATALOGUE_FILES[catalogue]))


def _catalogue_error(message: str, **available: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": message}
    payload.update(available)
    return payload


def _missing_catalogue_error(catalogue: str, exc: OSError) -> dict[str, Any]:
    """Error envelope for a catalogue whose backing file is missing/unreadable.

    Honours the "never raises" contract of ``load_catalogue`` /
    ``load_catalogue_entry``: a bad ``QA_KNOWLEDGE_PATH`` or a broken bundle
    must surface as an actionable envelope (listing the valid catalogues),
    not leak an ``OSError`` through the MCP tool wrapper."""
    return _catalogue_error(
        f"Catalogue {catalogue!r} could not be read: {exc}.",
        available_catalogues=sorted(_CATALOGUE_FILES),
    )


def load_catalogue_entry(
    catalogue: str,
    name: str | None = None,
    format: str = "full",
) -> dict[str, Any]:
    """Return one catalogue entry by name.

    ``name`` matches either the stable slug id (``api_contract_change``,
    ``equivalence-partitioning``) or the verbatim heading text
    (case-insensitive). ``format="full"`` (default) returns the entry's verbatim
    markdown with ``canonical=true``; ``format="compact"`` returns just the lead
    summary line with ``canonical=false`` (not a citation replacement).

    Never raises: an unknown catalogue, missing name, unknown name, or unknown
    format returns an actionable error envelope listing the valid choices."""
    if catalogue not in _CATALOGUE_FILES:
        return _catalogue_error(
            f"Unknown catalogue {catalogue!r}.",
            available_catalogues=sorted(_CATALOGUE_FILES),
        )
    if format not in _CATALOGUE_FORMATS:
        return _catalogue_error(
            f"Unknown format {format!r}.",
            available_formats=list(_CATALOGUE_FORMATS),
        )
    try:
        entries = list_catalogue_entries(catalogue)
    except OSError as exc:
        return _missing_catalogue_error(catalogue, exc)
    available = [e["id"] for e in entries]
    if name is None:
        return _catalogue_error(
            "name is required.",
            available_entries=available,
        )
    needle = name.strip().lower()
    match = next(
        (e for e in entries if e["id"] == needle or e["heading"].lower() == needle),
        None,
    )
    if match is None:
        return _catalogue_error(
            f"Unknown entry {name!r} in catalogue {catalogue!r}.",
            available_entries=available,
        )
    if format == "compact":
        return {
            "catalogue": catalogue,
            "id": match["id"],
            "heading": match["heading"],
            "format": "compact",
            "canonical": False,
            "text": match["summary"],
        }
    return {
        "catalogue": catalogue,
        "id": match["id"],
        "heading": match["heading"],
        "format": "full",
        "canonical": True,
        "text": match["text"],
    }


def load_catalogue(catalogue: str, format: str = "full") -> dict[str, Any]:
    """Return a whole catalogue in ``full`` or ``compact`` form.

    ``format="full"`` (default) returns ``{..., "canonical": true, "text": <the
    verbatim catalogue>}`` — byte-equal to the zero-argument loader.
    ``format="compact"`` returns ``{..., "canonical": false, "entries": [{id,
    heading, summary, canonical=false}, …]}`` — one lead-line summary per entry,
    explicitly NON-canonical (not a citation replacement).

    Never raises: unknown catalogue or format returns an error envelope."""
    if catalogue not in _CATALOGUE_FILES:
        return _catalogue_error(
            f"Unknown catalogue {catalogue!r}.",
            available_catalogues=sorted(_CATALOGUE_FILES),
        )
    if format not in _CATALOGUE_FORMATS:
        return _catalogue_error(
            f"Unknown format {format!r}.",
            available_formats=list(_CATALOGUE_FORMATS),
        )
    if format == "full":
        try:
            text = _read(_CATALOGUE_FILES[catalogue])
        except OSError as exc:
            return _missing_catalogue_error(catalogue, exc)
        return {
            "catalogue": catalogue,
            "format": "full",
            "canonical": True,
            "text": text,
        }
    try:
        entries = list_catalogue_entries(catalogue)
    except OSError as exc:
        return _missing_catalogue_error(catalogue, exc)
    return {
        "catalogue": catalogue,
        "format": "compact",
        "canonical": False,
        "entries": [
            {
                "id": e["id"],
                "heading": e["heading"],
                "summary": e["summary"],
                "canonical": False,
            }
            for e in entries
        ],
    }


def _standards_dir() -> Path:
    """Return the standards directory, honouring QA_STANDARDS_PATH override."""
    override = os.environ.get("QA_STANDARDS_PATH")
    if override:
        # Bind the literal-bearing expression to a variable so the
        # `"packs"` → `"PACKS"` mutation can be suppressed with a single
        # trailing `# pragma: no mutate` on the same physical line — mutmut
        # 3.5.0 only honours the pragma on the line carrying the mutated
        # token, and ruff's format-on-commit would re-split a multi-line
        # ternary expression across lines. The mutation is a Mac-survivor-
        # only artefact: killed on case-sensitive FS (Linux CI) by
        # test_standards_dir_env_var_with_packs_subdirectory, indistinguishable
        # on case-insensitive APFS.
        override_packs = Path(override) / "packs"  # pragma: no mutate
        return override_packs if override_packs.is_dir() else Path(override)
    for scope in ("project", "global"):
        candidate = paths.standards_packs_dir(scope)
        if _has_packs(candidate):
            return candidate
    bundled = Path(__file__).parent / "_data" / "standards" / "packs"
    if bundled.is_dir():
        return bundled
    # pragma: no mutate — "standards"/"packs" → "STANDARDS"/"PACKS" mutations
    # are Mac-survivor-only (same rationale as the override branch above);
    # killed on Linux CI by the fallback-path tests.
    return Path(__file__).parent.parent.parent / "standards" / "packs"  # pragma: no mutate


def sumo_qa_load_standards(classification: str | None = None) -> str:
    """Return the team's loaded standards as text. Optional metadata filter
    by classification — packs whose frontmatter declares any requested
    classification. Multiple classifications may be comma/space separated.
    No keyword inference; the filter is pure file-metadata selection."""
    root = _standards_dir()
    packs: list[str] = []
    pack_paths = sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml")))
    requested = _classification_filter_terms(classification)
    for path in pack_paths:
        text = path.read_text(encoding="utf-8")
        if requested is not None:
            try:
                doc = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                continue
            applies = _metadata_terms(
                doc.get("applies_to_classifications") or doc.get("classifications")
            )
            if not applies or requested.isdisjoint(applies):
                continue
        packs.append(f"# {path.name}\n\n{text}")
    return "\n\n---\n\n".join(packs)


def _rules_path() -> Path:
    override = os.environ.get("QA_RULES_PATH")
    if override:
        return Path(override)
    for scope in ("project", "global"):
        candidate = paths.rules_path(scope)
        if candidate.is_file():
            return candidate
    bundled = Path(__file__).parent / "_data" / "standards" / "rules" / "change_rules.yaml"
    if bundled.is_file():
        return bundled
    candidates = [
        Path(__file__).parent.parent.parent / "standards" / "rules" / "change_rules.yaml",
        Path(__file__).parent.parent.parent / "rules" / "change_rules.yaml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def sumo_qa_load_rules(classification: str | None = None) -> str:
    """Return the team's loaded change rules as text. Optional metadata filter
    by classification — the rules file is a dict keyed by classification, so
    filtering returns matching entries. Multiple classifications may be
    comma/space separated."""
    path = _rules_path()
    text = path.read_text(encoding="utf-8")
    requested = _classification_filter_terms(classification)
    if requested is None:
        return text
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return text
    if not isinstance(doc, dict):
        return text
    entries = {name: entry for name, entry in doc.items() if str(name) in requested}
    for term in sorted(requested):
        if term in entries:
            continue
        for alias in _RULE_CLASSIFICATION_ALIASES.get(term, ()):
            if alias in doc:
                entries[term] = doc[alias]
                break
    if not entries:
        # pragma: no mutate — equivalent: empty dict renders identically under any sort_keys value
        # (covers load_rules mutants that swap False↔None↔True or drop the kwarg)
        return yaml.safe_dump({}, sort_keys=False)  # pragma: no mutate
    # pragma: no mutate — equivalent: PyYAML treats sort_keys=None identically to False
    # (preserves insertion order); covers load_rules mutant that swaps False→None
    return yaml.safe_dump(entries, sort_keys=False)  # pragma: no mutate
