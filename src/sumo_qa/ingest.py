# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Ingest team-owned QA content into a user-writable pack.

Format-strict: accepts only sumo-qa's native files (knowledge markdown, a
standards-pack YAML, ``change_rules.yaml``). Non-native sources (PDF, PPTX,
URLs) are NOT parsed here — the result routes the agent through the
``sumo-qa-suggesting-external-skill`` flow to find, install, and run a
converter skill. Validated content is materialised under the chosen scope's
user-pack dir; nothing is written if validation fails.

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
import errno
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
    "standards-pack *.yaml, or change_rules.yaml). A {kind} needs converting to "
    "markdown first: route through sumo-qa's external-skill discovery (the "
    "sumo-qa-suggesting-external-skill flow) to find, install, and run a "
    "converter skill, then call ingest again with content_type set to the right "
    "catalogue. Do NOT read and hand-transcribe the source yourself."
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
        # Intentionally stricter than validate_content._check_standards_packs,
        # which only WARNS on a non-mapping pack. At ingest time a non-mapping
        # pack would be materialised but then silently skipped by the loader's
        # classification filter — writing dead content. Reject it up front so
        # the user fixes the shape instead of wondering why the pack never loads.
        if not isinstance(doc, dict):
            raise IngestValidationError(
                f"{label}: top-level value must be a mapping, got "
                f"{type(doc).__name__} — classification filtering would skip it"
            )
        return
    # kind == "rules"
    # Pre-check the top level is a mapping: StandardsRulesEngine.from_file calls
    # `.items()` on the parsed YAML, so a list/scalar would raise AttributeError
    # (not ValueError/YAMLError) and escape the catch below.
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IngestValidationError(f"{label}: not valid YAML ({exc})") from exc
    if doc is not None and not isinstance(doc, dict):
        raise IngestValidationError(
            f"{label}: top-level value must be a mapping of classification -> rule, "
            f"got {type(doc).__name__}"
        )
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


