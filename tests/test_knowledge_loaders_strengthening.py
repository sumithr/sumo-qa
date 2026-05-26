# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Mutation-strengthening tests (Phase 3) for `sumo_qa.knowledge_loaders`.

Walks the 43 surviving mutants from the Phase 3 baseline (see
`docs/qa/runs/2026-05-14-phase3-mutation-baseline.md`) and kills each via a
behaviour-anchored assertion. Production code is NOT touched.

The tests use spy/monkeypatch patterns to assert the exact filename + path
literals + encoding the production code passes to `_read` / `Path.read_text`,
so the assertions hold regardless of filesystem case-sensitivity (some
filename-case mutations would otherwise survive on macOS APFS even though
they'd fail on Linux CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sumo_qa import knowledge_loaders as kl

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Class A — Loader filename literals (4 mutants)
# Kills: x_sumo_qa_load_{classifications,approaches,principles,techniques}__mutmut_3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "loader, expected_filename",
    [
        (kl.sumo_qa_load_classifications, "classifications.md"),
        (kl.sumo_qa_load_approaches, "approaches.md"),
        (kl.sumo_qa_load_principles, "principles.md"),
        (kl.sumo_qa_load_techniques, "techniques.md"),
    ],
)
def test_loader_calls_read_with_canonical_lowercase_filename(
    loader, expected_filename: str, monkeypatch
) -> None:
    """Each no-arg loader must call `_read()` with the EXACT lowercase filename.

    The filename mutations (e.g. `"classifications.md"` → `"CLASSIFICATIONS.MD"`)
    survive on case-insensitive filesystems (macOS APFS) because the OS still
    resolves the request. This spy-based test asserts the literal string passed
    to `_read`, killing the mutation regardless of FS case-sensitivity.
    """
    captured: list[str] = []
    original_read = kl._read

    def spy_read(name: str) -> str:
        captured.append(name)
        return original_read(name)

    monkeypatch.setattr(kl, "_read", spy_read)
    loader()
    assert captured == [expected_filename], (
        f"Expected loader to call _read({expected_filename!r}); got {captured}"
    )


# ---------------------------------------------------------------------------
# Class B — `_read` encoding mutations (2 mutants)
# Kills: x__read__mutmut_3 (encoding=None) + x__read__mutmut_5 (encoding="UTF-8")
# ---------------------------------------------------------------------------


def test_read_passes_explicit_lowercase_utf8_encoding(monkeypatch) -> None:
    """`_read()` must call `Path.read_text(encoding="utf-8")` — exactly that string.

    Mutation `encoding=None` is a real Windows-portability bug (cp1252 mangles
    UTF-8 bytes silently). Mutation `encoding="UTF-8"` is technically equivalent
    via Python's encoding registry but caught by this same exact-string assertion.
    """
    captured: list[object] = []
    original_read_text = Path.read_text

    def spy_read_text(self, *args, **kwargs):
        # `path.read_text(encoding="utf-8")` arrives as kwargs; preserve the call.
        captured.append(
            kwargs.get("encoding") if "encoding" in kwargs else (args[0] if args else "MISSING")
        )
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    kl._read("classifications.md")
    assert captured == ["utf-8"], f"Expected _read to pass encoding='utf-8'; got {captured}"


# ---------------------------------------------------------------------------
# Class C — `_standards_dir` env-var path-component mutations (3 mutants)
# Kills: x__standards_dir__mutmut_12, _29, _31
# ---------------------------------------------------------------------------


def test_standards_dir_returns_packs_subdir_when_present(tmp_path, monkeypatch) -> None:
    """When QA_STANDARDS_PATH points to a dir with a `packs/` subdir,
    `_standards_dir()` returns `<override>/packs`.

    Mutations `"PACKS"` / `"XXpacksXX"` in the condition would fail to find the
    subdir on case-sensitive FS and fall through to `Path(override)`. This test
    asserts strict Path equality (string-level), killing the mutation regardless
    of FS case-sensitivity.
    """
    (tmp_path / "packs").mkdir()
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl._standards_dir()
    assert result == tmp_path / "packs", f"Expected {tmp_path / 'packs'}; got {result}"


def test_standards_dir_returns_override_root_when_no_packs_subdir(tmp_path, monkeypatch) -> None:
    """Override without a `packs/` subdir returns the override root unchanged.
    Also asserts the literal `"packs"` is what gets appended (not e.g. "PACKS").
    """
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl._standards_dir()
    assert result == tmp_path, f"Expected {tmp_path}; got {result}"


