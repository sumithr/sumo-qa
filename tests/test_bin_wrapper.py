import pathlib


def _repo_root() -> pathlib.Path:
    """Walk up from this file until we find the .git ancestor.

    Robust to mutmut's layout: when the mutation gate runs, mutmut copies
    ``tests/`` into ``mutants/tests/`` but does NOT copy ``bin/`` or
    ``docs/`` (only files under mutation + their tests). A naive
    ``parents[1]`` resolves to ``mutants/`` inside that copy and the bin
    / docs lookups under it fail. Anchoring on ``.git`` always finds the
    real repo root regardless of layout.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


REPO_ROOT = _repo_root()


def test_bin_wrapper_does_not_mention_node_or_npx():
    text = (REPO_ROOT / "bin" / "sumo-qa-doctor").read_text()
    lowered = text.lower()
    assert "npx" not in lowered, (
        "Node/npx analogy is pedagogical fluff for sumo-qa users — strip it"
    )
    assert "node-based" not in lowered


def test_install_md_uv_section_does_not_mention_npx():
    text = (REPO_ROOT / "docs" / "INSTALL.md").read_text()
    lowered = text.lower()
    assert "npx" not in lowered
    assert "node-based plugins assume" not in lowered
