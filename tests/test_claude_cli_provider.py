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


def _fake_cli(monkeypatch, stdout, returncode=0):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
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
    _fake_cli(monkeypatch, stdout, returncode)

    response = provider.call_api("the prompt", OPTIONS)

    assert set(response) == {"error"}


@pytest.mark.parametrize(
    "exc",
    [FileNotFoundError("claude"), subprocess.TimeoutExpired("claude", 600)],
    ids=["cli-missing", "timeout"],
)
def test_a_cli_that_cannot_run_is_an_error(monkeypatch, exc):
    def run(*args, **kwargs):
        raise exc

    monkeypatch.setattr(provider.subprocess, "run", run)

    assert set(provider.call_api("the prompt", OPTIONS)) == {"error"}


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


def test_an_answer_that_quotes_the_usage_limit_phrase_is_still_graded(monkeypatch):
    quoted = "Claude AI usage limit reached is the message the CLI prints when you hit the cap."
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": quoted}))

    assert provider.call_api("the prompt", OPTIONS)["output"] == quoted


JUDGE_OPTIONS = {"config": {**OPTIONS["config"], "jsonReply": True}}
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
    "reply",
    ["not json", '{"score": 1, "reason": "no pass key"}', '{"pass": true, "reason": "cut off'],
    ids=["no-json", "object-without-pass", "truncated-object"],
)
def test_a_json_reply_without_a_verdict_stays_the_raw_text(monkeypatch, reply):
    _fake_cli(monkeypatch, json.dumps({**SUCCESS, "result": reply}))

    assert provider.call_api("the prompt", JUDGE_OPTIONS)["output"] == reply


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
