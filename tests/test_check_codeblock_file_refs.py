# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the code-block file-ref drift checker.

The checker scans markdown for inline-code and fenced-code segments and
fails if a path-looking token inside them doesn't resolve to a real file.
These tests pin the path extractor's behaviour — what counts as a ref,
what gets ignored — so future loosening (e.g. accepting bare filenames
without a slash) doesn't happen by accident.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_codeblock_file_refs.py"

# Load the script as a module so we can call its functions directly without
# launching a subprocess for every test. Avoids ~50ms per case.
_spec = importlib.util.spec_from_file_location("_codeblock_check", SCRIPT)
assert _spec is not None and _spec.loader is not None
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


class TestExtractRefs:
    """Path extraction is the load-bearing logic — pin every shape."""

    def test_no_code_blocks_returns_empty(self) -> None:
        assert checker.extract_refs("plain prose with no code") == []

    def test_inline_code_with_path(self) -> None:
        text = "see `scripts/foo.py` for details"
        assert checker.extract_refs(text) == ["scripts/foo.py"]

    def test_fenced_bash_block_with_command(self) -> None:
        text = "```bash\npython scripts/dev_install.py\n```"
        assert checker.extract_refs(text) == ["scripts/dev_install.py"]

    def test_fenced_python_block_with_multiple_refs(self) -> None:
        text = "```python\nfrom src.foo import bar\nopen('configs/sample.yaml').read()\n```"
        # We don't try to extract from Python import paths (no dots-to-slash
        # logic); only `/`-separated paths with a known extension count.
        # `configs/sample.yaml` has both, so it should match.
        refs = checker.extract_refs(text)
        assert "configs/sample.yaml" in refs

    def test_tilde_fenced_block_treated_like_backtick(self) -> None:
        text = "~~~bash\nbash scripts/install.sh\n~~~"
        assert checker.extract_refs(text) == ["scripts/install.sh"]

    def test_url_inside_code_skipped_entirely(self) -> None:
        # The whole segment is skipped because telling "scripts/foo.py is a
        # local ref" apart from "example.com/scripts/foo.py is part of a URL"
        # is brittle. Conservative: ignore segments that contain URLs.
        text = "```bash\ncurl https://example.com/scripts/foo.py | sh\n```"
        assert checker.extract_refs(text) == []

    def test_glob_pattern_skipped(self) -> None:
        text = "```bash\nruff check src/**/*.py\n```"
        assert checker.extract_refs(text) == []

    def test_shell_variable_skipped(self) -> None:
        text = "```bash\npython ${PROJECT}/scripts/foo.py\n```"
        # The token contains `$` so we drop it.
        assert checker.extract_refs(text) == []

    def test_path_without_extension_ignored(self) -> None:
        text = "```bash\ncd scripts/sub\n```"
        assert checker.extract_refs(text) == []

    def test_path_with_unknown_extension_ignored(self) -> None:
        text = "```bash\ncat data/foo.bin\n```"
        # .bin not in EXTENSIONS — we're deliberately narrow to avoid
        # false positives on log/output snippets.
        assert checker.extract_refs(text) == []

    def test_bare_filename_no_slash_ignored(self) -> None:
        # `README.md` on its own (no slash) doesn't trip the matcher — too
        # noisy, the project has many README.md references in prose form.
        text = "see `README.md` for details"
        assert checker.extract_refs(text) == []

    def test_prose_with_dot_extension_lookalike_ignored(self) -> None:
        # Not in a code block at all → never extracted.
        text = "see file path/foo.py in prose"
        assert checker.extract_refs(text) == []


class TestCheckFile:
    """Integration-ish: write a fixture md, point check_file at it."""

    def test_existing_target_resolves(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "real.py").write_text("# real")
        md = tmp_path / "doc.md"
        md.write_text("```bash\npython scripts/real.py\n```")
        assert checker.check_file(md, tmp_path) == []

    def test_missing_target_reports(self, tmp_path: Path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("```bash\npython scripts/gone.py\n```")
        missing = checker.check_file(md, tmp_path)
        assert len(missing) == 1
        assert missing[0][0] == md
        assert missing[0][1] == "scripts/gone.py"

    def test_relative_ref_resolves_against_md_dir_not_repo_root(self, tmp_path: Path) -> None:
        """`../foo.md` should resolve relative to the markdown file's dir,
        not relative to repo root — that's how a human reading the doc on
        GitHub would expect the path to work."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "sibling.md").write_text("# sibling exists")
        md = tmp_path / "subdir" / "deep.md"
        md.write_text("see `../sibling.md` for details")
        # `../sibling.md` from subdir/ resolves to tmp_path/sibling.md (exists).
        # Without the relative-path fix it would have resolved against
        # repo root → tmp_path/../sibling.md → outside the tree → missing.
        # Note: bare `../sibling.md` is inline code without a slash in the
        # last segment — only matches if extracted. Let's use a fenced block:
        md.write_text("```bash\ncat ../sibling.md\n```")
        assert checker.check_file(md, tmp_path) == []


class TestCli:
    """End-to-end: invoke the script via subprocess against a fixture tree."""

    def test_exit_0_when_all_refs_resolve(self, tmp_path: Path) -> None:
        # Build a tiny git repo so `git ls-files` works.
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "ok.py").write_text("# ok")
        (tmp_path / "doc.md").write_text("```bash\npython scripts/ok.py\n```")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init", "--no-verify"],
            cwd=tmp_path,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "PATH": __import__("os").environ.get("PATH", ""),
            },
        )
        # Pass the doc explicitly so we don't rely on the fixture's cwd.
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(tmp_path / "doc.md")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_exit_1_when_ref_missing(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("```bash\npython scripts/missing.py\n```")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(tmp_path / "doc.md")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "scripts/missing.py" in result.stderr


def test_script_catches_actual_dev_install_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline acceptance test: if `scripts/dev_install.py` is removed,
    the script flags every doc that references it from a code block. This
    is the exact bug class the user originally cited.
    """
    # Copy the relevant docs + scripts dir to a tmp tree so we don't mutate
    # the worktree. Symlink the structure to keep paths relative.
    (tmp_path / "scripts").mkdir()
    # Note: we deliberately do NOT create scripts/dev_install.py in the tmp.
    (tmp_path / "README.md").write_text(
        "Per the docs:\n\n```bash\npython scripts/dev_install.py --help\n```\n"
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "README.md")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, "Should fail when dev_install.py is missing"
    assert "scripts/dev_install.py" in result.stderr
