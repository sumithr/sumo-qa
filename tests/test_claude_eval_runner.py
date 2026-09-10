# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the offline core of the Claude skill-eval runner.

Slice 1 of epic #660 (issue #661). The runner under test lives in
``tests/evals/claude/`` and is importable as ``claude`` because
``tests/evals`` is on ``[tool.pytest.ini_options].pythonpath``.

Everything here is offline: no Anthropic SDK, no network, no model ids.
The runner loads the EXISTING promptfoo YAML schema, resolves ``file://``
vars, renders ``{{var}}`` templates, evaluates the deterministic
``javascript`` assertions in Python, parses (never executes) ``llm-rubric``
assertions, and counts dry-run input tokens.
"""

from __future__ import annotations

import ast
import http.client
import json
import multiprocessing
import os
import re
import socket
import subprocess
from pathlib import Path

import pytest
from claude import assertions as ca
from claude import cli as ccli
from claude import loader as cl
from claude import templating as ct
from claude import tokens as ctok

# --------------------------------------------------------------------------
# Grounded inventory, verified against origin/main @ e7809d1 on 2026-09-09.
# Issue #661's body says 65 configs; the live tree holds 65 `*.yaml` files in
# `tests/evals/promptfoo/`, of which promptfoo itself RUNS 61: `npm run
# eval:all` globs `skill-*.yaml` and skips `*.gen.yaml` (two generator seeds
# whose own headers say they are not for running evals), and the two
# gitignored `*.generated-tests.yaml` files are test-include payloads, not
# configs. The runner excludes those two on top of `eval:all`'s own rule, so
# its selection is deliberately STRICTER than the shell script's: that glob
# would hand `promptfoo eval -c` a bare YAML list and fail. 61 is the number
# of real configs, which is what slice 3 compares config-for-config.
# These constants are a deliberate tripwire: if the matrix grows or shrinks,
# this test fails and whoever changed it updates the number here and on the
# epic, rather than the change passing silently.
# --------------------------------------------------------------------------
EXPECTED_CONFIG_COUNT = 61
EXPECTED_AB_CONFIG_COUNT = 15
EXPECTED_JAVASCRIPT_ASSERT_COUNT = 10

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"

# A `{{ var }}` interpolation, spelled out here rather than imported from the
# renderer so this file never asks the code under test whether its own output
# still holds placeholders.
LEFTOVER_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")


def _expected_selection(directory: Path) -> list[Path]:
    """The runner's selection rule, restated independently of the runner.

    `skill-*.yaml`, minus `*.gen.yaml` (generator seeds) and minus
    `*.generated-tests.yaml` (gitignored `tests:` include payloads - bare YAML
    lists, not configs). Spelled out here rather than imported so the test
    does not ask the code under test what its own rule is.

    This is stricter than `npm run eval:all`, which excludes only
    `*.gen.yaml`. Nothing here reads `package.json`: that file is deleted in a
    later slice of the epic, and coupling discovery to it would make this test
    fail for a reason that has nothing to do with discovery.
    """
    return sorted(
        p
        for p in directory.glob("skill-*.yaml")
        if not p.name.endswith((".gen.yaml", ".generated-tests.yaml"))
    )


# ==========================================================================
# Loader: reads every config in the live matrix
#
# Risk: the runner silently skips or crashes on a config, so the replacement
# matrix runs fewer scenarios than promptfoo does and the parity claim in
# slice 3 is built on a short read.
# Technique: equivalence partitioning over the config classes actually
# present (plain skill config, .ab.yaml A/B control, .gen.yaml generator
# seed, and a config whose `tests:` include is gitignored/absent).
# ==========================================================================


def test_loader_reads_every_config_in_the_live_matrix():
    paths = cl.discover_configs(PROMPTFOO_DIR)

    assert paths == _expected_selection(PROMPTFOO_DIR)
    assert len(paths) == EXPECTED_CONFIG_COUNT, (
        f"promptfoo matrix drifted: {len(paths)} configs selected, "
        f"{EXPECTED_CONFIG_COUNT} recorded. Update the constant and the epic."
    )

    configs = cl.load_all_configs(PROMPTFOO_DIR)
    assert len(configs) == EXPECTED_CONFIG_COUNT
    assert all(c.description for c in configs)


def test_discovery_excludes_the_generator_seeds_promptfoo_skips():
    """`eval:all` skips `*.gen.yaml` too; counting them reports a matrix
    promptfoo never runs, corrupting slice 3's config-for-config parity."""
    seeds = {p.name for p in PROMPTFOO_DIR.glob("*.gen.yaml")}
    selected = {p.name for p in cl.discover_configs(PROMPTFOO_DIR)}

    assert seeds, "expected the two generator seeds to still be on disk"
    assert not (selected & seeds)


def test_discovery_keeps_only_real_configs_in_a_mixed_directory(tmp_path):
    """A generator seed and a generated-tests payload sitting next to a real
    config: neither may be treated as a config. The payload is a bare YAML
    LIST, so treating it as one used to die with a raw AttributeError.

    `*.generated-tests.yaml` is where this selection is deliberately STRICTER
    than `npm run eval:all`, whose glob matches it and whose `*.gen.yaml`
    case does not exclude it. Matching that would mean handing promptfoo a
    file that is not a config, which is a latent bug in the shell script, not
    a behaviour worth reproducing."""
    (tmp_path / "skill-real.yaml").write_text(
        "description: d\nproviders: [echo]\nprompts: ['{{q}}']\ntests:\n  - vars: {q: hi}\n",
        encoding="utf-8",
    )
    (tmp_path / "skill-real.gen.yaml").write_text(
        "description: generator seed, not for running evals\nprompts: ['x']\n",
        encoding="utf-8",
    )
    (tmp_path / "skill-real.generated-tests.yaml").write_text(
        "- vars:\n    q: generated\n", encoding="utf-8"
    )
    (tmp_path / "promptfooconfig.yaml").write_text("description: not a skill config\n")

    selected = cl.discover_configs(tmp_path)

    assert [p.name for p in selected] == ["skill-real.yaml"]
    assert [c.description for c in cl.load_all_configs(tmp_path)] == ["d"]


def test_load_config_names_the_file_when_its_top_level_is_not_a_mapping(tmp_path):
    """A stray YAML that reaches `load_config` must fail with an error that
    names it, never a bare `AttributeError: 'list' object has no attribute
    'get'` from deep inside the parser."""
    stray = tmp_path / "skill-x.generated-tests.yaml"
    stray.write_text("- vars:\n    q: hi\n- vars:\n    q: there\n", encoding="utf-8")

    with pytest.raises(cl.MalformedConfigError) as excinfo:
        cl.load_config(stray)

    message = str(excinfo.value)
    assert stray.name in message
    assert "list" in message


@pytest.mark.parametrize(
    ("body", "described"),
    [
        pytest.param("- vars:\n    q: hi\n", "list", id="non-empty-list"),
        pytest.param("[]\n", "list", id="empty-list"),
        pytest.param("{}\n", None, id="empty-mapping-is-a-config"),
        pytest.param("false\n", "bool", id="false"),
        pytest.param("0\n", "int", id="zero"),
        pytest.param('""\n', "str", id="empty-string"),
        pytest.param("null\n", "empty document", id="explicit-null"),
        pytest.param("", "empty document", id="empty-file"),
        pytest.param("# only a comment\n", "empty document", id="comments-only"),
    ],
)
def test_a_falsy_top_level_is_refused_instead_of_loading_as_an_empty_config(
    tmp_path, body, described
):
    """Equivalence partitioning over YAML's falsy top levels.

    `yaml.safe_load(...) or {}` would run BEFORE the mapping check and turn
    every one of these into a silently-empty config: a truncated or clobbered
    file would then sit in the matrix contributing zero cases while still
    being counted as one. Only a real mapping - `{}` included - is a config.
    """
    stray = tmp_path / "skill-x.yaml"
    stray.write_text(body, encoding="utf-8")

    if described is None:
        assert cl.load_config(stray).tests == []
        return

    with pytest.raises(cl.MalformedConfigError) as excinfo:
        cl.load_config(stray)

    message = str(excinfo.value)
    assert stray.name in message
    assert described in message


def test_ab_subset_is_the_fifteen_ab_yaml_configs():
    configs = cl.load_all_configs(PROMPTFOO_DIR)
    ab = [c for c in configs if c.is_ab]

    assert len(ab) == EXPECTED_AB_CONFIG_COUNT
    assert {c.path.name for c in ab} == {p.name for p in PROMPTFOO_DIR.glob("*.ab.yaml")}
    assert all(c.disable_var_expansion for c in ab)


def test_missing_generated_tests_include_is_warned_not_fatal(tmp_path):
    """`tests: file://...generated-tests.yaml` is gitignored and absent on a
    fresh clone. Loading must degrade to zero tests plus a warning."""
    config = tmp_path / "skill-x.yaml"
    config.write_text(
        "description: d\n"
        "providers: [echo]\n"
        "prompts: ['{{q}}']\n"
        "tests: file://skill-x.generated-tests.yaml\n",
        encoding="utf-8",
    )

    loaded = cl.load_config(config)

    assert loaded.tests == []
    assert any("generated-tests" in w for w in loaded.warnings)


def test_present_tests_include_is_loaded_from_the_referenced_file(tmp_path):
    (tmp_path / "gen.yaml").write_text(
        "- vars:\n    q: hello\n- vars:\n    q: world\n", encoding="utf-8"
    )
    config = tmp_path / "skill-x.yaml"
    config.write_text(
        "description: d\nproviders: [echo]\nprompts: ['{{q}}']\ntests: file://gen.yaml\n",
        encoding="utf-8",
    )

    loaded = cl.load_config(config)

    assert [t.vars["q"] for t in loaded.tests] == ["hello", "world"]
    assert loaded.warnings == []


# ==========================================================================
# file:// var resolution
#
# Risk: the resolver resolves against the process cwd instead of the config's
# own directory, so `file://../../../skills/<skill>/SKILL.md` silently loads
# the wrong file (or nothing) and every scenario grades a candidate that
# never saw the skill.
# Technique: equivalence partitioning over path classes: same directory,
# a path escaping the config directory, and a missing target.
# ==========================================================================


def test_file_url_var_resolves_relative_to_the_config_directory(tmp_path):
    (tmp_path / "sibling.md").write_text("SIBLING BODY", encoding="utf-8")

    assert cl.resolve_var_value("file://sibling.md", tmp_path) == "SIBLING BODY"


def test_file_url_var_resolves_a_path_escaping_the_config_directory(tmp_path):
    deep = tmp_path / "tests" / "evals" / "promptfoo"
    deep.mkdir(parents=True)
    skill = tmp_path / "skills" / "sumo-qa-example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("ESCAPED SKILL BODY", encoding="utf-8")

    resolved = cl.resolve_var_value("file://../../../skills/sumo-qa-example/SKILL.md", deep)

    assert resolved == "ESCAPED SKILL BODY"


