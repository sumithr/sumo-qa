# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Explicit, user-confirmed review-feedback memory.

A low-friction way for a team to PROMOTE a recurring QA review finding (e.g.
"we always miss timezone boundaries in billing") into a local, inspectable,
reversible memory that future planning / review skills can consult as an
ADVISORY hint. It is deliberately NOT automatic learning:

- Nothing is persisted unless the caller supplies the full structured entry —
  there is no auto-capture from every review, prompt, or tool trace. The MCP
  tool / CLI is the only writer, and the host skill gates every write behind an
  explicit user confirmation.
- Each entry carries the five fields #145 requires: ``scope`` (where the lesson
  applies), ``trigger_signal`` (the change shape that should surface it),
  ``recommended_probe`` (the QA check to run), ``source_note`` (a user-written
  summary of where the lesson came from), and ``last_reviewed`` (an ISO-8601
  timestamp, defaulted to now when the caller omits it).
- Sensitive input is REJECTED, never silently stored: a free-text field that
  looks like a raw diff hunk, a source-code snippet, a secret/credential, or a
  pasted full issue/PR body fails validation and nothing is written. Only the
  user's own summary survives — raw code/diff/secret capture is out of scope.

Storage reuses the #92 user-writable pack location (``project`` =
``<cwd>/.sumo-qa``, ``global`` = the user data dir) under a ``feedback/``
subdir, so it is NOT a second hidden tree and NOT one of the bundled
knowledge/standards/rules tiers — which is what keeps it advisory: a
memory-derived probe is cited separately from canonical ISTQB/rules content and
never overrides a classification or change-rule (that authority belongs only to
a custom pack installed through #92's ingest path).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from sumo_qa import paths

# The five required fields every captured item carries (#145 AC).
REQUIRED_FIELDS = (
    "scope",
    "trigger_signal",
    "recommended_probe",
    "source_note",
    "last_reviewed",
)
# Valid writer/reader actions exposed by the MCP tool. Single source of truth so
# the tool's dispatch and its unknown-action error message stay in sync. (The
# free-text fields scanned for sensitive content are exactly REQUIRED_FIELDS
# minus ``last_reviewed``, which is a timestamp validated separately.)
ACTIONS = ("capture", "update", "delete", "list")

# Markers that betray a raw code/diff/secret/full-body paste rather than a
# user-written summary. The point is a deterministic guard the user can reason
# about — not a perfect classifier — so it errs toward rejecting the obvious
# raw-content shapes #145 names. A genuine prose lesson ("we miss the GBP->USD
# rounding boundary in billing") trips none of these.
_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Unified-diff hunk header / file markers (`@@ -1,3 +1,4 @@`, `diff --git`,
    # `+++ b/file`). A pasted diff, not a summary.
    (
        "a raw diff hunk",
        re.compile(r"^@@ .* @@|^diff --git |^[-+]{3} [ab]/", re.MULTILINE),
    ),
    # PEM / private-key / token blocks and common secret-assignment shapes.
    (
        "a secret or credential",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r"|\b(?:api[_-]?key|secret|password|passwd|token|bearer)\b\s*[:=]\s*\S",
            re.IGNORECASE,
        ),
    ),
    # BARE secret/credential VALUES — a pasted token with no `key=` framing. The
    # assignment shape above only fires on `secret=…`; a user who pastes the
    # value alone ("the leaked key was AKIA…") must still be rejected, since the
    # docstring promises a secret/credential fails validation and #145 AC bars
    # raw-secret persistence. Each prefix/shape is high-signal enough that an
    # ordinary prose lesson never collides with it.
    (
        "a bare AWS access key id",
        # AKIA/ASIA + 16 base32-ish chars (the documented access-key-id shape).
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "a bare GitHub token",
        # ghp_/gho_/ghs_/ghu_/ghr_ + base62 body (personal/OAuth/server/user/refresh).
        re.compile(r"\bgh[posur]_[0-9A-Za-z]{20,}\b"),
    ),
    (
        "a bare Slack token",
        # xoxb-/xoxp-/xoxo-/xoxa-/xoxs- + dash-separated digit/secret segments.
        re.compile(r"\bxox[bpoas]-[0-9A-Za-z-]{10,}\b"),
    ),
    (
        "a bare JWT",
        # Three base64url segments, the first a `eyJ…` (a base64 `{"` header).
        re.compile(r"\beyJ[0-9A-Za-z_-]{6,}\.[0-9A-Za-z_-]{6,}\.[0-9A-Za-z_-]{6,}\b"),
    ),
    (
        "an email address",
        # PII: a bare email. A user's lesson summary needs no literal address.
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "a credit-card-shaped number",
        # PII: 13-16 digits, optionally split in 4s by spaces/dashes. A 4-7 digit
        # invoice/year run (e.g. "off-by-one in Q1 2026") is too short to trip it.
        re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    ),
    # Source-code snippet tells: a fenced code block, or multiple lines that
    # read as code rather than prose (def/class/import/function/{}). A lone
    # trailing semicolon is NOT enough — ordinary prose can end in ';' — so the
    # statement-terminator tell requires a code-shaped line (an assignment, a
    # call, a brace/bracket) BEFORE the ';', or two or more such lines.
    (
        "a source-code snippet",
        re.compile(
            r"```"
            r"|^\s*(?:def |class |import |from \S+ import |function |public |private )"
            r"|^.*[\w\])][ \t]*[=(){}\[\]].*;[ \t]*$",
            re.MULTILINE,
        ),
    ),
)
# A bare 40-char base64 token is the AWS secret-access-key shape. It can't sit
# in the pattern table because rejecting it needs an entropy check the regex
# can't express cheaply: an exact-length 40-char [A-Za-z0-9/+] run is matched
# here, then `_looks_like_aws_secret` confirms it mixes case AND a digit so a
# 40-letter English run (improbable, but possible) can never trip it. (The
# AKIA/ASIA access-key-id, by contrast, has a fixed prefix and lives in the
# table above.)
_AWS_SECRET_TOKEN = re.compile(r"(?<![0-9A-Za-z/+])[0-9A-Za-z/+]{40}(?![0-9A-Za-z/+])")


