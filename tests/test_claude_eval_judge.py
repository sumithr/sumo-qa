# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the Claude candidate/judge tier of the eval runner.

Slice 2 of epic #660 (issue #662). Slice 1 built the offline half; this covers
the half that talks to a model. Every test here fakes the transport and NONE of
them starts a subprocess or opens a socket - `test_no_test_starts_a_subprocess`
is the guard on that claim.

The runner reaches Claude through the local Claude Code CLI on the account's
subscription, not through the Anthropic SDK with a metered API key. That
reverses what issue #662 originally specified, on the user's instruction of
2026-09-10: epic #660 exists because the eval gate stopped being runnable when
metered credit ran out, and buying tokens for its replacement would rebuild the
same trap.

The four risks these tests exist for, and the technique each applies:

* **A quota / usage-limit failure is absorbed and the run reports a degraded
  pass** - the #651 incident, where HTTP 429 `credit_balance_exhausted` turned
  into a zero-passed baseline on disk. Technique: *decision tables* over
  (failure text, api_error_status) -> abort / retry, with every row enumerated
  including the ones that must NOT abort.
* **An artifact survives an aborted run.** A report left on disk after a fatal
  failure IS the zero-passed snapshot. Technique: *state transition testing* -
  the legal transitions are in-flight -> completed (report written) and
  in-flight -> aborted (nothing written); the illegal one is
  aborted -> written.
* **The judge silently passes a malformed reply.** promptfoo's own
  `runJsonGradingPrompt` does `pass = parsed.pass ?? true`, so a reply with no
  `pass` key PASSES. Technique: *equivalence partitioning* over reply classes
  (well-formed, fenced, prose-wrapped, missing `pass`, stringly boolean,
  unparseable, empty).
* **Usage is invented rather than read.** Technique: *real-capture fixtures
  for external-output matchers* - `CLI_ENVELOPE` below is a real
  `claude -p --output-format json` envelope captured from this machine on
  2026-09-10, not a hand-written approximation of one. If the CLI's field
  names move, these tests fail rather than silently reporting zero tokens.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import pytest
from claude import cli as ccli
from claude import errors as ce
from claude import judge as cj
from claude import models as cm
from claude import provider as cp
from claude import report as crep
from claude import runner as crun
from claude.assertions import RubricAssertion

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Grounded model facts, read from the `claude-api` skill reference on
# 2026-09-10 (epic #660 forbids taking these from memory or from the issue
# body) and then confirmed to resolve through the local CLI. #660's stated
# intent: candidate = the WEAKEST current Claude model, judge = the STRONGEST
# widely-released one.
#
# Restated here rather than imported so the assertions do not ask the module
# under test what its own ids are. A model refresh updates both this block and
# `claude/models.py`, in the same change.
# --------------------------------------------------------------------------
EXPECTED_CANDIDATE_MODEL = "claude-haiku-4-5"
EXPECTED_JUDGE_MODEL = "claude-fable-5-1"

# --------------------------------------------------------------------------
# REAL CAPTURE. Emitted by:
#
#   claude -p "Reply with exactly: PONG" --model haiku --output-format json \
#     --max-turns 1 --system-prompt "You are a helpful assistant." --tools "" \
#     --strict-mcp-config --setting-sources "" --disable-slash-commands
#
# on 2026-09-10 with Claude Code 2.1.267, trimmed to the fields the runner
# reads. It is a capture rather than an invention on purpose: a fabricated
# envelope would validate the parser against an assumption about the CLI's
# field names, and `modelUsage` in particular uses camelCase keys and a
# `canonicalModel` field that no reasonable guess would produce.
#
# Note the second model in `modelUsage`: Claude Code runs a small model for its
# own background work, so a call made with one model can report usage for two.
# The runner records usage per model id for exactly that reason.
# --------------------------------------------------------------------------
CLI_ENVELOPE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "api_error_status": None,
    "stop_reason": "end_turn",
    "session_id": "ac4a7c8a-403f-4e1d-b021-f197d323e9c4",
    "result": "PONG",
    "num_turns": 1,
    "total_cost_usd": 0.0190620,
    "usage": {
        "input_tokens": 390,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 58,
        "service_tier": "standard",
    },
    "modelUsage": {
        "claude-haiku-4-5-20251001": {
            "inputTokens": 390,
            "outputTokens": 58,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
            "costUSD": 0.019062,
            "canonicalModel": "claude-haiku-4-5",
            "provider": "firstParty",
            "costBasis": "list",
        }
    },
}


def envelope(**overrides):
    """A copy of the captured envelope with fields replaced."""
    payload = json.loads(json.dumps(CLI_ENVELOPE))
    payload.update(overrides)
    return payload


class FakeProcess:
    """What `subprocess.run` returns, as far as the provider is concerned."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    """Stands in for `subprocess.run`, recording every invocation."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        outcome = self._outcomes.pop(0) if self._outcomes else FakeProcess(json.dumps(envelope()))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_provider(outcomes, **kwargs):
    runner = FakeRunner(outcomes)
    kwargs.setdefault("model", "test-model")
    kwargs.setdefault("system_prompt", "sp")
    kwargs.setdefault("sleep", lambda _: None)
    return cp.Provider(runner=runner, **kwargs), runner


def ok(text: str = "PONG", **overrides):
    return FakeProcess(json.dumps(envelope(result=text, **overrides)))


def _forbidden_subprocess_run(*args, **kwargs):
    raise AssertionError(
        "a test in this module shelled out to the real claude CLI, which would "
        "spend real subscription allowance. Every Provider here must be built "
        "with an injected fake runner."
    )


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """Poison `subprocess.run` for EVERY test in this module.

    Autouse on purpose. A guard that only holds inside the one test that
    installs it guards nothing: the runner in this package exists to spend a
    Claude subscription, and a test that reaches the real CLI spends it for
    real. The cost of that mistake is why this is a fixture and not an
    assertion.
    """
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess_run)


# ==========================================================================
# Model configuration - AC1: ids live in exactly one module
# ==========================================================================


def test_candidate_and_judge_ids_are_the_current_weakest_and_strongest():
    assert cm.CANDIDATE_MODEL == EXPECTED_CANDIDATE_MODEL
    assert cm.JUDGE_MODEL == EXPECTED_JUDGE_MODEL