def test_file_url_var_resolution_is_not_relative_to_the_process_cwd(tmp_path, monkeypatch):
    """Same basename in cwd and in the config dir: the config dir must win."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "decoy.md").write_text("WRONG (cwd)", encoding="utf-8")
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "decoy.md").write_text("RIGHT (config dir)", encoding="utf-8")
    monkeypatch.chdir(cwd)

    assert cl.resolve_var_value("file://decoy.md", conf_dir) == "RIGHT (config dir)"


def test_missing_file_url_var_raises_pointing_at_the_resolved_path(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        cl.resolve_var_value("file://nope.md", tmp_path)

    assert "nope.md" in str(excinfo.value)


def test_non_file_url_var_values_pass_through_untouched(tmp_path):
    assert cl.resolve_var_value("plain string", tmp_path) == "plain string"
    assert cl.resolve_var_value(["a", "b"], tmp_path) == ["a", "b"]
    assert cl.resolve_var_value(True, tmp_path) is True


def test_a_real_config_loads_its_skill_body_through_the_file_url_var():
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    body = config.default_vars["skill_content"]

    assert "sumo-qa-closing-qa-gaps" in body
    assert len(body) > 1000


# --- .yaml/.yml file vars are injected as compact JSON (promptfoo 0.121.20:
#     `vars[varName] = JSON.stringify(loadYaml(readFile(...)))`) ---


def test_yaml_file_var_is_injected_as_compact_json_in_document_order(tmp_path):
    (tmp_path / "rules.yaml").write_text(
        "beta:\n  - 1\n  - two\nalpha:\n  nested: true\n  missing: null\n",
        encoding="utf-8",
    )

    resolved = cl.resolve_var_value("file://rules.yaml", tmp_path)

    assert resolved == '{"beta":[1,"two"],"alpha":{"nested":true,"missing":null}}'


def test_yml_file_var_is_injected_as_json_too(tmp_path):
    (tmp_path / "pack.yml").write_text("id: p1\nchecks:\n  - a\n  - b\n", encoding="utf-8")

    assert cl.resolve_var_value("file://pack.yml", tmp_path) == '{"id":"p1","checks":["a","b"]}'


def test_yaml_file_var_keeps_non_ascii_unescaped_like_json_stringify(tmp_path):
    (tmp_path / "r.yaml").write_text('note: "café — ok"\n', encoding="utf-8")

    assert cl.resolve_var_value("file://r.yaml", tmp_path) == '{"note":"café — ok"}'


def test_yaml_timestamps_serialise_like_javascript_dates(tmp_path):
    """js-yaml resolves a timestamp to a `Date`, which `JSON.stringify` writes
    as a UTC ISO string; `json.dumps` would otherwise refuse a `datetime`."""
    (tmp_path / "t.yaml").write_text(
        "day: 2026-09-09\nmoment: 2026-09-09T03:04:05.6Z\n", encoding="utf-8"
    )

    assert cl.resolve_var_value("file://t.yaml", tmp_path) == (
        '{"day":"2026-09-09T00:00:00.000Z","moment":"2026-09-09T03:04:05.600Z"}'
    )


def test_a_yaml_value_javascript_never_produces_is_refused(tmp_path):
    """A `!!set` resolves to a Python `set`, which has no `JSON.stringify`
    equivalent: fail loudly rather than inject something promptfoo never
    would."""
    (tmp_path / "s.yaml").write_text("k: !!set\n  ? a\n  ? b\n", encoding="utf-8")

    with pytest.raises(TypeError, match="JSON.stringify"):
        cl.resolve_var_value("file://s.yaml", tmp_path)


def test_non_finite_yaml_numbers_serialise_as_null_like_json_stringify(tmp_path):
    """`JSON.stringify` has no JSON literal for `NaN`/`Infinity` and writes
    `null` for all three; `json.dumps` defaults to the non-standard `NaN`,
    `Infinity` and `-Infinity` tokens, which promptfoo would never inject.

    A `default=` hook cannot fix this - a float is already serialisable, so
    the hook never fires - so the parsed structure is walked instead. The
    nesting here proves the walk reaches into mappings and lists, not just
    top-level scalars.
    """
    (tmp_path / "n.yaml").write_text(
        "nan: .nan\ninf: .inf\nninf: -.inf\nnested:\n  deep: .nan\nlisted: [.inf, 1.5]\n",
        encoding="utf-8",
    )

    assert cl.resolve_var_value("file://n.yaml", tmp_path) == (
        '{"nan":null,"inf":null,"ninf":null,"nested":{"deep":null},"listed":[null,1.5]}'
    )


def test_finite_numbers_and_booleans_are_untouched_by_the_non_finite_walk(tmp_path):
    """`isinstance(True, float)` is False, and a finite float must keep its
    value: the walk must not flatten ordinary numbers to `null`."""
    (tmp_path / "f.yaml").write_text("a: 0\nb: 1.25\nc: true\nd: false\n", encoding="utf-8")

    assert cl.resolve_var_value("file://f.yaml", tmp_path) == (
        '{"a":0,"b":1.25,"c":true,"d":false}'
    )


def test_non_yaml_file_vars_keep_their_raw_text(tmp_path):
    (tmp_path / "skill.md").write_text("# Title\n\n- bullet\n", encoding="utf-8")

    assert cl.resolve_var_value("file://skill.md", tmp_path) == "# Title\n\n- bullet"


def test_the_live_security_testing_config_injects_its_yaml_vars_as_json():
    """`skill-security-testing.yaml:18-19` loads `change_rules.yaml` and
    `qa_shift_left_v1.yml` and interpolates them at :107 and :111."""
    config = cl.load_config(PROMPTFOO_DIR / "skill-security-testing.yaml")
    rules = config.default_vars["rules"]
    standards = config.default_vars["standards"]

    assert rules.startswith('{"api_contract_change":{"must_consider":["backward compatibility"')
    assert "\n" not in rules
    assert json.loads(rules)["api_contract_change"]["suggested_test_types"] == [
        "contract",
        "integration",
        "functional",
    ]
    assert standards.startswith('{"id":"qa-shift-left-core","version":"1.0.0"')
    assert "\n" not in standards
    assert json.loads(standards)["domain"] == "qa"


# --- terminal-newline handling (promptfoo trims file-backed vars, then strips
#     ONE terminal newline from every string var before rendering) ---


def test_file_backed_var_is_trimmed_at_both_ends(tmp_path):
    (tmp_path / "body.md").write_text("\n\n  BODY  \n\n", encoding="utf-8")

    assert cl.resolve_var_value("file://body.md", tmp_path) == "BODY"


def test_a_literal_string_var_loses_exactly_one_terminal_newline(tmp_path):
    """`replace(/\\n$/, '')`, not a trim: an inner blank line survives."""
    config = tmp_path / "skill-x.yaml"
    config.write_text(
        "description: d\n"
        "providers: [echo]\n"
        "prompts: ['[{{ blk }}]']\n"
        "tests:\n"
        '  - vars: {blk: "line\\n\\n", spaced: "  keep  "}\n',
        encoding="utf-8",
    )

    case = cl.build_cases(cl.load_config(config))[0]

    assert case.vars["blk"] == "line\n"
    assert case.vars["spaced"] == "  keep  "
    assert case.rendered_prompt == "[line\n]"


def test_live_block_scalar_and_skill_body_vars_have_no_terminal_newline():
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    case = next(c for c in cl.build_cases(config) if "ground_truth_context" in c.vars)

    assert not case.vars["ground_truth_context"].endswith("\n")
    assert not case.vars["skill_content"].endswith("\n")


# ==========================================================================
# disableVarExpansion
#
# Risk: promptfoo expands a list-valued var into one test per item unless
# expansion is disabled. Getting this wrong turns a 3-test config into a
# 30-test one and drops the anti-pattern LIST the rubric iterates over.
# Technique: decision tables over (top-level flag, options flag, var type).
# ==========================================================================


def _mini_config(tmp_path, *, top_level=None, options=None):
    lines = ["description: d", "providers: [echo]", "prompts: ['{{ aps }}']"]
    if top_level is not None:
        lines.insert(0, f"disableVarExpansion: {str(top_level).lower()}")
    lines.append("defaultTest:")
    lines.append("  vars:")
    lines.append("    aps: [one, two, three]")
    if options is not None:
        lines.append("  options:")
        lines.append(f"    disableVarExpansion: {str(options).lower()}")
    lines.append("tests:")
    lines.append("  - description: t")
    path = tmp_path / "skill-mini.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("top_level", "options"),
    [(True, None), (None, True), (True, True), (False, True), (True, False)],
)
def test_disable_var_expansion_keeps_a_list_var_as_one_case(tmp_path, top_level, options):
    """Either flag disables expansion (promptfoo ORs them)."""
    cases = cl.build_cases(
        cl.load_config(_mini_config(tmp_path, top_level=top_level, options=options))
    )

    assert len(cases) == 1
    assert cases[0].vars["aps"] == ["one", "two", "three"]
    assert cases[0].rendered_prompt == "one,two,three"


@pytest.mark.parametrize(("top_level", "options"), [(None, None), (False, None), (False, False)])
def test_expansion_enabled_explodes_a_list_var_into_one_case_per_item(tmp_path, top_level, options):
    cases = cl.build_cases(
        cl.load_config(_mini_config(tmp_path, top_level=top_level, options=options))
    )

    assert len(cases) == 3
    assert [c.vars["aps"] for c in cases] == ["one", "two", "three"]
    assert [c.rendered_prompt for c in cases] == ["one", "two", "three"]


def test_every_live_ab_config_disables_expansion_at_the_top_level():
    for path in sorted(PROMPTFOO_DIR.glob("*.ab.yaml")):
        assert cl.load_config(path).disable_var_expansion is True


# ==========================================================================
# Template rendering
#
# Risk: the prompt handed to the candidate differs from the one promptfoo
# builds, so a parity comparison in slice 3 measures the renderer, not the
# skill.
# Technique: equivalence partitioning over value shapes (scalar, list, bool,
# missing) plus the one control structure the rubrics actually use.
# ==========================================================================


def test_render_interpolates_scalars_with_and_without_inner_spaces():
    assert ct.render("a {{x}} b {{ x }} c", {"x": "V"}) == "a V b V c"


def test_render_joins_a_list_var_with_commas_like_nunjucks():
    assert ct.render("{{ aps }}", {"aps": ["a", "b"]}) == "a,b"


def test_render_writes_booleans_lowercase_like_nunjucks():
    assert ct.render("{{ f }}", {"f": True}) == "true"
    assert ct.render("{{ f }}", {"f": False}) == "false"


def test_render_treats_an_unknown_var_as_empty():
    assert ct.render("[{{ missing }}]", {}) == "[]"


def test_render_iterates_a_for_loop_over_a_list_var():
    rendered = ct.render(
        "{% for ap in anti_patterns %}\n- {{ ap }}\n{% endfor %}",
        {"anti_patterns": ["first", "second"]},
    )

    assert "- first" in rendered
    assert "- second" in rendered
    assert "{%" not in rendered


def test_render_of_a_for_loop_over_a_missing_var_emits_nothing():
    assert ct.render("x{% for a in nope %}{{ a }}{% endfor %}y", {}) == "xy"


def test_render_leaves_unmatched_braces_alone():
    assert ct.render("{ not a placeholder }", {}) == "{ not a placeholder }"


# ==========================================================================
# Assertions: the ten javascript asserts and the llm-rubric parser
#
# Risk (1): a ported evaluator diverges from the JS original, so the Python
# gate passes an output promptfoo fails (or vice versa) and slice 3's parity
# run is measuring the port's bugs.
# Risk (2, security-relevant): the runner executes the config-supplied
# `value:` as code. The YAML is repo-owned today but the loader also reads
# `file://` targets; executing them would turn a config edit into arbitrary
# code execution inside CI.
# Technique: equivalence partitioning, one passing and one failing output per
# assertion.
# ==========================================================================

SECURITY_PASS = (
    "A non-owner can read any document: no negative-path test asserts the authorisation failure."
)
SECURITY_FAIL = "Add a unit test for the sorting helper and one for the empty list."

RETROSPECTIVE_PASS = (
    "Restore the pre-fix file with `git show abc1234:src/pricing.py > "
    "src/pricing.py`, run the test to capture the red assertion, then reverse "
    "with `git checkout -- src/pricing.py` before the final green run."
)
RETROSPECTIVE_FAIL = (
    "Roll the tree back with `git reset --hard abc1234`, run the test, then pull the branch again."
)

# Keyed by (config filename, evaluator kind). Every javascript assert in the
# live matrix must appear here with a passing and a failing candidate output.
JAVASCRIPT_ASSERT_EXPECTATIONS = {
    ("skill-answering-testing-question-security-relevance.yaml", "security-relevance"): (
        SECURITY_PASS,
        SECURITY_FAIL,
        {"security_must_appear": True},
    ),
    ("skill-preparing-for-work-security-relevance.yaml", "security-relevance"): (
        SECURITY_PASS,
        SECURITY_FAIL,
        {"security_must_appear": True},
    ),
    ("skill-reviewing-before-merge-security-relevance.yaml", "security-relevance"): (
        SECURITY_PASS,
        SECURITY_FAIL,
        {"security_must_appear": True},
    ),
    ("skill-closing-qa-gaps.yaml", "regex-test"): (
        "Closing one QA gap at a time. Starting with the uncovered branch.",
        "Sure, I can help with that. Here is the fix.",
        {},
    ),
    ("skill-security-testing.yaml", "regex-test"): (
        "Focusing the security test evidence on the token refresh path.",
        "Here is a list of security tests you could run.",
        {},
    ),
    ("skill-triaging-test-failures.yaml", "regex-test"): (
        "Triaging this failure before any fix. The output shows a timeout.",
        "The test fails because the fixture is stale; here is the patch.",
        {},
    ),
    ("skill-implementing-with-tdd.yaml", "cites-catalogue-technique"): (
        "Applying boundary value analysis to the discount threshold.",
        "I will write a quick test for the discount threshold.",
        {},
    ),
    ("skill-implementing-with-tdd.ab.yaml", "cites-catalogue-technique"): (
        "Applying boundary value analysis to the discount threshold.",
        "I will write a quick test for the discount threshold.",
        {},
    ),
    ("skill-implementing-with-tdd-retrospective.yaml", "cites-catalogue-technique"): (
        "Applying boundary value analysis to the discount threshold.",
        "I will write a quick test for the discount threshold.",
        {},
    ),
    ("skill-implementing-with-tdd-retrospective.yaml", "retrospective-restore"): (
        RETROSPECTIVE_PASS,
        RETROSPECTIVE_FAIL,
        {},
    ),
}


def _live_javascript_asserts():
    found = []
    for config in cl.load_all_configs(PROMPTFOO_DIR):
        for assertion in config.all_assertions():
            if isinstance(assertion, ca.JavascriptAssertion):
                found.append((config.path.name, assertion))
    return found


def test_the_live_matrix_still_holds_exactly_ten_javascript_asserts():
    assert len(_live_javascript_asserts()) == EXPECTED_JAVASCRIPT_ASSERT_COUNT


def test_every_live_javascript_assert_maps_to_a_python_evaluator():
    keys = {(name, ca.evaluator_for(a).kind) for name, a in _live_javascript_asserts()}

    assert keys == set(JAVASCRIPT_ASSERT_EXPECTATIONS)


@pytest.mark.parametrize(
    "key", sorted(JAVASCRIPT_ASSERT_EXPECTATIONS), ids=lambda k: f"{k[0]}::{k[1]}"
)
def test_each_javascript_evaluator_passes_and_fails_the_right_output(key):
    config_name, kind = key
    passing, failing, context_vars = JAVASCRIPT_ASSERT_EXPECTATIONS[key]
    assertion = next(
        a
        for name, a in _live_javascript_asserts()
        if name == config_name and ca.evaluator_for(a).kind == kind
    )
    evaluator = ca.evaluator_for(assertion)

    good = evaluator.evaluate(passing, context_vars)
    bad = evaluator.evaluate(failing, context_vars)

    assert good.passed is True, good.reason
    assert good.score == 1
    assert bad.passed is False, bad.reason
    assert bad.score == 0
    assert bad.reason


def test_security_relevance_omission_seed_never_hard_fails():
    """The JS delegates the fabricated-security direction to the rubric."""
    assertion = next(
        a
        for name, a in _live_javascript_asserts()
        if name == "skill-preparing-for-work-security-relevance.yaml"
    )
    evaluator = ca.evaluator_for(assertion)

    assert evaluator.evaluate(SECURITY_FAIL, {"security_must_appear": False}).passed
    assert evaluator.evaluate(SECURITY_PASS, {"security_must_appear": False}).passed


# --- securityTerms regex flags are translated or refused, never dropped ----
#
# Risk: the `securityTerms` matcher lifts only the BODY of the JS regex. The
# three live regexes carry no flags, so nothing diverges today - but a flag
# added to one of them in the YAML would be silently discarded and the Python
# gate would quietly stop agreeing with promptfoo's. In a runner whose whole
# value is fidelity, a silent wrong is the worst outcome, so a flag is either
# translated into genuinely equivalent Python or raises.
# Technique: equivalence partitioning over the flag alphabet - BOTH halves,
# since a guard that only ever refuses would pass a test suite that only ever
# checks refusals - plus a guard test pinning the three live (unflagged)
# asserts against this hardening.

# The guard's flag policy, in one place, because BOTH lifted-regex paths
# (`regex-test` and `securityTerms`) are parametrized over it below. The flag
# allowlist is derived exactly as the construct allowlist is: the live matrix
# uses `i` (three announce literals) and nothing else, so `i` is translated
# and every other JavaScript flag - `s` included - is refused. `s` only ever
# qualifies `.`, which is itself off the allowlist.
TRANSLATED_JS_FLAGS = "i"
UNPORTABLE_JS_FLAGS = "dgmsuvy"

_SECURITY_TERMS_BODY = (
    r"(security|securit|vulnerab|owasp|\bxss\b|\bcsrf\b|\bsqli\b|injection|"
    r"authoris|authoriz|authentic|\btoken\b|\bsecret\b|sanitis|sanitiz|"
    r"replay|tamper|privilege escalation|idor)"
)


def _security_source(flags: str = "") -> str:
    """The live inline security assert, with `flags` on its regex literal."""
    return (
        "const out = String(output || '').toLowerCase();\n"
        f"const securityTerms = /{_SECURITY_TERMS_BODY}/{flags};\n"
        "const mentionsSecurity = securityTerms.test(out);\n"
        "if (context.vars.security_must_appear === true) {\n"
        "  return mentionsSecurity\n"
        "    ? { pass: true, score: 1, reason: 'present' }\n"
        "    : { pass: false, score: 0, reason: 'absent' };\n"
        "}\n"
        "return { pass: true, score: 1, reason: 'delegated' };\n"
    )


def test_an_unflagged_security_terms_regex_still_builds_its_evaluator():
    """The control for the two tests below: the live, flagless shape works."""
    evaluator = ca.evaluator_for(ca.JavascriptAssertion(source=_security_source()))

    assert evaluator.kind == "security-relevance"
    assert evaluator.terms == _SECURITY_TERMS_BODY


@pytest.mark.parametrize("flag", sorted(UNPORTABLE_JS_FLAGS))
def test_a_flag_on_the_security_terms_regex_is_refused_not_dropped(flag):
    """`evaluator_for` lifts the regex BODY only, so a flag it does not
    translate would be DROPPED and the Python gate would quietly stop agreeing
    with promptfoo. Every flag here either has no `re` equivalent (`u`, `v`,
    `y`, `d`), changes matching in a way `re` spells differently (`m` anchors
    at `\\r`/`\\u2028`/`\\u2029` in JS but not in Python), or is load-bearing
    state (`g` moves `lastIndex`), so each raises instead."""
    assertion = ca.JavascriptAssertion(source=_security_source(flag))

    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"no proven Python"):
        ca.evaluator_for(assertion)


@pytest.mark.parametrize("flag", sorted(TRANSLATED_JS_FLAGS))
def test_a_translatable_flag_on_the_security_terms_regex_is_carried_not_dropped(flag):
    """The other half of the same rule: a flag the guard CAN translate must
    reach the compiled matcher rather than being silently discarded. `i` and
    `s` are proved equivalent against Node by the differential harness."""
    evaluator = ca.evaluator_for(ca.JavascriptAssertion(source=_security_source(flag)))

    assert evaluator.kind == "security-relevance"
    assert evaluator.flags == flag, "the flag was dropped on the way to the evaluator"
    assert evaluator.evaluate(SECURITY_PASS, {"security_must_appear": True}).passed
    assert not evaluator.evaluate(SECURITY_FAIL, {"security_must_appear": True}).passed


def test_the_live_security_asserts_are_unflagged_and_survive_the_flag_guard():
    """Guard: the hardening above must not touch the three live gates. Pins
    the parsed terms, the three reasons and both verdicts for each config, so
    a stricter flag check cannot regress them into raising."""
    live = [
        (name, a)
        for name, a in _live_javascript_asserts()
        if name.endswith("-security-relevance.yaml")
    ]

    assert len(live) == 3

    for name, assertion in live:
        assert re.search(r"securityTerms\s*=\s*/.+/\s*;", assertion.source), name

        evaluator = ca.evaluator_for(assertion)

        assert evaluator.kind == "security-relevance", name
        assert evaluator.terms.startswith("(security|securit|vulnerab|owasp|"), name
        assert len(evaluator.reasons) == 3, name
        assert evaluator.evaluate(SECURITY_PASS, {"security_must_appear": True}).passed, name
        assert not evaluator.evaluate(SECURITY_FAIL, {"security_must_appear": True}).passed, name
        assert evaluator.evaluate(SECURITY_FAIL, {"security_must_appear": False}).passed, name


def test_regex_evaluator_anchors_the_announce_line_to_the_start():
    assertion = next(
        a for name, a in _live_javascript_asserts() if name == "skill-closing-qa-gaps.yaml"
    )
    evaluator = ca.evaluator_for(assertion)

    buried = "Here is my plan. Closing one QA gap at a time is the discipline."
    assert evaluator.evaluate(buried, {}).passed is False
    assert evaluator.evaluate("> **Closing one QA gap at a time.**", {}).passed is True


# --- JavaScript vs Python regex semantics ---------------------------------
#
# Risk: the ports lift JS patterns and compile them with Python `re`, but the
# engines disagree. Python's Unicode `re.IGNORECASE` folds `ſ` onto `s` and
# `K` onto `k` where JavaScript's `/i` deliberately does not (its Canonicalize
# step refuses any mapping from a non-ASCII code unit onto an ASCII one), and
# Python's `\b`/`\w` are Unicode-aware where JavaScript's are ASCII-only. Both
# directions flip verdicts, so slice 3 would be diffing the port's engine
# rather than the skill.
# Technique: boundary value analysis on the character classes themselves.


def test_regex_evaluator_case_folds_like_javascript_not_python():
    evaluator = ca.RegexTestEvaluator("security", "i")

    assert evaluator.evaluate("SECURITY matters here", {}).passed is True
    assert evaluator.evaluate("ſecurity matters here", {}).passed is False


def test_security_relevance_word_boundaries_are_ascii_like_javascript():
    """JS `\\b` is ASCII-based, so `/\\bxss\\b/` matches inside `éxssé`."""
    assertion = next(
        a
        for name, a in _live_javascript_asserts()
        if name == "skill-preparing-for-work-security-relevance.yaml"
    )
    evaluator = ca.evaluator_for(assertion)

    result = evaluator.evaluate("The éxssé payload is unescaped.", {"security_must_appear": True})

    assert result.passed is True, result.reason


def test_catalogue_technique_matching_case_folds_like_javascript(tmp_path):
    catalogue = tmp_path / "techniques.md"
    catalogue.write_text("### state transition testing\n", encoding="utf-8")
    evaluator = ca.CitesCatalogueTechniqueEvaluator(catalogue_path=catalogue)

    assert evaluator.evaluate("I used State Transition Testing.", {}).passed is True
    assert evaluator.evaluate("I used state tranſition testing.", {}).passed is False


def test_retrospective_restore_word_boundary_is_ascii_like_javascript():
    evaluator = ca.RetrospectiveRestoreEvaluator(
        ("no scoped restore", "destructive command", "no return", "ok")
    )
    text = (
        "Restore with `git show abc1234:src/a.py > src/a.py`, then wipe with "
        "`git cleané -fd`, then `git checkout -- src/a.py`."
    )

    result = evaluator.evaluate(text, {})

    assert result.passed is False
    assert result.reason == "destructive command"


# --- JS `\s`/`\S` are substituted, not narrowed by re.ASCII ---------------
#
# Risk: `re.ASCII` gives JS semantics for `\b`, `\w` and case folding but
# NARROWS `\s`/`\S` below JS's set, and the live retrospective gate is built
# out of `git\s+show\s+\S+:\S+\s*>\s*\S+` and friends. An answer separated by
# a non-breaking space passes in JavaScript and fails in Python, which is a
# verdict divergence on a live evaluator, not a theoretical one. Every lifted
# pattern therefore has its `\s`/`\S` rewritten to explicit JS-whitespace
# classes before compiling, so re.ASCII stops mattering for whitespace.
# Technique: boundary value analysis on the whitespace set, plus unit tests on
# the substitution itself, because a substitution bug (an escaped `\\s`, or a
# `\s` inside a character class) would corrupt patterns silently.

NBSP = " "


def test_js_whitespace_substitution_expands_a_bare_backslash_s():
    rewritten = ca.js_pattern_to_python(r"a\sb")

    assert re.fullmatch(rewritten, "a b")
    assert re.fullmatch(rewritten, f"a{NBSP}b")
    assert not re.fullmatch(rewritten, "axb")


def test_js_whitespace_substitution_negates_backslash_capital_s():
    rewritten = ca.js_pattern_to_python(r"a\Sb")

    assert re.fullmatch(rewritten, "axb")
    assert not re.fullmatch(rewritten, "a b")
    assert not re.fullmatch(rewritten, f"a{NBSP}b")


def test_js_whitespace_substitution_splices_into_an_existing_character_class():
    """The announce-line prefix is `[\\s>*_"']`. Expanding `\\s` to a nested
    `[...]` there would make `[` and `]` literal members and change what the
    class accepts, so the BODY is spliced in instead."""
    rewritten = ca.js_pattern_to_python(r"""^[\s>*_"']{0,8}hello""")

    assert re.match(rewritten, "> **hello")
    assert re.match(rewritten, f"{NBSP}hello")
    assert not re.match(rewritten, "[hello")
    assert not re.match(rewritten, "xhello")


