# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The live run: candidate answers, judge grades, deterministic asserts decide.

Slice 1 assembled every prompt offline; this drives them. For each case, once
per `--repeat`:

1. the CANDIDATE answers the assembled prompt;
2. every `javascript` assertion is evaluated in Python, offline, against that
   answer (slice 1's ported evaluators - no model involved);
3. every `llm-rubric` assertion is graded by the JUDGE, using the config's own
   `rubricPrompt` when it has one;
4. the case passes only if every assertion on it passed.

Ordering is not incidental. The deterministic assertions run FIRST and their
result is recorded whether or not the judge is reached, so a matrix that dies
part-way still has its cheap signal in memory - and a case whose regex gate
already failed is still sent to the judge, because the rubric's reason is what
makes a failure diagnosable. Cost, not correctness, would be the argument for
short-circuiting, and one skipped judge call is not worth a blind failure.

## Repeats

`--repeat N` runs each case N times and records each pass separately, tagged
with its 1-based repeat index. Slice 3 needs that to prove the `.ab.yaml`
controls hold (A0 fails, A1 passes) across three runs rather than once; a
single sample cannot distinguish a real control from a lucky one.

## Errors

A `FatalRunError` from either provider propagates straight out of `run` -
past the report, past the summary - so `claude/cli.py` exits non-zero having
written nothing. A model REFUSAL is different: it is recorded on the case as
an error and the case fails, because a refusal is a fact about that one prompt
rather than a reason to abandon the matrix.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from claude import loader
from claude.assertions import (
    AssertionResult,
    JavascriptAssertion,
    RubricAssertion,
    UnportableJavascriptPatternError,
    UnportedJavascriptAssertionError,
    evaluator_for,
)
from claude.judge import parse_judge_response, render_judge_prompt
from claude.provider import Completion, Provider, RefusedError
from claude.report import AssertionRecord, CaseRecord, RunReport

__all__ = [
    "CANDIDATE_SYSTEM_PROMPT",
    "JUDGE_SYSTEM_PROMPT",
    "UNPORTED_ASSERTION_KIND",
    "Runner",
]

# A distinct `kind` in the report for "the runner cannot grade this", as
# opposed to "the skill failed this". Anything reading the report - the
# eval-failure-diagnoser especially - must be able to tell a gap in the
# harness from a regression in a skill.
UNPORTED_ASSERTION_KIND = "javascript-unported"

# The candidate's system prompt is deliberately near-empty. Every eval config
# already carries its own full instruction in `prompts[].raw` - the skill body,
# the loaded catalogues, the developer's message - and promptfoo sent that as
# the entire prompt with no system message at all. Adding guidance here would
# be grading the skills plus an uncontrolled preamble.
CANDIDATE_SYSTEM_PROMPT = "Answer the user's message. Follow any instructions it contains exactly."

# The judge's system prompt is equally thin, for the same reason: all 61 live
# configs supply their own `rubricPrompt`, which states the grading contract in
# full. This only pins the output shape, which `--json-schema` also enforces.
JUDGE_SYSTEM_PROMPT = (
    "You are grading a candidate response against a rubric. "
    'Reply with a single JSON object: {"pass": <true|false>, "score": <0.0-1.0>, '
    '"reason": "<why>"}. No prose outside the JSON.'
)


@dataclass(frozen=True)
class _Graded:
    record: AssertionRecord
    completion: Completion | None = None


class Runner:
    """Drives configs through the candidate and judge tiers."""

    def __init__(self, candidate: Provider, judge: Provider) -> None:
        self.candidate = candidate
        self.judge = judge

    def run(
        self,
        config_paths: Sequence[Path],
        *,
        repeat: int = 1,
        report: RunReport | None = None,
    ) -> RunReport:
        """Grade every case in every config, `repeat` times each."""
        if repeat < 1:
            raise ValueError(f"--repeat must be at least 1, got {repeat}")

        report = report if report is not None else RunReport()
        report.repeat = repeat

        for path in config_paths:
            config = loader.load_config(Path(path))
            record = report.config_for(Path(path).name)
            for case in loader.build_cases(config):
                for index in range(1, repeat + 1):
                    record.cases.append(self._run_case(report, case, repeat=index))
        return report

    def _run_case(self, report: RunReport, case, *, repeat: int) -> CaseRecord:
        config_name = case.config_path.name
        try:
            answer = self.candidate.complete(case.rendered_prompt)
        except RefusedError as exc:
            # Not fatal: one declined prompt is not a reason to discard the
            # rest of the matrix, but it is not a pass either.
            return CaseRecord(
                prompt_label=case.prompt_label,
                description=case.description,
                repeat=repeat,
                passed=False,
                error=str(exc),
            )
        self._record(report, config_name, answer)

        records: list[AssertionRecord] = []
        for assertion in case.assertions:
            graded = self._grade(assertion, answer.text, case.vars)
            records.append(graded.record)
            if graded.completion is not None:
                self._record(report, config_name, graded.completion)

        return CaseRecord(
            prompt_label=case.prompt_label,
            description=case.description,
            repeat=repeat,
            passed=all(record.passed for record in records),
            assertions=records,
        )

    def _grade(self, assertion, output: str, variables) -> _Graded:
        if isinstance(assertion, RubricAssertion):
            return self._grade_rubric(assertion, output, variables)
        return _Graded(record=self._grade_javascript(assertion, output, variables))

    def _grade_rubric(self, assertion: RubricAssertion, output: str, variables) -> _Graded:
        messages = render_judge_prompt(
            assertion.rubric_prompt,
            rubric=assertion.rubric,
            output=output,
            variables=variables,
        )
        # A rubric prompt may be a system+user pair (promptfoo's default) or a
        # single user turn (every live config). The CLI takes one system prompt
        # and one message, so the system half is sent AS the system prompt -
        # not flattened into the user turn, and not dropped.
        system_turns = [entry["content"] for entry in messages if entry["role"] == "system"]
        user_turns = [entry["content"] for entry in messages if entry["role"] != "system"]
        reply = self.judge.complete(
            "\n\n".join(user_turns),
            system_prompt="\n\n".join(system_turns) if system_turns else None,
        )
        verdict = parse_judge_response(
            reply.text,
            threshold=assertion.threshold,
            structured_output=reply.structured_output,
        )
        return _Graded(
            record=AssertionRecord(
                kind="llm-rubric",
                passed=verdict.passed,
                score=verdict.score,
                reason=verdict.reason,
            ),
            completion=reply,
        )

    def _grade_javascript(self, assertion: JavascriptAssertion, output: str, variables):
        try:
            evaluator = evaluator_for(assertion)
        except (UnportedJavascriptAssertionError, UnportableJavascriptPatternError) as exc:
            # Slice 1 refuses rather than approximating an unported JS assert.
            # Recording it as a failed assertion keeps the refusal loud without
            # taking the whole matrix down over one config - but it is tagged
            # `javascript-unported`, NOT `javascript`. The distinction matters:
            # this is the RUNNER lacking a port, not the skill behaving badly,
            # and an epic that exists because a tooling failure was misread as
            # a catastrophic quality collapse (#651) must not let a second
            # tooling failure wear the same costume in the report.
            return AssertionRecord(
                kind=UNPORTED_ASSERTION_KIND,
                passed=False,
                score=0.0,
                reason=f"the runner has no Python port for this javascript assert: {exc}",
            )
        result: AssertionResult = evaluator.evaluate(output, variables)
        return AssertionRecord(
            kind="javascript",
            passed=result.passed,
            score=float(result.score),
            reason=result.reason,
        )

    @staticmethod
    def _record(report: RunReport, config_name: str, completion: Completion) -> None:
        for usage in completion.usage:
            report.record_usage(
                config_name,
                model=usage.model,
                input_tokens=usage.input_tokens
                + usage.cache_read_input_tokens
                + usage.cache_creation_input_tokens,
                output_tokens=usage.output_tokens,
                usd=usage.cost_usd,
            )
