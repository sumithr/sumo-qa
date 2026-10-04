# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The promptfoo provider that runs evals through `claude -p` (issue #662).

What matters is that a failed call reaches promptfoo as an `error`, never as
output that gets graded (#651), and that every call carries the isolation
flags. No test here runs the real CLI.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

_PATH = Path(__file__).parent / "evals" / "promptfoo" / "providers" / "claude_cli.py"
_spec = importlib.util.spec_from_file_location("claude_cli_provider", _PATH)
provider = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(provider)

OPTIONS = {"config": {"model": "claude-haiku-4-5", "systemPrompt": "Answer."}}
SUCCESS = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "the answer",
    "usage": {
        "input_tokens": 3,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 20,
        "output_tokens": 7,
    },
    "total_cost_usd": 0.25,
}


@pytest.fixture(autouse=True)
def _reply_dir(tmp_path, monkeypatch):
    """Unparsed judge replies land in a temp dir, never in tests/evals/results."""
    monkeypatch.setattr(provider, "REPLY_DIR", tmp_path / "judge-replies")
    return tmp_path / "judge-replies"


def _fake_cli(monkeypatch, *stdouts, returncode=0):
    """Each call answers with the next stdout; the last one repeats."""
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        stdout = stdouts[min(len(calls), len(stdouts)) - 1]
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(provider.subprocess, "run", run)
    return calls


def test_a_successful_call_returns_the_answer_with_all_prompt_tokens_counted(monkeypatch):
    calls = _fake_cli(monkeypatch, json.dumps(SUCCESS))

    response = provider.call_api("the prompt", OPTIONS)

    assert response == {
        "output": "the answer",
        "tokenUsage": {"prompt": 123, "completion": 7, "total": 130},
        "cost": 0.25,
    }
    argv, kwargs = calls[0]
    assert argv == [
        "claude",
        *provider.BASE_FLAGS,
        "--model",
        "claude-haiku-4-5",
        "--system-prompt",
        "Answer.",
    ]
    assert "--strict-mcp-config" in argv and argv[argv.index("--tools") + 1] == ""
    assert kwargs["input"] == "the prompt"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    # Each case trips exactly one check, so no check hides behind another.
    [
        pytest.param(
            json.dumps({**SUCCESS, "is_error": True, "result": "Claude usage limit reached"}),
            0,
            id="is-error-with-exit-0",
        ),
        pytest.param(
            json.dumps({**SUCCESS, "api_error_status": 429, "result": "rate limited"}),
            0,
            id="api-error-status-with-exit-0",
        ),
        pytest.param(
            json.dumps({**SUCCESS, "type": "error", "result": "Claude usage limit reached"}),
            0,
            id="unknown-envelope-type",
        ),
        pytest.param(
            json.dumps({**SUCCESS, "subtype": "error_max_turns"}), 0, id="non-success-subtype"
        ),
        pytest.param(json.dumps(SUCCESS), 1, id="success-envelope-with-nonzero-exit"),
        pytest.param(json.dumps({**SUCCESS, "result": "  "}), 0, id="success-without-answer"),
        pytest.param(
            json.dumps({**SUCCESS, "result": "Claude AI usage limit reached|1789400000"}),
            0,
            id="usage-limit-text-in-a-success-envelope",
        ),
        pytest.param(
            json.dumps({**SUCCESS, "result": "Error: Claude AI Usage Limit Reached|1789400000"}),
            0,
            id="usage-limit-text-with-a-prefix-and-other-case",
        ),
        pytest.param("not json", 1, id="unparseable-output"),
        pytest.param("[]", 0, id="json-but-not-an-envelope"),
    ],
)
def test_a_failed_call_is_an_error_never_graded_output(monkeypatch, stdout, returncode):
    _fake_cli(monkeypatch, stdout, returncode=returncode)

    response = provider.call_api("the prompt", OPTIONS)

    assert "output" not in response and response["error"]


@pytest.mark.parametrize(
    "exc",
    [FileNotFoundError("claude"), subprocess.TimeoutExpired("claude", 600)],
    ids=["cli-missing", "timeout"],
)
def test_a_cli_that_cannot_run_is_an_error(monkeypatch, exc):
    def run(*args, **kwargs):
        raise exc

    monkeypatch.setattr(provider.subprocess, "run", run)

    response = provider.call_api("the prompt", OPTIONS)

    assert "output" not in response and response["error"]


def test_a_config_without_a_model_is_an_error(monkeypatch):
    _fake_cli(monkeypatch, json.dumps(SUCCESS))

    assert set(provider.call_api("the prompt", {"config": {}})) == {"error"}


