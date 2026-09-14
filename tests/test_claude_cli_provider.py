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
    ],
    ids=["usage-not-a-dict", "non-numeric-tokens", "non-numeric-cost"],
)
def test_malformed_accounting_keeps_the_answer(monkeypatch, envelope):
    _fake_cli(monkeypatch, json.dumps(envelope))

    response = provider.call_api("the prompt", OPTIONS)

    assert response["output"] == "the answer"
    assert isinstance(response["cost"], float)