def test_no_other_runner_file_hardcodes_a_model_id():
    """AC1's real content: one module names the models, nothing else does.

    Scans the runner package and its own tests for anything shaped like a
    Claude model id. `models.py` is the one allowed home; this file restates
    the ids as expectations, and the captured CLI envelope above carries the
    dated id the CLI itself reported, so both are exempt. A THIRD file growing
    one - a default in the CLI, a literal in the judge - fails here, which is
    the drift AC1 is written against.
    """
    pattern = re.compile(r"claude-(?:opus|sonnet|haiku|fable|mythos)-[0-9][0-9a-z-]*")
    allowed = {
        REPO_ROOT / "tests" / "evals" / "claude" / "models.py",
        Path(__file__).resolve(),
    }
    offenders = {}
    scanned = [
        *(REPO_ROOT / "tests" / "evals" / "claude").glob("*.py"),
        *REPO_ROOT.glob("tests/test_claude_eval_*.py"),
    ]
    for path in scanned:
        if path.resolve() in allowed:
            continue
        hits = pattern.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[path.name] = sorted(set(hits))
    assert offenders == {}, f"model ids leaked outside models.py: {offenders}"


def test_the_runner_declares_no_pricing_table_of_its_own():
    """Cost comes from the CLI's reported `costUSD`, never a local rate card.

    A second copy of the rate card is a copy that goes stale silently, and a
    stale rate card makes every cost report wrong without failing anything.
    """
    package = REPO_ROOT / "tests" / "evals" / "claude"
    per_mtok = re.compile(r"usd_per_mtok|PRICING\s*[:=]|per_million_tokens", re.IGNORECASE)
    offenders = [p.name for p in package.glob("*.py") if per_mtok.search(p.read_text("utf-8"))]
    assert offenders == []


# ==========================================================================
# Failure classification - AC4/AC5/AC6, decision table, fail-closed
# ==========================================================================

FATAL_FAILURES = [
    pytest.param("api_error_status 429; result 'credit_balance_exhausted'", None, id="429-credit"),
    pytest.param("Claude usage limit reached. Resets at 5pm", None, id="subscription-usage-limit"),
    pytest.param("rate limit exceeded", None, id="rate-limit-text"),
    pytest.param("exit code 1; Invalid API key. Please run /login", None, id="auth"),
    pytest.param("exit code 1; unknown model 'nope'", 400, id="400-bad-request"),
    pytest.param("api_error_status 401", 401, id="401"),
    pytest.param("something nobody has ever seen before", None, id="unknown-defaults-to-fatal"),
    pytest.param("", None, id="empty-defaults-to-fatal"),
]

TRANSIENT_FAILURES = [
    pytest.param("Error: connection reset by peer", None, id="connection-reset"),
    pytest.param("ECONNREFUSED 127.0.0.1:443", None, id="econnrefused"),
    pytest.param("request timed out", None, id="timeout"),
    pytest.param("api_error_status 500", 500, id="500"),
    pytest.param("api_error_status 503", 503, id="503"),
    pytest.param("api_error_status 529", 529, id="529-overloaded"),
]


@pytest.mark.parametrize("text,status", FATAL_FAILURES)
def test_fatal_failures_are_classified_fatal(text, status):
    assert ce.classify_failure(text, api_error_status=status) == ce.FATAL


@pytest.mark.parametrize("text,status", TRANSIENT_FAILURES)
def test_transient_failures_are_classified_transient(text, status):
    assert ce.classify_failure(text, api_error_status=status) == ce.TRANSIENT


def test_an_unrecognised_failure_defaults_to_fatal_not_retryable():
    """The fail-closed property, asserted directly rather than only via a row.

    The runner cannot capture the exact wording the CLI uses when a
    subscription hits its usage limit without exhausting the account, so the
    classifier must not depend on having guessed it. Anything unrecognised
    stops the run: one wasted re-run beats a wrong baseline.
    """
    assert ce.classify_failure("☃ an emoji nobody planned for") == ce.FATAL


def test_a_quota_message_on_a_5xx_is_still_fatal():
    """The status code is not the only signal.

    A credit failure arriving as a server error must not be retried just
    because 5xx is normally transient.
    """
    assert (
        ce.classify_failure("api_error_status 500; credit balance is too low", api_error_status=500)
        == ce.FATAL
    )


# ==========================================================================
# Provider - the command it builds, its retries, its fail-fast
# ==========================================================================


def test_every_call_disables_tools_settings_mcp_and_slash_commands():
    """The isolation contract, and ~19,100 of the ~19,500 scaffolding tokens.

    Measured on this machine on 2026-09-10: a call with only --system-prompt
    carried ~19,500 tokens of Claude Code scaffolding; adding these flags took
    it to ~390. `--tools ""` accounted for ~16,800 of the saving and
    `--setting-sources ""` for ~1,500. They are correctness as much as
    economy: without --strict-mcp-config the developer's own sumo-qa MCP
    server would be attached to the candidate, which would be grading the
    skills against themselves.
    """
    argv = cp.build_command(model="m", system_prompt="sp")

    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--model") + 1] == "m"
    assert argv[argv.index("--system-prompt") + 1] == "sp"


def test_the_default_system_prompt_is_replaced_not_appended():
    """`--append-system-prompt` would keep Claude Code's own instructions.

    The eval config's prompt is the whole instruction; anything the host adds
    is a variable the matrix must not be sensitive to.
    """
    argv = cp.build_command(model="m", system_prompt="sp")

    assert "--system-prompt" in argv
    assert "--append-system-prompt" not in argv


def test_a_json_schema_is_passed_to_the_cli_when_one_is_given():
    argv = cp.build_command(model="m", system_prompt="sp", json_schema=cj.VERDICT_SCHEMA)

    assert json.loads(argv[argv.index("--json-schema") + 1]) == cj.VERDICT_SCHEMA


def test_the_prompt_is_sent_on_stdin_not_in_argv():
    """A rendered eval prompt reaches ~22,000 tokens.

    In argv that is both an ARG_MAX hazard and a leak of the whole prompt into
    the process table.
    """
    provider, runner = make_provider([ok()])

    provider.complete("a very long prompt")

    assert runner.calls[0]["input"] == "a very long prompt"
    assert "a very long prompt" not in runner.calls[0]["argv"]


def test_completion_carries_the_answer_and_the_reported_usage():
    provider, _ = make_provider([ok("candidate said this")])

    completion = provider.complete("p")

    assert completion.text == "candidate said this"
    assert completion.usage[0].model == EXPECTED_CANDIDATE_MODEL
    assert completion.usage[0].input_tokens == 390
    assert completion.usage[0].output_tokens == 58
    assert completion.usage[0].cost_usd == pytest.approx(0.019062)


def test_usage_is_keyed_by_canonical_model_not_the_dated_id():
    """The CLI reports `claude-haiku-4-5-20251001`; `models.py` names
    `claude-haiku-4-5`. Without the canonical id the report would key cost
    under a name nothing else in the runner uses."""
    provider, _ = make_provider([ok()])

    completion = provider.complete("p")

    assert [entry.model for entry in completion.usage] == [EXPECTED_CANDIDATE_MODEL]