@pytest.mark.parametrize(
    "envelope",
    [
        {**SUCCESS, "usage": "not a dict"},
        {**SUCCESS, "usage": {"input_tokens": "lots", "output_tokens": None}},
        {**SUCCESS, "total_cost_usd": "free"},
        {**SUCCESS, "usage": {"input_tokens": float("nan"), "output_tokens": float("inf")}},
    ],
    ids=["usage-not-a-dict", "non-numeric-tokens", "non-numeric-cost", "non-finite-tokens"],
)
def test_malformed_accounting_keeps_the_answer(monkeypatch, envelope):
    _fake_cli(monkeypatch, json.dumps(envelope))

    response = provider.call_api("the prompt", OPTIONS)

    assert response["output"] == "the answer"
    assert isinstance(response["cost"], float)


def test_a_call_that_fails_after_reporting_usage_is_still_counted(monkeypatch):
    limit = {**SUCCESS, "result": "Claude AI usage limit reached|1789400000"}
    _fake_cli(monkeypatch, json.dumps(limit))

    response = provider.call_api("the prompt", OPTIONS)

    assert response["error"].startswith("claude usage limit: ")
    assert response["tokenUsage"] == {"prompt": 123, "completion": 7, "total": 130}
    assert response["cost"] == 0.25


def test_an_answer_that_quotes_the_usage_limit_phrase_is_still_graded(monkeypatch):
    quoted = "Claude AI usage limit reached is the message the CLI prints when you hit the cap."
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": quoted}))

    assert provider.call_api("the prompt", OPTIONS)["output"] == quoted


JUDGE_OPTIONS = {"config": {**OPTIONS["config"], "jsonReply": True}}
# The console excerpt cap, written out so the test does not read it from the code under test.
_EXCERPT_CAP = 400
_VERDICT = {"pass": False, "score": 0.1, "reason": "x } y"}


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        # A judge reply whose reason ends in a lone `}`: promptfoo's brace counter finds no
        # object in it and drops the grade.
        pytest.param(
            '{"pass": true, "score": 0.87, "reason": "anti-patterns all ABSENT. Verdict: PASS.\\"}"}',
            {"pass": True, "score": 0.87, "reason": 'anti-patterns all ABSENT. Verdict: PASS."}'},
            id="lone-closing-brace-in-reason",
        ),
        # A lone `{` makes promptfoo extract a garbage object without "pass", which it
        # grades as a pass with score 1.
        pytest.param(
            '{"pass": false, "score": 0.1, "reason": "leaves a brace {\\"not closed\\" in it"}',
            {"pass": False, "score": 0.1, "reason": 'leaves a brace {"not closed" in it'},
            id="lone-opening-brace-in-reason",
        ),
        pytest.param("```json\n" + json.dumps(_VERDICT) + "\n```", _VERDICT, id="json-fence"),
        pytest.param(
            "Here is my grade: " + json.dumps(_VERDICT) + " Hope that helps {.",
            _VERDICT,
            id="prose-around-the-verdict",
        ),
        pytest.param(
            'Quoting {"note": 1} first, then ' + json.dumps(_VERDICT),
            _VERDICT,
            id="an-object-without-pass-before-the-verdict",
        ),
    ],
)
def test_a_json_reply_reaches_promptfoo_as_the_parsed_verdict(monkeypatch, reply, verdict):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": reply}))

    assert provider.call_api("the prompt", JUDGE_OPTIONS)["output"] == verdict


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        # A "pass" key nested inside a verdict that agrees with it is not a second verdict.
        pytest.param(
            '{"pass": false, "score": 0.2, "reason": "r", "detail": {"pass": false}}',
            {"pass": False, "score": 0.2, "reason": "r", "detail": {"pass": False}},
            id="a-nested-pass-that-agrees-with-the-verdict",
        ),
        # The word "pass" without a key separator after it is prose, not a pass key.
        pytest.param(
            "It passes, no bypass needed, and the candidate passed the test. "
            + json.dumps(_VERDICT),
            _VERDICT,
            id="pass-words-in-prose-before-the-verdict",
        ),
        pytest.param('{"pass": true}', {"pass": True}, id="pass-alone"),
        pytest.param(
            '{"pass": true, "score": 1, "reason": "integer score"}',
            {"pass": True, "score": 1, "reason": "integer score"},
            id="integer-score",
        ),
        # The verdict need not close the reply (#796): an object or prose after it is not
        # a grade.
        pytest.param(
            json.dumps(_VERDICT) + ' {"error": "grading unavailable"}',
            _VERDICT,
            id="an-object-without-pass-after-the-verdict",
        ),
        pytest.param(
            json.dumps(_VERDICT) + '\n\nNote: the test asserts `{"total": 7.99}`.',
            _VERDICT,
            id="trailing-prose-with-an-object-after-the-verdict",
        ),
        # A raw newline or tab inside the reason string is not valid strict JSON.
        pytest.param(
            '{"pass": true, "score": 0.9, "reason": "A SHAPE: PASS.\nB GROUNDING:\tPASS."}',
            {"pass": True, "score": 0.9, "reason": "A SHAPE: PASS.\nB GROUNDING:\tPASS."},
            id="raw-control-characters-in-the-reason",
        ),
        # The same verdict twice is one grade, and 1 and 1.0 are the same score.
        pytest.param(
            json.dumps(_VERDICT) + " Restated: " + json.dumps(_VERDICT),
            _VERDICT,
            id="the-same-verdict-repeated",
        ),
        pytest.param(
            '{"pass": true, "score": 1} {"pass": true, "score": 1.0}',
            {"pass": True, "score": 1},
            id="the-same-verdict-with-an-int-then-a-float-score",
        ),
        pytest.param(
            '{"pass": true, "d": {"s": [1]}} {"pass": true, "d": {"s": [1.0]}}',
            {"pass": True, "d": {"s": [1]}},
            id="the-same-verdict-with-a-nested-int-then-float",
        ),
        # A prose `{` (no quoted key after it) that does not decode is skipped.
        pytest.param(
            "Sets {x}, {} and {0: 1 aside: " + json.dumps(_VERDICT),
            _VERDICT,
            id="stray-prose-braces-before-the-verdict",
        ),
        # The rubric's own output-format template, quoted before the real verdict, is
        # not a verdict (its values are <placeholders>).
        pytest.param(
            'Required format {"pass": <true|false>, "score": <0.0 to 1.0>, "reason": '
            '"<grounding/relevance or redirect verdict>"}. Here: '
            '{"pass": true, "score": 0.9, "reason": "ok"}',
            {"pass": True, "score": 0.9, "reason": "ok"},
            id="the-rubric-format-template-before-the-verdict",
        ),
        pytest.param(
            '{ "pass": <true|false>, ... } Here: {"pass": true, "score": 0.9, "reason": "ok"}',
            {"pass": True, "score": 0.9, "reason": "ok"},
            id="a-spaced-format-template-before-the-verdict",
        ),
        # A verdict followed by prose punctuation, a newline, a fence or more prose stays
        # graded: only structural characters after an object mean it was cut out.
        pytest.param(json.dumps(_VERDICT) + ".", _VERDICT, id="a-verdict-then-a-full-stop"),
        pytest.param(json.dumps(_VERDICT) + "\n", _VERDICT, id="a-verdict-then-a-newline"),
        pytest.param("```\n" + json.dumps(_VERDICT) + "```", _VERDICT, id="a-verdict-then-a-fence"),
        pytest.param(
            json.dumps(_VERDICT) + " Both axes were weighed.",
            _VERDICT,
            id="a-verdict-then-more-prose",
        ),
        pytest.param(
            '{x} {"pass": true, "score": 1, "reason": "ok"}',
            {"pass": True, "score": 1, "reason": "ok"},
            id="a-prose-brace-pair-before-the-verdict",
        ),
    ],
)
def test_the_graded_verdict_is_the_one_top_level_verdict(monkeypatch, reply, verdict):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": reply}))

    assert provider.call_api("the prompt", JUDGE_OPTIONS)["output"] == verdict