def _atomic_write_via_dir_fd(
    dest: Path, text: str
) -> None:  # pragma: no cover -- platform-conditional (POSIX only)
    """TOCTOU-safe write used wherever the OS exposes ``*at`` syscalls.

    A caller validates ``dest`` against a confined root and THEN hands it here,
    so there is a window in which an attacker can swap the dest's parent for a
    symlink pointing outside the root. ``mkstemp(dir=...)`` / a plain
    ``os.open(path)`` would follow that swapped-in symlink and write out-of-root.

    Instead we open the parent directory itself with ``O_NOFOLLOW`` (refusing it
    outright if it has become a symlink) and then create the temp file, write it,
    and rename it into place *relative to that directory's file descriptor* with
    ``O_NOFOLLOW | O_EXCL`` — so every step lands in the real directory we just
    verified, never via a path that could be re-pointed between the check and the
    open.
    """
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    dir_fd = os.open(dest.parent, dir_flags)
    try:
        # A random suffix keeps the temp name unpredictable (mkstemp-like)
        # without re-introducing a path we'd have to re-resolve.
        tmp_name = f".{dest.name}.{os.urandom(8).hex()}.tmp"
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(tmp_name, file_flags, 0o600, dir_fd=dir_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            # Rename relative to the same verified directory fd so the final
            # swap likewise can't be redirected through a swapped-in parent
            # symlink. POSIX rename overwrites atomically (== os.replace).
            os.rename(tmp_name, dest.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            os.unlink(tmp_name, dir_fd=dir_fd)
            raise
    finally:
        os.close(dir_fd)


def _atomic_write_fallback(dest: Path, text: str) -> None:
    """Write path for platforms without ``*at`` syscalls / ``O_NOFOLLOW`` (e.g.
    Windows). mkstemp creates the temp file with O_EXCL + mode 0600 and a random
    name in the dest dir, so we never follow a pre-existing (possibly symlinked)
    temp path the way a predictable ``.<name>.tmp`` + write_text would. The
    parent-symlink swap is refused cross-platform by :func:`_write_atomic`
    (which rejects a symlinked ``dest.parent`` before dispatching here), so a
    swapped-in parent symlink never reaches this fallback; mkstemp lacks the
    POSIX ``O_NOFOLLOW`` race-free guarantee the dir-fd path adds on top."""
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# The dir-fd write needs renameat (os.rename with src/dst_dir_fd), openat
# (os.open with dir_fd), unlinkat, plus O_NOFOLLOW/O_DIRECTORY. POSIX exposes
# all of these; Windows exposes none — fall back there.
_SUPPORTS_DIR_FD_WRITE = (
    hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
)


def _write_atomic(dest: Path, text: str) -> None:
    # Refuse a symlinked parent BEFORE any mkdir/write, cross-platform. The
    # dir-fd path enforces this race-free via O_NOFOLLOW; the Windows fallback
    # has no such guard, so this shared check gives both platforms the same
    # "never write through a symlinked parent" contract and closes the
    # parent-symlink-swap TOCTOU where the dir-fd syscalls aren't available.
    if dest.parent.is_symlink():
        raise OSError(
            errno.ELOOP,
            "refusing to write through a symlinked parent directory",
            str(dest.parent),
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _SUPPORTS_DIR_FD_WRITE:
        _atomic_write_via_dir_fd(
            dest, text
        )  # pragma: no cover -- platform-conditional (POSIX only)
    else:
        _atomic_write_fallback(dest, text)


def _unsupported(source: str, kind: str) -> dict:
    return {
        "status": "unsupported_source",
        "source": source,
        # Structured routing so the host preserves the entry mode, not prose it infers.
        "next_skill": "sumo-qa-suggesting-external-skill",
        "entry_kind": "conversion",
        "guidance": _CONVERTER_GUIDANCE.format(src=source, kind=kind),
    }


# Canonical repo-shaped pack subdirectories, scanned in addition to the pack
# root so an exported `knowledge/` + `standards/` tree ingests without
# flattening. Scanning is restricted to these known locations rather than
# recursing everywhere, which would slurp unrelated nested .yaml / .md files.
_PACK_SUBDIRS = (
    Path("knowledge"),
    Path("standards") / "packs",
    Path("standards") / "rules",
)


def _gather_pack_files(root: Path, skipped: list[str]) -> list[Path]:
    """Collect native-candidate files from a pack directory.

    Scans the top level (flat pack) plus the canonical repo-shaped subdirs.
    Symlinks — files or whole subdirs — are skipped, never followed, so a link
    can't pull in content from outside the pack tree.
    """
    files: list[Path] = []
    for sub in (Path("."), *_PACK_SUBDIRS):
        directory = root / sub
        if sub != Path(".") and directory.is_symlink():
            skipped.append(str(sub))
            continue
        if not directory.is_dir():
            continue
        for p in sorted(directory.iterdir()):
            if p.is_symlink():
                skipped.append(p.name)
            elif p.is_file():
                files.append(p)
    return files


def ingest_pack(source: str, scope: str = "project", content_type: str | None = None) -> dict:
    """Validate and materialise native QA content into the scope's user pack.

    Returns a structured report dict. Raises ``IngestValidationError`` on bad
    content or a missing local path (writing nothing). Non-native files and
    remote URLs return an ``unsupported_source`` report that routes through the
    converter flow.
    """
    if scope not in paths.SCOPES:
        raise IngestValidationError(f"unknown scope {scope!r}; expected one of {paths.SCOPES}")
    src = Path(source)
    if not src.exists():
        if "://" in source:
            # A remote URL isn't a local file, but it IS a conversion candidate —
            # the discovered converter skill owns the fetch+convert.
            return _unsupported(source, "remote source")
        # A genuine missing local path is a not-found error, not a conversion
        # opportunity. Don't emit entry_kind=conversion for a file that isn't
        # there — that would send the agent hunting for a converter pointlessly.
        raise IngestValidationError(
            f"source not found: {source!r} — pass an existing native file or "
            f"directory, or a URL to convert via the sumo-qa-suggesting-external-skill flow"
        )

    skipped: list[str] = []
    files = [src] if src.is_file() else _gather_pack_files(src, skipped)
    classified: list[tuple[Path, str, str]] = []
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
    dest_sources: dict[Path, Path] = {}
    for f, kind, dest_name in classified:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # A mislabeled file (e.g. a non-UTF-8 export) must fail with an
            # actionable error, not a raw traceback out of the CLI's main().
            raise IngestValidationError(
                f"{f.name}: not valid UTF-8 ({exc}); re-export the file as UTF-8"
            ) from exc
        _validate(kind, text, f.name)
        dest = _dest_path(kind, dest_name, scope)
        # Two sources mapping to one destination (e.g. a flat `principles.md`
        # and a repo-shaped `knowledge/principles.md` in the same pack) is
        # ambiguous and would corrupt the transactional backup chain (both share
        # one `.<name>.sumo-bak`). Reject it before any write rather than guess.
        if dest in dest_sources:
            raise IngestValidationError(
                f"conflicting sources map to the same destination "
                f"({dest.name}): '{dest_sources[dest]}' and '{f}'. Provide only one."
            )
        dest_sources[dest] = f
        staged.append((kind.split(":", 1)[-1], dest, text))

    # All content validated above, so the only failure here is an OS write
    # error (disk full, permissions). Apply the pack transactionally: move any
    # pre-existing destination aside to a backup before overwriting it, and on
    # failure restore the backups — so a partial multi-file ingest never leaves
    # the pack half-applied AND never destroys the user's prior files.
    written = []
    restore: list[tuple[Path, Path | None]] = []  # (dest, backup-or-None) to undo
    try:
        for short_type, dest, text in staged:
            backup: Path | None = None
            if dest.exists():
                backup = dest.parent / f".{dest.name}.sumo-bak"
                os.replace(dest, backup)
            restore.append((dest, backup))  # record before writing so we can undo
            _write_atomic(dest, text)
            written.append({"type": short_type, "written": str(dest)})
    except OSError:
        for dest, backup in reversed(restore):
            dest.unlink(missing_ok=True)  # drop our (possibly partial) write
            if backup is not None:
                os.replace(backup, dest)  # restore the prior file
        raise
    # Success: discard the backups of overwritten files.
    for _, backup in restore:
        if backup is not None:
            backup.unlink(missing_ok=True)

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