def test_js_whitespace_substitution_does_not_fire_on_an_escaped_backslash():
    r"""`\\s` is a literal backslash followed by `s`, not a whitespace class.
    A naive `str.replace` would corrupt it into a backslash plus a class. The
    walk still reads it as one escape (`\\`) and one literal (`s`), so the
    substitution cannot fire - and because `\\` is not itself on the
    allowlist, the pattern refuses rather than compiling either reading."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"the escape \\\\"):
        ca.js_pattern_to_python(r"a\\sb")


def test_js_whitespace_substitution_leaves_other_escapes_and_classes_alone():
    r"""Only `\s`/`\S` move. `\b`, `\n` and a class that mentions neither must
    come back byte for byte, or the substitution is silently editing the
    lifted pattern."""
    assert ca.js_pattern_to_python(r"[^\n]*?") == r"[^\n]*?"
    assert ca.js_pattern_to_python(r"(?!--|HEAD)x") == r"(?!--|HEAD)x"
    assert ca.js_pattern_to_python(r"git\s+clean\b").endswith(r"clean\b")


def test_js_whitespace_substitution_closes_a_class_the_way_javascript_does():
    r"""In JavaScript `[]` is the EMPTY class, so a `]` straight after `[`
    CLOSES it and the `\s` that follows is OUTSIDE the class. Treating that
    `]` as a POSIX literal member - which is what Python's own parser does -
    would splice the whitespace body inside instead, silently changing what
    the pattern accepts. The boundary is still read JavaScript's way; the
    class it delimits is now REFUSED rather than translated, so neither
    reading can reach `re.compile`."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"empty character class"):
        ca.js_pattern_to_python(r"a[^]\sb")