# promptfoo grades a missing or non-boolean "pass" as a pass (`parsed.pass ?? true`, and
# "yes" matches its truthy pattern), so every reply here must be an error, never a grade.
@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        pytest.param("not json", "no verdict", id="no-json"),
        pytest.param(
            '{"score": 1, "reason": "no pass key"}', "no verdict", id="object-without-pass"
        ),
        # A "pass" key outside every decoded top-level object means a verdict did not
        # decode: the reply is refused whole, never graded through an object nested in it.
        pytest.param(
            '{"pass": true, "reason": "cut off', "malformed verdict", id="truncated-object"
        ),
        pytest.param(
            '{"pass": false, "score": 0.3, "axes": [{"pass": true, "score": 1}], "reason": "cut off',
            "malformed verdict",
            id="truncated-fail-with-a-nested-pass",
        ),
        pytest.param(
            '{"pass": false, "score": 0.3, "detail": {"pass": true},}',
            "malformed verdict",
            id="trailing-comma-around-a-nested-pass",
        ),
        pytest.param(
            '{"pass": false, "score": 0.3, "reason": "... fixture returns {"pass": true, '
            '"score": 1} for every row, and its config sets {"threshold": 0.5}. VERDICT: FAIL."}',
            "malformed verdict",
            id="unescaped-quotes-around-a-nested-pass",
        ),
        pytest.param(
            '{"A SHAPE": {"pass": true}, "B GROUNDING": {"pass": true}, "pass": false, '
            '"reason": "B is "weak""}',
            "malformed verdict",
            id="unescaped-quotes-after-nested-axis-passes",
        ),
        pytest.param(
            '{"1": {"pass": true, "score": 1}, "pass": false, "reason": "cut',
            "malformed verdict",
            id="truncated-with-a-numeric-first-key",
        ),
        pytest.param(
            '{"pass" false, "notes": {"pass": true, "score": 1}}',
            "malformed verdict",
            id="a-pass-key-missing-its-colon",
        ),
        pytest.param(
            '{"pass": <false>, "notes": {"pass": true, "score": 1}}',
            "malformed verdict",
            id="a-placeholder-that-is-not-the-format-template",
        ),
        pytest.param(
            '{"axes": [{"pass": true, "score": 1}], "pass": false, "reason": "cut',
            "malformed verdict",
            id="truncated-with-a-non-verdict-first-key",
        ),
        pytest.param(
            '{"verdict": "FAIL", "pass": false, "notes": {"pass": true, "score": 1}, }',
            "malformed verdict",
            id="trailing-comma-with-a-non-verdict-first-key",
        ),
        pytest.param(
            '{"verdict": "fail", "pass": false, "reason": "it said "see {"pass": true}" here"}',
            "malformed verdict",
            id="unescaped-quotes-with-a-non-verdict-first-key",
        ),
        pytest.param(
            "{'reason': 'output printed {\"pass\": true} verbatim', 'pass': False, 'score': 0}",
            "malformed verdict",
            id="single-quoted-keys",
        ),
        pytest.param(
            "{'reason': 'x {\"pass\": true}', 'pass': False}",
            "malformed verdict",
            id="single-quoted-pass-after-a-quoted-verdict",
        ),
        # A verdict that starts inside an object that does not decode is part of that
        # object, never the grade.
        pytest.param(
            '{"summary": {"pass": true, "score": 1}, "reason": "the answer is "fine""}',
            "malformed verdict",
            id="a-verdict-inside-an-object-with-unescaped-quotes",
        ),
        pytest.param(
            '{"summary": {"pass": true, "score": 1}, "reason": "x",}',
            "malformed verdict",
            id="a-verdict-inside-an-object-with-a-trailing-comma",
        ),
        pytest.param(
            '{"axes": [{"pass": true, "score": 1}], "reason": "cut',
            "malformed verdict",
            id="a-verdict-inside-a-truncated-object",
        ),
        pytest.param(
            '{"A SHAPE": {"pass": true, "score": 1}, "B GROUNDING": ',
            "malformed verdict",
            id="an-axis-verdict-inside-a-truncated-object",
        ),
        pytest.param(
            '{"PASS": false, "notes": {"pass": true, "score": 1}, "reason": "cut',
            "malformed verdict",
            id="a-verdict-inside-a-truncated-object-with-an-upper-case-pass",
        ),
        pytest.param("I think it passes {", "no verdict", id="stray-opening-brace"),
        pytest.param(
            '{"summary": {"pass": true, "score": 1}}',
            "malformed verdict",
            id="pass-only-inside-a-non-verdict-object",
        ),
        # Fail-closed: a quoted-key object that does not decode, or a "pass" key outside
        # every decoded verdict, may be the grade, so the reply is never graded from a guess.
        pytest.param(
            'Printed {\'status\': \'ok\'} as "ok". {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-quoted-python-dict-before-the-verdict",
        ),
        pytest.param(
            'Code: {"id": user.id}. {"pass": true, "score": 0.9, "reason": "ok"}',
            "malformed verdict",
            id="a-quoted-js-snippet-before-the-verdict",
        ),
        pytest.param(
            'Steps {"steps": [1, 2 then {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="an-unclosed-steps-fragment-before-the-verdict",
        ),
        pytest.param(
            'Sends {"method": "POST" here. {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="an-unclosed-method-fragment-before-the-verdict",
        ),
        pytest.param(
            'Rubric requires "pass": true only if A.\n{"pass": false, "score": 0.2, "reason": "bad"}',
            "malformed verdict",
            id="a-pass-key-in-prose-before-the-verdict",
        ),
        pytest.param(
            'Axis A: "pass": true. Axis B: "pass": false. '
            '{"pass": false, "score": 0.4, "reason": "B fails"}',
            "malformed verdict",
            id="per-axis-pass-keys-in-prose-before-the-verdict",
        ),
        pytest.param(
            'Final: "pass": false. Example of format: {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-prose-grade-then-an-example-verdict",
        ),
        pytest.param(
            'Example: {"pass": true, "score": 1, "reason": "ok"}. My verdict: '
            '{"pass": <false>, "score": 0.1, "reason": "bad"}',
            "malformed verdict",
            id="an-example-verdict-then-a-placeholder-verdict",
        ),
        pytest.param(
            '{"reason": "the "}" char", "inner": {"pass": true, "score": 1, "reason": "x"}}',
            "malformed verdict",
            id="a-quoted-closing-brace-before-a-nested-verdict",
        ),
        pytest.param(
            '{"reason": "x "} y", "inner": [{"pass": true, "score": 1, "reason": "x"}]}',
            "malformed verdict",
            id="a-quoted-closing-brace-before-a-verdict-in-a-list",
        ),
        # An object followed by `,` `"` `:` `}` or `]` was cut out of a larger structure,
        # so a verdict after it may be nested, never top level.
        pytest.param(
            '{"reason": "x "} y", "axes": [{"a": 1}, {"pass": true}]}',
            "malformed verdict",
            id="a-quoted-closing-brace-before-a-sibling-of-a-nested-verdict",
        ),
        pytest.param(
            '{"a": 1}, {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="an-object-followed-by-a-comma-before-the-verdict",
        ),
        pytest.param(
            '{"reason": "it printed "}" alone", "axes": [{"pass": true, "score": 1}], '
            '"pass": false, "score": 0.1}',
            "malformed verdict",
            id="a-quoted-closing-brace-before-nested-axis-passes",
        ),
        pytest.param(
            'Example: {"pass": true, "score": 1, "reason": "ok"}. Mine: {score: 0.1, "pass": false}',
            "malformed verdict",
            id="an-example-verdict-then-an-unquoted-key-verdict",
        ),
        # A repeated key never collapses to its last value.
        pytest.param(
            '{"pass": false, "score": 0.1, "reason": "x", "pass": true}',
            "malformed verdict",
            id="a-duplicate-pass-key-false-then-true",
        ),
        pytest.param(
            '{"pass": false, "pass": true, "score": 1}',
            "malformed verdict",
            id="a-duplicate-pass-key-before-the-score",
        ),
        # A pass key in any spelling outside the verdict may be the grade.
        pytest.param(
            'Mine: {pass: false, score: 0.1}. Example {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="an-unquoted-pass-key-then-an-example-verdict",
        ),
        pytest.param(
            'PASS: false. Example: {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="an-upper-case-prose-pass-key-then-an-example-verdict",
        ),
        pytest.param(
            'pass: false\nscore: 0.1\n\nExample: {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-yaml-verdict-then-an-example-verdict",
        ),
        pytest.param(
            '**"pass"**: false\n{"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-bold-pass-key-then-a-verdict",
        ),
        pytest.param(
            '"pass" = false. Example: {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-pass-key-with-an-equals-sign-then-a-verdict",
        ),
        pytest.param(
            '{\u201cpass\u201d: false} {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-curly-quoted-pass-key-then-a-verdict",
        ),
        pytest.param(
            'Verdict string: "{\\"pass\\": false}". {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="an-escaped-pass-key-then-a-verdict",
        ),
        pytest.param(
            '{"Pass": false, "reason": "fails"}\n{"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-capitalised-pass-key-object-then-a-verdict",
        ),
        pytest.param(
            '`pass`: false\n{"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-backticked-pass-key-then-a-verdict",
        ),
        # Inside a decoded object, a key spelled like "pass" or a boolean "passed" or
        # "verdict" may be the grade.
        pytest.param(
            '{"pass": true, "score": 1, "reason": "ok", " PASS": false}',
            "malformed verdict",
            id="a-variant-pass-key-inside-the-verdict",
        ),
        pytest.param(
            '{"passed": false} {"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-boolean-passed-key-then-a-verdict",
        ),
        pytest.param(
            '{"pass": true, "score": 1, "reason": "ok", "verdict": false}',
            "malformed verdict",
            id="a-boolean-verdict-key-inside-the-verdict",
        ),
        # A nested "pass" that differs from the verdict's leaves the grade ambiguous.
        pytest.param(
            '{"pass": true, "score": 1, "reason": "x", "final": {"pass": false, "score": 0.1}}',
            'nested "pass"',
            id="a-nested-pass-that-contradicts-the-verdict",
        ),
        pytest.param(
            '{"pass": true, "score": 1, "reason": "x", "axes": [{"pass": false}]}',
            'nested "pass"',
            id="a-nested-pass-in-a-list-that-contradicts-the-verdict",
        ),
        # Only an exact format template is exempt: a filled-in placeholder is not one.
        pytest.param(
            '{"pass": <true|false> false, "score": 0.1}\n{"pass": true, "score": 1, "reason": "ok"}',
            "malformed verdict",
            id="a-filled-in-format-template-then-a-verdict",
        ),
        pytest.param('{"pass": null, "score": 1}', '"pass"', id="pass-null"),
        pytest.param('{"pass": "yes", "score": 1}', '"pass"', id="pass-string"),
        pytest.param('{"pass": 1}', '"pass"', id="pass-number"),
        pytest.param('{"pass": true, "score": "0.9"}', '"score"', id="score-string"),
        pytest.param('{"pass": true, "score": true}', '"score"', id="score-boolean"),
        pytest.param('{"pass": true, "score": NaN}', '"score"', id="score-nan"),
        pytest.param('{"pass": true, "reason": 5}', '"reason"', id="reason-not-a-string"),
        # Two different verdicts leave the grade ambiguous, whichever comes last.
        pytest.param(
            'The format is {"pass": true, "score": 1.0, "reason": "example"}. Mine: '
            + json.dumps(_VERDICT),
            "2 different verdict objects",
            id="a-quoted-example-verdict-before-the-real-one",
        ),
        pytest.param(
            json.dumps(_VERDICT) + ' then {"pass": null}',
            "2 different verdict objects",
            id="an-invalid-verdict-after-a-valid-one",
        ),
        pytest.param(
            '{"pass": true, "score": 0.9, "reason": "r"} On reflection: '
            '{"pass": false, "score": 0.4, "reason": "r"}',
            "2 different verdict objects",
            id="a-changed-mind",
        ),
        # A non-boolean "pass" is never the same verdict as a boolean one, in either order.
        pytest.param(
            '{"pass": true, "score": 1} {"pass": 1, "score": 1}',
            "2 different verdict objects",
            id="a-boolean-then-a-numeric-pass",
        ),
        pytest.param(
            '{"pass": 1, "score": 1} {"pass": true, "score": 1}',
            "2 different verdict objects",
            id="a-numeric-then-a-boolean-pass",
        ),
        pytest.param(
            '{"pass": true, "score": 1} {"pass": true, "score": true}',
            "2 different verdict objects",
            id="an-int-then-a-boolean-score",
        ),
        pytest.param(
            '{"pass": true, "d": {"x": 1}} {"pass": true, "d": {"x": true}}',
            "2 different verdict objects",
            id="a-nested-int-then-a-nested-boolean",
        ),
        # A score too large for a float must be an error, never an OverflowError.
        pytest.param('{"pass": true, "score": 1' + "0" * 400 + "}", '"score"', id="score-huge-int"),
    ],
)
def test_a_json_reply_without_a_boolean_verdict_is_an_error(monkeypatch, reply, problem):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": reply}))

    response = provider.call_api("the prompt", JUDGE_OPTIONS)

    assert "output" not in response
    assert response["error"].startswith("judge reply ")
    assert problem in response["error"]
    # The excerpt is the reply's repr, which escapes a quote the reply mixes with the other.
    assert repr(reply[:40])[1:-1] in response["error"]


