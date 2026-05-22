#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Second-layer doc-drift gate: catch file refs inside markdown code blocks.

`pytest-check-links` covers `[text](path)` markdown links. It does NOT look
inside ``` ``inline code`` ``` or ```` ```bash …``` ```` fenced blocks, where
most "run this command" snippets live — and that's exactly where the
canonical `python scripts/dev_install.py`-shaped drift hides.

This script parses each markdown file, walks every inline-code and
fenced-code segment, extracts file-path-looking tokens, and asserts they
resolve relative to the repo root.

CLI:
    python scripts/check_codeblock_file_refs.py [<file> ...]
    # No args  → scans every git-tracked .md
    # With args → scans only those files

Exit:
    0  no broken refs
    1  one or more refs point at files that do not exist
    2  usage / config error
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# What counts as a file-path-looking token inside code:
#   - One or more path segments separated by '/'
#   - Ends in one of the dev-relevant extensions below
#   - No URL scheme, no shell variable, no glob wildcard
#
# This is deliberately conservative — we want zero false positives over
# zero false negatives. Adding extensions is easy when a real ref slips
# past; loosening the regex risks blowing up on documented `*.py` patterns.
EXTENSIONS = (
    "py",
    "sh",
    "md",
    "yml",
    "yaml",
    "toml",
    "json",
    "js",
    "ts",
    "tsx",
    "html",
    "css",
)
_EXT_RE = "|".join(EXTENSIONS)
PATH_RE = re.compile(
    r"(?<![\w/.-])"  # left boundary: not part of a longer identifier
    r"((?:[\w.-]+/)+"  # at least one path segment with '/'
    r"[\w.-]+\."  # filename with a dot
    rf"(?:{_EXT_RE}))"  # one of the known extensions
    r"(?![\w/.-])",  # right boundary
)

# Lines / tokens we never treat as file refs:
URL_RE = re.compile(r"https?://")
SHELL_VAR_RE = re.compile(r"[$%]")
GLOB_RE = re.compile(r"[*?\[\]]")


def _tracked_markdown(repo_root: Path) -> list[Path]:
    out = subprocess.check_output(
        ["git", "ls-files", "*.md"],
        cwd=repo_root,
        text=True,
    )
    return [repo_root / line.strip() for line in out.splitlines() if line.strip()]


def _code_segments(text: str) -> list[str]:
    """Yield every inline-code and fenced-code segment from markdown text.

    Fenced code blocks come first (``` … ```) so their content doesn't get
    re-matched as inline code. Tilde fences (~~~) are accepted for parity.
    """
    segments: list[str] = []

    # Strip fenced blocks first, capturing their contents.
    def _eat_fenced(match: re.Match[str]) -> str:
        segments.append(match.group("body"))
        return ""

    fenced_re = re.compile(
        r"^(?P<fence>```|~~~)[^\n]*\n"
        r"(?P<body>.*?)"
        r"^(?P=fence)\s*$",
        re.MULTILINE | re.DOTALL,
    )
    stripped = fenced_re.sub(_eat_fenced, text)

    # Inline code: ` … ` (single backticks). Multi-backtick spans are rare
    # in real docs; skip them to keep the parser simple.
    for match in re.finditer(r"`([^`\n]+)`", stripped):
        segments.append(match.group(1))

    return segments


def extract_refs(text: str) -> list[str]:
    """Return file-path-looking tokens from every code segment in `text`."""
    refs: list[str] = []
    for segment in _code_segments(text):
        if URL_RE.search(segment):
            # Skip the whole segment if it contains a URL — we can't easily
            # tell which token is the URL path vs an independent file ref.
            # In practice these segments are full command lines like
            # `curl https://… | sh` and don't reference local files.
            continue
        for match in PATH_RE.finditer(segment):
            token = match.group(1)
            # Don't claim a hit on glob patterns or shell-variable interpolation.
            if GLOB_RE.search(token) or SHELL_VAR_RE.search(token):
                continue
            refs.append(token)
    return refs


def _gitignored(refs: list[str], repo_root: Path) -> set[str]:
    """Return the subset of `refs` that match a .gitignore pattern.

    Gitignored paths in docs are intentional output locations
    (`docs/qa-strategy.md` is a runtime artefact sumo-qa writes), not
    references to files that *should* exist in the source tree. Treating
    them as drift would force docs to talk around real runtime outputs.
    """
    if not refs:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "--stdin"],
            input="\n".join(refs),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        # No git on PATH — can't filter. Fall through and flag everything.
        return set()
    # `git check-ignore --stdin` exits 0 if anything was ignored, 1 if not,
    # 128 if git error. Either 0 or 1 is fine; 128 means something is wrong.
    if result.returncode == 128:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def check_file(md_path: Path, repo_root: Path) -> list[tuple[Path, str]]:
    """Return a list of (md_path, missing_ref) for refs that don't resolve.

    Resolution rule: refs starting with `./` or `../` are relative to the
    markdown file's directory (matches how a human reads the link). All
    other refs are repo-root-relative — the common pattern in install /
    contributor docs (`python scripts/dev_install.py`).

    Gitignored refs are treated as intentional runtime outputs, not drift.
    """
    text = md_path.read_text(encoding="utf-8", errors="replace")
    refs = extract_refs(text)
    if not refs:
        return []
    ignored = _gitignored(refs, repo_root)
    missing: list[tuple[Path, str]] = []
    for ref in refs:
        if ref in ignored:
            continue
        if ref.startswith("./") or ref.startswith("../"):
            target = (md_path.parent / ref).resolve()
        else:
            target = (repo_root / ref).resolve()
        if not target.exists():
            missing.append((md_path, ref))
    return missing


def _resolve_repo_root_for(path: Path) -> Path:
    """Walk up from `path` looking for a repo marker (.git / pyproject.toml).

    Falls back to the file's own directory if no marker is found — used by
    tests that point the script at a tmp file without a surrounding git repo.
    Prod invocations always find .git (in pre-commit, in CI checkouts).
    """
    start = path if path.is_dir() else path.parent
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return start


def _resolve_default_root() -> Path:
    """Repo root for the no-args / `git ls-files` discovery path."""
    here = Path(__file__).resolve().parent
    return here.parent  # scripts/.. == repo root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if a markdown code block (fenced or inline) references a "
            "relative file path that doesn't exist. Companion to "
            "scripts/check_markdown_links.sh."
        ),
    )
    parser.add_argument("files", nargs="*", help="Markdown files to scan; default: all tracked .md")
    args = parser.parse_args(argv)

    if args.files:
        files = [Path(f).resolve() for f in args.files]
    else:
        files = _tracked_markdown(_resolve_default_root())

    if not files:
        print("check_codeblock_file_refs: no markdown files to check")
        return 0

    failures: list[tuple[Path, str]] = []
    for md in files:
        if not md.exists():
            print(f"check_codeblock_file_refs: SKIP {md} (does not exist)", file=sys.stderr)
            continue
        repo_root = _resolve_repo_root_for(md)
        failures.extend(check_file(md, repo_root))

    if failures:
        for md, ref in failures:
            try:
                rel = md.relative_to(repo_root)
            except ValueError:
                rel = md
            print(
                f"BROKEN: {rel}: code-block references {ref} (file does not exist)", file=sys.stderr
            )
        print(f"\n{len(failures)} broken code-block file ref(s) found.", file=sys.stderr)
        return 1

    print(f"check_codeblock_file_refs: {len(files)} file(s) scanned, all refs resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