def test_a_transient_failure_is_retried_and_then_succeeds():
    provider, runner = make_provider(
        [FakeProcess("", "connection reset by peer", 1), ok("second attempt")]
    )
    slept: list[float] = []
    provider._sleep = slept.append

    completion = provider.complete("p")

    assert completion.text == "second attempt"
    assert len(runner.calls) == 2
    assert slept, "a retry must back off before the second attempt"


def test_a_usage_limit_failure_is_never_retried():
    """AC5. One call, then abort - not a second attempt, not a degraded result."""
    slept: list[float] = []
    provider, runner = make_provider(
        [FakeProcess("", "Claude usage limit reached", 1)], sleep=slept.append
    )

    with pytest.raises(ce.FatalRunError) as excinfo:
        provider.complete("p")

    assert len(runner.calls) == 1
    assert slept == []
    assert "usage limit reached" in str(excinfo.value)


def test_a_credit_exhaustion_envelope_is_never_retried():
    """AC4's failure, in the shape the CLI would actually report it."""
    body = json.dumps(
        envelope(
            is_error=True,
            subtype="error_during_execution",
            api_error_status=429,
            result="credit_balance_exhausted",
        )
    )
    provider, runner = make_provider([FakeProcess(body)])

    with pytest.raises(ce.FatalRunError):
        provider.complete("p")

    assert len(runner.calls) == 1


def test_a_timeout_is_retried_rather_than_aborting_the_run():
    """A hung request is the clearest case a retry exists for.

    It also produces no output to classify, so it is handled by exception
    type rather than by inspecting text.
    """
    timeout = subprocess.TimeoutExpired(cmd=["claude"], timeout=600)
    provider, runner = make_provider([timeout, ok("second attempt")])

    assert provider.complete("p").text == "second attempt"
    assert len(runner.calls) == 2


def test_a_process_that_never_finished_is_a_failure_not_a_success():
    """A `returncode` of None means "did not finish".

    Coercing it to 0 would read an unfinished call as a clean one and hand the
    judge whatever happened to be on stdout.
    """
    unfinished = FakeProcess(json.dumps(envelope()))
    unfinished.returncode = None
    provider, _ = make_provider([unfinished])

    with pytest.raises(ce.FatalRunError):
        provider.complete("p")


def test_stderr_alone_is_not_treated_as_a_failure():
    """Claude Code writes ordinary warnings to stderr.

    Treating any stderr output as a failed call would abort healthy runs.
    """
    noisy = FakeProcess(
        json.dumps(envelope(result="fine")), stderr="warning: something", returncode=0
    )
    provider, _ = make_provider([noisy])

    assert provider.complete("p").text == "fine"


def test_an_unrecognised_envelope_shape_aborts_instead_of_being_graded():
    """The #651 incident, rebuilt and caught. This is the regression.

    The CLI exits 0 and prints an envelope the runner has never seen:

        {"type": "error", "result": "Claude usage limit reached"}

    No `is_error` flag, no `api_error_status`, nothing that a "did anything
    look wrong?" check would notice. An earlier version of `_failure_text`
    called that a SUCCESS and handed the usage-limit message to the judge as
    the candidate's answer - a quota failure graded as a skill response, which
    is exactly how a run ends up writing a report in which nothing passed.

    Success is now established positively, so an unknown shape aborts.
    """
    envelope_shape = json.dumps({"type": "error", "result": "Claude usage limit reached"})
    provider, runner = make_provider([FakeProcess(envelope_shape, returncode=0)])

    with pytest.raises(ce.FatalRunError) as excinfo:
        provider.complete("p")

    assert len(runner.calls) == 1, "an unrecognised envelope must not be retried"
    assert "usage limit reached" in str(excinfo.value)


def test_a_success_envelope_missing_its_subtype_is_not_trusted():
    """Positive validation means BOTH fields, not just `type`."""
    provider, _ = make_provider([FakeProcess(json.dumps(envelope(subtype="error_max_turns")))])

    with pytest.raises(ce.FatalRunError):
        provider.complete("p")


def test_a_quota_phrase_beyond_the_message_excerpt_is_still_fatal():
    """The classifier must read the WHOLE failure text, not an excerpt.

    Truncating before classification would send a 5xx whose quota explanation
    sits past the boundary down the transient path, where it is retried and
    can be absorbed by a later attempt.
    """
    padding = "x" * 2000
    body = json.dumps(
        envelope(
            type="error",
            is_error=True,
            subtype="error_during_execution",
            api_error_status=500,
            result=f"{padding} credit balance is too low",
        )
    )
    provider, runner = make_provider([FakeProcess(body, returncode=1)])

    with pytest.raises(ce.FatalRunError):
        provider.complete("p")

    assert len(runner.calls) == 1, "a quota failure is never retried, wherever the phrase sits"


def test_exhausting_the_retry_budget_aborts_the_run_rather_than_escaping():
    """The budget running out ends the run, so it must be a FatalRunError.

    A bare RuntimeError would sail past the CLI's one handler and surface as a
    traceback, losing the documented exit code.
    """
    reset = FakeProcess("", "connection reset by peer", 1)
    provider, _ = make_provider([reset, reset, reset], max_attempts=3)

    with pytest.raises(ce.FatalRunError, match="failed 3 times"):
        provider.complete("p")


def test_transient_failures_stop_after_the_attempt_budget():
    reset = FakeProcess("", "connection reset by peer", 1)
    provider, runner = make_provider([reset, reset, reset], max_attempts=3)

    with pytest.raises(ce.FatalRunError, match="failed 3 times"):
        provider.complete("p")

    assert len(runner.calls) == 3


def test_unparseable_cli_output_aborts_rather_than_being_read_as_an_answer():
    """Stdout that is not the JSON envelope means the call did not work.

    Treating it as an empty answer would hand the judge a blank response and
    score the skill on something it never said.
    """
    provider, _ = make_provider([FakeProcess("Segmentation fault", "", 139)])

    with pytest.raises(ce.FatalRunError):
        provider.complete("p")


def test_a_refusal_stop_reason_is_not_read_as_an_answer():
    provider, _ = make_provider(
        [FakeProcess(json.dumps(envelope(stop_reason="refusal", result="")))]
    )

    with pytest.raises(cp.RefusedError):
        provider.complete("p")


def test_a_missing_cli_names_itself():
    provider, _ = make_provider([FileNotFoundError("claude")])

    with pytest.raises(cp.ClaudeCliMissingError):
        provider.complete("p")