# Real judge replies (tests/fixtures/judge_replies.json). The replies the old parser
# rejected were never stored past a 400-character excerpt, so each failure shape the
# excerpts point at is built from a real reply here.
_REPLIES = json.loads(
    (Path(__file__).parent / "fixtures" / "judge_replies.json").read_text(encoding="utf-8")
)
_REAL_VERDICTS = list(_REPLIES["verdicts"].values())
_REAL_IDS = list(_REPLIES["verdicts"])
_SHAPES = {
    "as-captured": lambda reply: reply,
    "trailing-object": lambda reply: reply + '\n\n{"note": "graded on axis A only"}',
    "trailing-prose-with-braces": lambda reply: reply + "\n\nThe test's dict `{a: 1}` is fine.",
    "raw-newline-between-sections": lambda reply: reply.replace(" B GROUNDING", "\nB GROUNDING", 1),
    "verdict-repeated": lambda reply: reply + "\n\n" + reply,
}


@pytest.mark.parametrize("shape", list(_SHAPES))
@pytest.mark.parametrize("reply", _REAL_VERDICTS, ids=_REAL_IDS)
def test_a_real_judge_verdict_is_graded_in_every_captured_shape(monkeypatch, reply, shape):
    shaped = _SHAPES[shape](reply)
    # The newline shape is the reply's own verdict with a raw newline in its reason.
    verdict = json.loads(shaped if shape == "raw-newline-between-sections" else reply, strict=False)
    calls = _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": shaped}))

    response = provider.call_api("the prompt", JUDGE_OPTIONS)

    assert response["output"] == verdict
    assert len(calls) == 1


