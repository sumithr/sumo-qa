# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract tests for the reviewing-before-merge root + lazy-module split
(issue #451, epic #508).

``sumo-qa-reviewing-before-merge`` is the first bundled skill that ships
``modules/*.md``: a compact routing root (``SKILL.md``) plus cold modules the
host fetches through ``sumo_qa_load_skill_context(mode="module")`` only when
the review needs them. This module pins the contracts that make the split
safe:

1. **Manifest contract** — every module id the root's routing table names
   exists on disk, every shipped module is routed from the root (no orphans),
   and the MCP manifest/module loader exposes exactly that set, byte-for-byte.
2. **Content integrity** — each load-bearing review rule that moved out of the
   root lives in exactly ONE canonical module (present there, absent from the
   root and every other module). Losing a rule, or growing a second prose
   copy, fails here.
3. **Measured budgets** — the root stays under the 3,000 global root ceiling,
   each module under the 1,500 module ceiling, and three representative
   review paths (ordinary runtime change, test/eval-only change,
   documentation/configuration change) are measured separately against the
   pre-split full-body baseline.
4. **Eval assembly** — every ``skill-reviewing-before-merge*.yaml`` promptfoo
   config assembles the root plus ONLY the modules it declares (through the
   shared ``fixtures/assemble-review-skill.js`` var), never the whole old
   body and never every module unconditionally, and sets
   ``defaultTest.options.disableVarExpansion: true`` so the ``review_modules``
   list reaches the assembler intact.
5. **Module self-containment** — every ``(pinned)`` rule keeps its body in
   the paragraph under its header, and no module points at prose "below" /
   "above" / at a root line number: cross-references name the module or root
   step that holds the rule.

Techniques: *build artifact contents verification* for the manifest/loader
parity (assert against the served slice, not the source tree alone),
*boundary value analysis* for every ceiling, *equivalence partitioning* for
the three representative paths.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from sumo_qa.skill_manifest import _approx_tokens, load_skill_context

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "sumo-qa-reviewing-before-merge"
SKILL_DIR = REPO_ROOT / "skills" / SKILL_NAME
ROOT_PATH = SKILL_DIR / "SKILL.md"
MODULES_DIR = SKILL_DIR / "modules"
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"
ASSEMBLER_REF = "file://fixtures/assemble-review-skill.js"
LEGACY_FULL_BODY_REF = f"file://../../../skills/{SKILL_NAME}/SKILL.md"

# --------------------------------------------------------------------------
# Budgets (approx tokens, chars/4 — the shared skill_manifest estimator).
# --------------------------------------------------------------------------

# The pre-split full body measured on main @ 2930a3a (73,177 bytes, 72,563
# chars -> chars/4) right before #451 landed. The representative-path savings below are measured
# against THIS number, never against a re-derived live figure — the whole
# point is to prove the split beats the body it replaced.
PRE_SPLIT_FULL_BODY_TOKENS = 18141
ROOT_TOKEN_BUDGET = 3000  # the global root ceiling (test_skill_md_token_budget.py)
MODULE_TOKEN_BUDGET = 1500  # the global module ceiling (test_skill_modules.py)
RUNTIME_PATH_SAVING_FLOOR = 0.50  # AC: >= 50% below the full-body baseline

# The three representative review paths (AC: measured separately). Each is
# the root plus the modules the routing table loads for that change shape:
# `runtime-scope` on every path (step 4 settles the diff shape with it), the
# "every runtime review" rows on the runtime path, plus the conditional module
# each shape triggers. A runtime review that ALSO carries an eval surface, a
# feature flow, and a discharged check loads ~10.4k tokens (~43% below the
# pre-split body); that heavier path is real but is not the "standard
# runtime-code review" the >=50% AC names, so it is documented, not gated.
REPRESENTATIVE_PATHS: dict[str, list[str]] = {
    "ordinary-runtime-change": [
        "runtime-scope",
        "discovery-probes",
        "coverage-ledger",
        "unproven-escalation",
    ],
    "test-eval-only-change": [
        "runtime-scope",
        "test-only-diff",
        "surface-verifier",
    ],
    "docs-config-change": [
        "runtime-scope",
        "inventory-drift",
    ],
}

# Load-bearing rules that moved OUT of the root. Each phrase must appear
# verbatim in exactly its canonical module and nowhere else (root included).
# The phrases are the pinned output-contract fragments the promptfoo seeds
# grade, so losing one is a graded-behaviour regression, not a wording nit.
LOAD_BEARING_RULES: dict[str, list[str]] = {
    "context-inputs": [
        "`probable_mapping_gap` is true",
        "`untrustworthy_evidence_fields`",
    ],
    "discovery-probes": [
        "Reordered statements in a write/persist path",
        "**Discovery → verdict (pinned).**",
        "The sweep produces 3–7 named risks",
        "**The two-pass split (pinned).**",
    ],
    "security-relevance": [
        "run the grounded security-relevance pass from `using-sumo-qa`",
        "do NOT invent a security risk",
    ],
    "external-contract": [
        "**Producer test (apply first):**",
        "**External-contract rule (pinned).**",
        "**Anti-over-discovery (pinned):**",
    ],
    "contract-and-fence-probes": [
        "a 4-tick fence wrapping a 3-tick block",
        "`Never raises` / always-returns-envelope claim is violated",
    ],
    "coverage-ledger": [
        "**Module-match rule (pinned):**",
        "forbidden hallucinated bridges",
        "**Re-anchor first.**",
        "`Risk: <exact name> | Anchor: <diff file:line> | Required test path:",
        "**2c. External-contract extension (pinned).**",
        "**2d. Internal/self-produced declination (pinned).**",
        "Retry, Duplicate, or Idempotency",
        "**Concurrent, Race, or Lock** require overlapping execution",
        "`External-contract anchor: <file:line> | External source: <tool/CLI/API>",
        "`External-contract axis: NOT FIRED (internal/self-produced)",
    ],
    "inventory-drift": [
        "**Documented-inventory drift rule (pinned).**",
        "`Inventory drift anchor: <path>:<line> (<old> → <new>) | Required update: this file",
    ],
    "unproven-escalation": [
        "**2b. UNPROVEN-escalation extension (pinned).**",
        "`UNPROVEN escalation: <risk name> | Discriminating input: <the input>",
        "`UNPROVEN deferral: <risk name> | Accepted failure mode:",
        "**Technique-keyed failure-mode hints (pinned).**",
    ],
    "acceptance-criteria": [
        "**Acceptance-criteria coverage (pinned).**",
        "`AC<n>: <criterion text> | Classification: <MET | UNMET | UNVERIFIED>",
        # Pre-split step 10(d)'s closing sentence, dropped by the split.
        "The verdict names each unmet/unverified criterion.",
    ],
    "ac-evidence-views": [
        "**Worked contrast — MET vs UNVERIFIED",
        "**AC-coverage view (same schema, no new tool).**",
    ],
    "surface-verifier": [
        "**(i) Surface-specific verifier ran (right runtime/env/scope/tree).**",
        "**Name that eval VERBATIM**",
        "`Surface verifier: <verifier",
        "**Sibling/combined-tree rule:**",
    ],
    "feature-flow": [
        "**(ii) Primary feature flow exercised end-to-end.**",
        "`Feature flow: <the realistic UI/API/CLI/worker/artifact path",
    ],
    "eval-validity": [
        "**(iii) A newly-added regression guard's eval exercises BOTH directions.**",
        "**(iv) An eval-driven skill change's A/B control is structurally load-bearing.**",
        "`Guard added: <the guard>",
        "`A/B control: <the .ab.yaml>",
    ],
    "discharged-check": [
        "**Discharged-check discipline (anti-over-fire, pinned).**",
        "**Residuals are LISTED under SAFE, never blocking, on a discharged check (pinned):**",
    ],
    "test-only-diff": [
        "**Test-only-diff probe (pinned).**",
        "`Test probe: <test name> | Discriminates broken→fixed?",
        "**Test-only-diff (test_change) discipline (pinned):**",
    ],
    "runtime-scope": [
        "**What counts as a runtime change (pinned — behaviour, not path prefix):**",
        "**Trivial-change exemption (pinned):**",
        "SKIP item 2; the verification command (linter/formatter/build) IS the coverage",
    ],
    "ledger-appendix": [
        "`| Risk | Statement | Source | Test / check | Evidence | Residual |`",
        "`uncovered_blocker_count` must be 0",
    ],
    "readiness-scorecard": [
        "`sumo_qa_format_qa_scorecard`",
        "`ready_with_accepted_residuals`",
    ],
    "feedback-memory": [
        "advisory hint from saved review feedback (trigger: <trigger_signal>)",
    ],
}

# Always-on rules that must STAY in the root: the gates every review pays for.
ROOT_ALWAYS_ON_RULES = (
    "NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE.",
    "<HARD-GATE>",
    "`Evidence (command): $ pytest tests/auth -q → 42 passed, 2 skipped`",
    # The two gate-reporting clauses the split dropped (pre-split root line 26).
    "Test names or counts alone, with no labeled source behind them, do NOT count as a cite.",
    "Keep it compact: a status word + a short source cite per line, never a second dump.",
    "`SAFE TO MERGE` | `NOT SAFE TO MERGE` | `NEEDS WORK`",
    "`No acceptance criteria supplied — AC-coverage check skipped; verdict rests on risk coverage.`",
    "`no coverage/mutation artifact this turn — not measured`",
    "`no saved review feedback supplied — advisory-hint check skipped`",
    '"I\'ll ask which test framework / where tests live"',
    "## Checklist",
    "## Process Flow",
    "## Red Flags",
)

# Every "(pinned)" rule block the pre-split body carried. Each marker must
# appear EXACTLY once across root + modules: zero = a pinned block was lost,
# two = a second prose copy crept in. Complements LOAD_BEARING_RULES (which
# pins the body text of the rules the evals grade) with block-level coverage.
PINNED_RULE_MARKERS = (
    "**2b. UNPROVEN-escalation extension (pinned).**",
    "**2c. External-contract extension (pinned).**",
    "**2d. Internal/self-produced declination (pinned).**",
    "**Acceptance-criteria coverage (pinned).**",
    "**Anti-over-discovery (pinned):**",
    "**Discharged-check discipline (anti-over-fire, pinned).**",
    "**Discovery → verdict (pinned).**",
    "**Documented-inventory drift rule (pinned).**",
    "**External-contract exception (pinned):**",
    "**External-contract rule (pinned).**",
    "**Module-match rule (pinned):**",
    "**Producer test (apply first):**",
    "**Re-anchor first.**",
    "**Residuals are LISTED under SAFE, never blocking, on a discharged check (pinned):**",
    "**Technique-keyed failure-mode hints (pinned).**",
    "**Test-only-diff (test_change) discipline (pinned):**",
    "**Test-only-diff probe (pinned).**",
    "**The two-pass split (pinned).**",
    "**Trivial-change exemption (pinned):**",
    "**Verification-evidence discipline (pinned).**",
    "**What counts as a runtime change (pinned — behaviour, not path prefix):**",
)

# One distinctive body phrase per pinned header: it must sit in the BODY of
# that header (after the marker, before the next pinned header in the same
# paragraph), not merely somewhere in the file. The header is a label, the
# body is the rule: gutting a body, or padding it with filler, fails here.
PINNED_BODY_PHRASES: dict[str, tuple[str, ...]] = {
    "**2b. UNPROVEN-escalation extension (pinned).**": (
        "`UNPROVEN escalation: <risk name> | Discriminating input: <the input>",
        "`UNPROVEN deferral: <risk name> | Accepted failure mode:",
    ),
    "**2c. External-contract extension (pinned).**": (
        "`External-contract anchor: <file:line> | External source: <tool/CLI/API>",
    ),
    "**2d. Internal/self-produced declination (pinned).**": (
        "`External-contract axis: NOT FIRED (internal/self-produced)",
    ),
    "**Acceptance-criteria coverage (pinned).**": (
        "Surfacing every supplied criterion is MANDATORY, not verdict-conditional",
    ),
    "**Anti-over-discovery (pinned):**": (
        "Do NOT then manufacture SPECULATIVE output-format-variant risks",
    ),
    "**Discharged-check discipline (anti-over-fire, pinned).**": (
        "NOT on a manufactured extra blocker",
    ),
    "**Discovery → verdict (pinned).**": (
        'Do NOT demote a discovered latent defect to a "residual concern" under a SAFE verdict',
    ),
    "**Documented-inventory drift rule (pinned).**": (
        "each path it surfaces is a separate UNCOVERED anchor that needs its own ledger row",
    ),
    "**External-contract exception (pinned):**": (
        "Its evidence is REAL captured output, never a `tests/<module>/` test",
    ),
    "**External-contract rule (pinned).**": (
        "a green matcher proves LOGIC, not that its INPUT matches reality",
    ),
    "**Module-match rule (pinned):**": ("forbidden hallucinated bridges",),
    "**Producer test (apply first):**": (
        "the axis fires ONLY when the value is produced by something the diff does NOT control",
    ),
    "**Re-anchor first.**": (
        "Without an anchor you cannot apply the module-match rule and will hallucinate coverage",
    ),
    "**Residuals are LISTED under SAFE, never blocking, on a discharged check (pinned):**": (
        "is a RESIDUAL you LIST under `SAFE TO MERGE`; it MUST NOT flip the verdict",
    ),
    "**Technique-keyed failure-mode hints (pinned).**": (
        "`unlocked` matches `locked`, `concurrency` matches `currency`",
    ),
    "**Test-only-diff (test_change) discipline (pinned):**": (
        "`Test probe: <test name> | Discriminates broken→fixed?",
    ),
    "**Test-only-diff probe (pinned).**": (
        "the expected value must be derived INDEPENDENTLY of the SUT",
    ),
    "**The two-pass split (pinned).**": (
        "it prescribes the discriminating input ITSELF (step 9 / 2b)",
    ),
    "**Trivial-change exemption (pinned):**": (
        "SKIP item 2; the verification command (linter/formatter/build) IS the coverage",
    ),
    "**Verification-evidence discipline (pinned).**": ("One discipline, four checks",),
    "**What counts as a runtime change (pinned — behaviour, not path prefix):**": (
        "Keyed on what the file *does*, NOT on `app/`/`src/`/`lib/` location",
    ),
}
# A pinned header with fewer body characters than this (up to the next pinned
# header in the same paragraph, or the paragraph end) is a label with no rule.
PINNED_BODY_MIN_CHARS = 80
# Any bold header on disk that says "(pinned" is a pinned marker; a new one
# must be added to PINNED_RULE_MARKERS and PINNED_BODY_PHRASES to be guarded.
_PINNED_HEADER_ON_DISK_RE = re.compile(r"\*\*[^*\n]*\(pinned[^*\n]*\*\*")
# The root's numbered bold items (checklist steps, verdict-format items):
# `1. **Read the diff ...**`. A module line that restarts one of THESE
# numbers+titles is a copy of the root list, not a list of its own.
_ROOT_NUMBERED_BOLD_ITEM_RE = re.compile(r"^\d+\. \*\*(.+?)\*\*", re.MULTILINE)

# Location references a module may NOT carry: after the split, "below" /
# "above" / a root line number / a copied root list number point at prose that
# is no longer in the same file. Every cross-reference names the module (or
# root step) that holds the rule instead. Literal, so a recurrence is caught
# byte-for-byte rather than by a fuzzy prose heuristic.
DANGLING_MODULE_REFERENCE_PATTERNS = (
    re.compile(r"\(below\)"),
    re.compile(r"\b(?:rule|rows?|probes?|ledger|inspection|exemption) (?:below|above)\b"),
    re.compile(r"coverage-ledger below"),
    re.compile(r"SKILL\.md:\d+"),  # a root line anchor the split invalidated
)
# (A copied root list number, `7. **AC lines ...`, is matched dynamically
# against the root's own numbered bold titles in _dangling_reference_hits, so
# a module's OWN numbered bold list is not rejected.)

# A routing-table data row: `| \`module-id\` | <load when> |`. Every data row in
# the routing-table section MUST match this strict shape; a row whose first
# cell is not a backticked kebab-case id is malformed and rejected outright
# (a host would otherwise be pointed at an id no module can have).
_ROUTING_ROW_RE = re.compile(r"^\|\s*`([a-z0-9]+(?:-[a-z0-9]+)*)`\s*\|[^\n]*\|\s*$")
_ROUTING_SECTION_RE = re.compile(
    r"^## Module routing table\n(.*?)(?=^#{2,3} )", re.MULTILINE | re.DOTALL
)


def _root_text() -> str:
    return ROOT_PATH.read_text(encoding="utf-8")


def _shipped_module_ids() -> list[str]:
    if not MODULES_DIR.is_dir():
        return []
    return sorted(p.stem for p in MODULES_DIR.glob("*.md"))


def _module_text(module_id: str) -> str:
    return (MODULES_DIR / f"{module_id}.md").read_text(encoding="utf-8")


def _routing_table_rows(root_text: str) -> list[str]:
    """Every table data row inside the routing-table section (header and
    separator rows excluded), verbatim."""
    match = _ROUTING_SECTION_RE.search(root_text)
    assert match, "the root SKILL.md has no '## Module routing table' section"
    rows = [ln for ln in match.group(1).splitlines() if ln.startswith("|")]
    return [r for r in rows if not r.startswith("| Module") and not r.startswith("|---")]


def _routing_table_ids(root_text: str) -> list[str]:
    ids: list[str] = []
    for row in _routing_table_rows(root_text):
        m = _ROUTING_ROW_RE.match(row)
        assert m, (
            f"malformed routing-table row (first cell must be a backticked kebab-case id): {row!r}"
        )
        ids.append(m.group(1))
    return ids


def _all_skill_text() -> dict[str, str]:
    """root + every module, keyed by a display name."""
    out = {"SKILL.md": _root_text()}
    for module_id in _shipped_module_ids():
        out[f"modules/{module_id}.md"] = _module_text(module_id)
    return out


def _path_tokens(module_ids: list[str]) -> tuple[int, dict[str, int], int]:
    root = _approx_tokens(_root_text())
    per_module = {m: _approx_tokens(_module_text(m)) for m in module_ids}
    return root, per_module, root + sum(per_module.values())


def _paragraph_containing(text: str, marker: str) -> str:
    """The blank-line-delimited block that carries ``marker`` (headings are
    their own blocks). Raises if the marker is absent."""
    for block in re.split(r"\n\s*\n", text):
        if marker in block:
            return block
    raise AssertionError(f"marker {marker!r} not found")


def _pinned_body(paragraph: str, marker: str) -> str:
    """The rule text that follows ``marker`` inside its paragraph, cut at the
    next pinned header (two pinned rules can share one paragraph)."""
    body = paragraph.split(marker, 1)[1]
    cut = len(body)
    for other in PINNED_RULE_MARKERS:
        if other != marker and other in body:
            cut = min(cut, body.index(other))
    return body[:cut].strip()


def _assert_pinned_body_intact(text: str, marker: str, name: str) -> None:
    """The single checker behind the per-marker test and its fault
    injection: the body after ``marker`` (cut at the next pinned header or
    the paragraph end) carries at least PINNED_BODY_MIN_CHARS of rule text,
    and every phrase mapped to the marker lives in that body."""
    paragraph = _paragraph_containing(text, marker)
    body = _pinned_body(paragraph, marker)
    assert len(body) >= PINNED_BODY_MIN_CHARS, (
        f"{name}: pinned rule {marker!r} has only {len(body)} chars of body: {body!r}"
    )
    for phrase in PINNED_BODY_PHRASES.get(marker, ()):
        assert phrase in body, (
            f"{name}: {phrase!r} is not in the body of its pinned header {marker!r}"
        )


def _root_numbered_item_titles(root_text: str) -> list[str]:
    return _ROOT_NUMBERED_BOLD_ITEM_RE.findall(root_text)


def _dangling_reference_hits(text: str, root_text: str) -> list[str]:
    """Every dangling location reference in ``text`` (module prose), as
    ``pattern at line N: match`` strings."""
    titles = _root_numbered_item_titles(root_text)
    assert titles, "the root carries no numbered bold items"
    copied_root_item = re.compile(
        r"^\d+\. \*\*(?:" + "|".join(re.escape(t) for t in titles) + r")", re.MULTILINE
    )
    hits: list[str] = []
    for pat in (*DANGLING_MODULE_REFERENCE_PATTERNS, copied_root_item):
        for m in pat.finditer(text):
            line = text[: m.start()].count("\n") + 1
            hits.append(f"{pat.pattern!r} at line {line}: {m.group(0)!r}")
    return hits


def _assert_no_dangling_references(text: str, name: str, root_text: str) -> None:
    hits = _dangling_reference_hits(text, root_text)
    assert not hits, f"{name} carries dangling location references: {hits}"


# --------------------------------------------------------------------------
# 1. Manifest contract
# --------------------------------------------------------------------------


def test_root_routing_table_names_at_least_one_module():
    ids = _routing_table_ids(_root_text())
    assert ids, "the root SKILL.md carries no module-routing table (no `| `<id>` |` rows)"
    assert len(ids) == len(set(ids)), f"duplicate routing-table ids: {ids}"


def test_every_routing_table_module_exists_on_disk():
    """A routing-table id with no ``modules/<id>.md`` is a dangling pointer the
    host would fail to load. Unknown id → FAIL."""
    missing = [
        m for m in _routing_table_ids(_root_text()) if not (MODULES_DIR / f"{m}.md").is_file()
    ]
    assert not missing, f"routing table names modules that do not exist: {missing}"


def test_every_shipped_module_is_reachable_from_the_root():
    """A ``modules/*.md`` file the routing table never names is an orphan no
    host can discover. Orphan shipped module → FAIL."""
    shipped = set(_shipped_module_ids())
    assert shipped, f"{MODULES_DIR} ships no modules"
    routed = set(_routing_table_ids(_root_text()))
    assert shipped - routed == set(), (
        f"shipped modules not routed from the root: {sorted(shipped - routed)}"
    )
    assert routed - shipped == set(), (
        f"routed ids with no shipped module: {sorted(routed - shipped)}"
    )


def test_manifest_exposes_exactly_the_shipped_modules():
    manifest = load_skill_context(SKILL_NAME, "manifest")
    assert [m["id"] for m in manifest["modules"]] == _shipped_module_ids()
    for entry in manifest["modules"]:
        assert entry["path"] == f"skills/{SKILL_NAME}/modules/{entry['id']}.md"


@pytest.mark.parametrize("module_id", _shipped_module_ids())
def test_module_slice_is_served_byte_for_byte_with_its_hash(module_id):
    """The served module slice IS the file (no rewriting), and its
    ``content_hash`` is the sha256 of exactly that slice — the change-detection
    affordance the loader advertises."""
    text = _module_text(module_id)
    out = load_skill_context(SKILL_NAME, "module", module=module_id)
    assert "error" not in out, out
    assert out["content"] == text
    assert out["content_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert out["estimated_tokens"] == _approx_tokens(text)
    unchanged = load_skill_context(
        SKILL_NAME, "module", module=module_id, known_hash=out["content_hash"]
    )
    assert unchanged["changed"] is False and "content" not in unchanged


def test_root_full_body_is_served_inline_not_as_an_oversize_pointer():
    """AC: the #393/#450 over-cap route stays compatible. The compact root is
    UNDER the cap, so ``mode="full"`` serves it byte-for-byte; the oversize
    pointer (still tested in test_skill_response_oversize.py on a synthetic
    over-cap body) is no longer what a host gets for this skill."""
    out = load_skill_context(SKILL_NAME, "full")
    assert out.get("oversize") is not True
    assert out["content"] == _root_text()


# --------------------------------------------------------------------------
# 2. Content integrity — one canonical source per moved rule
# --------------------------------------------------------------------------


def test_load_bearing_rule_map_covers_every_shipped_module():
    """Every shipped module must pin at least one load-bearing phrase, so a
    module cannot be emptied (or replaced by a stub) unnoticed."""
    assert set(LOAD_BEARING_RULES) == set(_shipped_module_ids()), (
        "LOAD_BEARING_RULES is out of step with modules/: "
        f"missing={sorted(set(_shipped_module_ids()) - set(LOAD_BEARING_RULES))} "
        f"stale={sorted(set(LOAD_BEARING_RULES) - set(_shipped_module_ids()))}"
    )


@pytest.mark.parametrize(
    ("module_id", "phrase"),
    [(m, p) for m, phrases in LOAD_BEARING_RULES.items() for p in phrases],
    ids=lambda v: v if v in LOAD_BEARING_RULES else v[:40],
)
def test_load_bearing_rule_lives_only_in_its_canonical_module(module_id, phrase):
    """Loss of a named load-bearing rule → FAIL (absent from its module). A
    second prose copy in the root or another module → FAIL (the issue's
    one-canonical-source decision)."""
    assert phrase in _module_text(module_id), (
        f"load-bearing rule missing from modules/{module_id}.md: {phrase!r}"
    )
    assert phrase not in _root_text(), (
        f"rule duplicated in the root SKILL.md (must live only in modules/{module_id}.md): {phrase!r}"
    )
    for other in _shipped_module_ids():
        if other == module_id:
            continue
        assert phrase not in _module_text(other), (
            f"rule duplicated in modules/{other}.md (canonical source is modules/{module_id}.md): {phrase!r}"
        )


@pytest.mark.parametrize("marker", PINNED_RULE_MARKERS)
def test_pinned_rule_block_appears_exactly_once_across_root_and_modules(marker):
    """Block-level integrity: every pinned rule the pre-split body carried
    survives in exactly one place. Deleting a pinned block (0 hits) or
    restating it (2+ hits) fails here even if no LOAD_BEARING_RULES phrase
    was touched."""
    hits = {name: text.count(marker) for name, text in _all_skill_text().items() if marker in text}
    total = sum(hits.values())
    assert total == 1, f"pinned rule marker {marker!r} appears {total} times: {hits or 'nowhere'}"


@pytest.mark.parametrize("marker", PINNED_RULE_MARKERS)
def test_pinned_rule_keeps_its_body_in_the_same_paragraph(marker):
    """A ``(pinned)`` header with its rule body gutted (label kept, prose
    removed, or replaced by filler) must fail: the body after the marker, up
    to the next pinned header or the paragraph end, carries the rule AND the
    distinctive phrase mapped to that header."""
    for name, text in _all_skill_text().items():
        if marker in text:
            _assert_pinned_body_intact(text, marker, name)


def test_pinned_body_phrase_map_covers_every_pinned_marker():
    """Every pinned marker maps to at least one distinctive body phrase (so
    80 chars of filler cannot satisfy the body check), and every "(pinned"
    header on disk is a known marker, so a new pinned rule without a mapped
    phrase goes red here."""
    assert set(PINNED_BODY_PHRASES) == set(PINNED_RULE_MARKERS), (
        f"unmapped pinned markers: {sorted(set(PINNED_RULE_MARKERS) - set(PINNED_BODY_PHRASES))}; "
        f"stale keys: {sorted(set(PINNED_BODY_PHRASES) - set(PINNED_RULE_MARKERS))}"
    )
    for marker, phrases in PINNED_BODY_PHRASES.items():
        assert phrases, f"{marker!r} maps to no phrase"
    on_disk = {
        m for text in _all_skill_text().values() for m in _PINNED_HEADER_ON_DISK_RE.findall(text)
    }
    assert on_disk <= set(PINNED_RULE_MARKERS), (
        f"pinned headers on disk that PINNED_RULE_MARKERS does not guard: "
        f"{sorted(on_disk - set(PINNED_RULE_MARKERS))}"
    )


def test_pinned_body_check_rejects_a_gutted_rule():
    """Fault injection through the REAL checker: gut the Module-match body
    (header kept, so the exactly-once marker count stays green), then replace
    it with filler that keeps the mapped phrase elsewhere in the paragraph;
    both must raise."""
    marker = "**Module-match rule (pinned):**"
    neighbour = "**External-contract exception (pinned):**"
    text = _module_text("coverage-ledger")
    _assert_pinned_body_intact(text, marker, "healthy")
    paragraph = _paragraph_containing(text, marker)
    tail = paragraph.split(neighbour, 1)[1]
    gutted = text.replace(paragraph, f"{marker} see the ledger. {neighbour}{tail}")
    assert gutted.count(marker) == 1
    with pytest.raises(AssertionError, match="has only 15 chars of body"):
        _assert_pinned_body_intact(gutted, marker, "gutted")
    filler = "lorem ipsum " * 12  # > PINNED_BODY_MIN_CHARS, carries no rule
    phrase = PINNED_BODY_PHRASES[marker][0]
    displaced = text.replace(paragraph, f"{marker} {filler}{neighbour} {phrase}{tail}")
    with pytest.raises(AssertionError, match="is not in the body of its pinned header"):
        _assert_pinned_body_intact(displaced, marker, "displaced")


@pytest.mark.parametrize("module_id", _shipped_module_ids())
def test_module_carries_no_dangling_location_reference(module_id):
    """Module self-containment: a module never points at prose "below" /
    "above" / at a root line number / with a copied root list number. Every
    cross-module rule reference names the module (or root step) that holds
    it (and says to load it when the rule is load-bearing for this check)."""
    _assert_no_dangling_references(_module_text(module_id), f"modules/{module_id}.md", _root_text())


def test_dangling_reference_check_distinguishes_root_list_numbers_from_module_lists():
    """Fault injection through the REAL checker: a module's OWN numbered bold
    list passes; a line that restarts one of the root's numbered items (its
    number + bold title) fails; a bare "(below)" fails."""
    root = _root_text()
    titles = _root_numbered_item_titles(root)
    assert "AC lines" in titles and "Read the diff via the host's git tools" in titles, titles
    _assert_no_dangling_references(
        "3. **Some legitimate bold heading** body text\n", "own-list", root
    )
    with pytest.raises(AssertionError, match="dangling location references"):
        _assert_no_dangling_references(
            "7. **AC lines** when criteria were supplied\n", "copied", root
        )
    with pytest.raises(AssertionError, match="dangling location references"):
        _assert_no_dangling_references("see the 2a row (below).\n", "below", root)


def test_routing_table_rejects_malformed_rows():
    """A routing row whose first cell is not a backticked kebab-case id is a
    dangling pointer the loose regex used to skip silently; the strict parser
    must reject it."""
    root = _root_text()
    sep = "|---|---|\n"
    assert sep in root
    bad = root.replace(sep, sep + "| `missing_module` | every review |\n", 1)
    with pytest.raises(AssertionError, match="malformed routing-table row"):
        _routing_table_ids(bad)
    # A well-formed row elsewhere in the file is NOT a routing row (the parser
    # is section-scoped), so appending one after the table changes nothing.
    assert _routing_table_ids(root + "| `not-routed` | never |\n") == _routing_table_ids(root)


@pytest.mark.parametrize("phrase", ROOT_ALWAYS_ON_RULES)
def test_always_on_rule_stays_in_the_root(phrase):
    assert phrase in _root_text(), f"always-on rule missing from the root SKILL.md: {phrase!r}"


def test_root_points_every_routed_module_at_the_loader():
    """The root must tell a host HOW to fetch a module, not just name it."""
    root = _root_text()
    assert "sumo_qa_load_skill_context" in root
    assert 'mode="module"' in root or "mode='module'" in root


# --------------------------------------------------------------------------
# 3. Measured budgets
# --------------------------------------------------------------------------


def test_root_stays_under_the_global_root_ceiling():
    tokens = _approx_tokens(_root_text())
    assert tokens <= ROOT_TOKEN_BUDGET, (
        f"root SKILL.md is ~{tokens} tokens (>{ROOT_TOKEN_BUDGET}); move deep rules into a module"
    )


@pytest.mark.parametrize("module_id", _shipped_module_ids())
def test_each_module_stays_under_the_module_ceiling(module_id):
    tokens = _approx_tokens(_module_text(module_id))
    assert tokens <= MODULE_TOKEN_BUDGET, (
        f"modules/{module_id}.md is ~{tokens} tokens (>{MODULE_TOKEN_BUDGET}); split it"
    )


def test_representative_paths_name_only_shipped_modules():
    shipped = set(_shipped_module_ids())
    for path_name, ids in REPRESENTATIVE_PATHS.items():
        unknown = [m for m in ids if m not in shipped]
        assert not unknown, f"{path_name} names unknown modules {unknown}"
        assert len(ids) == len(set(ids)), f"{path_name} repeats a module"


# The conditional module each representative path exists to exercise, and the
# routing-table phrase that obligates it. Pinning both ties the measured path
# to the table: dropping the module from the path OR rewording the row away
# from its trigger fails here.
PATH_CONDITIONAL_OBLIGATIONS: dict[str, dict[str, str]] = {
    "ordinary-runtime-change": {"unproven-escalation": "any risk is UNPROVEN"},
    "test-eval-only-change": {
        "test-only-diff": "the diff touches only test files",
        "surface-verifier": "ALWAYS for a skill or eval change",
    },
    "docs-config-change": {"inventory-drift": "generated artifact changed"},
}


def test_representative_paths_carry_their_conditional_modules():
    """Each representative path loads the conditional module its change shape
    triggers, and the routing row for that module still states the trigger."""
    rows = {_ROUTING_ROW_RE.match(r).group(1): r for r in _routing_table_rows(_root_text())}
    for path_name, obligations in PATH_CONDITIONAL_OBLIGATIONS.items():
        for module_id, trigger in obligations.items():
            assert module_id in REPRESENTATIVE_PATHS[path_name], (
                f"{path_name} must load {module_id} (routing trigger: {trigger!r})"
            )
            assert trigger in rows[module_id], (
                f"routing row for {module_id} no longer states its trigger {trigger!r}: {rows[module_id]!r}"
            )


def test_representative_paths_honour_the_routing_obligations():
    """The path lists are tied to what the root actually routes: every path
    loads `runtime-scope` (step 4 settles the diff shape with it), and the
    ordinary runtime path loads every module whose routing row says it applies
    to every runtime review."""
    rows = _routing_table_rows(_root_text())
    always_runtime = {
        _ROUTING_ROW_RE.match(r).group(1) for r in rows if "every runtime review" in r
    }
    assert always_runtime, "no routing row is marked for every runtime review"
    for path_name, ids in REPRESENTATIVE_PATHS.items():
        assert "runtime-scope" in ids, f"{path_name} must settle the diff shape with runtime-scope"
    missing = sorted(always_runtime - set(REPRESENTATIVE_PATHS["ordinary-runtime-change"]))
    assert not missing, f"ordinary runtime path omits always-on runtime modules {missing}"


def test_ordinary_runtime_review_path_is_at_least_half_the_pre_split_body():
    """AC: a standard runtime-code review (root + its required modules) loads
    at least 50% below the pre-split full-body baseline."""
    root, per_module, total = _path_tokens(REPRESENTATIVE_PATHS["ordinary-runtime-change"])
    saving = (PRE_SPLIT_FULL_BODY_TOKENS - total) / PRE_SPLIT_FULL_BODY_TOKENS
    assert saving >= RUNTIME_PATH_SAVING_FLOOR, (
        f"ordinary runtime review loads ~{total} tokens (root {root} + {per_module}) vs the "
        f"pre-split ~{PRE_SPLIT_FULL_BODY_TOKENS}: only {saving:.0%} below (floor "
        f"{RUNTIME_PATH_SAVING_FLOOR:.0%})"
    )


@pytest.mark.parametrize("path_name", sorted(REPRESENTATIVE_PATHS))
def test_every_representative_path_is_lighter_than_the_pre_split_body(path_name):
    """Each of the three representative paths is measured separately and must
    beat the pre-split body; the exact figures are reported in the failure
    message (and via ``python -m pytest -k representative -rA`` for the PR)."""
    root, per_module, total = _path_tokens(REPRESENTATIVE_PATHS[path_name])
    saving = (PRE_SPLIT_FULL_BODY_TOKENS - total) / PRE_SPLIT_FULL_BODY_TOKENS
    assert total < PRE_SPLIT_FULL_BODY_TOKENS, (
        f"{path_name}: root {root} + modules {per_module} = {total} "
        f"(not below {PRE_SPLIT_FULL_BODY_TOKENS})"
    )
    assert saving >= RUNTIME_PATH_SAVING_FLOOR, (
        f"{path_name}: root {root} + modules {per_module} = {total} tokens, {saving:.0%} below "
        f"the pre-split body (floor {RUNTIME_PATH_SAVING_FLOOR:.0%})"
    )


def test_all_modules_together_are_not_the_ordinary_path():
    """Guard the routing intent: the ordinary runtime path must not quietly
    grow into 'load everything'."""
    ordinary = set(REPRESENTATIVE_PATHS["ordinary-runtime-change"])
    assert ordinary < set(_shipped_module_ids())


# --------------------------------------------------------------------------
# 4. Eval assembly — root + declared modules only
# --------------------------------------------------------------------------

REVIEW_EVAL_CONFIGS = sorted(
    PROMPTFOO_DIR.glob(f"skill-{SKILL_NAME.removeprefix('sumo-qa-')}*.yaml")
)


def _declared_module_sets(config: dict) -> list[list[str]]:
    """Every effective ``review_modules`` declaration a seed can resolve to:
    the seed's own override, else the defaultTest default."""
    default_vars = (config.get("defaultTest") or {}).get("vars") or {}
    default = default_vars.get("review_modules")
    sets: list[list[str]] = []
    for test in config.get("tests") or []:
        seed_vars = test.get("vars") or {}
        declared = seed_vars.get("review_modules", default)
        assert declared is not None, (
            f"seed {test.get('description')!r} has no review_modules declaration"
        )
        assert isinstance(declared, list), f"review_modules must be a list, got {declared!r}"
        sets.append(declared)
    return sets


def test_review_eval_matrix_is_non_empty():
    assert len(REVIEW_EVAL_CONFIGS) >= 20, [p.name for p in REVIEW_EVAL_CONFIGS]


@pytest.mark.parametrize("config_path", REVIEW_EVAL_CONFIGS, ids=lambda p: p.name)
def test_review_eval_assembles_root_plus_declared_modules_only(config_path):
    """Each config loads the live skill through the shared assembler (never the
    legacy whole-body ``file://`` var), declares a module set for every seed,
    names only shipped modules, and never loads every module unconditionally.
    The frozen ``fixtures/*-PRE-*.SKILL.md`` A0 bodies of the ``.ab.yaml``
    controls are untouched by design."""
    raw = config_path.read_text(encoding="utf-8")
    assert LEGACY_FULL_BODY_REF not in raw, (
        f"{config_path.name} still loads the whole SKILL.md body; route it through {ASSEMBLER_REF}"
    )
    config = yaml.safe_load(raw)
    default_vars = (config.get("defaultTest") or {}).get("vars") or {}
    seed_vars = [t.get("vars") or {} for t in config.get("tests") or []]
    live_keys = ("skill_content", "skill_content_new")
    live_refs = [v.get(k) for v in [default_vars, *seed_vars] for k in live_keys if k in v]
    assert live_refs, f"{config_path.name} declares no skill_content / skill_content_new var"
    assert all(ref == ASSEMBLER_REF for ref in live_refs), f"{config_path.name}: {live_refs}"
    shipped = set(_shipped_module_ids())
    for declared in _declared_module_sets(config):
        unknown = sorted(set(declared) - shipped)
        assert not unknown, f"{config_path.name} declares unknown modules {unknown}"
        assert set(declared) != shipped, f"{config_path.name} loads every module unconditionally"


def _assert_var_expansion_disabled(config: dict, name: str) -> None:
    """``review_modules`` is a LIST var. promptfoo expands an array-valued var
    into one test case per element unless ``disableVarExpansion`` is set, so
    the assembler would receive a bare string (and throw) or grade a
    one-module slice per row. The option must be set per config, under
    ``defaultTest.options``, whenever ``review_modules`` is declared."""
    default_test = config.get("defaultTest") or {}
    declares = "review_modules" in (default_test.get("vars") or {}) or any(
        "review_modules" in (t.get("vars") or {}) for t in config.get("tests") or []
    )
    if not declares:
        return
    options = default_test.get("options") or {}
    assert options.get("disableVarExpansion") is True, (
        f"{name} declares review_modules (a list) but does not set "
        "defaultTest.options.disableVarExpansion: true; promptfoo would expand the list "
        "into per-module test cases and the assembler would grade the wrong slice"
    )


@pytest.mark.parametrize("config_path", REVIEW_EVAL_CONFIGS, ids=lambda p: p.name)
def test_review_eval_declaring_modules_disables_var_expansion(config_path):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    _assert_var_expansion_disabled(config, config_path.name)


def test_var_expansion_check_rejects_a_config_that_drops_the_option():
    """Fault injection on a parsed config: removing the option (or moving it
    to the top level only) must be rejected; a config with no
    review_modules declaration is out of scope."""
    config = yaml.safe_load(REVIEW_EVAL_CONFIGS[0].read_text(encoding="utf-8"))
    _assert_var_expansion_disabled(config, "healthy")
    dropped = json.loads(json.dumps(config))
    del dropped["defaultTest"]["options"]["disableVarExpansion"]
    dropped["disableVarExpansion"] = True  # top-level only: not the per-test option
    with pytest.raises(AssertionError, match="disableVarExpansion"):
        _assert_var_expansion_disabled(dropped, "dropped")
    root_only = {"defaultTest": {"vars": {"skill_content": ASSEMBLER_REF}}, "tests": []}
    _assert_var_expansion_disabled(root_only, "no-declaration")


def test_every_module_is_exercised_by_at_least_one_review_eval():
    """A module no eval ever loads has no graded behaviour behind it."""
    used: set[str] = set()
    for config_path in REVIEW_EVAL_CONFIGS:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        for declared in _declared_module_sets(config):
            used.update(declared)
    unused = sorted(set(_shipped_module_ids()) - used)
    assert not unused, f"modules no reviewing-before-merge eval loads: {unused}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)")
def test_assembler_executes_root_plus_declared_modules_in_order():
    """Run the real assembler under node: the output is the root, then ONLY
    the declared modules, verbatim and in declared order; an unknown id
    throws instead of silently returning a wrong slice."""
    ids = list(reversed(_shipped_module_ids()[:2]))  # deliberately NOT sorted
    assert ids != sorted(ids)
    script = (
        "const a = require(process.argv[1]);"
        "process.stdout.write(JSON.stringify({"
        "  out: a.assemble(process.argv.slice(2)),"
        "  err: (() => { try { a.assemble(['nope-module']); return null; } catch (e) { return String(e.message); } })(),"
        "}));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(PROMPTFOO_DIR / "fixtures" / "assemble-review-skill.js"), *ids],
        capture_output=True,
        encoding="utf-8",  # node emits UTF-8; never the Windows locale codepage
        check=True,
    )
    payload = json.loads(proc.stdout)
    # The assembler normalises CRLF to LF, so a Windows autocrlf checkout
    # assembles the same bytes Python's read_text() sees here.
    out = payload["out"]
    assert "\r" not in out, "assembler must emit LF-only text regardless of checkout line endings"
    assert out.startswith(_root_text().rstrip())
    for module_id in ids:
        assert _module_text(module_id).rstrip() in out
    positions = [out.index(f"--- MODULE {m} ---") for m in ids]
    assert positions == sorted(positions), "modules not emitted in declared order"
    for other in _shipped_module_ids():
        if other not in ids:
            assert f"--- MODULE {other} ---" not in out, f"undeclared module {other} was loaded"
    assert payload["err"] and "unknown module id" in payload["err"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH (the promptfoo runtime)")
def test_assembler_normalises_injected_crlf_to_lf(tmp_path):
    """Assemble a synthetic skill whose root AND module are CRLF files (what a
    Windows autocrlf checkout produces) through the SAME `assemble` path the
    evals use, and require LF-only output equal to the LF form. The real
    checkout files carry no CR bytes, so only injected input proves it."""
    skill_dir = tmp_path / "sumo-qa-fake"
    (skill_dir / "modules").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"# Root\r\n\r\nalways-on rule\r\n")
    (skill_dir / "modules" / "alpha.md").write_bytes(b"# Alpha\r\n\r\nmodule rule\r\n")
    script = (
        "const a = require(process.argv[1]);"
        "process.stdout.write(JSON.stringify(a.assemble(['alpha'], process.argv[2])));"
    )
    proc = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(PROMPTFOO_DIR / "fixtures" / "assemble-review-skill.js"),
            str(skill_dir),
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out == (
        "# Root\n\nalways-on rule\n"
        '\n--- LOADED MODULES (fetched via sumo_qa_load_skill_context mode="module") ---\n\n'
        "--- MODULE alpha ---\n# Alpha\n\nmodule rule\n--- END MODULE alpha ---\n"
    )


def test_assembler_reads_the_shipped_modules_not_a_mirror():
    """The JS assembler resolves modules from ``skills/.../modules/`` — no
    generated mirror of module prose anywhere under tests/evals."""
    source = (PROMPTFOO_DIR / "fixtures" / "assemble-review-skill.js").read_text(encoding="utf-8")
    assert "'skills', 'sumo-qa-reviewing-before-merge'" in source
    assert "modules" in source
    mirrors = sorted(p for p in PROMPTFOO_DIR.rglob("*.md") if "modules" in p.parts)
    assert not mirrors, f"module prose mirrored under tests/evals: {mirrors}"
