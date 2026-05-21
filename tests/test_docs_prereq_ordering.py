"""Regression: uv prereq must precede the `claude plugin install` command.

A first-time reader following the install doc top-down should encounter the
"install uv first" signal BEFORE they hit the plugin install command.
Otherwise they run the install, hit a silent MCP failure, and only discover
the prereq after debugging.
"""

from __future__ import annotations

import pathlib


def _repo_root() -> pathlib.Path:
    """Walk up from this file until we find the .git ancestor.

    Robust to mutmut's layout: when the mutation gate runs, mutmut copies
    ``tests/`` into ``mutants/tests/`` so the mutated source can be tested
    — but it does NOT copy ``docs/``, ``README.md``, ``bin/``, etc.
    (only files under mutation + their tests). A naive
    ``parents[1]`` resolves to ``mutants/`` inside that copy, and any
    docs lookup under it fails. Anchoring on ``.git`` always finds the
    real repo root regardless of layout.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


REPO = _repo_root()


def test_install_md_uv_prereq_precedes_plugin_install_command():
    text = (REPO / "docs" / "INSTALL.md").read_text()
    prereq_idx = text.find("### Prerequisite: `uv`")
    plugin_install_idx = text.find("claude plugin install sumithr/sumo-qa")
    assert prereq_idx > 0, "Prerequisite: `uv` section missing from INSTALL.md"
    assert plugin_install_idx > 0
    assert prereq_idx < plugin_install_idx, (
        "INSTALL.md must surface the uv prereq BEFORE the plugin install command"
    )


def test_readme_mentions_uv_prereq_before_plugin_install_in_install_section():
    text = (REPO / "README.md").read_text()
    # The Install section: between '## Install' and the next '## ' heading
    install_start = text.find("## Install")
    next_section = text.find("\n## ", install_start + 1)
    install_section = text[install_start:next_section]
    plugin_install_idx = install_section.find("claude plugin install")
    if plugin_install_idx < 0:
        # If README doesn't mention plugin install in this section, that's fine
        return
    uv_mention_idx = install_section.find("uv")
    assert uv_mention_idx > 0, "README Install section must mention uv prereq"
    assert uv_mention_idx < plugin_install_idx, (
        "README Install section must mention uv BEFORE 'claude plugin install'"
    )