@pytest.mark.parametrize("reply", _REAL_VERDICTS, ids=_REAL_IDS)
def test_a_real_verdict_contradicted_later_in_the_reply_is_an_error(monkeypatch, reply):
    verdict = json.loads(reply)
    flipped = json.dumps({**verdict, "pass": not verdict["pass"]})
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": reply + "\n\n" + flipped}))

    assert "2 different verdict objects" in provider.call_api("the prompt", JUDGE_OPTIONS)["error"]


def test_a_real_answer_with_no_verdict_is_an_error_after_two_calls(monkeypatch):
    [answer] = _REPLIES["no_verdict"].values()
    calls = _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": answer}))

    error = provider.call_api("the prompt", JUDGE_OPTIONS)["error"]

    assert error.startswith('judge reply has no verdict object with a "pass" key (asked twice')
    assert len(calls) == 2


def test_a_valid_judge_reply_reaches_promptfoo_unchanged_after_one_call(monkeypatch):
    calls = _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": json.dumps(_VERDICT)}))

    response = provider.call_api("the prompt", JUDGE_OPTIONS)

    assert response == {
        "output": _VERDICT,
        "tokenUsage": {"prompt": 123, "completion": 7, "total": 130},
        "cost": 0.25,
    }
    assert len(calls) == 1