def test_js_whitespace_substitution_refuses_backslash_capital_s_in_a_class():
    """Python has no set subtraction in a character class, so `[\\S>]` cannot
    be translated. No live pattern uses it; failing loudly beats compiling
    something whose verdict quietly differs from JavaScript's."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"\\S inside"):
        ca.js_pattern_to_python(r"[\S>]")


# --- closed by default: the allowlist is the guarantee --------------------
#
# Risk: the guard used to be OPEN by default - it translated the constructs it
# recognised and trusted everything else, on a stated promise that a lifted
# pattern always matched the same set in Python as in Node. That promise is a
# claim about the whole ECMAScript regex grammar, and four review rounds each
# found a new corner where it failed (a legacy octal escape, the Python-only
# `\N{...}` and `\U........` forms, astral characters where JavaScript
# consumes UTF-16 code units and Python code points, malformed literal
# syntax). Each was patched one at a time; the next round found another.
#
# The defect was the promise, not the corners. The guard now admits exactly
# the constructs the live matrix uses and REFUSES everything else, which
# closes all of them structurally: an unrecognised escape, a non-ASCII
# character and a bare `.` are all simply off the allowlist. The refusal is
# the guarantee.
#
# Technique: equivalence partitioning over the ECMAScript construct space
# (on the allowlist / off it), plus differential testing against Node for the
# on-list half. The Node harness is deliberately NOT in this suite, which must
# stay offline and Node-free; its 15 live patterns are pinned offline by
# `test_every_live_lifted_pattern_survives_the_completed_guard`.

LINE_SEPARATOR = "\u2028"
PARAGRAPH_SEPARATOR = "\u2029"

# The allowlist, as a construct-by-construct table. Every entry is present in
# at least one of the 15 live regex instances, which is where it came from -
# see the derivation in `assertions.py`. If this list ever grows, the Node
# differential has to grow with it.
SUPPORTED_CONSTRUCTS = [
    ("printable-ASCII literal", "git", "git", "cat"),
    ("start anchor", "^git", "git show", "a git"),
    ("alternation", "xss|csrf", "csrf", "idor"),
    ("capturing group", "(xss|csrf)", "xss", "idor"),
    ("negative lookahead", r"git checkout (?!--)\S+", "git checkout main", "git checkout --"),
    ("greedy star", "ab*c", "ac", "abx"),
    ("greedy plus", "ab+c", "abbc", "ac"),
    ("optional", "ab?c", "ac", "abbc"),
    ("lazy quantifier", r"a[^\n]*?c", "abc", "ab"),
    ("lazy star", "ab*?c", "ac", "abx"),
    ("lazy plus", "ab+?c", "abbc", "ac"),
    ("lazy optional", "ab??c", "ac", "abbc"),
    ("bounded quantifier", "ab{2,3}c", "abbc", "abc"),
    ("lazy bounded quantifier", "ab{2,3}?c", "abbc", "abc"),
    (r"\s", r"git\sshow", "git show", "gitshow"),
    (r"\S", r"git\s\S+", "git abc", "git  "),
    (r"\b", r"\bxss\b", "an xss bug", "xssbug"),
    (r"\n inside a class", r"a[^\n]c", "abc", "a\nc"),
    ("character class", r"""^[\s>*_"']{0,8}go""", "> **go", "xgo"),
]

