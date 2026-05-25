# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Ingest team-owned QA content into a user-writable pack.

Format-strict: accepts only sumo-qa's native files (knowledge markdown, a
standards-pack YAML, ``change_rules.yaml``). Non-native sources (PDF, PPTX,
URLs) are NOT parsed here — the result routes the agent to a dedicated
converter skill discovered via skill-discovery. Validated content is
materialised under the chosen scope's user-pack dir; nothing is written if
validation fails.

Usage:
    sumo-qa-ingest principles.md                 # ingest into <cwd>/.sumo-qa
    sumo-qa-ingest pack/ --scope global          # ingest a directory globally
    sumo-qa-ingest converted.md --type principles
    python -m sumo_qa.ingest principles.md       # equivalent

Exit codes:
    0 — content ingested
    1 — validation failure, unsupported source, or nothing ingested
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import yaml

from sumo_qa import paths

# Canonical knowledge filename -> short content-type name.
_KNOWLEDGE_CANONICAL = {
    "classifications.md": "classifications",
    "approaches.md": "approaches",
    "principles.md": "principles",
    "techniques.md": "techniques",
}
# short content-type name -> canonical destination filename.
_KNOWLEDGE_DEST = {v: k for k, v in _KNOWLEDGE_CANONICAL.items()}
_RULES_FILE = "change_rules.yaml"
_YAML_SUFFIXES = (".yaml", ".yml")
_PRECEDENCE = "explicit env var > project pack > global pack > bundled > repo root"

_CONVERTER_GUIDANCE = (
    "Unsupported source '{src}'. The ingest tool only accepts native sumo-qa "
    "files (principles.md, techniques.md, classifications.md, approaches.md, a "
    "standards-pack *.yaml, or change_rules.yaml). To ingest a {kind}: use "
    "skill-discovery (find-skills / sumo_qa_search_external_skills) to find a "
    "dedicated converter skill (e.g. a 'pdf-to-markdown' skill), convert the "
    "source to markdown in one shot, then call ingest again with "
    "content_type='principles' (or the right catalogue). Do NOT read and "
    "hand-transcribe the source yourself."
)


class IngestValidationError(ValueError):
    """Raised when provided content fails validation. Nothing is written."""


def _classify(path: Path, content_type: str | None) -> tuple[str, str] | None:
    """Return ``(kind, dest_filename)`` or ``None`` when the source is non-native.

    ``kind`` is ``"knowledge:<name>"``, ``"rules"``, or ``"standards"``.
    """
    if content_type is not None:
        if content_type in _KNOWLEDGE_DEST:
            return (f"knowledge:{content_type}", _KNOWLEDGE_DEST[content_type])
        if content_type == "rules":
            return ("rules", _RULES_FILE)
        if content_type == "standards":
            name = path.name if path.suffix in _YAML_SUFFIXES else f"{path.stem}.yaml"
            return ("standards", name)
        raise IngestValidationError(
            f"unknown content_type {content_type!r}; expected one of "
            f"{sorted(set(_KNOWLEDGE_DEST) | {'rules', 'standards'})}"
        )
    if path.name in _KNOWLEDGE_CANONICAL:
        return (f"knowledge:{_KNOWLEDGE_CANONICAL[path.name]}", path.name)
    if path.name == _RULES_FILE:
        return ("rules", _RULES_FILE)
    if path.suffix in _YAML_SUFFIXES:
        return ("standards", path.name)
    return None