def test_a_reply_without_a_verdict_is_asked_once_more(monkeypatch, _reply_dir):
    calls = _fake_cli(
        monkeypatch,
        json.dumps({**SUCCESS, "result": "I think it passes."}),
        json.dumps({**SUCCESS, "result": json.dumps(_VERDICT)}),
    )

    response = provider.call_api("the prompt", JUDGE_OPTIONS)

    # Both calls are spent, so both are counted.
    assert response == {
        "output": _VERDICT,
        "tokenUsage": {"prompt": 246, "completion": 14, "total": 260},
        "cost": 0.5,
    }
    assert len(calls) == 2
    assert calls[1] == calls[0]
    assert not _reply_dir.exists()


def test_a_second_reply_without_a_verdict_is_kept_in_full_and_redacted(monkeypatch, _reply_dir):
    home = str(Path.home())
    first = "no verdict here " + "x" * 5000 + f" {home}/repo sk-ant-api03-{'a' * 30}"
    second = "no verdict " + "x" * 5000
    calls = _fake_cli(
        monkeypatch,
        json.dumps({**SUCCESS, "result": first}),
        json.dumps({**SUCCESS, "result": second}),
    )

    response = provider.call_api("the prompt", JUDGE_OPTIONS)
    error = response["error"]

    assert len(calls) == 2
    # The console gets a short excerpt of the last reply and where the full ones are.
    assert error.startswith('judge reply has no verdict object with a "pass" key (asked twice')
    assert second[:_EXCERPT_CAP] in error and second[: _EXCERPT_CAP + 1] not in error
    [kept] = list(_reply_dir.iterdir())
    assert str(kept) in error
    saved = json.loads(kept.read_text(encoding="utf-8"))
    assert [entry["problem"] for entry in saved] == ['has no verdict object with a "pass" key'] * 2
    assert saved[0]["reply"] == first.replace(home, "~").replace(
        f"sk-ant-api03-{'a' * 30}", "[REDACTED]"
    )
    assert saved[1]["reply"] == second
    # Both calls were spent, so both are counted even though no grade came back.
    assert response["tokenUsage"] == {"prompt": 246, "completion": 14, "total": 260}
    assert response["cost"] == 0.5