# Everything else. Each entry names a construct that is NOT in any live
# pattern, so the guard must refuse it rather than approximate it. The four
# findings the previous round turned up are the first four rows.
UNSUPPORTED_CONSTRUCTS = [
    ("legacy octal escape", r"caf\351", r"the escape \\3"),
    ("python-only named escape", r"caf\N{LATIN SMALL LETTER E WITH ACUTE}", r"the escape \\N"),
    ("python-only wide escape", r"caf\U000000E9", r"the escape \\U"),
    ("bare dot", "^.$", r"uses `\.`"),
    ("astral literal", "^\U0001f600$", "the character"),
    ("non-ascii literal", "caf\u00e9", "the character"),
    ("end anchor", "a$", r"uses `\$`"),
    ("javascript empty class", r"a[]b", "empty character class"),
    ("javascript match-anything class", r"a[^]b", "empty character class"),
    ("unicode code point escape", r"caf\u00e9", r"the escape \\u"),
    ("hex escape", r"caf\xe9", r"the escape \\x"),
    ("digit class", r"\d+", r"the escape \\d"),
    ("word class", r"\w+", r"the escape \\w"),
    ("identity escape", r"a\.b", r"the escape \\\."),
    ("backreference", r"(a)\1", r"the escape \\1"),
    ("non-capturing group", "(?:ab)", r"the group prefix `\(\?:`"),
    ("lookahead", "a(?=b)", r"the group prefix `\(\?=`"),
    ("lookbehind", "(?<=a)b", r"the group prefix `\(\?<`"),
    ("class range", "[a-z]+", "`-` inside a character class"),
    ("escaped bracket in a class", r"a[\]]b", r"the escape \\\] inside a character class"),
    ("nested class bracket", r"a[x[y]b", r"`\[` inside a character class"),
    ("non-leading class caret", r"a[x^y]b", r"`\^` inside a character class"),
    ("non-ascii class member", "[\u00e9x]", "inside a character class"),
    ("unterminated class", "a[xy", "unterminated character class"),
    ("stray brace", "a{b}", "not a bounded quantifier"),
    ("possessive plus", "a++", "stacked on another quantifier"),
    ("possessive star", "a*+", "stacked on another quantifier"),
    ("possessive optional", "a?+", "stacked on another quantifier"),
    ("possessive bounded quantifier", "a{1,2}+", "stacked on another quantifier"),
    ("doubly-lazy quantifier", "a*??", "stacked on another quantifier"),
    ("bare closing bracket", "a]b", r"uses `\]`"),
    ("bare closing brace", "a}b", r"uses `\}`"),
    ("trailing backslash", "ab\\", "the escape"),
    ("raw control character", "a\tb", "the character"),
]


@pytest.mark.parametrize(
    "construct,pattern,matching,non_matching",
    SUPPORTED_CONSTRUCTS,
    ids=[row[0] for row in SUPPORTED_CONSTRUCTS],
)
def test_every_allowlisted_construct_still_translates(construct, pattern, matching, non_matching):
    """The half of the allowlist that must keep WORKING.

    A guard that only ever refuses would sail through a suite that only ever
    checks refusals, and would also break the live matrix. Each construct is
    exercised on an output it must accept and one it must reject, so a
    translation that compiles but matches the wrong set is caught too."""
    evaluator = ca.RegexTestEvaluator(pattern)

    assert evaluator.evaluate(matching, {}).passed is True, construct
    assert evaluator.evaluate(non_matching, {}).passed is False, construct


@pytest.mark.parametrize(
    "construct,pattern,expected",
    UNSUPPORTED_CONSTRUCTS,
    ids=[row[0] for row in UNSUPPORTED_CONSTRUCTS],
)
def test_every_construct_off_the_allowlist_is_refused(construct, pattern, expected):
    """The other half: the guard is CLOSED, so anything not derived from a
    live pattern raises rather than compiling into an unchecked verdict.

    This is the test that makes the four latest findings structural rather
    than patched: `\\351`, `\\N{...}`, `\\U........` and an astral-sensitive
    `.` are refused for the same reason as everything else on this list, not
    by four bespoke checks."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=expected):
        ca.RegexTestEvaluator(pattern)


def test_an_unsupported_construct_in_a_config_names_the_construct_and_the_fix():
    """A refusal is only useful if the author can act on it: it has to say
    which construct, which config, and what to do about it."""
    assertion = ca.JavascriptAssertion(
        source=r"/^.$/.test(output)", config_path=Path("skill-made-up.yaml")
    )

    with pytest.raises(ca.UnportableJavascriptPatternError) as raised:
        ca.evaluator_for(assertion)

    message = str(raised.value)
    assert "`.`" in message
    assert "skill-made-up.yaml" in message
    assert "extend the port" in message
    assert "Node differential" in message


def test_the_astral_divergence_is_closed_by_the_allowlist_not_by_a_special_case():
    r"""Codex's fourth finding: JavaScript matches a pattern against UTF-16
    code units and Python against code points, so `/^.$/` is FALSE in Node for
    an emoji (two units, one dot) and was TRUE here. `.` is off the allowlist
    and so is a raw astral character, so both spellings of the divergence
    refuse - and so does the `[^]` that would also have exposed it."""
    for pattern in ["^.$", "^[^]$", "^\U0001f600$"]:
        with pytest.raises(ca.UnportableJavascriptPatternError):
            ca.RegexTestEvaluator(pattern)


def test_regex_test_evaluator_refuses_a_flag_it_cannot_translate():
    """Finding 1: `RegexTestEvaluator` had the identical hole `securityTerms`
    had - it lifted `/<pattern>/<flags>` and then dropped the flags. Node says
    `/x/y.test("ax")` is false (sticky: the match must start at `lastIndex`);
    the evaluator used to say true."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"no proven Python"):
        ca.RegexTestEvaluator("x", "y")


@pytest.mark.parametrize("flag", sorted(UNPORTABLE_JS_FLAGS))
def test_both_lifted_regex_paths_refuse_the_same_flags(flag):
    """The two paths used to check flags separately, and one of them forgot.
    They now share `_js_flags`, so this pins them to the SAME answer for the
    same flag - the drift itself is what is being tested."""
    with pytest.raises(ca.UnportableJavascriptPatternError):
        ca.RegexTestEvaluator("x", flag)
    with pytest.raises(ca.UnportableJavascriptPatternError):
        ca.evaluator_for(ca.JavascriptAssertion(source=_security_source(flag)))


def test_the_multiline_flag_is_refused_rather_than_mismapped():
    r"""Finding 2: `m` used to map to `re.MULTILINE`, which is a REAL
    divergence, not an approximation. JavaScript's `/m` anchors `^`/`$` at
    `\r`, U+2028 and U+2029; Python's anchors only at `\n`, so
    `/^b/m.test("a\rb")` is true in Node and was false here. A silent mismap
    is worse than a refusal, and no live pattern uses `m`."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"no proven Python"):
        ca.RegexTestEvaluator("^b", "m")


def test_a_repeated_flag_is_refused():
    """`new RegExp("x", "ii")` is a SyntaxError in JavaScript, so the assert
    would throw rather than return a verdict. Accepting it as plain `i` would
    invent a verdict promptfoo never produces."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"repeats a flag"):
        ca.RegexTestEvaluator("x", "ii")


@pytest.mark.parametrize("terminator", ["\n", "\r", LINE_SEPARATOR, PARAGRAPH_SEPARATOR], ids=repr)
def test_a_lifted_dot_is_refused_rather_than_approximated(terminator):
    r"""`.` was the hardest construct to keep honest, and it is now simply off
    the allowlist. JavaScript's `.` excludes `\n`, `\r`, U+2028 and U+2029
    where Python's excludes only `\n`; and on top of that the two engines
    disagree about what a single `.` consumes in an astral character. The
    previous port substituted an explicit negated class, which fixed the first
    divergence and not the second. No live pattern uses `.`, so the port owes
    it nothing - and the terminators below are what an approximation would
    have had to get right."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"uses `\.`"):
        ca.RegexTestEvaluator("a.b")

    assert f"a{terminator}b" != "a b"


def test_the_dotall_flag_is_refused_because_the_construct_it_qualifies_is():
    """`s` only ever changes what `.` matches, and `.` is off the allowlist,
    so honouring `/s` could only ever qualify a construct that is already
    refused. It is refused with every other unported flag rather than kept as
    the one flag with nothing left to do."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"no proven Python"):
        ca.RegexTestEvaluator("ab", "s")


def test_a_dot_inside_a_character_class_stays_a_literal():
    """The refusal is scoped to the construct, not to the character: inside a
    class `.` is an ordinary member in both languages, and the live announce
    prefix depends on exactly that treatment for `*` and `>`."""
    evaluator = ca.RegexTestEvaluator(r"a[.x]b")

    assert evaluator.evaluate("a.b", {}).passed is True
    assert evaluator.evaluate("axb", {}).passed is True
    assert evaluator.evaluate("ayb", {}).passed is False


