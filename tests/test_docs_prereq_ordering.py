"""Regression: uv prereq must precede the plugin-install command anywhere
it appears in user-facing docs.

A first-time reader following the install doc top-down should encounter the
"install uv first" signal BEFORE they hit a plugin-install invocation
(`claude --plugin-dir` today, `claude plugin install ...` once the marketplace
ships). Otherwise they run the install, hit a silent MCP failure, and only
discover the prereq after debugging.

The literal `claude plugin install sumithr/sumo-qa` string was removed
from docs in PR #139 because marketplace publication hasn't shipped —
until it does, only the `--plugin-dir` flow is documented as a real
install path. The regression now anchors on whichever plugin-install
command appears first.
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


def _first_plugin_install_mention(text: str) -> int:
    """Return the earliest index of an actual plugin-install invocation.

    Anchors must match a real invocation (with a path or owner/repo
    argument), not a prose mention of the command word — otherwise the
    doctor's descriptive text "detects whether sumo-qa is installed via
    `claude plugin install`" would trip the test even though it's not
    instructing the user to run anything.

    Accepted today:
      - `claude --plugin-dir /` (the working local-dev install)
      - `claude --plugin-dir <` (the same, with a placeholder)
    Accepted when marketplace ships:
      - `claude plugin install sumithr/`

    Returns -1 if no real invocation appears.
    """
    candidates = [
        text.find("claude --plugin-dir /"),
        text.find("claude --plugin-dir <"),
        text.find("claude plugin install sumithr/"),
    ]
    found = [i for i in candidates if i >= 0]
    return min(found) if found else -1


def test_install_md_uv_prereq_precedes_plugin_install_command():
    """uv prereq must precede the documented plugin-install command in INSTALL.md."""
    text = (REPO / "docs" / "INSTALL.md").read_text()
    prereq_idx = text.find("### Prerequisite: `uv`")
    plugin_install_idx = _first_plugin_install_mention(text)
    assert prereq_idx > 0, "Prerequisite: `uv` section missing from INSTALL.md"
    assert plugin_install_idx > 0, "Plugin-install command missing from INSTALL.md"
    assert prereq_idx < plugin_install_idx, (
        "INSTALL.md must surface the uv prereq BEFORE the plugin-install command"
    )


def test_readme_mentions_uv_prereq_before_plugin_install_in_install_section():
    """If README mentions a plugin-install command in the Install section,
    uv must be mentioned first."""
    text = (REPO / "README.md").read_text()
    install_start = text.find("## Install")
    next_section = text.find("\n## ", install_start + 1)
    install_section = text[install_start:next_section]
    plugin_install_idx = _first_plugin_install_mention(install_section)
    if plugin_install_idx < 0:
        return  # README has no plugin-install mention — nothing to enforce
    uv_mention_idx = install_section.find("uv")
    assert uv_mention_idx > 0, "README Install section must mention uv prereq"
    assert uv_mention_idx < plugin_install_idx, (
        "README Install section must mention uv BEFORE the plugin-install command"
    )