_KEY = "sk-ant-api03-" + "a" * 30


def test_the_console_excerpt_of_an_unparsed_reply_is_redacted(monkeypatch):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": f"no verdict, key {_KEY}"}))

    error = provider.call_api("the prompt", JUDGE_OPTIONS)["error"]

    assert _KEY not in error and "no verdict, key [REDACTED]" in error


def test_a_failed_cli_call_error_is_redacted(monkeypatch):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": f"key {_KEY}"}), returncode=1)

    error = provider.call_api("the prompt", OPTIONS)["error"]

    assert error.startswith("claude call failed") and _KEY not in error and "[REDACTED]" in error


def test_a_retry_that_fails_keeps_the_first_reply(monkeypatch, _reply_dir):
    _fake_cli(
        monkeypatch,
        json.dumps({**SUCCESS, "result": "I think it passes."}),
        json.dumps({**SUCCESS, "result": "Claude AI usage limit reached|1789400000"}),
    )

    response = provider.call_api("the prompt", JUDGE_OPTIONS)
    error = response["error"]

    [kept] = list(_reply_dir.iterdir())
    assert error.startswith("claude usage limit: ")
    assert error.endswith(f"; the earlier judge reply is kept at {kept}")
    assert json.loads(kept.read_text(encoding="utf-8"))[0]["reply"] == "I think it passes."
    # Both calls reported usage, so both are counted, the failed one too.
    assert response["tokenUsage"] == {"prompt": 246, "completion": 14, "total": 260}
    assert response["cost"] == 0.5


def test_the_kept_reply_path_names_home_as_a_tilde(monkeypatch, tmp_path):
    # Path.home, not HOME: on Windows it reads USERPROFILE.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": "no verdict"}))

    error = provider.call_api("the prompt", JUDGE_OPTIONS)["error"]

    assert f"kept at {Path('~', 'judge-replies', 'judge-reply-')}" in error
    assert str(tmp_path) not in error


def test_home_is_redacted_only_as_a_whole_path_component(monkeypatch, tmp_path):
    home = tmp_path / "al"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    text = f"{home / 'repo'} {tmp_path / 'alice' / 'repo'} '{home}' {home}"

    assert provider._redact(text) == f"{Path('~', 'repo')} {tmp_path / 'alice' / 'repo'} '~' ~"


