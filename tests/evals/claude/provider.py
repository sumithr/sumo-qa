# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The single call path to a Claude model, for both the candidate and the judge.

The runner reaches the model through the local Claude Code CLI in headless
mode (`claude -p --output-format json`), NOT through the Anthropic SDK with an
API key. That is a deliberate reversal of what issue #662 originally specified,
made on 2026-09-10: the whole point of epic #660 is that the eval gate stopped
being runnable when metered credit ran out, and paying per token for the
replacement reintroduces the same failure mode. The CLI runs on the account's
existing Claude subscription, so a full matrix consumes subscription allowance
rather than billed credit.

## The flags, and why each one is there

Every call is made with the same five flags. Together they take the scaffolding
Claude Code normally wraps around a prompt from about 19,500 tokens down to
about 390 - measured on this machine, both figures, before and after:

* `--system-prompt` REPLACES Claude Code's default system prompt (as opposed
  to `--append-system-prompt`, which keeps it). The eval's own prompt is the
  whole instruction; anything else is contamination.
* `--tools ""` disables every built-in tool. This is the big one: the tool
  definitions alone accounted for ~16,800 of the ~19,500 tokens. An eval
  candidate answering a QA question has no business holding a file-edit tool
  either, so this is correctness as much as economy.
* `--setting-sources ""` ignores user, project and local settings, which
  otherwise pull in CLAUDE.md files, output styles and permissions - ~1,500
  tokens, and a per-developer variable the matrix must not be sensitive to.
* `--strict-mcp-config` with no `--mcp-config` means no MCP server is loaded.
  Without it the developer's own sumo-qa MCP server would be attached to the
  candidate, which would be grading the skills against themselves.
* `--disable-slash-commands` keeps the host's skills out of the session, for
  the same reason.

`--max-turns 1` pins the call to a single model response: with no tools there
is nothing to iterate on, and a multi-turn drift would break the one-prompt
one-answer contract the rubrics assume.

## Usage and cost come from the CLI, not from a rate card

The JSON envelope carries a `usage` block with real token counts and a
`modelUsage` map with a `costUSD` per model at published list rates. Those are
the numbers the report uses. See `claude/models.py` for why no local pricing
table exists, and note that under a subscription the dollar figure is notional.

`modelUsage` can name MORE than the requested model - Claude Code uses a small
model for its own background work - so usage is recorded per model id rather
than attributed wholesale to the tier that was asked for.

## Prompts go in on stdin

A rendered eval prompt reaches ~22,000 tokens, which is far past a safe argv
length. `claude -p` with no prompt argument reads the prompt from stdin, which
has no such limit and keeps the prompt out of the process table.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from claude.errors import FATAL, FatalRunError, classify_failure

__all__ = [
    "BASE_FLAGS",
    "CLI_NAME",
    "ClaudeCliMissingError",
    "Completion",
    "ModelUsage",
    "Provider",
    "RefusedError",
    "build_command",
]

CLI_NAME = "claude"

# Flags applied to every call. `--model`, `--system-prompt` and any JSON schema
# are appended per call by `build_command`.
BASE_FLAGS = (
    "-p",
    "--output-format",
    "json",
    "--max-turns",
    "1",
    "--tools",
    "",
    "--strict-mcp-config",
    "--setting-sources",
    "",
    "--disable-slash-commands",
)

# The only envelope shape the CLI emits for a completed, successful call.
# Anything else is a failure - see `_failure_text`.
_SUCCESS_TYPE = "result"
_SUCCESS_SUBTYPE = "success"

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_TIMEOUT_SECONDS = 600
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0
# How much of a failure string reaches the human-readable abort message.
_MESSAGE_EXCERPT = 600


class ClaudeCliMissingError(RuntimeError):
    """The `claude` executable is not on PATH, so no call can be made."""


class RefusedError(RuntimeError):
    """The model declined the request; there is no answer to grade."""