def test_a_lifted_dollar_is_refused_rather_than_rewritten_to_end_of_input():
    r"""`$` diverges with no flags involved: JavaScript's (without `/m`)
    matches only at end of input; Python's ALSO matches just before a final
    `\n`, so `/a$/.test("a\n")` is false in Node and true here. The previous
    port rewrote it to `\Z`. That was correct, and it is still gone: no live
    pattern anchors at the end, so the construct is not on the allowlist and
    the rewrite is one fewer thing to be right about."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"uses `\$`"):
        ca.RegexTestEvaluator("a$")

    assert ca.RegexTestEvaluator("[$]").evaluate("$", {}).passed is True


def test_the_ignorecase_flag_is_translated_for_an_ascii_pattern():
    """`i` is kept, not refused: under `re.ASCII` Python folds only ASCII,
    which is exactly JavaScript's `/i` for an ASCII pattern - JS refuses any
    mapping of a non-ASCII code unit onto an ASCII one. The three live
    announce gates all carry `/i`, and the harness confirms them."""
    evaluator = ca.RegexTestEvaluator("security", "i")

    assert evaluator.evaluate("SECURITY", {}).passed is True
    assert evaluator.evaluate("ſecurity", {}).passed is False


@pytest.mark.parametrize("pattern", ["é", r"é", r"\xe9"], ids=repr)
@pytest.mark.parametrize("flags", ["i", ""], ids=["with /i", "without /i"])
def test_a_non_ascii_code_point_is_refused_however_it_is_spelled(pattern, flags):
    r"""The `/i` half of this used to be a bespoke check - `_folds_only_ascii`
    decoded `\uXXXX`/`\xXX` escapes, because `"\\u00e9".isascii()` is True and
    a bare ASCII test would have waved the escaped forms straight through.
    Node says `/é/i.test("É")` is true and `re.ASCII` cannot fold it.

    The allowlist subsumes that check and widens it: a non-ASCII code point is
    refused with OR without `/i`, spelled as a literal or as either escape.
    Without `/i` the two engines do agree on a lone `é` - but they stop
    agreeing the moment it is astral or quantified, and no live pattern has
    one, so the guard no longer has to know the difference."""
    with pytest.raises(ca.UnportableJavascriptPatternError):
        ca.RegexTestEvaluator(pattern, flags)


def test_a_pattern_python_cannot_parse_becomes_the_guards_own_error():
    r"""Secondary: allowlisted constructs can still be ASSEMBLED into
    something Python's parser rejects - an unbalanced group, a quantifier with
    nothing to quantify. That already failed loudly; it now fails with the
    guard's own error naming the pattern and the config, instead of leaking a
    raw `re.error`."""
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"no Python equivalent"):
        ca.RegexTestEvaluator("(ab")
    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"no Python equivalent"):
        ca.RegexTestEvaluator("*a")


def test_the_refusal_names_the_config_it_came_from():
    """A refusal is only useful if it says which config to go and fix."""
    assertion = ca.JavascriptAssertion(
        source="/x/y.test(output);", config_path=Path("skill-made-up.yaml")
    )

    with pytest.raises(ca.UnportableJavascriptPatternError, match=r"skill-made-up\.yaml"):
        ca.evaluator_for(assertion)


# --- the dispatch regex reads a JS literal, it does not reinterpret one ----
#
# Risk: a PARSING bug rather than a translation one, and the more dangerous
# kind, because it changed which pattern got compiled before the guard ever
# saw it. `_REGEX_TEST` captured the body with a greedy `.*` that ran through
# to the LAST slash, so `/x/i/.test(output)` - a SyntaxError in JavaScript,
# which promptfoo would never have produced a verdict for - was silently read
# here as the valid pattern `x/i` with no flags. A malformed literal must
# refuse, not be reinterpreted into a different gate.
# Technique: boundary value analysis on the literal's delimiters, both
# directions - the well-formed literals must still parse to the RIGHT body and
# flags, or a stricter regex would "pass" by refusing everything.


@pytest.mark.parametrize(
    "source,pattern,flags",
    [
        ("/x/i.test(output)", "x", "i"),
        ("/x/.test(output);", "x", ""),
        ("  /a b/i.test( output ) ;  ", "a b", "i"),
        (r"/^[\s>*_]{0,8}go/i.test(output)", r"^[\s>*_]{0,8}go", "i"),
    ],
    ids=["flagged", "unflagged", "whitespace", "announce-shaped"],
)
def test_a_well_formed_regex_literal_still_parses_to_its_body_and_flags(source, pattern, flags):
    evaluator = ca.evaluator_for(ca.JavascriptAssertion(source=source))

    assert evaluator.kind == "regex-test"
    assert evaluator.pattern == pattern
    assert evaluator.flags == flags


@pytest.mark.parametrize(
    "source",
    [
        "/x/i/.test(output)",
        "/x//.test(output)",
        "/x/q.test(output)",
        "//.test(output)",
    ],
    ids=["trailing-slash", "double-slash", "not-a-flag", "empty-body"],
)
def test_a_malformed_regex_literal_refuses_instead_of_being_reinterpreted(source):
    """`/x/i/.test(output)` is the trigger: JavaScript rejects it at parse
    time, so there is no verdict to agree with. The old greedy capture turned
    it into the pattern `x/i` and graded outputs against that."""
    with pytest.raises(ca.UnportableJavascriptPatternError) as raised:
        ca.evaluator_for(ca.JavascriptAssertion(source=source, config_path=Path("skill-x.yaml")))

    message = str(raised.value)
    assert "not a well-formed JavaScript regex literal" in message
    assert "skill-x.yaml" in message


def test_a_regex_literal_with_an_unescaped_slash_in_its_body_is_refused():
    r"""The general form of the same bug. A `/` inside the body must be
    escaped in JavaScript, and `\/` is an identity escape the port does not
    carry - so either way the assert refuses rather than compiling a body the
    author did not write."""
    with pytest.raises(ca.UnportableJavascriptPatternError):
        ca.evaluator_for(ca.JavascriptAssertion(source="/a/b/.test(output)"))
    with pytest.raises(ca.UnportableJavascriptPatternError):
        ca.evaluator_for(ca.JavascriptAssertion(source=r"/a\/b/.test(output)"))


def test_the_security_terms_literal_is_read_with_the_same_strictness():
    """The two lifted-regex paths must not drift: `_SECURITY_TERMS` carried
    the identical greedy `.+`, so the same malformed literal would have been
    reinterpreted there too."""
    malformed = _security_source().replace(
        f"/{_SECURITY_TERMS_BODY}/;", f"/{_SECURITY_TERMS_BODY}/i/;"
    )

    with pytest.raises(ca.UnportedJavascriptAssertionError):
        ca.evaluator_for(ca.JavascriptAssertion(source=malformed))


def test_every_live_lifted_pattern_survives_the_completed_guard():
    """Regression guard for the whole change: the guard is now much stricter,
    and the 15 pattern instances the runner actually compiles must all still
    build and still agree with the whitespace work. The differential harness
    checks these same patterns against Node; this pins them offline."""
    built = [ca.evaluator_for(a) for _, a in _live_javascript_asserts()]

    assert len(built) == EXPECTED_JAVASCRIPT_ASSERT_COUNT
    for evaluator in built:
        if evaluator.kind == "regex-test":
            assert evaluator.flags == "i"
        elif evaluator.kind == "security-relevance":
            assert evaluator.flags == ""


def test_retrospective_restore_treats_a_non_breaking_space_as_javascript_does():
    """Codex's counterexample: JS `\\s` matches U+00A0, so this output has a
    scoped restore and a return-reverse in JavaScript. Under bare `re.ASCII`
    Python saw no scoped restore and returned the opposite verdict."""
    evaluator = ca.RetrospectiveRestoreEvaluator(
        ("no scoped restore", "destructive command", "no return", "ok")
    )
    text = (
        f"git{NBSP}show{NBSP}abc:src/a.py{NBSP}>{NBSP}src/a.py then "
        f"git{NBSP}checkout{NBSP}--{NBSP}src/a.py"
    )

    result = evaluator.evaluate(text, {})

    assert result.passed is True, result.reason
    assert result.reason == "ok"


def test_regex_evaluator_announce_prefix_accepts_a_non_breaking_space():
    """The live announce gates use `^[\\s>*_"']{0,8}<phrase>/i`; JS `\\s`
    covers U+00A0, so an answer opening with one still announces."""
    assertion = next(
        a for name, a in _live_javascript_asserts() if name == "skill-closing-qa-gaps.yaml"
    )
    evaluator = ca.evaluator_for(assertion)

    assert evaluator.evaluate(f"{NBSP}Closing one QA gap at a time.", {}).passed is True


def test_ascii_semantics_still_hold_after_the_whitespace_substitution():
    """The substitution must not cost the other two axes: `re.ASCII` still has
    to give JS case folding and JS `\\b`/`\\w` on the same patterns."""
    evaluator = ca.RetrospectiveRestoreEvaluator(
        ("no scoped restore", "destructive command", "no return", "ok")
    )
    text = (
        f"Restore with `git{NBSP}show abc1234:src/a.py > src/a.py`, then wipe with "
        "`git cleané -fd`, then `git checkout -- src/a.py`."
    )

    assert evaluator.evaluate(text, {}).reason == "destructive command"
    assert ca.RegexTestEvaluator("security", "i").evaluate("ſecurity", {}).passed is False


# --- cites-catalogue-technique: allowlist derived, never hardcoded (#350) ---


def test_catalogue_technique_allowlist_is_derived_from_the_catalogue_headings(tmp_path):
    catalogue = tmp_path / "techniques.md"
    catalogue.write_text(
        "# Test design techniques\n\n## Black-box\n\n### boundary value analysis\nx\n",
        encoding="utf-8",
    )
    evaluator = ca.CitesCatalogueTechniqueEvaluator(catalogue_path=catalogue)

    assert evaluator.evaluate("I used boundary value analysis here.", {}).passed is True
    assert evaluator.evaluate("I used error guessing here.", {}).passed is False

    catalogue.write_text(
        "# Test design techniques\n\n## Black-box\n\n### boundary value analysis\nx\n"
        "\n## Experience-based\n\n### error guessing\ny\n",
        encoding="utf-8",
    )
    widened = ca.CitesCatalogueTechniqueEvaluator(catalogue_path=catalogue)

    assert widened.evaluate("I used error guessing here.", {}).passed is True


def test_catalogue_technique_ignores_level_two_category_headings(tmp_path):
    catalogue = tmp_path / "techniques.md"
    catalogue.write_text("## Black-box\n\n### pairwise / orthogonal arrays\n", encoding="utf-8")
    evaluator = ca.CitesCatalogueTechniqueEvaluator(catalogue_path=catalogue)

    assert evaluator.evaluate("this is a Black-box concern", {}).passed is False
    assert evaluator.evaluate("used pairwise / orthogonal arrays", {}).passed is True


def test_catalogue_technique_ignores_headings_inside_fenced_code_blocks(tmp_path):
    catalogue = tmp_path / "techniques.md"
    catalogue.write_text(
        "### real technique\n\n````\n### fenced impostor\n```\nstill fenced\n```\n````\n"
        "### second real technique\n",
        encoding="utf-8",
    )

    names = ca.catalogue_technique_names(catalogue.read_text(encoding="utf-8"))

    assert names == ["real technique", "second real technique"]


def test_catalogue_technique_evaluator_refuses_an_empty_catalogue(tmp_path):
    catalogue = tmp_path / "techniques.md"
    catalogue.write_text("# Title only\n\n## Category only\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no technique headings"):
        ca.CitesCatalogueTechniqueEvaluator(catalogue_path=catalogue).evaluate("x", {})


def test_catalogue_technique_evaluator_refuses_a_non_ascii_heading(tmp_path):
    """The one compiled pattern that does not go through the portability
    guard, because it is Python assembled from `re.escape` rather than a
    lifted JS pattern - routing it through would mean re-admitting exactly the
    identity escapes the allowlist just closed.

    What it does borrow is the guard's standard. `IGNORECASE | ASCII` folds
    case the way JavaScript's `/i` does only while every heading is ASCII, and
    `knowledge/techniques.md` is an editable file anyone can add a heading to.
    A cased non-ASCII heading diverges - Python with these flags will not
    match `CAFÉ` against `café`, where Node's `/i` does - so the invariant is
    asserted rather than assumed."""
    catalogue = tmp_path / "techniques.md"
    catalogue.write_text("### café testing\n\n### plain technique\n", encoding="utf-8")
    evaluator = ca.CitesCatalogueTechniqueEvaluator(catalogue_path=catalogue)

    with pytest.raises(ca.UnportableJavascriptPatternError) as raised:
        evaluator.evaluate("I used CAFÉ TESTING here.", {})

    message = str(raised.value)
    assert "café testing" in message
    assert str(catalogue) in message
    assert "plain technique" not in message


def test_every_live_catalogue_heading_is_ascii():
    """The guard above is only latent while this holds - so pin it. All 21
    live headings are ASCII today; the day one is not, the eval fails loudly
    rather than quietly grading differently from promptfoo."""
    names = ca.catalogue_technique_names(ca.TECHNIQUES_MD.read_text(encoding="utf-8"))

    assert names
    assert [name for name in names if not name.isascii()] == []


def test_live_catalogue_evaluator_uses_the_repo_techniques_catalogue():
    evaluator = ca.CitesCatalogueTechniqueEvaluator()

    assert evaluator.evaluate("I applied state transition testing.", {}).passed is True
    assert (
        "state transition testing"
        in evaluator.evaluate("I applied state transition testing.", {}).reason
    )


# --- llm-rubric: parsed, carried, never executed ---


def test_llm_rubric_asserts_are_parsed_with_their_judge_overrides():
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    rubrics = [a for a in config.all_assertions() if isinstance(a, ca.RubricAssertion)]

    assert rubrics
    rubric = rubrics[0]
    assert "Expected QA shape" in rubric.rubric
    assert rubric.rubric_prompt is not None
    assert "adversarial reviewer" in rubric.rubric_prompt
    assert rubric.judge_provider["id"] == "openai:chat:gpt-5.5"


def test_every_rubric_in_the_live_matrix_parses_and_none_is_executable():
    total = 0
    for config in cl.load_all_configs(PROMPTFOO_DIR):
        for assertion in config.all_assertions():
            if isinstance(assertion, ca.RubricAssertion):
                total += 1
                assert isinstance(assertion.rubric, str)
                assert not hasattr(assertion, "evaluate")

    assert total == 66


def test_rubric_evaluation_is_out_of_scope_for_this_slice():
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    rubric = next(a for a in config.all_assertions() if isinstance(a, ca.RubricAssertion))

    with pytest.raises(ca.RubricNotExecutableError):
        ca.evaluator_for(rubric)


def test_assert_threshold_is_carried_through():
    config = cl.load_config(PROMPTFOO_DIR / "skill-triaging-test-failures.yaml")
    js = next(a for a in config.all_assertions() if isinstance(a, ca.JavascriptAssertion))

    assert js.threshold == 1


def test_an_unsupported_assertion_type_is_rejected(tmp_path):
    config = tmp_path / "skill-x.yaml"
    config.write_text(
        "description: d\n"
        "providers: [echo]\n"
        "prompts: ['{{q}}']\n"
        "defaultTest:\n"
        "  assert:\n"
        "    - type: contains\n"
        "      value: hello\n"
        "tests:\n"
        "  - vars: {q: hi}\n",
        encoding="utf-8",
    )

    with pytest.raises(ca.UnsupportedAssertionTypeError, match="contains"):
        cl.load_config(config)


def test_the_runner_never_executes_assertion_source():
    sources = [
        p.read_text(encoding="utf-8")
        for p in (REPO_ROOT / "tests" / "evals" / "claude").glob("*.py")
    ]
    joined = "\n".join(sources)

    for forbidden in ("eval(", "exec(", "subprocess", "node "):
        assert forbidden not in joined, f"runner must not use {forbidden!r}"


# ==========================================================================
# Case assembly
# ==========================================================================


def test_cases_carry_prompt_label_rendered_prompt_and_assertions():
    config = cl.load_config(PROMPTFOO_DIR / "skill-implementing-with-tdd.ab.yaml")
    cases = cl.build_cases(config)

    assert len(cases) == len(config.prompts) * len(config.tests)
    labels = {c.prompt_label for c in cases}
    assert labels == {p.label for p in config.prompts}
    assert any(label.startswith("A0") for label in labels)
    first = cases[0]
    assert "{{" not in first.rendered_prompt
    assert first.assertions
    assert any(isinstance(a, ca.JavascriptAssertion) for a in first.assertions)


def test_unlabelled_prompts_get_a_positional_label():
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")

    assert config.prompts[0].label == "prompt[0]"


def test_a_test_scoped_to_named_prompts_only_yields_those_cases():
    config = cl.load_config(PROMPTFOO_DIR / "skill-reviewing-before-merge-fence-parser.ab.yaml")
    cases = cl.build_cases(config)

    assert len(cases) == len(config.tests)
    assert len({c.prompt_label for c in cases}) == 2
    for case in cases:
        assert case.prompt_label.split()[0] in case.description


def test_per_test_asserts_append_to_the_default_asserts(tmp_path):
    config = tmp_path / "skill-x.yaml"
    config.write_text(
        "description: d\n"
        "providers: [echo]\n"
        "prompts: ['{{q}}']\n"
        "defaultTest:\n"
        "  assert:\n"
        "    - type: llm-rubric\n"
        "      value: shared rubric\n"
        "tests:\n"
        "  - vars: {q: hi}\n"
        "    assert:\n"
        "      - type: llm-rubric\n"
        "        value: extra rubric\n",
        encoding="utf-8",
    )

    cases = cl.build_cases(cl.load_config(config))

    assert [a.rubric for a in cases[0].assertions] == ["shared rubric", "extra rubric"]


def test_the_whole_live_matrix_assembles_without_leaving_placeholders():
    """Both constructs: a renderer that expands `{% for %}` but leaves every
    `{{ var }}` untouched must not pass this."""
    for config in cl.load_all_configs(PROMPTFOO_DIR):
        for case in cl.build_cases(config):
            assert "{%" not in case.rendered_prompt
            assert "{{" not in case.rendered_prompt
            assert LEFTOVER_PLACEHOLDER.search(case.rendered_prompt) is None
            assert case.rendered_prompt.strip()


# ==========================================================================
# Rubric values are rendered per case
#
# Risk: promptfoo renders an assertion's `value:` against the resolved test
# vars before grading (`renderedValue = nunjucks.renderString(renderedValue,
# resolvedVars)` in 0.121.20's `runAssertion`). 65 of the 66 live rubrics
# carry template syntax, so attaching them raw would hand slice 2's judge
# literal `{{expected_shape}}` text and silently destroy every rubric.
# The judge-time `rubricPrompt` is the deliberate exception: its `{{rubric}}`
# and `{{output}}` are filled by the grader, not by the case builder.
# ==========================================================================


def test_rubric_values_are_rendered_against_the_resolved_case_vars():
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    case = next(c for c in cl.build_cases(config) if "anti_patterns" in c.vars)
    rubric = next(a for a in case.assertions if isinstance(a, ca.RubricAssertion))

    assert "{{" not in rubric.rubric
    assert "{%" not in rubric.rubric
    assert "**Expected QA shape:**" in rubric.rubric
    assert "- Starts work on more than one gap in this loop (batching all three)." in rubric.rubric


def test_per_test_rubric_substitutions_reach_the_ab_control_rubrics():
    config = cl.load_config(PROMPTFOO_DIR / "skill-deciding-approach.ab.yaml")

    for case in cl.build_cases(config):
        for assertion in case.assertions:
            if isinstance(assertion, ca.RubricAssertion):
                assert LEFTOVER_PLACEHOLDER.search(assertion.rubric) is None
                assert "{%" not in assertion.rubric
                for anti_pattern in case.vars.get("anti_patterns", []):
                    assert anti_pattern in assertion.rubric


def test_no_rubric_in_the_live_matrix_reaches_a_case_unrendered():
    checked = 0
    for config in cl.load_all_configs(PROMPTFOO_DIR):
        for case in cl.build_cases(config):
            for assertion in case.assertions:
                if isinstance(assertion, ca.RubricAssertion):
                    checked += 1
                    assert "{%" not in assertion.rubric, case.config_path
                    assert LEFTOVER_PLACEHOLDER.search(assertion.rubric) is None, case.config_path

    assert checked > 100


def test_the_judge_rubric_prompt_is_left_unrendered_for_slice_two():
    """`{{rubric}}` / `{{output}}` are judge-time substitutions: promptfoo
    fills them in `matchesLlmRubric`, not when the case is built."""
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    case = cl.build_cases(config)[0]
    rubric = next(a for a in case.assertions if isinstance(a, ca.RubricAssertion))

    assert "{{rubric}}" in rubric.rubric_prompt
    assert "{{output}}" in rubric.rubric_prompt


def test_the_parsed_config_keeps_the_unrendered_rubric_template():
    """Rendering happens at case build, so `config.all_assertions()` still
    shows what the YAML said - the source of truth slice 3 diffs against."""
    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    rubric = next(a for a in config.all_assertions() if isinstance(a, ca.RubricAssertion))

    assert "{{expected_shape}}" in rubric.rubric


# ==========================================================================
# --skill / glob filter
# ==========================================================================


def test_skill_filter_selects_only_that_skills_configs():
    paths = cl.discover_configs(PROMPTFOO_DIR, skill="triaging-test-failures")

    assert [p.name for p in paths] == ["skill-triaging-test-failures.yaml"]


def test_skill_filter_accepts_the_sumo_qa_prefixed_skill_name():
    prefixed = cl.discover_configs(PROMPTFOO_DIR, skill="sumo-qa-closing-qa-gaps")
    bare = cl.discover_configs(PROMPTFOO_DIR, skill="closing-qa-gaps")

    assert prefixed == bare
    assert [p.name for p in prefixed] == ["skill-closing-qa-gaps.yaml"]


def test_skill_filter_picks_up_every_variant_config_for_that_skill():
    names = {p.name for p in cl.discover_configs(PROMPTFOO_DIR, skill="implementing-with-tdd")}

    assert names == {
        "skill-implementing-with-tdd.yaml",
        "skill-implementing-with-tdd.ab.yaml",
        "skill-implementing-with-tdd-retrospective.yaml",
    }


def test_an_unknown_skill_filter_selects_nothing():
    assert cl.discover_configs(PROMPTFOO_DIR, skill="no-such-skill") == []


@pytest.mark.parametrize(
    "truncated",
    [
        "reviewing",
        "reviewing-before",
        "implementing",
        "implementing-with",
    ],
)
def test_a_truncated_skill_name_selects_nothing_rather_than_a_wrong_matrix(truncated):
    """`no-such-skill` shares no prefix with anything, so it cannot catch the
    real failure: a name that is a PREFIX of a real skill matched on the
    hyphen boundary and silently scoped the run to that skill's whole family.
    A mistyped or shell-truncated `--skill` then produced a confident,
    non-empty, WRONG matrix - a wrong spend in #662 and a wrong parity
    comparison in #663 - instead of failing."""

    assert cl.discover_configs(PROMPTFOO_DIR, skill=truncated) == []