# ==========================================================================
# Judge - AC2 (default prompt + override) and AC3 (loud failure)
# ==========================================================================


def test_default_rubric_prompt_reproduces_promptfoos_two_message_shape():
    """promptfoo's DEFAULT_GRADING_PROMPT is a JSON system+user message pair.

    Read from promptfoo 0.121.20 `src/prompts/grading.ts` - the version pinned
    in package.json - not from memory. The placeholders are what the renderer
    fills, so they must survive verbatim in the unrendered default.
    """
    messages = json.loads(cj.DEFAULT_RUBRIC_PROMPT)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "{reason: string, pass: boolean, score: number}" in messages[0]["content"]
    assert (
        messages[1]["content"]
        == "<Output>\n{{ output }}\n</Output>\n<Rubric>\n{{ rubric }}\n</Rubric>"
    )


def test_the_default_prompt_is_used_when_a_config_declares_no_override():
    rendered = cj.render_judge_prompt(
        None, rubric="Mentions a named risk", output="I named a risk.", variables={}
    )

    assert [m["role"] for m in rendered] == ["system", "user"]
    assert "<Output>\nI named a risk.\n</Output>" in rendered[-1]["content"]
    assert "<Rubric>\nMentions a named risk\n</Rubric>" in rendered[-1]["content"]


def test_a_config_rubric_prompt_override_is_rendered_with_output_rubric_and_vars():
    """The live matrix's shape: a plain string carrying {{rubric}}, {{output}}
    AND the case's own vars - several configs embed the loaded catalogues into
    the judge context that way. All three must resolve."""
    override = "RUBRIC:{{rubric}} OUT:{{output}} CAT:{{principles}}"

    rendered = cj.render_judge_prompt(
        override, rubric="be strict", output="the answer", variables={"principles": "P1"}
    )

    assert len(rendered) == 1
    assert rendered[0]["role"] == "user"
    assert rendered[0]["content"] == "RUBRIC:be strict OUT:the answer CAT:P1"


def test_an_override_cannot_be_shadowed_by_a_var_named_output():
    """`output` and `rubric` are judge-time values, not case vars.

    A config var called `output` must not replace the candidate's real answer
    in the judge context - that would grade the fixture, not the response.
    """
    rendered = cj.render_judge_prompt(
        "{{output}}", rubric="r", output="the real answer", variables={"output": "a decoy"}
    )

    assert rendered[0]["content"] == "the real answer"


def test_every_live_config_rubric_prompt_renders_without_leftover_placeholders():
    """Grounded on the real matrix, not a fixture.

    A judge prompt reaching the model with an unresolved `{{expected_shape}}`
    in it would grade against a literal placeholder and no assertion would
    notice. This walks every rubric in the live configs.
    """
    from claude import loader as cl

    leftover = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}")
    checked = 0
    for config in cl.load_all_configs():
        for case in cl.build_cases(config):
            for assertion in case.assertions:
                if not isinstance(assertion, RubricAssertion):
                    continue
                rendered = cj.render_judge_prompt(
                    assertion.rubric_prompt,
                    rubric=assertion.rubric,
                    output="a candidate answer",
                    variables=case.vars,
                )
                for message in rendered:
                    assert not leftover.search(message["content"]), (
                        f"{config.path.name} left a placeholder in the judge prompt"
                    )
                checked += 1
    assert checked > 0, "no rubric assertions were exercised"


JUDGE_REPLY_CLASSES = [
    pytest.param('{"pass": true, "score": 1.0, "reason": "good"}', True, 1.0, id="well-formed"),
    pytest.param(
        '```json\n{"pass": false, "score": 0.0, "reason": "bad"}\n```', False, 0.0, id="fenced"
    ),
    pytest.param(
        'Verdict below.\n{"pass": true, "score": 0.8, "reason": "ok"}\nDone.',
        True,
        0.8,
        id="prose-wrapped",
    ),
    pytest.param('{"pass": false, "reason": "nope"}', False, 0.0, id="score-absent-derived"),
    pytest.param('{"pass": "yes", "score": 1.0, "reason": "y"}', True, 1.0, id="stringly-true"),
    pytest.param('{"pass": "no", "score": 0.0, "reason": "n"}', False, 0.0, id="stringly-false"),
    pytest.param(
        '{"pass": true, "score": 1.0, "reason": "brace { inside the reason"}',
        True,
        1.0,
        id="brace-inside-a-string",
    ),
    # The four below are the DISCRIMINATING inputs for the extractor, which is
    # a stateful brace-and-quote scanner. Each one is chosen because a scanner
    # missing one specific piece of state gets it wrong, so a green result here
    # is evidence rather than a code read:
    #
    #   nested object          -> a depth-less scanner closes at the first `}`
    #                             inside `meta` and hands back a truncated
    #                             fragment that will not parse.
    #   close brace in a string-> a string-unaware scanner closes at the `}`
    #                             sitting in the reason text.
    #   escaped quote          -> an escape-unaware scanner thinks the string
    #                             ended at `\"` and mis-tracks everything after.
    #   invalid then valid     -> a scanner that stops at the first BALANCED
    #                             candidate gives up on `{bad: 1}` instead of
    #                             going on to the real verdict.
    pytest.param(
        '{"pass": true, "score": 1.0, "reason": "ok", "meta": {"axis": {"a": 1}}}',
        True,
        1.0,
        id="nested-object",
    ),
    pytest.param(
        '{"pass": true, "score": 1.0, "reason": "a } in the text"}',
        True,
        1.0,
        id="close-brace-inside-a-string",
    ),
    pytest.param(
        '{"pass": false, "score": 0.0, "reason": "judge said \\"no\\" here"}',
        False,
        0.0,
        id="escaped-quote-inside-a-string",
    ),
    pytest.param(
        '{bad: 1}\n{"pass": true, "score": 0.5, "reason": "second object"}',
        True,
        0.5,
        id="invalid-object-before-the-real-one",
    ),
]


@pytest.mark.parametrize("text,expected_pass,expected_score", JUDGE_REPLY_CLASSES)
def test_parseable_judge_replies_yield_the_stated_verdict(text, expected_pass, expected_score):
    verdict = cj.parse_judge_response(text)

    assert verdict.passed is expected_pass
    assert verdict.score == pytest.approx(expected_score)


UNGRADEABLE_REPLIES = [
    pytest.param("", id="empty"),
    pytest.param("I cannot grade this.", id="prose-only"),
    pytest.param('{"score": 1.0, "reason": "looks fine"}', id="pass-key-absent"),
    pytest.param('{"pass": ', id="truncated-json"),
    pytest.param("{'pass': True}", id="python-repr-not-json"),
]


