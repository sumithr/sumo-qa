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

import http.client
import socket
from pathlib import Path

import pytest
from claude import assertions as ca
from claude import cli as ccli
from claude import loader as cl
from claude import templating as ct
from claude import tokens as ctok

# --------------------------------------------------------------------------
# Grounded inventory, verified against origin/main @ e7809d1 on 2026-09-09.
# Issue #661's body says 65 configs; the live tree has 63 (drift recorded on
# the issue). These constants are a deliberate tripwire: if the matrix grows
# or shrinks, this test fails and whoever changed it updates the number here
# and on the epic, rather than the change passing silently.
# --------------------------------------------------------------------------
EXPECTED_CONFIG_COUNT = 63
EXPECTED_AB_CONFIG_COUNT = 15
EXPECTED_JAVASCRIPT_ASSERT_COUNT = 10

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"


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
    on_disk = sorted(PROMPTFOO_DIR.glob("*.yaml"))

    assert paths == on_disk
    assert len(paths) == EXPECTED_CONFIG_COUNT, (
        f"promptfoo matrix drifted: {len(paths)} configs on disk, "
        f"{EXPECTED_CONFIG_COUNT} recorded. Update the constant and the epic."
    )

    configs = cl.load_all_configs(PROMPTFOO_DIR)
    assert len(configs) == EXPECTED_CONFIG_COUNT
    assert all(c.description for c in configs)


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


def test_regex_evaluator_anchors_the_announce_line_to_the_start():
    assertion = next(
        a for name, a in _live_javascript_asserts() if name == "skill-closing-qa-gaps.yaml"
    )
    evaluator = ca.evaluator_for(assertion)

    buried = "Here is my plan. Closing one QA gap at a time is the discipline."
    assert evaluator.evaluate(buried, {}).passed is False
    assert evaluator.evaluate("> **Closing one QA gap at a time.**", {}).passed is True


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
    for config in cl.load_all_configs(PROMPTFOO_DIR):
        for case in cl.build_cases(config):
            assert "{%" not in case.rendered_prompt
            assert case.rendered_prompt.strip()


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


def test_dry_run_totals_match_the_assembled_cases(capsys):
    ccli.main(["--dry-run", "--skill", "closing-qa-gaps", "--config-dir", str(PROMPTFOO_DIR)])
    out = capsys.readouterr().out

    config = cl.load_config(PROMPTFOO_DIR / "skill-closing-qa-gaps.yaml")
    cases = cl.build_cases(config)
    expected = sum(ctok.estimate_tokens(c.rendered_prompt) for c in cases)

    assert f"{expected:,}" in out
    assert f"{len(cases)} cases" in out


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


def test_dry_run_constructs_no_socket_and_no_http_client(monkeypatch, capsys):
    def explode(*args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("the dry run must not touch the network")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", explode)
    monkeypatch.setattr(http.client.HTTPSConnection, "__init__", explode)

    code = ccli.main(["--dry-run", "--config-dir", str(PROMPTFOO_DIR)])

    assert code == 0
    assert "TOTAL" in capsys.readouterr().out


def test_the_runner_imports_no_http_client_or_anthropic_sdk():
    banned = ("anthropic", "openai", "requests", "httpx", "urllib.request", "urllib3")
    for module in (cl, ct, ca, ctok, ccli):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for name in banned:
            assert f"import {name}" not in source, f"{module.__name__} imports {name}"