@dataclass(frozen=True)
class ModelUsage:
    """What one model actually consumed on one call."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class Completion:
    """One answer, plus the usage the CLI reported for producing it."""

    text: str
    usage: tuple[ModelUsage, ...] = ()
    structured_output: Any = None
    session_id: str = ""

    @property
    def total_cost_usd(self) -> float:
        return sum(entry.cost_usd for entry in self.usage)

    @property
    def input_tokens(self) -> int:
        """Every input token billed, cache included.

        Cache tokens are counted in rather than reported separately because
        the CLI's `costUSD` already prices them at their own rates; splitting
        them out here would invite double-counting in the report.
        """
        return sum(
            entry.input_tokens + entry.cache_read_input_tokens + entry.cache_creation_input_tokens
            for entry in self.usage
        )

    @property
    def output_tokens(self) -> int:
        return sum(entry.output_tokens for entry in self.usage)


def build_command(
    *,
    model: str,
    system_prompt: str,
    json_schema: Mapping[str, Any] | None = None,
    executable: str = CLI_NAME,
) -> list[str]:
    """The exact argv for one call. Split out so the tests can assert on it."""
    argv = [executable, *BASE_FLAGS, "--model", model, "--system-prompt", system_prompt]
    if json_schema is not None:
        argv += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    return argv


def _usage_from_envelope(envelope: Mapping[str, Any]) -> tuple[ModelUsage, ...]:
    """Read `modelUsage` into one record per model that actually ran."""
    model_usage = envelope.get("modelUsage") or {}
    entries = []
    for reported_id, stats in model_usage.items():
        stats = stats or {}
        entries.append(
            ModelUsage(
                # `canonicalModel` drops the date suffix the CLI reports
                # (`<id>-<YYYYMMDD>` -> `<id>`), which is the form
                # `claude/models.py` names, so keying on the raw id would put
                # the cost under a name nothing else in the runner uses. Fall
                # back to that raw key only when the field is absent, rather
                # than losing the row entirely.
                model=str(stats.get("canonicalModel") or reported_id),
                input_tokens=int(stats.get("inputTokens") or 0),
                output_tokens=int(stats.get("outputTokens") or 0),
                cache_read_input_tokens=int(stats.get("cacheReadInputTokens") or 0),
                cache_creation_input_tokens=int(stats.get("cacheCreationInputTokens") or 0),
                cost_usd=float(stats.get("costUSD") or 0.0),
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.model))


@dataclass
class _Attempt:
    """What one subprocess run produced, before it is judged good or bad."""

    returncode: int
    stdout: str
    stderr: str
    envelope: dict[str, Any] = field(default_factory=dict)


class Provider:
    """One model, one system prompt, one retry policy."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str,
        json_schema: Mapping[str, Any] | None = None,
        executable: str = CLI_NAME,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] | None = None,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.json_schema = dict(json_schema) if json_schema is not None else None
        self.executable = executable
        self.max_attempts = max(1, max_attempts)
        self.timeout = timeout
        self._sleep = sleep
        # Injected so every test drives the real parsing and classification
        # code against a fake process result, with no subprocess and no
        # network. Nothing in the suite passes a real runner.
        self._runner = runner or subprocess.run

    def command_for(self, system_prompt: str | None = None) -> list[str]:
        """The argv for one call, optionally with a per-call system prompt.

        The override exists for promptfoo's DEFAULT rubric prompt, which is a
        system+user pair: its system half has to reach the model AS a system
        prompt, not be flattened into the user turn or silently dropped.
        """
        return build_command(
            model=self.model,
            system_prompt=self.system_prompt if system_prompt is None else system_prompt,
            json_schema=self.json_schema,
            executable=self.executable,
        )

    @property
    def command(self) -> list[str]:
        return self.command_for()

    def ensure_available(self) -> None:
        """Fail early and by name when the CLI is not installed.

        Called once before a live run rather than per case, so a missing CLI
        costs one clear message instead of N confusing ones.
        """
        if shutil.which(self.executable) is None:
            raise ClaudeCliMissingError(
                f"{self.executable!r} is not on PATH. The Claude eval runner drives the "
                "Claude Code CLI on your existing subscription; install it, or use "
                "--dry-run, which makes no model call."
            )

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter, capped."""
        delay = min(_BASE_BACKOFF_SECONDS * (2**attempt), _MAX_BACKOFF_SECONDS)
        return delay + random.uniform(0, min(1.0, delay))

    def _wait(self, seconds: float) -> None:
        if self._sleep is not None:
            self._sleep(seconds)
            return
        import time

        time.sleep(seconds)

    def _run_once(self, prompt: str, system_prompt: str | None = None) -> _Attempt:
        completed = self._runner(
            self.command_for(system_prompt),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        # An absent or None returncode means "did not finish", which is a
        # failure, not a success. `or 0` would have turned it into one.
        returncode = getattr(completed, "returncode", None)
        attempt = _Attempt(
            returncode=int(returncode) if returncode is not None else 1,
            stdout=getattr(completed, "stdout", "") or "",
            stderr=getattr(completed, "stderr", "") or "",
        )
        try:
            parsed = json.loads(attempt.stdout)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            attempt.envelope = parsed
        return attempt

    def complete(self, prompt: str, *, system_prompt: str | None = None) -> Completion:
        """Send one prompt and return its answer plus its reported usage.

        Raises `FatalRunError` for anything not demonstrably transient -
        immediately, without a retry - and re-raises the last failure once the
        transient budget is spent. See `claude/errors.py` for why the default
        is to stop.
        """
        last: BaseException | str | None = None
        for attempt_index in range(self.max_attempts):
            try:
                attempt = self._run_once(prompt, system_prompt)
            except subprocess.TimeoutExpired as exc:
                # A timeout is the one failure whose class is known without
                # inspecting it: the call produced no output to classify, and
                # a hung request is exactly what a retry is for.
                last = exc
                self._maybe_wait(attempt_index)
                continue
            except FileNotFoundError as exc:
                raise ClaudeCliMissingError(
                    f"{self.executable!r} is not on PATH; cannot run the eval."
                ) from exc

            failure = self._failure_text(attempt)
            if failure is None:
                return self._completion(attempt)

            status = attempt.envelope.get("api_error_status")
            verdict = classify_failure(
                failure, api_error_status=status if isinstance(status, int) else None
            )
            if verdict == FATAL:
                raise self._fatal(failure)
            last = failure
            self._maybe_wait(attempt_index)

        # A FatalRunError, not a bare RuntimeError: the run IS over, and
        # `claude/cli.py` catches exactly this to exit 3 with nothing written.
        # A different exception type would escape as a traceback and lose the
        # documented abort contract.
        raise FatalRunError(
            f"aborting the run: {self.model} failed {self.max_attempts} times with a "
            f"retryable error and the attempt budget is spent. Last failure: {last}. "
            "No report or baseline is written."
        )

    def _maybe_wait(self, attempt_index: int) -> None:
        if attempt_index + 1 < self.max_attempts:
            self._wait(self._backoff(attempt_index))

    def _fatal(self, detail: str) -> FatalRunError:
        # Shortened HERE, at display time, and nowhere earlier: the classifier
        # must read the whole failure text or a quota phrase past the boundary
        # would be missed (and a 5xx carrying one would then be retried).
        shown = detail if len(detail) <= _MESSAGE_EXCERPT else detail[:_MESSAGE_EXCERPT] + "..."
        return FatalRunError(
            f"aborting the run: {self.model} call failed with {shown!r}. This failure "
            "class is never retried, and no report or baseline is written - a "
            "partially-graded matrix is worse than no matrix (#651)."
        )

    def _failure_text(self, attempt: _Attempt) -> str | None:
        """Everything the runner saw about a failure, or None if it SUCCEEDED.

        Success is established POSITIVELY, and that is the whole point. An
        earlier version asked "did anything look wrong?" and treated silence
        as success, which meant an envelope shape it had never seen - say
        `{"type": "error", "result": "Claude usage limit reached"}` - sailed
        through with exit code 0, and the usage-limit message itself became
        the candidate's answer and got graded. That is the #651 incident
        rebuilt inside the module written to prevent it.

        So a call has succeeded ONLY when the envelope says so in the shape
        the CLI actually emits: `type: "result"`, `subtype: "success"`, no
        error flag, no API error status, exit code 0. Every other shape,
        including every shape not seen before, is a failure - the same
        fail-closed posture `claude/errors.py` takes, applied one layer
        earlier.
        """
        parts: list[str] = []
        if attempt.returncode != 0:
            parts.append(f"exit code {attempt.returncode}")
        if not attempt.envelope:
            parts.append(f"unparseable output: {attempt.stdout!r}")
        else:
            envelope_type = attempt.envelope.get("type")
            subtype = attempt.envelope.get("subtype")
            if envelope_type != _SUCCESS_TYPE or subtype != _SUCCESS_SUBTYPE:
                parts.append(
                    f"envelope is not a success result: type={envelope_type!r} "
                    f"subtype={subtype!r}"
                )
            if attempt.envelope.get("is_error"):
                parts.append(f"is_error with subtype {subtype!r}")
            status = attempt.envelope.get("api_error_status")
            if status:
                parts.append(f"api_error_status {status}")
            result = attempt.envelope.get("result")
            if parts and isinstance(result, str) and result:
                parts.append(f"result {result!r}")
        # Appended only when something else already marked this a failure:
        # Claude Code writes ordinary warnings to stderr, so stderr alone is
        # not evidence of one. When there IS a failure it must be included,
        # because quota wording can reach stderr and nowhere else.
        if parts and attempt.stderr.strip():
            parts.append(f"stderr {attempt.stderr.strip()!r}")
        # NOT truncated. The classifier reads this string, and a quota phrase
        # that happened to sit past a truncation boundary would be classified
        # transient and retried. Shortening happens at display time only.
        return "; ".join(parts) if parts else None

    def _completion(self, attempt: _Attempt) -> Completion:
        envelope = attempt.envelope
        if envelope.get("stop_reason") == "refusal":
            raise RefusedError(
                f"{self.model} declined the request; there is no answer to grade. "
                "Treat the case as ungraded, not as a fail."
            )
        result = envelope.get("result")
        return Completion(
            text=result if isinstance(result, str) else "",
            usage=_usage_from_envelope(envelope),
            structured_output=envelope.get("structured_output"),
            session_id=str(envelope.get("session_id") or ""),
        )