@pytest.mark.parametrize("text", UNGRADEABLE_REPLIES)
def test_an_ungradeable_judge_reply_fails_loudly(text):
    """AC3, and a deliberate divergence from promptfoo.

    promptfoo 0.121.20 `runJsonGradingPrompt` does `pass = parsed.pass ?? true`
    - a reply with no `pass` key PASSES. That default is how a broken judge
    becomes a green gate, so this runner refuses instead. The raw reply has to
    reach the reason, or the failure is unactionable.
    """
    verdict = cj.parse_judge_response(text)

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert (text.strip()[:20] in verdict.reason) or ("<empty reply>" in verdict.reason)


def test_the_schema_validated_object_is_preferred_over_re_parsing_the_text():
    verdict = cj.parse_judge_response(
        "ignored prose", structured_output={"pass": True, "score": 0.9, "reason": "from schema"}
    )

    assert verdict.passed is True
    assert verdict.reason == "from schema"


def test_the_verdict_schema_forbids_extra_keys_and_bounds_the_score():
    """`--json-schema` is the first line of defence on the reply shape.

    An open schema would let the judge return a differently-shaped object that
    still validated, which is most of the value gone.
    """
    assert cj.VERDICT_SCHEMA["additionalProperties"] is False
    assert set(cj.VERDICT_SCHEMA["required"]) == {"pass", "score", "reason"}
    assert cj.VERDICT_SCHEMA["properties"]["score"]["minimum"] == 0.0
    assert cj.VERDICT_SCHEMA["properties"]["score"]["maximum"] == 1.0


NON_FINITE_SCORES = [
    pytest.param('{"pass": true, "score": NaN, "reason": "x"}', id="nan"),
    pytest.param('{"pass": true, "score": Infinity, "reason": "x"}', id="infinity"),
    pytest.param('{"pass": true, "score": -Infinity, "reason": "x"}', id="negative-infinity"),
]


@pytest.mark.parametrize("text", NON_FINITE_SCORES)
def test_a_non_finite_score_cannot_clear_a_threshold(text):
    """`json.loads` accepts `NaN` and the infinities; JSON does not.

    They are not a formatting nicety here. `NaN < threshold` is False, so a
    NaN score sails through the threshold check and the verdict PASSES - the
    same default-to-pass behaviour this runner refuses everywhere else - and
    `Infinity` clears any threshold at all. A bare `NaN` in the reply also
    reaches the JSON report, where no other reader can parse it.
    """
    verdict = cj.parse_judge_response(text, threshold=0.9)

    assert verdict.passed is False
    assert verdict.score == 0.0


NON_FINITE_STRUCTURED = [
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
]


@pytest.mark.parametrize("score", NON_FINITE_STRUCTURED)
def test_a_non_finite_score_is_refused_through_the_schema_door_too(score):
    """The same malformed value must not fail one way and pass the other.

    Two doors reach the verdict. The TEXT path is blocked by `parse_constant`,
    which refuses `NaN` and the infinities outright. `structured_output` comes
    from the CLI's own envelope, parsed by an ordinary `json.loads` that
    accepts all three - so it bypasses that guard entirely.

    The first attempt at this fix fell back to the boolean for a non-finite
    score, which turned `pass: true` into score 1.0 and cleared a 0.9
    threshold: the reply the runner exists to refuse, passing. An ABSENT score
    still falls back; a PRESENT but unusable one is refused.
    """
    verdict = cj.parse_judge_response(
        "ignored prose",
        threshold=0.9,
        structured_output={"pass": True, "score": score, "reason": "r"},
    )

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert "not a finite number" in verdict.reason


def test_an_absent_score_still_falls_back_to_the_boolean_verdict():
    """The carve-out the rule above must not swallow.

    promptfoo derives a missing `score` from `pass`, and so does this runner.
    Only a score that is present and unusable is refused.
    """
    verdict = cj.parse_judge_response('{"pass": true, "reason": "no score given"}')

    assert verdict.passed is True
    assert verdict.score == 1.0


def test_a_report_carrying_a_non_finite_number_refuses_to_be_written(tmp_path: Path):
    """The second gate on the same class, at the file boundary.

    Python would happily write the bare token `NaN`, producing a report that
    nothing else can read. Failing loudly while writing beats shipping one.
    """
    report = _report_with_one_case()
    report.config_for("skill-example.yaml").by_model["m"] = crep.ModelCost(usd=float("nan"))

    with pytest.raises(ValueError):
        crep.write_report(tmp_path / "report.json", report)

    assert list(tmp_path.iterdir()) == [], "a refused write leaves no partial file"


def test_a_truncated_reply_is_not_rescued_by_its_own_nested_object():
    """A cut-off reply must not be graded from a fragment inside it.

    `{"wrapper": {"pass": true, "score": 1.0, "reason": "ok"}` never closes -
    the judge's answer was cut off mid-flight. The inner object nonetheless
    looks like a complete verdict, so a scan that decodes from every `{`
    finds it and returns a PASS from a reply that never finished.

    A `{` is a candidate only when nothing is open around it, and its span is
    decoded only once the brackets close. A reply that ends mid-structure
    never gets there, whether it was cut off inside an object or inside an
    array.
    """
    for truncated in (
        # cut off inside an object...
        '{"wrapper": {"pass": true, "score": 1.0, "reason": "ok"}',
        # ...and inside an array, which the first attempt at this missed
        '[{"pass": true, "score": 1.0, "reason": "ok"}',
    ):
        assert cj.extract_first_json_object(truncated) is None, truncated
        assert cj.parse_judge_response(truncated).passed is False, truncated


def test_a_nested_object_inside_a_COMPLETE_reply_is_still_read():
    """The carve-out above must not cost the ordinary nested case.

    When the outer object does close, it parses as a whole and its nested
    values come with it.
    """
    verdict = cj.parse_judge_response(
        '{"pass": true, "score": 1.0, "reason": "ok", "meta": {"axis": {"a": 1}}}'
    )

    assert verdict.passed is True


def test_a_brace_heavy_reply_cannot_stall_the_run():
    """The scan is one linear pass, whatever the reply looks like.

    The CLI puts no ceiling on a reply's length. An earlier version decoded
    from every `{` in turn, which is quadratic: 40,000 braces cost about two
    and a half seconds, per case, across the whole matrix.
    """
    started = time.perf_counter()

    assert cj.extract_first_json_object("{" * 40_000) is None

    assert time.perf_counter() - started < 1.0


