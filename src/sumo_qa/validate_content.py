# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Validate user-authored content against the sumo-qa loaders.

Runs the strict-schema loaders (`StandardsRulesEngine.from_file`,
`TestDataCatalogue.list_entries`) against the repo's content directories so
malformed packs / rules / test-data fail loudly before they reach a host.
Permissive content (knowledge markdown, classification-unfiltered standards
packs) gets soft warnings only — empty files, unparseable YAML headers — so
teams can ship loose content where the schema is genuinely loose.

Usage:
    sumo-qa-validate                          # validate repo at cwd
    sumo-qa-validate /path/to/clone           # validate a specific clone
    python -m sumo_qa.validate_content        # equivalent

Exit codes:
    0 — all required schemas pass (warnings may be present)
    1 — one or more required schemas failed
    2 — usage error (no repo root found)
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import yaml

REQUIRED_KNOWLEDGE_FILES = (
    "classifications.md",
    "approaches.md",
    "principles.md",
    "techniques.md",
)
OPTIONAL_KNOWLEDGE_FILES = ("repo_walk.md",)


class _Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.passes: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self, msg: str) -> None:
        self.passes.append(msg)


def _check_change_rules(repo_root: Path, r: _Report) -> None:
    """change_rules.yaml: strict Pydantic schema in rules.StandardsRulesEngine."""
    from sumo_qa.rules import StandardsRulesEngine

    path = repo_root / "standards" / "rules" / "change_rules.yaml"
    if not path.is_file():
        r.warn(
            f"{path.relative_to(repo_root)}: not present — change-rule lookups will return empty"
        )
        return
    try:
        engine = StandardsRulesEngine.from_file(path)
    except (ValueError, yaml.YAMLError) as exc:
        r.err(f"{path.relative_to(repo_root)}: {exc}")
        return
    rule_count = len(engine._rules)
    if rule_count == 0:
        r.warn(f"{path.relative_to(repo_root)}: parsed OK but contains zero rules")
    else:
        r.ok(f"{path.relative_to(repo_root)}: {rule_count} change rules")


def _check_test_data(repo_root: Path, r: _Report) -> None:
    """knowledge/test_data/<domain>/<record>.y(a)ml: strict Pydantic via TDM."""
    from sumo_qa.tdm_catalogue import TestDataCatalogue

    root = repo_root / "knowledge" / "test_data"
    if not root.is_dir():
        r.warn(f"{root.relative_to(repo_root)}: not present — test-data tools will return empty")
        return
    catalogue = TestDataCatalogue(root)
    try:
        entries = catalogue.list_entries()
    except (ValueError, yaml.YAMLError) as exc:
        r.err(f"{root.relative_to(repo_root)}: {exc}")
        return
    if not entries:
        r.warn(f"{root.relative_to(repo_root)}: 0 test-data entries (fresh-install default)")
    else:
        r.ok(f"{root.relative_to(repo_root)}: {len(entries)} test-data entries")


def _check_standards_packs(repo_root: Path, r: _Report) -> None:
    """standards/packs/*.y(a)ml: YAML parseable; warn if no classification metadata."""
    packs_dir = repo_root / "standards" / "packs"
    if not packs_dir.is_dir():
        r.warn(f"{packs_dir.relative_to(repo_root)}: directory missing")
        return
    pack_paths = sorted(list(packs_dir.glob("*.yaml")) + list(packs_dir.glob("*.yml")))
    if not pack_paths:
        r.warn(f"{packs_dir.relative_to(repo_root)}: no *.yml / *.yaml files")
        return
    for path in pack_paths:
        rel = path.relative_to(repo_root)
        text = path.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            r.err(f"{rel}: not valid YAML ({exc})")
            continue
        if doc is None:
            r.warn(f"{rel}: empty document")
            continue
        if not isinstance(doc, dict):
            r.warn(
                f"{rel}: top-level value is {type(doc).__name__}, not a mapping — "
                f"classification filtering will silently skip this pack"
            )
            continue
        has_filter = "applies_to_classifications" in doc or "classifications" in doc
        if not has_filter:
            r.warn(
                f"{rel}: no 'applies_to_classifications' / 'classifications' key — "
                f"pack will always load regardless of change type"
            )
        r.ok(f"{rel}: valid YAML" + (" (always-load)" if not has_filter else ""))


def _check_knowledge_catalogues(repo_root: Path, r: _Report) -> None:
    """knowledge/*.md: must exist and be non-empty for the four canonical files."""
    knowledge_dir = repo_root / "knowledge"
    if not knowledge_dir.is_dir():
        r.err(f"{knowledge_dir.relative_to(repo_root)}: directory missing")
        return
    for name in REQUIRED_KNOWLEDGE_FILES:
        path = knowledge_dir / name
        rel = path.relative_to(repo_root)
        if not path.is_file():
            r.err(f"{rel}: required knowledge file missing")
            continue
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            r.err(f"{rel}: empty — the matching sumo_qa_load_* tool will return an empty string")
            continue
        r.ok(f"{rel}: {len(body.splitlines())} non-blank lines")
    for name in OPTIONAL_KNOWLEDGE_FILES:
        path = knowledge_dir / name
        rel = path.relative_to(repo_root)
        if not path.is_file():
            r.warn(f"{rel}: optional knowledge file missing (referenced by sumo-qa-strategising)")


def _resolve_repo_root(arg: str | None) -> Path | None:
    """Resolve the target repo. CLI arg wins; otherwise walk up from cwd looking
    for a pyproject.toml whose project name is sumo-qa."""
    if arg is not None:
        candidate = Path(arg).resolve()
        if not candidate.is_dir():
            sys.stderr.write(f"sumo-qa-validate: {candidate} is not a directory\n")
            return None
        return candidate
    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        if (directory / "knowledge").is_dir() and (directory / "standards").is_dir():
            return directory
    sys.stderr.write(
        "sumo-qa-validate: no knowledge/ + standards/ at cwd or any parent. "
        "Pass a path explicitly: sumo-qa-validate /path/to/clone\n"
    )
    return None


def _render(report: _Report) -> str:
    lines = []
    if report.passes:
        lines.append("OK:")
        lines.extend(f"  - {msg}" for msg in report.passes)
    if report.warnings:
        lines.append("WARN:")
        lines.extend(f"  - {msg}" for msg in report.warnings)
    if report.errors:
        lines.append("FAIL:")
        lines.extend(f"  - {msg}" for msg in report.errors)
    lines.append("")
    summary = (
        f"{len(report.passes)} ok, {len(report.warnings)} warning(s), {len(report.errors)} error(s)"
    )
    lines.append(summary)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    arg = argv[0] if argv else None
    repo_root = _resolve_repo_root(arg)
    if repo_root is None:
        return 2

    report = _Report()
    checks: tuple[Callable[[Path, _Report], None], ...] = (
        _check_knowledge_catalogues,
        _check_standards_packs,
        _check_change_rules,
        _check_test_data,
    )
    for check in checks:
        check(repo_root, report)

    print(f"sumo-qa-validate  (target: {repo_root})")
    print(_render(report))
    return 1 if report.errors else 0


if __name__ == "__main__":  # pragma: no cover -- main guard
    raise SystemExit(main())