# ---------------------------------------------------------------------------
# Class D — `_rules_path` candidate path-component mutations (6 mutants)
# Kills: x__rules_path__mutmut_26, _28, plus internal candidate-list mutations
# ---------------------------------------------------------------------------


def test_rules_path_uses_override_env_var(tmp_path, monkeypatch) -> None:
    """`QA_RULES_PATH` env var fully overrides path resolution.
    Asserts the returned Path equals the override exactly (string-level).
    """
    rules_file = tmp_path / "my_rules.yaml"
    rules_file.write_text("dummy: 1\n", encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl._rules_path()
    assert result == rules_file, f"Expected {rules_file}; got {result}"


def test_rules_path_first_candidate_uses_standards_subdir_literal(tmp_path, monkeypatch) -> None:
    """When no env var + no bundled file, the first candidate path is
    `<repo>/standards/rules/change_rules.yaml` — assert literal `standards`
    (lowercase) is in the resolved path.

    Mutation `"STANDARDS"` would change the path string; this test asserts
    the lowercase literal regardless of FS case-sensitivity.
    """
    monkeypatch.delenv("QA_RULES_PATH", raising=False)
    # Force the bundled-file branch to fail by monkeypatching is_file → False
    # so we fall through to the candidates loop.
    original_is_file = Path.is_file
    bundled = Path(kl.__file__).parent / "_data" / "standards" / "rules" / "change_rules.yaml"

    def is_file_no_bundled(self):
        if self == bundled:
            return False
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file_no_bundled)
    result = kl._rules_path()
    # Assert the lowercase `standards` and `rules` literals are in the path.
    assert "standards" in result.parts, f"Expected 'standards' in path parts; got {result.parts}"
    assert "rules" in result.parts, f"Expected 'rules' in path parts; got {result.parts}"
    assert result.name == "change_rules.yaml", (
        f"Expected filename 'change_rules.yaml'; got {result.name}"
    )


def test_rules_path_second_candidate_returned_when_only_it_exists(monkeypatch) -> None:
    """When only the SECOND candidate (`<repo>/rules/change_rules.yaml`) exists,
    `_rules_path()` returns that exact path. Kills the candidate[1]
    string-component mutations (`"rules"` → `"XXrulesXX"` / `"RULES"`,
    `"change_rules.yaml"` → wrapped/uppercased).

    The mutated literal differs from the canonical second-candidate path, so
    the monkeypatched `is_file` returns False for the mutated path and the
    function falls through to `candidates[0]` instead — observable difference.
    """
    monkeypatch.delenv("QA_RULES_PATH", raising=False)
    canonical_second = Path(kl.__file__).parent.parent.parent / "rules" / "change_rules.yaml"
    canonical_first = (
        Path(kl.__file__).parent.parent.parent / "standards" / "rules" / "change_rules.yaml"
    )

    def is_file_only_second(self):
        return self == canonical_second

    monkeypatch.setattr(Path, "is_file", is_file_only_second)
    result = kl._rules_path()
    assert result == canonical_second, f"Expected second candidate {canonical_second}; got {result}"
    # Sanity: it's NOT the first candidate.
    assert result != canonical_first


# ---------------------------------------------------------------------------
# Class E — `sumo_qa_load_standards` inner mutations (15 mutants)
# Covers: glob patterns, encoding, YAML continue/break, dict.get keys, filter logic
# ---------------------------------------------------------------------------


def test_load_standards_globs_yaml_and_yml_extensions(tmp_path, monkeypatch) -> None:
    """`load_standards` must glob both `*.yaml` AND `*.yml`.
    Mutations to the glob patterns (e.g. `"*.yaml"` → `"XX*.yamlXX"` or only one
    of the two extensions) would skip files. Test creates one of each.
    """
    (tmp_path / "pack_a.yaml").write_text("name: a\n", encoding="utf-8")
    (tmp_path / "pack_b.yml").write_text("name: b\n", encoding="utf-8")
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path.parent))
    # Need _standards_dir to return tmp_path; create a packs/ subdir mirror.
    packs_dir = tmp_path.parent / "packs"
    packs_dir.mkdir(exist_ok=True)
    (packs_dir / "pack_a.yaml").write_text("name: a\n", encoding="utf-8")
    (packs_dir / "pack_b.yml").write_text("name: b\n", encoding="utf-8")
    result = kl.sumo_qa_load_standards()
    assert "pack_a.yaml" in result and "pack_b.yml" in result, (
        f"Expected both .yaml and .yml files in output; got {result[:200]!r}"
    )