REALISTIC_JUDGE_REPLIES = [
    pytest.param('{"pass": true, "score": 1.0, "reason": "ok"}', id="bare"),
    pytest.param(
        'Here is my verdict: {"pass": true, "score": 1.0, "reason": "ok"}', id="after-a-colon"
    ),
    pytest.param('Grading, {"pass": true, "score": 1.0, "reason": "ok"}', id="after-a-comma"),
    pytest.param('My verdict. {"pass": true, "score": 1.0, "reason": "ok"}', id="after-prose"),
    pytest.param(
        'Verdict:\n```json\n{"pass": true, "score": 1.0, "reason": "ok"}\n```',
        id="labelled-fence",
    ),
]


@pytest.mark.parametrize("text", REALISTIC_JUDGE_REPLIES)
def test_the_shapes_a_judge_actually_replies_in_are_all_read(text):
    """The anti-over-fire side of the truncation guard.

    Refusing fragments must not cost ordinary replies. An earlier attempt
    skipped any `{` preceded by a `:` or a `,`, which refused
    `Here is my verdict: {...}` - among the most natural things a judge can
    write, and a wrong FAIL on a skill that had actually passed.
    """
    verdict = cj.parse_judge_response(text)

    assert verdict.passed is True
    assert verdict.reason == "ok"


def test_an_unmatched_brace_in_prose_fails_closed_and_that_is_the_trade():
    """The one case this deliberately gives up, and why.

    A stray `{` in the judge's prose leaves the bracket stack non-empty, so
    the genuine verdict after it is never seen as top-level and the reply is
    refused. The judge did answer, so this is a recoverable reply being
    failed.

    It is kept that way on purpose. Two attempts to rescue it each admitted
    something worse: decoding from every brace graded fragments of truncated
    replies, and skipping braces after `:`/`,` refused the common
    `Here is my verdict: {...}`. Both swapped a safe, visible failure for a
    silent wrong PASS. A refusal carries the raw reply into its reason and a
    human resolves it in seconds; a fragment graded as a pass is the failure
    nobody sees.
    """
    verdict = cj.parse_judge_response(
        'I thought { about it carefully. {"pass": true, "score": 1.0, "reason": "ok"}'
    )

    assert verdict.passed is False
    assert "I thought {" in verdict.reason


def test_a_threshold_below_the_score_fails_a_would_be_pass():
    verdict = cj.parse_judge_response(
        '{"pass": true, "score": 0.4, "reason": "meh"}', threshold=0.7
    )

    assert verdict.passed is False


def test_a_threshold_at_or_below_the_score_leaves_a_pass_alone():
    verdict = cj.parse_judge_response('{"pass": true, "score": 0.7, "reason": "ok"}', threshold=0.7)

    assert verdict.passed is True


# ==========================================================================
# Report - AC7/AC8
# ==========================================================================


def _report_with_one_case() -> crep.RunReport:
    report = crep.RunReport(generated_at="2026-09-10T00:00:00+00:00")
    record = report.config_for("skill-example.yaml")
    record.cases.append(
        crep.CaseRecord(
            prompt_label="A0 - control",
            description="a seed",
            repeat=1,
            passed=True,
            assertions=[
                crep.AssertionRecord(kind="llm-rubric", passed=True, score=1.0, reason="good")
            ],
        )
    )
    return report


def test_the_written_report_carries_the_documented_shape():
    report = _report_with_one_case()
    report.record_usage(
        "skill-example.yaml",
        model=EXPECTED_CANDIDATE_MODEL,
        input_tokens=1000,
        output_tokens=100,
        usd=0.006,
    )

    payload = report.to_dict()

    assert payload["schema_version"] == crep.REPORT_SCHEMA_VERSION
    assert payload["candidate_model"] == EXPECTED_CANDIDATE_MODEL
    assert payload["judge_model"] == EXPECTED_JUDGE_MODEL
    config = payload["configs"][0]
    assert config["config"] == "skill-example.yaml"
    assert config["passed"] is True
    assert config["cases"][0]["assertions"][0]["kind"] == "llm-rubric"
    assert config["cost"]["input_tokens"] == 1000
    assert config["cost"]["output_tokens"] == 100
    assert config["cost"]["by_model"][EXPECTED_CANDIDATE_MODEL]["usd"] == pytest.approx(0.006)
    assert payload["totals"]["cases"] == 1
    assert payload["totals"]["passed"] == 1


def test_the_cost_basis_is_labelled_list_price_not_an_invoice():
    """The run is covered by the subscription, so the dollars are notional.

    Reporting them unlabelled would invite reading a subscription run as a
    bill, which is the wrong conclusion in both directions.
    """
    assert _report_with_one_case().to_dict()["cost_basis"] == "list"


def test_run_cost_sums_real_usage_across_candidate_and_judge():
    """AC8 - the summary is measured, not estimated.

    Both figures come from the CLI's own per-model `costUSD`, which it derives
    from that call's real usage.
    """
    report = _report_with_one_case()
    report.record_usage(
        "skill-example.yaml",
        model=EXPECTED_CANDIDATE_MODEL,
        input_tokens=1000,
        output_tokens=100,
        usd=1.00,
    )
    report.record_usage(
        "skill-example.yaml",
        model=EXPECTED_JUDGE_MODEL,
        input_tokens=2000,
        output_tokens=200,
        usd=10.00,
    )

    payload = report.to_dict()

    assert payload["totals"]["usd"] == pytest.approx(11.00)
    assert payload["totals"]["input_tokens"] == 3000
    assert set(payload["configs"][0]["cost"]["by_model"]) == {
        EXPECTED_CANDIDATE_MODEL,
        EXPECTED_JUDGE_MODEL,
    }


def test_a_failed_case_fails_its_config_and_the_run():
    report = _report_with_one_case()
    report.config_for("skill-example.yaml").cases.append(
        crep.CaseRecord(prompt_label="A1", description="", repeat=1, passed=False)
    )

    assert report.passed is False
    assert report.to_dict()["totals"]["failed"] == 1


def test_writing_the_report_produces_readable_json(tmp_path: Path):
    path = tmp_path / "report.json"

    written = crep.write_report(path, _report_with_one_case())

    assert json.loads(path.read_text(encoding="utf-8")) == written


def test_writing_leaves_no_temporary_file_behind(tmp_path: Path):
    """The write is atomic via a temp file plus os.replace."""
    path = tmp_path / "report.json"

    crep.write_report(path, _report_with_one_case())

    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]


def test_the_report_never_carries_the_api_key(tmp_path: Path, monkeypatch):
    """The report is a shareable artifact; a leaked credential would travel."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    path = tmp_path / "report.json"

    crep.write_report(path, _report_with_one_case())

    assert "sk-ant-secret-value" not in path.read_text(encoding="utf-8")


# ==========================================================================
# Runner - repeats, grading, and the aborted-run state transition
# ==========================================================================

MINIMAL_CONFIG = """
description: a tiny config for the runner tests
providers:
  - id: candidate