def test_the_real_skill_those_truncations_point_at_is_still_selectable():
    """The negative representative from the adjacent class: rejecting
    prefixes must not also reject the real name, nor drop its variants."""

    names = {p.name for p in cl.discover_configs(PROMPTFOO_DIR, skill="reviewing-before-merge")}

    assert len(names) == 28
    assert "skill-reviewing-before-merge.yaml" in names
    assert "skill-reviewing-before-merge.ab.yaml" in names
    assert "skill-reviewing-before-merge-verifier-evidence.yaml" in names


def test_a_variant_config_name_is_itself_selectable():
    """A variant has a config of its own, so it stays a legal `--skill`
    value - the rule is "names a config", not "names a skills/ directory"."""

    names = {
        p.name
        for p in cl.discover_configs(
            PROMPTFOO_DIR, skill="reviewing-before-merge-verifier-evidence"
        )
    }

    assert names == {
        "skill-reviewing-before-merge-verifier-evidence.yaml",
        "skill-reviewing-before-merge-verifier-evidence.ab.yaml",
    }


def test_glob_filter_scopes_the_matrix_to_matching_filenames():
    paths = cl.discover_configs(PROMPTFOO_DIR, pattern="*.ab.yaml")

    assert len(paths) == EXPECTED_AB_CONFIG_COUNT


