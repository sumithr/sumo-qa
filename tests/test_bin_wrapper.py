import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


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