prompts:
  - label: A0 - control
    raw: |
      Say something about {{topic}}.
defaultTest:
  options:
    disableVarExpansion: true
    rubricPrompt: 'RUBRIC {{rubric}} OUTPUT {{output}}'
  assert:
    - type: llm-rubric
      value: the answer mentions {{topic}}
tests:
  - description: seed one
    vars:
      topic: risk
"""


# Three seeds, so an abort can be made to land mid-matrix with completed
# cases behind it - which is the only shape that proves the report is withheld
# rather than merely never produced.
THREE_CASE_CONFIG = (
    MINIMAL_CONFIG
    + """  - description: seed two
    vars:
      topic: risk
  - description: seed three
    vars:
      topic: risk
"""
)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "configs"
    directory.mkdir()
    (directory / "skill-tiny.yaml").write_text(MINIMAL_CONFIG, encoding="utf-8")
    return directory


@pytest.fixture
def three_case_config_dir(tmp_path: Path) -> Path:
    """A separate fixture, because the abort test needs cases BEHIND the abort."""
    directory = tmp_path / "configs"
    directory.mkdir()
    (directory / "skill-tiny.yaml").write_text(THREE_CASE_CONFIG, encoding="utf-8")
    return directory


def _runner(candidate_outcomes, judge_outcomes):
    candidate, candidate_runner = make_provider(candidate_outcomes)
    judge, judge_runner = make_provider(judge_outcomes)
    return crun.Runner(candidate, judge), candidate_runner, judge_runner


PASS_VERDICT = '{"pass": true, "score": 1.0, "reason": "mentions risk"}'
FAIL_VERDICT = '{"pass": false, "score": 0.0, "reason": "no mention"}'


def test_a_case_passes_when_the_judge_passes_it(config_dir: Path):
    runner, _, _ = _runner([ok("risk is the thing")], [ok(PASS_VERDICT)])

    report = runner.run([config_dir / "skill-tiny.yaml"])

    assert report.passed is True
    case = report.configs[0].cases[0]
    assert case.prompt_label == "A0 - control"
    assert case.assertions[0].reason == "mentions risk"


def test_a_case_fails_when_the_judge_fails_it(config_dir: Path):
    runner, _, _ = _runner([ok("waffle")], [ok(FAIL_VERDICT)])

    report = runner.run([config_dir / "skill-tiny.yaml"])

    assert report.passed is False


def test_repeat_runs_each_case_n_times_and_records_each(config_dir: Path):
    """AC9, and what slice 3's `--repeat 3` A/B proof needs.

    A single sample cannot distinguish a real A0-fails / A1-passes control
    from a lucky one, so each pass is recorded separately with its index.
    """
    runner, candidate_calls, judge_calls = _runner(
        [ok("a"), ok("b"), ok("c")], [ok(PASS_VERDICT), ok(FAIL_VERDICT), ok(PASS_VERDICT)]
    )

    report = runner.run([config_dir / "skill-tiny.yaml"], repeat=3)

    cases = report.configs[0].cases
    assert [case.repeat for case in cases] == [1, 2, 3]
    assert [case.passed for case in cases] == [True, False, True]
    assert len(candidate_calls.calls) == 3
    assert len(judge_calls.calls) == 3
    assert report.to_dict()["repeat"] == 3


def test_repeat_below_one_is_refused(config_dir: Path):
    runner, _, _ = _runner([], [])

    with pytest.raises(ValueError, match="at least 1"):
        runner.run([config_dir / "skill-tiny.yaml"], repeat=0)


def test_the_judge_receives_the_configs_own_rubric_prompt(config_dir: Path):
    """A config's `options.rubricPrompt` must reach the judge, rendered.

    All 61 live configs declare one; sending the built-in default instead
    would silently discard every rubric's actual grading contract.
    """
    runner, _, judge_calls = _runner([ok("risk!")], [ok(PASS_VERDICT)])

    runner.run([config_dir / "skill-tiny.yaml"])

    sent = judge_calls.calls[0]["input"]
    assert sent.startswith("RUBRIC ")
    assert "OUTPUT risk!" in sent
    assert "the answer mentions risk" in sent


def test_usage_from_both_tiers_lands_on_the_configs_cost(config_dir: Path):
    runner, _, _ = _runner([ok("risk")], [ok(PASS_VERDICT)])

    report = runner.run([config_dir / "skill-tiny.yaml"])
    cost = report.to_dict()["configs"][0]["cost"]

    # Two calls (candidate + judge) at 390 in / 58 out each, from the captured
    # envelope both fakes replay.
    assert cost["input_tokens"] == 780
    assert cost["output_tokens"] == 116
    assert cost["usd"] == pytest.approx(0.019062 * 2)


def test_a_fatal_error_mid_run_propagates_rather_than_degrading(config_dir: Path):
    """The #651 shape at the runner level: no partial result is returned."""
    runner, _, _ = _runner([FakeProcess("", "Claude usage limit reached", 1)], [])

    with pytest.raises(ce.FatalRunError):
        runner.run([config_dir / "skill-tiny.yaml"])


UNPORTED_CONFIG = """
description: a config carrying a javascript assert the runner cannot port
providers:
  - id: candidate
prompts:
  - label: A0 - control
    raw: 'say something'
defaultTest:
  options:
    disableVarExpansion: true
  assert:
    - type: javascript
      value: 'someUnportedHelper(output) && output.length > 3'
tests:
  - description: seed one
    vars:
      topic: risk
"""


def test_an_unported_javascript_assert_is_tagged_as_a_harness_gap(tmp_path: Path):
    """A gap in the RUNNER must not look like a regression in a SKILL.

    Slice 1 refuses to approximate a javascript assert it has no Python port
    for. Recording that refusal as an ordinary failed `javascript` assertion
    would put a tooling failure in the report wearing the costume of a skill
    failure - which is the #651 confusion that this whole epic exists to
    undo. It gets its own kind so the diagnoser can tell them apart.
    """
    directory = tmp_path / "configs"
    directory.mkdir()
    (directory / "skill-unported.yaml").write_text(UNPORTED_CONFIG, encoding="utf-8")
    runner, _, _ = _runner([ok("an answer")], [])

    report = runner.run([directory / "skill-unported.yaml"])

    assertion = report.configs[0].cases[0].assertions[0]
    assert assertion.kind == crun.UNPORTED_ASSERTION_KIND
    assert assertion.kind != "javascript"
    assert assertion.passed is False
    assert "no Python port" in assertion.reason