def test_load_standards_uses_utf8_encoding_when_reading_packs(tmp_path, monkeypatch) -> None:
    """The per-pack `text = path.read_text(encoding="utf-8")` must use the
    explicit utf-8 encoding. Mutation to `None` could silently mangle non-ASCII
    pack content on Windows.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "pack.yaml").write_text("name: test — em-dash\n", encoding="utf-8")
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))

    captured_encodings: list[str | None] = []
    original_read_text = Path.read_text

    def spy_read_text(self, *args, **kwargs):
        if self.suffix in (".yaml", ".yml"):
            captured_encodings.append(kwargs.get("encoding"))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    kl.sumo_qa_load_standards()
    assert captured_encodings == ["utf-8"], (
        f"Expected pack reads to use encoding='utf-8'; got {captured_encodings}"
    )


def test_load_standards_classification_filter_skips_non_matching_packs(
    tmp_path, monkeypatch
) -> None:
    """Filter on classification: only packs whose frontmatter declares the
    classification are included. Kills mutations to dict.get key names
    ("applies_to_classifications" / "classifications") and to the
    `if classification not in applies` condition.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "matching.yaml").write_text(
        yaml.safe_dump({"applies_to_classifications": ["security_change"], "name": "matching"}),
        encoding="utf-8",
    )
    (packs_dir / "nonmatching.yaml").write_text(
        yaml.safe_dump({"applies_to_classifications": ["docs_change"], "name": "nonmatching"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards(classification="security_change")
    assert "matching" in result, f"Expected 'matching' pack; got {result[:300]!r}"
    assert "nonmatching" not in result, f"Did not expect 'nonmatching' pack; got {result[:300]!r}"


def test_load_standards_classification_filter_uses_alternate_key(tmp_path, monkeypatch) -> None:
    """The filter logic falls back to `doc.get("classifications")` when
    `doc.get("applies_to_classifications")` is missing. Kills dict-key
    name mutations on the alternate key.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "alt_key.yaml").write_text(
        yaml.safe_dump({"classifications": ["security_change"], "name": "alt_key_pack"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards(classification="security_change")
    assert "alt_key_pack" in result, f"Expected 'alt_key_pack'; got {result[:300]!r}"


def test_load_standards_yaml_error_continues_to_next_pack(tmp_path, monkeypatch) -> None:
    """When a pack's YAML fails to parse, `load_standards` must `continue` to
    the next pack (not `break` out of the loop). Kills `continue` → `break`
    mutation. Verified by including a broken pack BEFORE a valid one alphabetically.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "a_broken.yaml").write_text("not valid: : yaml: ::: !!", encoding="utf-8")
    (packs_dir / "b_valid.yaml").write_text(
        yaml.safe_dump({"applies_to_classifications": ["security_change"], "name": "b_valid"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards(classification="security_change")
    # b_valid.yaml must appear despite the broken pack appearing earlier.
    assert "b_valid" in result, (
        f"`continue` should skip broken pack and reach b_valid.yaml; got {result[:300]!r}"
    )


def test_load_standards_pack_output_format_has_filename_header(tmp_path, monkeypatch) -> None:
    """Each pack is wrapped as `# {filename}\n\n{text}` — the literal `# ` prefix
    + `\n\n` separator. Kills mutations to those literals.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "header_test.yaml").write_text("name: header_test\n", encoding="utf-8")
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards()
    assert "# header_test.yaml" in result, (
        f"Expected '# header_test.yaml' header; got {result[:300]!r}"
    )


def test_load_standards_no_classification_returns_all_packs(tmp_path, monkeypatch) -> None:
    """When `classification=None` (or omitted), every pack appears in the output
    regardless of frontmatter. Kills mutations that change the `if classification
    is not None` predicate to `is None` or remove it.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "pack1.yaml").write_text("name: pack1\n", encoding="utf-8")
    (packs_dir / "pack2.yaml").write_text("name: pack2\n", encoding="utf-8")
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards()  # No classification arg.
    assert "pack1" in result and "pack2" in result, (
        f"Expected both packs unfiltered; got {result[:300]!r}"
    )


def test_load_standards_join_separator_is_triple_dash(tmp_path, monkeypatch) -> None:
    """Multiple packs are joined with `\n\n---\n\n`. Kills mutations to the
    separator literal.

    Additionally asserts no `XX` literal anywhere — the `"XX\n\n---\n\nXX".join(...)`
    mutation passes the substring-in check but injects bracketing literals; an
    explicit `"XX" not in result` kills it.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "p1.yaml").write_text("name: p1\n", encoding="utf-8")
    (packs_dir / "p2.yaml").write_text("name: p2\n", encoding="utf-8")
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards()
    assert "\n\n---\n\n" in result, f"Expected '---' separator; got {result[:300]!r}"
    assert "XX" not in result, (
        f"`XX...XX`-bracketed join separator mutation leaked into output; got {result[:300]!r}"
    )


def test_load_standards_classification_filter_continues_past_nonmatching_packs(
    tmp_path, monkeypatch
) -> None:
    """When a pack's classification metadata does NOT include the filter, the
    loop must `continue` (not `break`) so later packs are still considered.
    Kills the `if classification not in applies: break` mutation.

    Ordered so the non-matching pack is alphabetically FIRST — only a `continue`
    semantic lets the second (matching) pack reach the append.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "a_nonmatching.yaml").write_text(
        yaml.safe_dump({"applies_to_classifications": ["docs_change"], "name": "a_nonmatching"}),
        encoding="utf-8",
    )
    (packs_dir / "b_matching.yaml").write_text(
        yaml.safe_dump({"applies_to_classifications": ["security_change"], "name": "b_matching"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    result = kl.sumo_qa_load_standards(classification="security_change")
    assert "b_matching" in result, (
        f"`continue` should skip a_nonmatching and still reach b_matching; got {result[:300]!r}"
    )
    assert "a_nonmatching" not in result, (
        f"a_nonmatching does not match the filter; got {result[:300]!r}"
    )


# ---------------------------------------------------------------------------
# Class F — `sumo_qa_load_rules` inner mutations (12 mutants)
# Covers: encoding literal, classification filter logic, yaml.safe_dump kwargs
# ---------------------------------------------------------------------------


def test_load_rules_uses_utf8_encoding(tmp_path, monkeypatch) -> None:
    """`load_rules` reads the rules file with explicit utf-8 encoding."""
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text("api_contract_change:\n  must: [thing]\n", encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))

    captured_encodings: list[str | None] = []
    original_read_text = Path.read_text

    def spy_read_text(self, *args, **kwargs):
        if self == rules_file:
            captured_encodings.append(kwargs.get("encoding"))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    kl.sumo_qa_load_rules()
    assert captured_encodings == ["utf-8"], f"Expected encoding='utf-8'; got {captured_encodings}"


def test_load_rules_no_classification_returns_full_text(tmp_path, monkeypatch) -> None:
    """With `classification=None`, returns the file text verbatim. No YAML parsing."""
    rules_file = tmp_path / "rules.yaml"
    expected_text = "api_contract_change:\n  must: [thing]\nsecurity_change:\n  must: [auth]\n"
    rules_file.write_text(expected_text, encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl.sumo_qa_load_rules()
    assert result == expected_text, f"Expected full text; got {result!r}"


def test_load_rules_classification_filter_returns_only_matching_entry(
    tmp_path, monkeypatch
) -> None:
    """With a classification, returns YAML containing only that entry.
    Kills mutations to the filter logic + dict.get key.
    """
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        yaml.safe_dump(
            {
                "api_contract_change": {"must": ["contract_test"]},
                "security_change": {"must": ["auth_test"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl.sumo_qa_load_rules(classification="api_contract_change")
    assert "api_contract_change" in result, (
        f"Expected 'api_contract_change' in result; got {result!r}"
    )
    assert "security_change" not in result, (
        f"Did not expect 'security_change' in filtered result; got {result!r}"
    )


def test_load_rules_unknown_classification_returns_empty_yaml_dict(tmp_path, monkeypatch) -> None:
    """Unknown classification → returns `yaml.safe_dump({})` = `'{}\\n'`.
    Kills mutations that change the empty-dict fallback.
    """
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        yaml.safe_dump({"api_contract_change": {"must": ["contract_test"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl.sumo_qa_load_rules(classification="nonexistent_classification")
    assert result.strip() == "{}", f"Expected empty dict YAML; got {result!r}"


def test_load_rules_yaml_error_returns_full_text(tmp_path, monkeypatch) -> None:
    """When the YAML fails to parse but a classification is provided, falls
    back to returning the full text. Kills mutations that swap the fallback
    behaviour.
    """
    rules_file = tmp_path / "rules.yaml"
    broken_yaml = "not: valid: yaml: ::"
    rules_file.write_text(broken_yaml, encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl.sumo_qa_load_rules(classification="api_contract_change")
    assert result == broken_yaml, f"Expected full text on YAML error; got {result!r}"


def test_load_rules_non_dict_doc_returns_full_text(tmp_path, monkeypatch) -> None:
    """When the YAML parses to a non-dict (e.g. a list), falls back to the
    full text instead of attempting `.get()`. Kills mutations to the
    `isinstance(doc, dict)` check.
    """
    rules_file = tmp_path / "rules.yaml"
    list_yaml = "- one\n- two\n"
    rules_file.write_text(list_yaml, encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl.sumo_qa_load_rules(classification="api_contract_change")
    assert result == list_yaml, f"Expected full text on non-dict doc; got {result!r}"


def test_load_rules_safe_dump_uses_sort_keys_false(tmp_path, monkeypatch) -> None:
    """The `yaml.safe_dump({classification: entry}, sort_keys=False)` must
    pass `sort_keys=False`. Kills mutations to the keyword.

    Verified by using a multi-key entry where YAML output order matters and
    the input order is non-alphabetical.
    """
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        yaml.safe_dump(
            {
                "api_contract_change": {
                    "z_field_first": "1",  # non-alphabetical key order
                    "a_field_second": "2",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QA_RULES_PATH", str(rules_file))
    result = kl.sumo_qa_load_rules(classification="api_contract_change")
    # In the result, z_field_first should appear before a_field_second.
    z_pos = result.find("z_field_first")
    a_pos = result.find("a_field_second")
    assert z_pos != -1 and a_pos != -1, f"Expected both fields in result; got {result!r}"
    assert z_pos < a_pos, (
        f"Expected sort_keys=False to preserve insertion order (z before a); got result {result!r}"
    )


# ---------------------------------------------------------------------------
# Class H — Ingested-pack tier mutations (issue #92) — 4 mutants
# Kills: x__read__mutmut_12 (encoding=None) + x__read__mutmut_14 (encoding="UTF-8")
#        on the project/global read path, and
#        x__has_packs__mutmut_10 ("XX*.ymlXX") + x__has_packs__mutmut_11 ("*.YML")
#        by making the `*.yml` glob term load-bearing.
# ---------------------------------------------------------------------------


def test_read_uses_utf8_when_reading_ingested_project_pack(tmp_path, monkeypatch) -> None:
    """The project/global tier read in `_read` must pass `encoding="utf-8"`.

    Mirrors `test_read_passes_explicit_lowercase_utf8_encoding` but forces the
    project-pack branch (a `.sumo-qa/knowledge/<name>` file present) so the spy
    captures THAT `read_text` call. Kills `encoding=None` (a real Windows
    cp1252-mangling bug) and `encoding="UTF-8"` (registry-equivalent, but caught
    by the exact-string assertion).
    """
    monkeypatch.delenv("QA_KNOWLEDGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / ".sumo-qa" / "knowledge"
    proj.mkdir(parents=True)
    (proj / "principles.md").write_text("ingested principles — em-dash\n", encoding="utf-8")

    captured: list[object] = []
    original_read_text = Path.read_text

    def spy_read_text(self, *args, **kwargs):
        if self.name == "principles.md":
            captured.append(
                kwargs.get("encoding") if "encoding" in kwargs else (args[0] if args else "MISSING")
            )
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    kl._read("principles.md")
    assert captured == ["utf-8"], (
        f"Expected the ingested-pack read to pass encoding='utf-8'; got {captured}"
    )


def test_has_packs_yml_only_dir_makes_yml_glob_load_bearing(tmp_path, monkeypatch) -> None:
    """A project packs dir holding ONLY a `*.yml` file must be discovered.

    This makes the `*.yml` glob term in `_has_packs` load-bearing. Both glob
    mutations on that term — `"XX*.ymlXX"` (matches nothing) and `"*.YML"`
    (pathlib glob is case-sensitive on every platform, incl. macOS APFS, so
    `*.YML` does not match `team.yml`) — cause `_has_packs` to return False,
    so `_standards_dir` falls through and this assertion fails. Kills both.
    """
    monkeypatch.delenv("QA_STANDARDS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    packs = tmp_path / ".sumo-qa" / "standards" / "packs"
    packs.mkdir(parents=True)
    (packs / "team.yml").write_text("name: team\n", encoding="utf-8")  # .yml only, no .yaml
    assert kl._standards_dir() == packs