def _validate_rules_text(text: str) -> None:
    """Validate change-rules YAML through the real strict schema.

    ``StandardsRulesEngine`` has no from-text constructor, so the text is
    written to a temp file and routed through ``from_file``.
    """
    from sumo_qa.rules import StandardsRulesEngine

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        tmp_path = Path(fh.name)
    try:
        StandardsRulesEngine.from_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _validate(kind: str, text: str, label: str) -> None:
    """Raise IngestValidationError with an actionable message on bad content."""
    if kind.startswith("knowledge:"):
        if not text.strip():
            raise IngestValidationError(
                f"{label}: empty — the matching loader would return an empty string"
            )
        return
    if kind == "standards":
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise IngestValidationError(f"{label}: not valid YAML ({exc})") from exc
        if not isinstance(doc, dict):
            raise IngestValidationError(
                f"{label}: top-level value must be a mapping, got "
                f"{type(doc).__name__} — classification filtering would skip it"
            )
        return
    # kind == "rules"
    try:
        _validate_rules_text(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise IngestValidationError(f"{label}: {exc}") from exc


def _dest_path(kind: str, dest_name: str, scope: str) -> Path:
    if kind.startswith("knowledge:"):
        return paths.knowledge_dir(scope) / dest_name
    if kind == "rules":
        return paths.rules_path(scope)
    return paths.standards_packs_dir(scope) / dest_name


def _write_atomic(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, dest)


def _unsupported(source: str, kind: str) -> dict:
    return {
        "status": "unsupported_source",
        "source": source,
        "guidance": _CONVERTER_GUIDANCE.format(src=source, kind=kind),
    }


def ingest_pack(source: str, scope: str = "project", content_type: str | None = None) -> dict:
    """Validate and materialise native QA content into the scope's user pack.

    Returns a structured report dict. Raises ``IngestValidationError`` on bad
    content (writing nothing). Non-native or missing sources return an
    ``unsupported_source`` report.
    """
    if scope not in paths.SCOPES:
        raise IngestValidationError(f"unknown scope {scope!r}; expected one of {paths.SCOPES}")
    src = Path(source)
    if not src.exists():
        kind = "remote source" if "://" in source else "missing path"
        return _unsupported(source, kind)

    files = [src] if src.is_file() else sorted(p for p in src.iterdir() if p.is_file())
    classified: list[tuple[Path, str, str]] = []
    skipped: list[str] = []
    for f in files:
        ct = content_type if src.is_file() else None
        result = _classify(f, ct)
        if result is None:
            skipped.append(f.name)
            continue
        classified.append((f, result[0], result[1]))

    if not classified:
        if src.is_file():
            kind = f"{src.suffix.lstrip('.') or 'binary'} file"
            return _unsupported(source, kind)
        return {"status": "nothing_ingested", "source": source, "skipped": skipped}

    # Validate everything first; write nothing until all checks pass.
    staged: list[tuple[str, Path, str]] = []  # (short_type, dest_path, text)
    for f, kind, dest_name in classified:
        text = f.read_text(encoding="utf-8")
        _validate(kind, text, f.name)
        staged.append((kind.split(":", 1)[-1], _dest_path(kind, dest_name, scope), text))

    written = []
    for short_type, dest, text in staged:
        _write_atomic(dest, text)
        written.append({"type": short_type, "written": str(dest)})

    return {
        "status": "ingested",
        "scope": scope,
        "destination": str(paths.user_pack_root(scope)),
        "files": written,
        "skipped": skipped,
        "precedence": _PRECEDENCE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sumo-qa-ingest",
        description="Ingest a native QA knowledge pack into a user-writable location.",
    )
    parser.add_argument("source", help="File or directory of native md/yaml content")
    parser.add_argument("--scope", choices=paths.SCOPES, default="project")
    parser.add_argument(
        "--type",
        dest="content_type",
        default=None,
        help="Force content type (principles, techniques, classifications, approaches, "
        "rules, standards) — e.g. for markdown converted from a PDF.",
    )
    args = parser.parse_args(argv)
    try:
        report = ingest_pack(args.source, scope=args.scope, content_type=args.content_type)
    except IngestValidationError as exc:
        sys.stderr.write(f"sumo-qa-ingest: {exc}\n")
        return 1
    status = report["status"]
    if status == "ingested":
        print(f"ingested {len(report['files'])} file(s) -> {report['destination']}")
        for f in report["files"]:
            print(f"  - {f['type']}: {f['written']}")
        return 0
    if status == "unsupported_source":
        sys.stderr.write(report["guidance"] + "\n")
        return 1
    sys.stderr.write(
        f"nothing ingested from {report['source']} (skipped: {report.get('skipped')})\n"
    )
    return 1


if __name__ == "__main__":  # pragma: no cover -- main guard
    raise SystemExit(main())