def test_a_judge_refusal_fails_one_case_rather_than_escaping(config_dir: Path):
    """A refusal from the JUDGE, not the candidate.

    An earlier version wrapped only the candidate call, so a judge that
    declined to grade raised straight out of the run - past the report, past
    the CLI's single handler - and the process died with a traceback instead
    of the documented exit code. It is the same fact about one prompt either
    way: the case fails, the matrix continues.
    """
    refusal = FakeProcess(json.dumps(envelope(stop_reason="refusal", result="")))
    runner, _, _ = _runner([ok("an answer")], [refusal])

    report = runner.run([config_dir / "skill-tiny.yaml"])

    case = report.configs[0].cases[0]
    assert case.passed is False
    assert "declined" in case.error


def test_a_refusal_fails_one_case_without_abandoning_the_matrix(config_dir: Path):
    refusal = FakeProcess(json.dumps(envelope(stop_reason="refusal", result="")))
    runner, _, _ = _runner([refusal], [])

    report = runner.run([config_dir / "skill-tiny.yaml"])

    case = report.configs[0].cases[0]
    assert case.passed is False
    assert "declined" in case.error


# ==========================================================================
# CLI - AC4's artifact guarantee, scoping, exit codes
# ==========================================================================


def test_an_aborted_run_writes_no_report(
    tmp_path: Path, three_case_config_dir: Path, monkeypatch, capsys
):
    """AC4, and the state transition that must not exist.

    A usage-limit failure MID-run must exit non-zero and leave NO report and
    NO baseline on disk. The old `run_baseline.py` wrote a zero-passed
    snapshot in exactly this situation, which read as a catastrophic skill
    regression and became the next run's comparison point.

    The abort deliberately lands on the THIRD case, not the first, and the two
    before it succeed. Failing on the first call would prove only that a run
    which produced nothing writes nothing - a bar an implementation that wrote
    the report incrementally after each completed case would also clear. What
    has to be true is stronger: a matrix that got PART of the way through
    still leaves an empty disk.
    """
    report_path = tmp_path / "report.json"
    candidate, candidate_calls = make_provider(
        [ok("first"), ok("second"), FakeProcess("", "Claude usage limit reached", 1)]
    )
    judge, _ = make_provider([ok(PASS_VERDICT), ok(PASS_VERDICT)])
    monkeypatch.setattr(ccli, "build_providers", lambda args: (candidate, judge))

    code = ccli.main(
        [
            "--live",
            "--config-dir",
            str(three_case_config_dir),
            "--config",
            "skill-tiny.yaml",
            "--report",
            str(report_path),
        ]
    )

    assert code == ccli.EXIT_ABORTED
    assert len(candidate_calls.calls) == 3, "the abort must land after two cases completed"
    assert not report_path.exists()
    assert list(tmp_path.iterdir()) == [three_case_config_dir]
    assert "RUN ABORTED" in capsys.readouterr().err


def test_a_completed_run_writes_the_report_and_exits_zero(
    tmp_path: Path, config_dir: Path, monkeypatch
):
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        ccli,
        "build_providers",
        lambda args: (make_provider([ok("risk")])[0], make_provider([ok(PASS_VERDICT)])[0]),
    )

    code = ccli.main(
        [
            "--live",
            "--config-dir",
            str(config_dir),
            "--config",
            "skill-tiny.yaml",
            "--report",
            str(report_path),
        ]
    )

    assert code == ccli.EXIT_OK
    assert json.loads(report_path.read_text("utf-8"))["totals"]["passed"] == 1


def test_a_completed_run_with_failures_still_writes_the_report(
    tmp_path: Path, config_dir: Path, monkeypatch
):
    """Exit 1 is not exit 3. A finished run that found real failures is
    exactly what the report exists to record; only an ABORT withholds it."""
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        ccli,
        "build_providers",
        lambda args: (make_provider([ok("waffle")])[0], make_provider([ok(FAIL_VERDICT)])[0]),
    )

    code = ccli.main(
        [
            "--live",
            "--config-dir",
            str(config_dir),
            "--config",
            "skill-tiny.yaml",
            "--report",
            str(report_path),
        ]
    )

    assert code == ccli.EXIT_FAILED
    assert json.loads(report_path.read_text("utf-8"))["totals"]["failed"] == 1


def test_config_scoping_selects_only_the_named_configs():
    """AC10, against the REAL config directory rather than a fixture."""
    parser = ccli.build_parser()
    args = parser.parse_args(["--config", "skill-using-sumo-qa.yaml"])

    selected = ccli._select(args)

    assert [path.name for path in selected] == ["skill-using-sumo-qa.yaml"]


def test_skill_scoping_selects_every_variant_for_that_skill():
    parser = ccli.build_parser()
    args = parser.parse_args(["--skill", "reviewing-before-merge"])

    names = [path.name for path in ccli._select(args)]

    assert len(names) > 1
    assert all(name.startswith("skill-reviewing-before-merge") for name in names)


def test_an_unknown_skill_selects_nothing_and_exits_usage(capsys):
    code = ccli.main(["--skill", "no-such-skill-anywhere"])

    assert code == ccli.EXIT_USAGE
    assert "no configs matched" in capsys.readouterr().err


def test_repeat_below_one_is_refused_at_the_cli(config_dir: Path, capsys):
    code = ccli.main(["--config-dir", str(config_dir), "--repeat", "0"])

    assert code == ccli.EXIT_USAGE
    assert "--repeat must be at least 1" in capsys.readouterr().err


def test_the_dry_run_still_works_and_names_no_model(config_dir: Path, capsys):
    """Slice 1's contract survives slice 2: --dry-run makes no call."""
    code = ccli.main(["--config-dir", str(config_dir), "--dry-run"])

    assert code == ccli.EXIT_OK
    assert "no model calls, no network" in capsys.readouterr().out


# ==========================================================================
# Offline guard
# ==========================================================================


def test_the_subprocess_guard_covers_every_test_in_this_module(config_dir: Path):
    """The autouse fixture above is the real guard; this documents it.

    An earlier version patched `subprocess.run` inside ONE test, which its
    name claimed guarded the suite. It did not: any other test could have
    shelled out to the real CLI and spent real subscription allowance without
    failing anything. The fixture is autouse, so the patch is in force for
    every test in this file - including this one, which drives a full run
    through injected fakes and would trip the guard if any of them reached
    `subprocess.run`.
    """
    assert subprocess.run is _forbidden_subprocess_run
    runner, _, _ = _runner([ok("risk")], [ok(PASS_VERDICT)])

    assert runner.run([config_dir / "skill-tiny.yaml"]).passed is True