def _looks_like_aws_secret(value: str) -> bool:
    """True when ``value`` carries a bare 40-char high-entropy base64 token."""
    for tok in _AWS_SECRET_TOKEN.findall(value):
        if (
            any(c.islower() for c in tok)
            and any(c.isupper() for c in tok)
            and any(c.isdigit() for c in tok)
        ):
            return True
    return False


# A full issue/PR body is long, multi-paragraph, and usually carries markdown
# headings — a summary is one or two sentences. Reject a field that is both very
# long AND multi-line with heading/checkbox structure.
_FULL_BODY_CHARS = 600
_FULL_BODY_STRUCTURE = re.compile(r"^#{1,6} |^\s*[-*] \[[ xX]\]", re.MULTILINE)


class FeedbackValidationError(ValueError):
    """Raised when a feedback entry fails validation. Nothing is written."""


def _now_iso() -> str:
    """Current UTC time as a second-precision ISO-8601 string with ``Z``."""
    return (
        dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _slugify(text: str) -> str:
    """Stable kebab id from a trigger signal (first words). Deterministic."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    # Keep ids short and human-scannable; the leading words of the trigger are
    # the discriminating part. Empty -> "entry" so an id always exists.
    return "-".join(slug.split("-")[:8]) or "entry"


# Zero-width / invisible code points a fragmented credential can hide in
# (ZWSP, ZWNJ, ZWJ, word-joiner, BOM). Stripped before scanning so a token
# split by an invisible joiner ("ghp_<ZWJ>AAAA…") cannot evade a contiguous-run
# pattern.
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


def _check_not_sensitive(field: str, value: str) -> None:
    """Reject a free-text field that looks like raw code/diff/secret/full body."""
    # NFKC-fold Unicode look-alikes and strip zero-width / invisible chars before
    # scanning so a credential cannot evade the contiguous-run patterns by hiding
    # behind confusable characters or invisible joiners. This strictly strengthens
    # the scan (anything that matched the raw value still matches) and preserves
    # line structure, so the diff/code/full-body patterns are unaffected. A token
    # a user deliberately splits with real whitespace ("ghp_ AAAA BBBB") is a known
    # residual — a best-effort guard, not a perfect classifier.
    scan = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", value))
    for label, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(scan):
            raise FeedbackValidationError(
                f"{field!r} looks like {label}; feedback memory stores only your "
                f"own short summary of the lesson, never raw code, diffs, secrets, "
                f"or pasted issue/PR bodies. Re-phrase it as a one-line summary."
            )
    if _looks_like_aws_secret(scan):
        raise FeedbackValidationError(
            f"{field!r} looks like a bare AWS secret access key; feedback memory "
            f"stores only your own short summary of the lesson, never raw code, "
            f"diffs, secrets, or pasted issue/PR bodies. Re-phrase it as a one-line "
            f"summary."
        )
    if len(value) >= _FULL_BODY_CHARS and _FULL_BODY_STRUCTURE.search(value):
        raise FeedbackValidationError(
            f"{field!r} reads like a pasted full issue/PR body ({len(value)} chars "
            f"with heading/checkbox structure); summarise the lesson in a sentence "
            f"or two instead."
        )


def _validate_entry(entry: Any) -> dict[str, str]:
    """Validate a raw entry mapping and return the normalised stored record.

    Raises ``FeedbackValidationError`` (writing nothing) when a required field is
    missing/blank, an unknown field is present, the timestamp is malformed, or a
    free-text field carries sensitive content.
    """
    if not isinstance(entry, dict):
        raise FeedbackValidationError(
            f"entry must be a mapping of the fields {list(REQUIRED_FIELDS)}, got "
            f"{type(entry).__name__}"
        )
    # An ``id`` is allowed (used by update/delete to target a row) but never
    # required from the user — capture derives it from the trigger signal.
    unknown = set(entry) - set(REQUIRED_FIELDS) - {"id"}
    if unknown:
        raise FeedbackValidationError(
            f"unknown field(s) {sorted(unknown)}; allowed fields are "
            f"{list(REQUIRED_FIELDS)} (plus an optional 'id')"
        )
    record: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        if field == "last_reviewed":
            continue  # filled below, defaulting to now
        raw = entry.get(field)
        if raw is None or not str(raw).strip():
            raise FeedbackValidationError(
                f"missing required field {field!r}; every captured item needs "
                f"scope, trigger_signal, recommended_probe, and source_note"
            )
        value = str(raw).strip()
        _check_not_sensitive(field, value)
        record[field] = value
    record["last_reviewed"] = _normalise_timestamp(entry.get("last_reviewed"))
    return record


def _normalise_timestamp(raw: Any) -> str:
    """Return a validated ISO-8601 timestamp; default to now when omitted."""
    if raw is None or not str(raw).strip():
        return _now_iso()
    text = str(raw).strip()
    try:
        # Accept a trailing ``Z`` (datetime.fromisoformat rejects it before 3.11
        # in some forms) by normalising to +00:00 for the parse check.
        dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeedbackValidationError(
            f"last_reviewed {text!r} is not an ISO-8601 timestamp "
            f"(e.g. '2026-06-04T09:00:00Z'): {exc}"
        ) from exc
    return text


def _read_entries(scope: str) -> list[dict[str, str]]:
    """Load the stored entries for ``scope`` (empty list when absent/empty)."""
    path = paths.feedback_memory_path(scope)
    if not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not doc:
        return []
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        raise FeedbackValidationError(
            f"{path} is malformed: expected a top-level mapping with an 'entries' "
            f"list. Inspect or delete the file and re-capture."
        )
    return [e for e in entries if isinstance(e, dict)]


def _write_entries(scope: str, entries: list[dict[str, str]]) -> Path:
    """Atomically write ``entries`` for ``scope`` and return the file path."""
    path = paths.feedback_memory_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump({"entries": entries}, sort_keys=False, allow_unicode=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def _require_scope(scope: str) -> None:
    if scope not in paths.SCOPES:
        raise FeedbackValidationError(f"unknown scope {scope!r}; expected one of {paths.SCOPES}")


def capture_feedback(entry: dict[str, Any], scope: str = "project") -> dict[str, Any]:
    """Add a new feedback entry (or replace one with the same id) at ``scope``.

    The caller MUST supply the structured entry — this never infers a lesson
    from a trace. Returns a report dict; raises ``FeedbackValidationError`` on a
    missing field, an unknown field, a bad timestamp, or sensitive content.
    """
    _require_scope(scope)
    record = _validate_entry(entry)
    explicit_id = str(entry.get("id") or "").strip()
    record_id = explicit_id or _slugify(record["trigger_signal"])
    record = {"id": record_id, **record}
    entries = _read_entries(scope)
    existing = next((i for i, e in enumerate(entries) if e.get("id") == record_id), None)
    action = "captured"
    if existing is not None and explicit_id:
        # Replace-in-place is the UPDATE path: only an explicitly-supplied id that
        # matches an existing row overwrites it (the caller is targeting that row).
        entries[existing] = record
        action = "updated"
    else:
        if existing is not None:
            # A GENERATED id collided with an existing entry — two DISTINCT lessons
            # whose trigger signals slugify to the same first-8-words id. Without
            # this branch the capture would silently overwrite the earlier lesson
            # (data loss). Disambiguate so the new lesson is appended, not lost.
            record_id = _unique_id(record_id, entries)
            record["id"] = record_id
        entries.append(record)
    path = _write_entries(scope, entries)
    return {
        "status": action,
        "scope": scope,
        "id": record_id,
        "destination": str(path),
        "entry": record,
        "advisory": True,
    }


def _unique_id(base: str, entries: list[dict[str, str]]) -> str:
    existing = {e.get("id") for e in entries}
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def update_feedback(entry_id: str, entry: dict[str, Any], scope: str = "project") -> dict[str, Any]:
    """Replace the fields of an existing entry by id. Raises if the id is absent."""
    _require_scope(scope)
    entries = _read_entries(scope)
    idx = next((i for i, e in enumerate(entries) if e.get("id") == entry_id), None)
    if idx is None:
        raise FeedbackValidationError(
            f"no feedback entry with id {entry_id!r} at scope {scope!r}; "
            f"list the entries first to find the right id"
        )
    record = _validate_entry(entry)
    record = {"id": entry_id, **record}
    entries[idx] = record
    path = _write_entries(scope, entries)
    return {
        "status": "updated",
        "scope": scope,
        "id": entry_id,
        "destination": str(path),
        "entry": record,
        "advisory": True,
    }


def delete_feedback(entry_id: str, scope: str = "project") -> dict[str, Any]:
    """Remove an entry by id. Raises if the id is absent (nothing to delete)."""
    _require_scope(scope)
    entries = _read_entries(scope)
    remaining = [e for e in entries if e.get("id") != entry_id]
    if len(remaining) == len(entries):
        raise FeedbackValidationError(
            f"no feedback entry with id {entry_id!r} at scope {scope!r}; nothing deleted"
        )
    path = _write_entries(scope, remaining)
    return {
        "status": "deleted",
        "scope": scope,
        "id": entry_id,
        "destination": str(path),
        "remaining": len(remaining),
    }


def list_feedback(scope: str | None = None) -> dict[str, Any]:
    """List stored entries, advisory-flagged and tagged by scope.

    ``scope=None`` merges project + global (project listed first), so a planning
    or review skill can consult both at once. Each returned entry carries its
    ``scope`` and ``advisory: true`` so the caller cites it SEPARATELY from
    canonical ISTQB/rules content.
    """
    scopes: tuple[str, ...]
    if scope is not None:
        _require_scope(scope)
        scopes = (scope,)
    else:
        scopes = paths.SCOPES
    items: list[dict[str, Any]] = []
    for sc in scopes:
        for e in _read_entries(sc):
            # ``pack_scope`` (project|global) is the STORE the lesson lives in;
            # the entry's own ``scope`` is the lesson's applicability (e.g.
            # "billing service") and must be preserved, not overwritten.
            items.append({**e, "pack_scope": sc, "advisory": True})
    return {
        "status": "listed",
        "count": len(items),
        "entries": items,
        "advisory": True,
        "note": (
            "Advisory memory only. Cite memory-derived probes SEPARATELY from "
            "bundled ISTQB/rules content; they never override canonical "
            "classifications or change-rules."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI for inspecting/removing saved feedback (the MCP tool owns capture).

    The console script intentionally exposes ``list`` and ``delete`` only: a
    capture must go through a host that can confirm with the user, so it is not
    a fire-and-forget CLI flag. Listing and deleting need no confirmation gate
    (read / explicit removal of a named id), so they are safe to script.

    Usage:
        sumo-qa-feedback list                      # all saved lessons (this repo + global)
        sumo-qa-feedback list --scope project      # this repo only
        sumo-qa-feedback list --scope global       # cross-repo lessons only
        sumo-qa-feedback delete <id> --scope project
    """
    parser = argparse.ArgumentParser(
        prog="sumo-qa-feedback",
        description="Inspect or remove saved review-feedback memory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="List saved feedback (advisory).")
    p_list.add_argument("--scope", choices=paths.SCOPES, default=None)
    p_del = sub.add_parser("delete", help="Delete a saved feedback entry by id.")
    p_del.add_argument("entry_id", help="The id shown by `list`.")
    p_del.add_argument("--scope", choices=paths.SCOPES, default="project")
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            report = list_feedback(scope=args.scope)
            print(json.dumps(report, indent=2))
            return 0
        report = delete_feedback(args.entry_id, scope=args.scope)
        print(f"deleted {report['id']} from {args.scope} ({report['remaining']} remaining)")
        return 0
    except FeedbackValidationError as exc:
        sys.stderr.write(f"sumo-qa-feedback: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover -- main guard
    raise SystemExit(main())