def test_home_is_redacted_before_punctuation_but_not_inside_another_path(monkeypatch, tmp_path):
    home = tmp_path / "al"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    text = f"{home}. {home}, {home}: ({home}) [{home}] /data{home}/x {home}-x {home}_x"

    assert provider._redact(text) == (f"~. ~, ~: (~) [~] /data{home}/x {home}-x {home}_x")


def test_home_is_redacted_before_a_full_stop_but_not_before_a_dotted_name(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/Users/al")))
    text = "/Users/al.smith/x /Users/al.old see /Users/al."

    assert provider._redact(text) == "/Users/al.smith/x /Users/al.old see ~."


def _fake_cli_stderr(monkeypatch, stderr):
    """A CLI that prints no JSON envelope, only `stderr`."""

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(provider.subprocess, "run", run)


def test_a_secret_cut_at_the_excerpt_cap_leaks_no_prefix(monkeypatch):
    _fake_cli_stderr(monkeypatch, "x" * (_EXCERPT_CAP - 11) + " " + _KEY)

    error = provider.call_api("the prompt", OPTIONS)["error"]

    assert _KEY[:10] not in error and "[REDACTED]" in error


def _secret_at(prefix, render=lambda result: result):
    """A result whose _KEY starts 10 characters before the excerpt cap of `render(result)`,
    the text the error excerpt is cut from."""
    pad = _EXCERPT_CAP - 10 - render(prefix + " " + _KEY).index(_KEY)
    return prefix + "x" * pad + " " + _KEY


def test_a_failed_call_excerpt_is_redacted_before_the_cut(monkeypatch):
    result = _secret_at("", lambda result: json.dumps({**SUCCESS, "result": result}))
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": result}), returncode=1)

    error = provider.call_api("the prompt", OPTIONS)["error"]

    assert error.startswith("claude call failed") and "sk-ant-api" not in error


def test_a_usage_limit_excerpt_is_redacted_before_the_cut(monkeypatch):
    _fake_cli(
        monkeypatch,
        json.dumps({**SUCCESS, "result": _secret_at("Claude AI usage limit reached|1789400000")}),
    )

    error = provider.call_api("the prompt", OPTIONS)["error"]

    assert error.startswith("claude usage limit: ") and "sk-ant-api" not in error


def test_a_windows_home_is_redacted_before_the_excerpt_is_quoted(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("C:\\Users\\al")))
    _fake_cli_stderr(monkeypatch, "Traceback: C:\\Users\\al\\repo\\run.py")

    error = provider.call_api("the prompt", OPTIONS)["error"]

    assert "Users" not in error and repr("Traceback: ~\\repo\\run.py") in error


def test_a_root_home_is_never_redacted(monkeypatch, tmp_path):
    root = Path(tmp_path.anchor)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: root))
    text = str(tmp_path / "repo")

    assert provider._redact(text) == text


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-" + "a" * 30,
        "ghp_" + "A1" * 15,
        "github_pat_" + "11ABCDEFG0" * 3,
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "ASIA" + "ABCDEFGHIJKLMNOP",
        "xoxb-" + "1234567890-abcdef",
        "eyJhbGciOiJ.eyJzdWIiOiIx.c2lnbmF0dXJl",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----",
    ],
    ids=[
        "anthropic",
        "github-classic",
        "github-fine-grained",
        "aws-akia",
        "aws-asia",
        "slack",
        "jwt",
        "pem-private-key",
    ],
)
def test_a_kept_reply_has_bare_secrets_redacted(monkeypatch, _reply_dir, secret):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": f"no verdict, key {secret} here"}))

    provider.call_api("the prompt", JUDGE_OPTIONS)

    [kept] = list(_reply_dir.iterdir())
    text = kept.read_text(encoding="utf-8")
    assert secret not in text and "key [REDACTED] here" in text


def test_an_unwritable_reply_dir_still_returns_the_error(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setattr(provider, "REPLY_DIR", blocker / "judge-replies")
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": "no verdict"}))

    error = provider.call_api("the prompt", JUDGE_OPTIONS)["error"]

    assert "kept at nowhere (could not write " in error


def test_without_json_reply_a_json_answer_stays_text(monkeypatch):
    reply = json.dumps(_VERDICT)
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": reply}))

    assert provider.call_api("the prompt", OPTIONS)["output"] == reply


@pytest.mark.parametrize(
    ("config_file", "json_reply"),
    [("claude-judge.yaml", True), ("claude-candidate.yaml", None)],
)
def test_only_the_judge_asks_for_a_parsed_json_reply(config_file, json_reply):
    config = yaml.safe_load((_PATH.parent / config_file).read_text())["config"]

    assert config.get("jsonReply") is json_reply