def test_skill_and_glob_filters_intersect():
    paths = cl.discover_configs(PROMPTFOO_DIR, skill="implementing-with-tdd", pattern="*.ab.yaml")

    assert [p.name for p in paths] == ["skill-implementing-with-tdd.ab.yaml"]


# ==========================================================================
# Token estimate
# ==========================================================================


def test_token_estimate_is_zero_for_empty_text():
    assert ctok.estimate_tokens("") == 0


def test_token_estimate_grows_with_length_and_is_at_least_one():
    assert ctok.estimate_tokens("a") == 1
    assert ctok.estimate_tokens("a" * 400) == 100
    assert ctok.estimate_tokens("a" * 401) == 101


def test_token_estimate_documents_its_method():
    assert "character" in ctok.ESTIMATE_METHOD.lower()


# ==========================================================================
# CLI dry run
#
# Risk: the "offline" runner reaches the network anyway (an SDK import with a
# client constructed at module import, a telemetry ping), so a dry run costs
# money or fails in a sandbox. #660 exists because the OpenAI credit backing
# the old gate ran out; a dry run that spends anything defeats the point.
# Technique: error guessing on the historic failure mode, enforced by
# poisoning every socket/HTTP constructor for the duration of the run.
# ==========================================================================


def test_dry_run_prints_per_config_and_total_and_exits_zero(capsys):
    code = ccli.main(["--dry-run", "--config-dir", str(PROMPTFOO_DIR)])
    out = capsys.readouterr().out

    assert code == 0
    assert "skill-closing-qa-gaps.yaml" in out
    assert out.count("\n") > EXPECTED_CONFIG_COUNT
    assert "TOTAL" in out
    assert f"{EXPECTED_CONFIG_COUNT} configs" in out


def test_dry_run_totals_are_the_hand_counted_fixture_figures(tmp_path, capsys):
    """Independently derived, never re-derived from the code under test.

    Two prompts x two tests = four cases, with these rendered prompts and
    `ceil(len / 4)` token counts, counted by hand:

        "Question: aa"     -> 12 chars -> 3 tokens
        "Q: aa"            ->  5 chars -> 2 tokens
        "Question: bbbbbb" -> 16 chars -> 4 tokens
        "Q: bbbbbb"        ->  9 chars -> 3 tokens
                                         --------
                                         12 tokens

    Recomputing the figure with the loader, renderer and estimator the CLI
    itself calls would make both sides agree on a wrong number.
    """
    (tmp_path / "skill-fixture.yaml").write_text(
        "description: hand-countable fixture\n"
        "providers: [echo]\n"
        "prompts:\n"
        '  - "Question: {{q}}"\n'
        '  - "Q: {{q}}"\n'
        "tests:\n"
        '  - vars: {q: "aa"}\n'
        '  - vars: {q: "bbbbbb"}\n',
        encoding="utf-8",
    )

    code = ccli.main(["--dry-run", "--config-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "skill-fixture.yaml" in out
    assert "4 cases" in out
    assert "12 tokens" in out
    assert "1 configs  4 cases  12 tokens (estimated)" in out


def test_the_hand_counted_fixture_renders_the_prompts_it_claims(tmp_path):
    """The arithmetic above is only sound if these are the rendered prompts."""
    (tmp_path / "skill-fixture.yaml").write_text(
        "description: hand-countable fixture\n"
        "providers: [echo]\n"
        "prompts:\n"
        '  - "Question: {{q}}"\n'
        '  - "Q: {{q}}"\n'
        "tests:\n"
        '  - vars: {q: "aa"}\n'
        '  - vars: {q: "bbbbbb"}\n',
        encoding="utf-8",
    )

    rendered = [
        c.rendered_prompt for c in cl.build_cases(cl.load_config(tmp_path / "skill-fixture.yaml"))
    ]

    assert rendered == ["Question: aa", "Q: aa", "Question: bbbbbb", "Q: bbbbbb"]
    assert [len(p) for p in rendered] == [12, 5, 16, 9]


def test_dry_run_with_a_skill_filter_scopes_the_matrix(capsys):
    code = ccli.main(
        ["--dry-run", "--skill", "triaging-test-failures", "--config-dir", str(PROMPTFOO_DIR)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "skill-triaging-test-failures.yaml" in out
    assert "skill-closing-qa-gaps.yaml" not in out
    assert "1 configs" in out


def test_dry_run_over_an_empty_selection_exits_non_zero(capsys):
    code = ccli.main(["--dry-run", "--skill", "nope", "--config-dir", str(PROMPTFOO_DIR)])

    assert code == 1
    assert "no configs" in capsys.readouterr().err.lower()


def test_running_without_dry_run_is_refused_in_this_slice(capsys):
    code = ccli.main(["--config-dir", str(PROMPTFOO_DIR)])

    assert code == 2
    assert "--dry-run" in capsys.readouterr().err


# Every process-creation entry point `os` can expose, across platforms.
# The set is NOT the same everywhere: `posix_spawn`, `posix_spawnp` and
# `fork` are POSIX-only, `startfile` is Windows-only. Patching the whole
# list unconditionally raised `AttributeError` on the Windows runners before
# the dry run even started, and simply dropping the platform-specific names
# would have left Windows with a thinner guard than POSIX.
_OS_SPAWN_ENTRY_POINTS = (
    "system",
    "execv",
    "execve",
    "spawnv",
    "spawnve",
    "posix_spawn",
    "posix_spawnp",
    "startfile",
    "fork",
    "forkpty",
)


def _available_spawn_entry_points(module: object) -> list[str]:
    """Which of those entry points `module` actually exposes.

    Takes the module as an argument rather than reading `os` directly so the
    Windows selection can be asserted from a POSIX host - flipping `os.name`
    to fake a platform is not an option, since it desyncs `pathlib` from the
    real filesystem and breaks config discovery.
    """
    return [name for name in _OS_SPAWN_ENTRY_POINTS if hasattr(module, name)]


class _PlatformOs:
    """Stands in for a platform's `os`, exposing only its own entry points."""

    def __init__(self, names: tuple[str, ...]) -> None:
        for name in names:
            setattr(self, name, lambda *args, **kwargs: None)


_WINDOWS_SPAWN = ("system", "execv", "execve", "spawnv", "spawnve", "startfile")
_POSIX_SPAWN = (
    "system",
    "execv",
    "execve",
    "spawnv",
    "spawnve",
    "posix_spawn",
    "posix_spawnp",
    "fork",
    "forkpty",
)


def test_the_spawn_guard_selects_each_platform_s_own_entry_points():
    """The guard below must not be thinner on one platform than the other,
    and a misspelled name would be skipped by `hasattr` in silence."""

    windows = _available_spawn_entry_points(_PlatformOs(_WINDOWS_SPAWN))
    posix = _available_spawn_entry_points(_PlatformOs(_POSIX_SPAWN))

    assert windows == list(_WINDOWS_SPAWN)
    assert posix == list(_POSIX_SPAWN)

    # Every listed name is real on at least one platform, so none is a typo.
    assert set(_OS_SPAWN_ENTRY_POINTS) == set(windows) | set(posix)

    # Each platform keeps its own primitives, not just the shared ones.
    assert "startfile" in windows and "startfile" not in posix
    assert {"posix_spawn", "fork"} <= set(posix)
    assert {"posix_spawn", "fork"}.isdisjoint(windows)

    # And the list matches the `os` this run is actually on.
    assert _available_spawn_entry_points(os) == list(
        _POSIX_SPAWN if os.name != "nt" else _WINDOWS_SPAWN
    )


def test_dry_run_constructs_no_socket_no_http_client_and_no_child_process(monkeypatch, capsys):
    """In-process socket poisoning alone would miss an `os.system("curl ...")`
    or any other spawn, so the process-creation entry points are refused for
    the duration of the guarded run too."""

    def explode(*args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("the dry run must not touch the network")

    def no_spawn(*args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("the dry run must not spawn a child process")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", explode)
    monkeypatch.setattr(http.client.HTTPSConnection, "__init__", explode)
    monkeypatch.setattr(subprocess.Popen, "__init__", no_spawn)
    # `multiprocessing` reaches neither `subprocess.Popen` nor any `os` name
    # below: it goes through `_posixsubprocess.fork_exec` on POSIX and
    # `_winapi.CreateProcess` on Windows. A child started that way would also
    # miss the socket poisoning above, so it is an out-of-process network
    # escape this test would otherwise pass straight through.
    monkeypatch.setattr(multiprocessing.Process, "start", no_spawn)

    patched = _available_spawn_entry_points(os)
    for name in patched:
        monkeypatch.setattr(os, name, no_spawn)

    # Without this the guard could cover nothing at all and still pass green.
    assert {"system", "execv", "execve", "spawnv", "spawnve"} <= set(patched)

    code = ccli.main(["--dry-run", "--config-dir", str(PROMPTFOO_DIR)])

    assert code == 0
    assert "TOTAL" in capsys.readouterr().out


def _imported_root_modules(source: str) -> set[str]:
    """Every module name a source file imports, from its parsed AST.

    Grepping for `import anthropic` misses `from anthropic import Anthropic`,
    `import anthropic as a`, and `from anthropic.types import X`.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module)
    return {name.split(".")[0] for name in roots} | roots


def test_the_runner_imports_no_http_client_or_anthropic_sdk():
    banned = {
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "http",
        "urllib",
        "urllib3",
        "socket",
        "ssl",
        "subprocess",
        "multiprocessing",
        "asyncio",
    }
    for module in (cl, ct, ca, ctok, ccli):
        imported = _imported_root_modules(Path(module.__file__).read_text(encoding="utf-8"))
        offending = imported & banned
        assert not offending, f"{module.__name__} imports {sorted(offending)}"


def test_the_import_guard_catches_a_from_import(tmp_path):
    """The guard's own teeth: a substring check for `import anthropic` would
    let this line through."""
    assert "anthropic" in _imported_root_modules("from anthropic import Anthropic\n")
    assert "anthropic" in _imported_root_modules("import anthropic as sdk\n")
    assert "anthropic" in _imported_root_modules("from anthropic.types import Message\n")
    assert "urllib" in _imported_root_modules("import urllib.request\n")
